"""
Pipeline RAG Híbrido con Text-to-Cypher dinámico (V3).

V3 sobre V2: refactor sin cambio de comportamiento — se elimina la cadena de
revisión muerta, se factoriza la duplicación de remisiones/formato/dedup en
helpers, se endurece el filtro de escritura del Cypher y se documenta el flujo.

FLUJO de responder() — el orden REAL de ejecución es:
  1. Fase 1   — extracción de parámetros (sujeto + frases) con el LLM lite.
  2. Fase 2   — búsqueda vectorial semántica, filtrada por sujeto.
  3. Fase 3.5 — remisiones explícitas (REMITE_A) desde lo recuperado en Fase 2.
  4. Gate     — evaluación de suficiencia: ¿alcanza el contexto vectorial?
  5. Fase 3   — SOLO si el gate dio "insuficiente": Cypher dinámico. Es la
                operación más cara (genera Cypher con LLM y lo ejecuta), por eso
                va detrás del gate; si lo vectorial ya alcanza, se evita.
  6. Fase 3.5 — segunda pasada de remisiones, ahora desde los artículos nuevos
                que trajo la Fase 3.
  7. Fase 4   — vecindario ontológico (entidades relacionadas) + respuesta final.

Nota sobre las etiquetas de log: "Fase 3.5" se imprime ANTES que "Fase 3" en la
primera pasada. Se conservan los rótulos de V2 para no romper logs/comparaciones;
el orden de arriba es la guía de lectura.
"""
import os
import re
import sys
import json
import time
import unicodedata

_t_inicio_script = time.time()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from utils.connectors import get_neo4j_driver, get_gemini_embeddings, get_gemini_llm
from utils.extractor_base import RELACIONES_PERMITIDAS
from langchain_neo4j import Neo4jVector
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

llm_lite   = get_gemini_llm()                          # flash-lite: tareas simples (extracción, evaluación)
llm        = get_gemini_llm("gemini-2.5-flash")        # flash: respuesta final y Cypher
embeddings = get_gemini_embeddings()
neo4j_driver = get_neo4j_driver()

# --- Parámetros de recuperación (heurísticas explicadas donde se usan) ---
K_VECTORIAL          = 3   # vecinos a recuperar por cada frase de búsqueda
LONGITUD_MIN_KEYWORD = 4   # palabras del sujeto más cortas se ignoran (poco discriminantes)
MIN_DOCS_TRAS_FILTRO = 2   # si el filtro por sujeto deja menos, se descarta el filtro (prioriza recall)

# ==========================================
# 1. MOTOR VECTORIAL
# ==========================================

retrieval_query = """
OPTIONAL MATCH (norma:Norma)-[:CONTIENE]->(node)
RETURN
    "FUENTE: " + coalesce(norma.titulo, norma.id, 'Norma no identificada') + "\\n" +
    "ARTICULO: " + coalesce(node.numero, '') + "\\n" +
    "TEXTO: " + coalesce(node.texto, '') AS text,
    score,
    {
        ley: coalesce(norma.titulo, norma.id, ''),
        norma_id: coalesce(norma.id, ''),
        art: coalesce(node.numero, ''),
        id: node.id,
        ubicacion: coalesce(node.ubicacion, '')
    } AS metadata
"""

vector_db = Neo4jVector.from_existing_index(
    embeddings,
    url=os.getenv("NEO4J_URI"),
    username=os.getenv("NEO4J_USERNAME"),
    password=os.getenv("NEO4J_PASSWORD"),
    index_name="index_articulos",
    retrieval_query=retrieval_query
)
retriever = vector_db.as_retriever(search_kwargs={"k": K_VECTORIAL})

# ==========================================
# 2. UTILIDADES
# ==========================================

def _strip_markdown(content: str) -> str:
    """Quita el cercado ```...``` (con prefijo json/cypher) que el LLM suele añadir."""
    if "```" in content:
        partes = content.split("```")
        content = partes[1] if len(partes) > 1 else content
        if content.startswith("json"):
            content = content[4:]
        elif content.startswith("cypher"):
            content = content[6:]
    return content.strip()

def normalizar(texto: str) -> str:
    """Minúsculas sin tildes ni diacríticos, para comparaciones tolerantes a acentos."""
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii").lower()

def _formato_articulo(fuente: str, numero: str, texto: str) -> str:
    """Formato canónico de un artículo para el contexto del LLM.
    Replica el mismo layout que arma `retrieval_query` en Cypher."""
    return f"FUENTE: {fuente}\nARTICULO: {numero}\nTEXTO: {texto}"


class ContextoAcumulado:
    """Acumula artículos únicos (dedup por id) con su texto ya formateado.

    Centraliza los tres estados que en V2 se mantenían a mano y en paralelo dentro
    de responder() (el set de vistos, la lista de ids y la lista de textos), que
    había que mantener sincronizados en cada fase.
    """
    def __init__(self):
        self._vistos: set[str] = set()
        self.ids: list[str] = []
        self.textos: list[str] = []

    def agregar(self, art_id, texto: str) -> bool:
        """Registra el artículo si no fue visto antes. Devuelve True si era nuevo."""
        art_id = str(art_id)
        if not art_id or art_id in self._vistos:
            return False
        self._vistos.add(art_id)
        self.ids.append(art_id)
        self.textos.append(texto)
        return True

    def __contains__(self, art_id) -> bool:
        return str(art_id) in self._vistos

    def __len__(self) -> int:
        return len(self._vistos)

# ==========================================
# 3. EXTRACCIÓN PARA FASE VECTORIAL
# ==========================================

def extraer_parametros_vectoriales(pregunta: str) -> tuple[str, list[str]]:
    prompt = f"""Analizá la pregunta jurídica y extraé parámetros para búsqueda semántica.
Devolvé un JSON con:
- "sujeto": El tipo societario en lenguaje natural (ej: "sociedad anonima", "SAS").
- "frases_vectoriales": Lista de 2 o 3 frases en lenguaje natural. Incluí el número de artículo si se menciona.
Devuelve SOLO el JSON.
Pregunta: {pregunta}"""
    try:
        respuesta = llm_lite.invoke(prompt)
        data = json.loads(_strip_markdown(str(respuesta.content)))
        return str(data.get("sujeto", "")), data.get("frases_vectoriales", [pregunta])
    except Exception:
        return "", [pregunta]

_STOPWORDS = {"sociedad", "capital", "social", "socios"}

def filtrar_por_sujeto(docs: list, sujeto: str) -> list:
    """Filtra los docs vectoriales para quedarse con los del sujeto preguntado.

    Heurística (privilegia recall sobre precisión):
    - Solo se usan como keywords las palabras del sujeto con más de
      LONGITUD_MIN_KEYWORD letras y que no sean stopwords del dominio: las cortas
      o genéricas ("social", "socios") matchean demasiado y no discriminan.
    - Un doc pasa si menciona la keyword (en texto o en ubicación) O si fue
      devuelto por >= 2 frases de búsqueda distintas: aparecer en varias
      iteraciones es señal de relevancia genuina aunque no nombre la keyword.
    - Si el filtro dejaría menos de MIN_DOCS_TRAS_FILTRO docs, se descarta el
      filtro y se devuelven todos (mejor contexto de más que vacío).
    """
    if not sujeto:
        return docs
    words = [w for w in normalizar(sujeto).split() if len(w) > LONGITUD_MIN_KEYWORD and w not in _STOPWORDS]
    if not words:
        return docs

    # Frecuencia: cuántas frases de búsqueda distintas devolvieron cada doc.
    frecuencia: dict[str, int] = {}
    for doc in docs:
        doc_id = str(doc.metadata.get("id", ""))
        if doc_id:
            frecuencia[doc_id] = frecuencia.get(doc_id, 0) + 1

    filtrados = [
        doc for doc in docs
        if any(w in normalizar(doc.page_content) or w in normalizar(str(doc.metadata.get("ubicacion", ""))) for w in words)
        or frecuencia.get(str(doc.metadata.get("id", "")), 0) >= 2
    ]
    return filtrados if len(filtrados) >= MIN_DOCS_TRAS_FILTRO else docs

# ==========================================
# 4. MOTOR CYPHER DINÁMICO
# ==========================================

def _cargar_etiquetas_entidades(driver) -> list[str]:
    """Lee los labels reales de entidades ontológicas desde Neo4j (se ejecuta una sola vez al cargar el módulo)."""
    with driver.session() as session:
        result = session.run("""
            MATCH (n)
            WHERE NOT n:Articulo AND NOT n:Norma
            RETURN DISTINCT labels(n)[0] AS label
            ORDER BY label
        """)
        return [row["label"] for row in result if row["label"]]


class MotorCypherDinamico:
    # Cláusulas que no deben aparecer en una query de solo lectura.
    # execute_read() protege a nivel de routing pero no garantiza read-only en
    # servidores únicos; este filtro es la barrera real.
    _CLAUSULAS_ESCRITURA = {"DELETE", "DETACH", "REMOVE", "SET", "MERGE", "CREATE", "DROP", "CALL"}
    # Regex con límites de palabra: detecta la cláusula aunque venga pegada a un
    # paréntesis o llave (ej. "CREATE(n)", "CALL{") — el split por espacios de V2
    # no la veía. \b ancla en la frontera palabra/no-palabra.
    _PATRON_ESCRITURA = re.compile(r"\b(" + "|".join(_CLAUSULAS_ESCRITURA) + r")\b", re.IGNORECASE)

    def __init__(self, driver, llm_model, etiquetas_entidades: list[str]):
        self.driver = driver
        self.llm = llm_model

        relaciones_fmt = "\n  ".join(RELACIONES_PERMITIDAS)
        etiquetas_fmt = " | ".join(etiquetas_entidades) if etiquetas_entidades else "(ninguna cargada)"

        # Esquema real del grafo inyectado en el prompt.
        # Los IDs de entidades son MAYUSCULAS_CON_GUIONES_BAJOS; no existe la propiedad "nombre".
        self._esquema = f"""
NODOS Y PROPIEDADES REALES:
  (:Norma        {{id: "Ley_19550",          numero: "19.550", titulo: "Ley General de Sociedades"}})
  (:Articulo     {{id: "Art_163_Ley_19550",  numero: "163",    texto: "...", ubicacion: "..."}})
  (:<Etiqueta>   {{id: "NOMBRE_EN_MAYUSCULAS_CON_GUIONES"}})
    — La propiedad de búsqueda es SIEMPRE "id", nunca "nombre".
    — Etiquetas de entidades ontológicas presentes en la DB:
      {etiquetas_fmt}

RELACIONES:
  (:Norma)-[:CONTIENE]->(:Articulo)
  (:Norma)-[:APLICA_SUPLETORIAMENTE]->(:Norma)   // supletoriedad entre leyes, NO entre entidades
  (:Articulo o :Entidad)-[:TIPO]->(: Articulo o :Entidad)
    Tipos disponibles:
  {relaciones_fmt}
"""

        # Ejemplo con supletoriedad correcto: traversal a nivel de Norma, no de entidad.
        self._ejemplo = """
EJEMPLO — supletoriedad (Ley 27349 aplica Ley 19550 supletoriamente):
Pregunta: "¿Puede una SAS emitir debentures?"
Cypher:
OPTIONAL MATCH (art_directo:Articulo)-[r]-(sas:SociedadPorAccionesSimplificada)
WHERE type(r) IN ['REGULA', 'AUTORIZA', 'PROHIBE', 'DEFINE']
  AND toLower(art_directo.texto) CONTAINS 'debenture'

MATCH (norma_origen:Norma)-[:CONTIENE]->(art_directo)
MATCH (norma_origen)-[:APLICA_SUPLETORIAMENTE]->(norma_sup:Norma)-[:CONTIENE]->(art_sup:Articulo)
WHERE toLower(art_sup.texto) CONTAINS 'debenture'

WITH collect(DISTINCT art_directo) + collect(DISTINCT art_sup) AS todos
UNWIND todos AS art
WITH art WHERE art IS NOT NULL
RETURN DISTINCT art.id AS id, art.numero AS numero, art.texto AS texto
LIMIT 5
"""

    def _generar_prompt(self, pregunta: str) -> str:
        return f"""Eres un experto en Neo4j y derecho argentino. Generá una query Cypher de SOLO LECTURA.

ESQUEMA DEL GRAFO:
{self._esquema}

{self._ejemplo}

REGLAS ESTRICTAS:
1. Devolvé ÚNICAMENTE el código Cypher. Sin texto adicional.
2. NO inventes etiquetas ni propiedades que no estén en el esquema.
3. Para buscar entidades usá su etiqueta específica y filtrá por "id" con toLower() + CONTAINS.
4. Para supletoriedad traversá a nivel de NORMA: (norma)-[:APLICA_SUPLETORIAMENTE]->(norma_sup)-[:CONTIENE]->(art).
5. Retorná exactamente estas columnas: id, numero, texto.
6. LIMIT 5.

PREGUNTA:
{pregunta}
Cypher:"""

    @staticmethod
    def _postprocesar(cypher: str) -> str:
        """Corrige patrones Cypher inválidos que el LLM genera por su training data."""
        # El LLM frecuentemente genera `UNWIND x AS y \n WHERE` que es inválido en Neo4j.
        # La forma correcta es `UNWIND x AS y \n WITH y WHERE`.
        cypher = re.sub(
            r'(UNWIND\s+\S+\s+AS\s+(\w+))(\s*\n\s*)WHERE',
            lambda m: f"{m.group(1)}{m.group(3)}WITH {m.group(2)} WHERE",
            cypher,
            flags=re.IGNORECASE,
        )
        return cypher

    def consultar(self, pregunta: str) -> list[dict]:
        print("  [Grafo] Generando Cypher dinámicamente...")
        try:
            respuesta_llm = self.llm.invoke(self._generar_prompt(pregunta))
            cypher = _strip_markdown(str(respuesta_llm.content))
            cypher = self._postprocesar(cypher)

            bloqueadas = {m.upper() for m in self._PATRON_ESCRITURA.findall(cypher)}
            if bloqueadas:
                print(f"  [Grafo] Cypher rechazado: cláusulas no permitidas detectadas: {bloqueadas}")
                return []

            print(f"  [Grafo] Cypher:\n{'-'*30}\n{cypher}\n{'-'*30}")

            with self.driver.session() as session:
                records = session.execute_read(lambda tx: tx.run(cypher).data())
                return [r for r in records if r.get("id") and r.get("texto")]

        except Exception as e:
            print(f"  [Grafo] Error: {e}")
            return []


# Inicialización única al cargar el módulo: carga las etiquetas reales desde Neo4j.
_etiquetas_entidades = _cargar_etiquetas_entidades(neo4j_driver)
print(f"[Init] Etiquetas ontológicas cargadas: {_etiquetas_entidades}")
motor_cypher = MotorCypherDinamico(neo4j_driver, llm, _etiquetas_entidades)

# ==========================================
# 5. VECINDARIO ONTOLÓGICO
# ==========================================

def seguir_remite_a(article_ids: list[str]) -> list[dict]:
    """Dado un conjunto de artículos, devuelve los artículos referenciados vía REMITE_A.
    Solo traversa hacia nodos Articulo (los nodos Norma no tienen texto útil para el contexto)."""
    if not article_ids:
        return []
    query = """
    UNWIND $ids AS art_id
    MATCH (art:Articulo {id: art_id})-[:REMITE_A]->(referenciado:Articulo)
    WHERE referenciado.texto IS NOT NULL
    RETURN DISTINCT
        referenciado.id     AS id,
        referenciado.numero AS numero,
        referenciado.texto  AS texto,
        art_id              AS citado_desde
    """
    with neo4j_driver.session() as session:
        return [dict(row) for row in session.run(query, ids=article_ids)]


def _agregar_remisiones(ids_origen: list[str], ctx: ContextoAcumulado) -> None:
    """Sigue REMITE_A desde `ids_origen` y agrega al contexto los artículos
    referenciados que sean nuevos. Unifica las dos pasadas idénticas de V2."""
    for art in seguir_remite_a(ids_origen):
        origen_num = art["citado_desde"].replace("Art_", "").split("_Ley_")[0]
        norma_ref  = str(art.get("id", "")).split("_Ley_")[-1]
        texto = _formato_articulo(
            f"Ley {norma_ref} (referenciada por Art. {origen_num})",
            art.get("numero", ""),
            art.get("texto", ""),
        )
        if ctx.agregar(art.get("id", ""), texto):
            print(f"  • [Remisión] Art. {art.get('numero', '')} [Ley {norma_ref}] recuperado (citado por Art. {origen_num}).")


def _obtener_normas(article_ids: list[str]) -> dict[str, str]:
    """Devuelve {article_id: norma_titulo} para los artículos dados."""
    if not article_ids:
        return {}
    query = """
    UNWIND $ids AS art_id
    MATCH (norma:Norma)-[:CONTIENE]->(art:Articulo {id: art_id})
    RETURN art_id, coalesce(norma.titulo, norma.id, '?') AS norma_titulo
    """
    with neo4j_driver.session() as session:
        return {row["art_id"]: row["norma_titulo"] for row in session.run(query, ids=article_ids)}


def obtener_entidades_relacionadas(article_ids: list[str]) -> list[dict]:
    if not article_ids:
        return []
    query = """
    UNWIND $ids AS art_id
    MATCH (art:Articulo {id: art_id})-[r]-(entidad)
    WHERE NOT entidad:Norma AND NOT entidad:Articulo
    RETURN DISTINCT
        labels(entidad)[0] AS tipo,
        entidad.id         AS id,
        type(r)            AS relacion,
        art_id             AS articulo
    ORDER BY tipo, id
    """
    with neo4j_driver.session() as session:
        return [dict(row) for row in session.run(query, ids=article_ids)]

def format_entidades(entidades: list[dict]) -> str:
    if not entidades:
        return ""
    lines = ["\n\nENTIDADES JURÍDICAS RELACIONADAS:"]
    for e in entidades:
        lines.append(f"  [{e['tipo']}] {e['id']}  —  {e['relacion']}  →  Art. {e['articulo']}")
    return "\n".join(lines)

# ==========================================
# 6. GENERACIÓN DE RESPUESTA
# ==========================================

template_respuesta = """Eres un asistente legal experto en derecho argentino.

PASO PREVIO OBLIGATORIO: Antes de escribir la respuesta, identificá mentalmente cuáles artículos del contexto responden DIRECTAMENTE a la pregunta. Los demás artículos deben ser descartados por completo, aunque sean temáticamente cercanos.

INSTRUCCIONES:
1. Respondé EXCLUSIVAMENTE sobre el sujeto y el supuesto que se pregunta. Si el contexto incluye artículos que tratan un caso similar pero para un sujeto distinto al preguntado, esos artículos son irrelevantes: no los mencionés, no los cités ni los uses como apoyo.
2. Si la norma enumera condiciones, requisitos o excepciones aplicables al sujeto y supuesto preguntado, incluilos TODOS sin omitir ninguno.
3. Usá ÚNICAMENTE el contexto provisto. No inventes.
4. Citá siempre el número de artículo y la norma de la que proviene cada afirmación.

CONTEXTO LEGAL RECUPERADO:
{context}

PREGUNTA:
{question}

RESPUESTA:"""

answer_chain = ChatPromptTemplate.from_template(template_respuesta) | llm | StrOutputParser()


def _evaluar_suficiencia(pregunta: str, contexto: list[str]) -> tuple[bool, str]:
    """Evalúa si el contexto vectorial es suficiente para responder sin recurrir al grafo."""
    contexto_txt = "\n\n---\n\n".join(contexto) if contexto else "(ningún artículo recuperado)"
    prompt = f"""Eres un experto en derecho societario argentino. Evaluá si el contexto legal recuperado \
es SUFICIENTE para responder la pregunta del usuario de forma útil y precisa.

CRITERIO: Respondé "suficiente: true" si los artículos recuperados permiten dar una respuesta \
sustancialmente completa. Respondé "suficiente: false" SOLO si hay aspectos CENTRALES de la pregunta \
que los artículos no abordan en absoluto y cuya ausencia cambiaría materialmente la respuesta.

PREGUNTA:
{pregunta}

CONTEXTO RECUPERADO:
{contexto_txt}

Devolvé SOLO un JSON con este formato exacto:
{{"suficiente": true, "razon": "explicación breve de una línea"}}"""
    try:
        respuesta = llm_lite.invoke(prompt)
        data = json.loads(_strip_markdown(str(respuesta.content)))
        return bool(data.get("suficiente", False)), str(data.get("razon", ""))
    except Exception as e:
        return False, f"Error al evaluar: {e}"


def responder(pregunta: str) -> str:
    t0 = time.time()
    print(f"\nProcesando: {pregunta}")

    # Fase 1: parámetros de búsqueda (sujeto + frases) extraídos con el LLM lite.
    sujeto, frases_vectoriales = extraer_parametros_vectoriales(pregunta)
    print(f"\n[Fase 1] Sujeto extraído: '{sujeto}' ({time.time()-t0:.1f}s)")

    ctx = ContextoAcumulado()

    # Fase 2: búsqueda vectorial. Se consulta cada frase (y la pregunta cruda) y
    # luego se filtra por sujeto; los duplicados alimentan la señal de frecuencia.
    print("\n[Fase 2] Buscando en Base Vectorial...")
    docs_raw = []
    for frase in frases_vectoriales + [pregunta]:
        for doc in retriever.invoke(frase):
            docs_raw.append(doc)

    docs_filtrados = filtrar_por_sujeto(docs_raw, sujeto)

    # Docs que el filtro de sujeto dejó afuera, para reportarlos (solo logging).
    ids_aceptados = {str(d.metadata.get("id", "")) for d in docs_filtrados}
    descartados_por_id: dict = {}
    for d in docs_raw:
        doc_id = str(d.metadata.get("id", ""))
        if doc_id and doc_id not in ids_aceptados and doc_id not in descartados_por_id:
            descartados_por_id[doc_id] = d

    for doc in docs_filtrados:
        if ctx.agregar(doc.metadata.get("id", ""), doc.page_content):
            norma_display = doc.metadata.get('ley') or doc.metadata.get('norma_id', '?')
            print(f"  • [Vector] Art. {doc.metadata.get('art', '')} [{norma_display}] recuperado.")
    if descartados_por_id:
        print(f"  (+ {len(descartados_por_id)} descartados por filtro de sujeto):")
        for doc in descartados_por_id.values():
            norma = doc.metadata.get('norma_id') or doc.metadata.get('ley', '?')
            print(f"    ✗ Art. {doc.metadata.get('art', '?')} [{norma}]")
    print(f"  [Fase 2 completada en {time.time()-t0:.1f}s]")

    # Fase 3.5 (primera pasada): remisiones explícitas desde lo recuperado en Fase 2.
    print("\n[Fase 3.5] Siguiendo remisiones explícitas (REMITE_A)...")
    _agregar_remisiones(ctx.ids, ctx)
    print(f"  [Fase 3.5 completada en {time.time()-t0:.1f}s]")

    # Gate: ¿el contexto vectorial + remisiones ya alcanza? Si sí, se omite el
    # Cypher dinámico (la operación más cara del pipeline).
    suficiente, razon = _evaluar_suficiencia(pregunta, ctx.textos)
    icono = "✓" if suficiente else "✗"
    print(f"\n[Evaluación post-Fase 2] {icono} {'Suficiente' if suficiente else 'Insuficiente'} — {razon} ({time.time()-t0:.1f}s)")

    # Fase 3: Cypher dinámico (solo si el gate dio insuficiente).
    if not suficiente:
        print("\n[Fase 3] Buscando en Grafo Dinámico (Text-to-Cypher)...")
        ids_antes_fase3 = list(ctx.ids)
        arts_grafo = motor_cypher.consultar(pregunta)
        arts_grafo_nuevos = [a for a in arts_grafo if str(a.get("id", "")) and a.get("id") not in ctx]
        normas_grafo = _obtener_normas([str(a["id"]) for a in arts_grafo_nuevos])
        for art in arts_grafo_nuevos:
            art_id = str(art["id"])
            texto = _formato_articulo("Grafo Ontológico", art.get("numero", ""), art.get("texto", ""))
            if ctx.agregar(art_id, texto):
                print(f"  • [Grafo] Art. {art.get('numero', '')} [{normas_grafo.get(art_id, '?')}] recuperado transversalmente.")
        print(f"  [Fase 3 completada en {time.time()-t0:.1f}s]")

        # Fase 3.5 (segunda pasada): remisiones desde los artículos nuevos del grafo.
        ids_nuevos_fase3 = [i for i in ctx.ids if i not in ids_antes_fase3]
        if ids_nuevos_fase3:
            print("\n[Fase 3.5] Siguiendo remisiones de artículos del grafo...")
            _agregar_remisiones(ids_nuevos_fase3, ctx)
            print(f"  [Fase 3.5 completada en {time.time()-t0:.1f}s]")
    else:
        print("\n[Fase 3] Omitida (contexto suficiente tras Fase 2 + remisiones).")

    print(f"\n{'─'*50}")
    print(f"Total artículos únicos: {len(ctx)}")

    # Fase 4: vecindario ontológico (entidades) + generación de la respuesta final.
    entidades = obtener_entidades_relacionadas(ctx.ids)
    print(f"Entidades relacionadas: {len(entidades)}")
    print(f"{'─'*50}")

    context = "\n\n---\n\n".join(ctx.textos) + format_entidades(entidades)
    print("Generando respuesta...")
    resultado = answer_chain.invoke({"context": context, "question": pregunta})
    print(f"\n{'─'*50}")
    print(f"Tiempo total: {time.time()-t0:.1f}s")
    print(f"{'─'*50}")
    return resultado


# --- Ejecución ---
if __name__ == "__main__":
    pregunta = "¿Qué requisitos establece la LSC para la transformación de una SRL en SA y qué documentación exige la RG IGJ 15/2024 para inscribir esa transformación ante la IGJ?"

    respuesta = responder(pregunta)
    print("\n\n=== RESPUESTA FINAL ===")
    print(respuesta)
    print(f"\n{'═'*50}")
    print(f"Tiempo total de ejecución (incluyendo carga): {time.time() - _t_inicio_script:.1f}s")
    print(f"{'═'*50}")

    neo4j_driver.close()
