"""
Pipeline RAG Híbrido con Text-to-Cypher dinámico — versión streaming para la API.

Adaptación de tests/testRagDinamicoV3.py (misma lógica y mismo orden de fases) en la
que responder() se convierte en el generador responder_stream(): en lugar de imprimir
el progreso por consola, emite eventos que el servidor FastAPI reenvía por SSE y el
frontend muestra como indicadores de avance. La respuesta final se streamea token a
token con answer_chain.stream() en vez de invoke().

Eventos emitidos (dicts serializables a JSON):
  {"type": "fase",    "fase": str, "label": str}    — comienza una fase del pipeline
  {"type": "item",    "texto": str}                 — detalle dentro de la fase actual
  {"type": "fuentes", "articulos": [{id, numero, norma}]} — artículos del contexto final
  {"type": "token",   "texto": str}                 — fragmento de la respuesta final
  {"type": "fin",     "articulos": int, "segundos": float}
  {"type": "error",   "mensaje": str}
"""
import os
import re
import sys
import json
import time
import unicodedata
from typing import Iterator

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from utils.connectors import get_neo4j_driver, get_gemini_embeddings, get_gemini_llm
from utils.extractor_base import RELACIONES_PERMITIDAS
from utils.citas import NOMBRE_NORMA
from langchain_neo4j import Neo4jVector
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

llm_lite   = get_gemini_llm()                          # flash-lite: tareas simples (extracción, evaluación)
llm        = get_gemini_llm("gemini-2.5-flash")        # flash: respuesta final y Cypher
embeddings = get_gemini_embeddings()
neo4j_driver = get_neo4j_driver()

# --- Parámetros de recuperación (heurísticas explicadas donde se usan) ---
K_VECTORIAL          = 5   # vecinos a recuperar por cada frase de búsqueda
LONGITUD_MIN_KEYWORD = 4   # palabras del sujeto más cortas se ignoran (poco discriminantes)
MIN_DOCS_TRAS_FILTRO = 2   # si el filtro por sujeto deja menos, se descarta el filtro (prioriza recall)

# ==========================================
# 1. MOTOR VECTORIAL
# ==========================================

retrieval_query = f"""
OPTIONAL MATCH (norma:Norma)-[:CONTIENE]->(node)
RETURN
    "FUENTE: " + {NOMBRE_NORMA} + "\\n" +
    "ARTICULO: " + coalesce(node.numero, '') + "\\n" +
    "TEXTO: " + coalesce(node.texto, '') AS text,
    score,
    {{
        ley: {NOMBRE_NORMA},
        norma_id: coalesce(norma.id, ''),
        art: coalesce(node.numero, ''),
        id: node.id,
        ubicacion: coalesce(node.ubicacion, '')
    }} AS metadata
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
    """Acumula artículos únicos (dedup por id) con su texto ya formateado."""
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
- "sujeto": El sujeto o instituto jurídico central de la pregunta, en lenguaje natural
  (ej: "sociedad anonima", "SAS", "hipoteca", "escritura publica", "usufructo",
  "reporte de operacion sospechosa", "tracto abreviado"). Si la pregunta no gira sobre
  un instituto identificable, devolvé "".
- "frases_vectoriales": Lista de 2 o 3 frases en lenguaje natural. Incluí el número de artículo si se menciona.
Devuelve SOLO el JSON.
Pregunta: {pregunta}"""
    try:
        respuesta = llm_lite.invoke(prompt)
        data = json.loads(_strip_markdown(str(respuesta.content)))
        return str(data.get("sujeto", "")), data.get("frases_vectoriales", [pregunta])
    except Exception:
        return "", [pregunta]

# Palabras demasiado genéricas para discriminar: aparecen en casi cualquier norma del
# corpus (societario, civil, registral, notarial, penal, tributario). Las de <= 4 letras
# ya las descarta LONGITUD_MIN_KEYWORD.
_STOPWORDS = {
    "sociedad", "capital", "social", "socios",
    "derecho", "derechos", "juridico", "juridica",
    "articulo", "articulos", "norma", "normas",
    "publico", "publica", "general", "nacional", "legal", "legales",
}

def filtrar_por_sujeto(docs: list, sujeto: str) -> list:
    """Filtra los docs vectoriales para quedarse con los del sujeto preguntado.
    Misma heurística que V3 (privilegia recall sobre precisión)."""
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
    """Lee los labels reales de entidades ontológicas desde Neo4j (una sola vez al cargar el módulo).

    Se excluyen los labels estructurales (Norma, Articulo, VersionHistorica) y Jurisprudencia:
    no son entidades de ontología y en el prompt de Cypher se leen como etiquetas consultables.
    """
    with driver.session() as session:
        result = session.run("""
            MATCH (n)
            WHERE NOT n:Articulo AND NOT n:Norma AND NOT n:VersionHistorica AND NOT n:Jurisprudencia
            RETURN DISTINCT labels(n)[0] AS label
            ORDER BY label
        """)
        return [row["label"] for row in result if row["label"]]


class MotorCypherDinamico:
    # Cláusulas que no deben aparecer en una query de solo lectura.
    # execute_read() protege a nivel de routing pero no garantiza read-only en
    # servidores únicos; este filtro es la barrera real.
    _CLAUSULAS_ESCRITURA = {"DELETE", "DETACH", "REMOVE", "SET", "MERGE", "CREATE", "DROP", "CALL"}
    _PATRON_ESCRITURA = re.compile(r"\b(" + "|".join(_CLAUSULAS_ESCRITURA) + r")\b", re.IGNORECASE)

    def __init__(self, driver, llm_model, etiquetas_entidades: list[str]):
        self.driver = driver
        self.llm = llm_model

        relaciones_fmt = "\n  ".join(RELACIONES_PERMITIDAS)
        etiquetas_fmt = " | ".join(etiquetas_entidades) if etiquetas_entidades else "(ninguna cargada)"

        self._esquema = f"""
NODOS Y PROPIEDADES REALES:
  (:Norma {{id, numero, titulo, tipo, rama, jurisdiccion, vigente}})
    — tipo: "Ley" | "Codigo" | "Decreto" | "ResolucionGeneral" | "Resolución" |
            "DisposicionTecnicoRegistral" | "InstruccionDeTrabajo"
    — rama: LISTA de strings, filtrá con IN (ej: 'registral' IN norma.rama). Valores:
            registral | societario | civil | penal | financiero | notarial | tributario |
            inversiones | comercial | datos_personales | asociaciones_civiles
    — jurisdiccion: "Nacional" | "Ciudad Autónoma de Buenos Aires"
    — titulo puede ser NULL: usá coalesce(norma.titulo, norma.id).
    — Ejemplos de id: "Ley_19550" | "CCyCN" | "Decreto_2080_1980" | "RG_15_2024" | "DTR_5_2019"

  (:Articulo {{id, numero, texto, ubicacion, vigente, modificado}})
    — El id NO tiene un formato único: "Art_163_Ley_19550", "Art_1_CCyCN",
      "Art_105_Decreto_2080_1980", "Art_1_DTR_5_2019", "Art_3_RG_2139_2006".
      NUNCA lo parsees ni lo construyas: llegá al artículo por (:Norma)-[:CONTIENE]->(:Articulo).
    — vigente = false ⇒ artículo derogado: no debe usarse como derecho vigente.

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

        self._ejemplo = """
EJEMPLO — supletoriedad (Ley 27349 aplica Ley 19550 supletoriamente):
Pregunta: "¿Puede una SAS emitir debentures?"
Cypher:
OPTIONAL MATCH (art_directo:Articulo)-[r]-(sas:SociedadPorAccionesSimplificada)
WHERE type(r) IN ['REGULA', 'AUTORIZA', 'PROHIBE', 'DEFINE']
  AND toLower(art_directo.texto) CONTAINS 'debenture'
  AND art_directo.vigente = true

MATCH (norma_origen:Norma)-[:CONTIENE]->(art_directo)
MATCH (norma_origen)-[:APLICA_SUPLETORIAMENTE]->(norma_sup:Norma)-[:CONTIENE]->(art_sup:Articulo)
WHERE toLower(art_sup.texto) CONTAINS 'debenture'
  AND art_sup.vigente = true

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
7. Devolvé SOLO artículos vigentes: agregá `AND art.vigente = true` a cada match de artículo.
8. Si la pregunta acota una rama o una jurisdicción, filtrá por la Norma que lo contiene:
   MATCH (n:Norma)-[:CONTIENE]->(art)
   WHERE 'registral' IN n.rama AND n.jurisdiccion = 'Ciudad Autónoma de Buenos Aires'

PREGUNTA:
{pregunta}
Cypher:"""

    @staticmethod
    def _postprocesar(cypher: str) -> str:
        """Corrige patrones Cypher inválidos que el LLM genera por su training data."""
        # `UNWIND x AS y \n WHERE` es inválido; la forma correcta es `UNWIND x AS y \n WITH y WHERE`.
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
    """Dado un conjunto de artículos, devuelve los artículos referenciados vía REMITE_A."""
    if not article_ids:
        return []
    query = f"""
    UNWIND $ids AS art_id
    MATCH (origen:Articulo {{id: art_id}})-[:REMITE_A]->(referenciado:Articulo)
    WHERE referenciado.texto IS NOT NULL
    OPTIONAL MATCH (norma:Norma)-[:CONTIENE]->(referenciado)
    RETURN DISTINCT
        referenciado.id     AS id,
        referenciado.numero AS numero,
        referenciado.texto  AS texto,
        {NOMBRE_NORMA}      AS norma,
        origen.numero       AS origen_numero
    """
    with neo4j_driver.session() as session:
        return [dict(row) for row in session.run(query, ids=article_ids)]


def _agregar_remisiones(ids_origen: list[str], ctx: ContextoAcumulado) -> Iterator[dict]:
    """Sigue REMITE_A desde `ids_origen`, agrega al contexto los artículos nuevos
    y emite un evento por cada uno."""
    for art in seguir_remite_a(ids_origen):
        origen_num = art.get("origen_numero", "")
        norma_ref  = art.get("norma", "")
        texto = _formato_articulo(
            f"{norma_ref} (referenciada por Art. {origen_num})",
            art.get("numero", ""),
            art.get("texto", ""),
        )
        if ctx.agregar(art.get("id", ""), texto):
            yield {"type": "item", "texto": f"Art. {art.get('numero', '')} ({norma_ref}) — citado por el Art. {origen_num}"}


def _obtener_datos_articulos(article_ids: list[str]) -> dict[str, dict]:
    """Devuelve {article_id: {"numero", "norma"}} para los artículos dados.

    El número y la norma se leen del grafo y nunca se derivan del id: los ids no
    tienen un formato único (Art_163_Ley_19550, Art_1_CCyCN, Art_1_DTR_5_2019).
    """
    if not article_ids:
        return {}
    query = f"""
    UNWIND $ids AS art_id
    MATCH (norma:Norma)-[:CONTIENE]->(art:Articulo {{id: art_id}})
    RETURN art_id,
           art.numero AS numero,
           {NOMBRE_NORMA} AS norma
    """
    with neo4j_driver.session() as session:
        return {
            row["art_id"]: {"numero": row["numero"], "norma": row["norma"]}
            for row in session.run(query, ids=article_ids)
        }


def obtener_entidades_relacionadas(article_ids: list[str]) -> list[dict]:
    if not article_ids:
        return []
    query = """
    UNWIND $ids AS art_id
    MATCH (art:Articulo {id: art_id})-[r]-(entidad)
    WHERE NOT entidad:Norma AND NOT entidad:Articulo AND NOT entidad:VersionHistorica
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
    prompt = f"""Eres un experto en derecho argentino (societario, civil, registral, notarial, penal \
y tributario). Evaluá si el contexto legal recuperado \
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


def responder_stream(pregunta: str) -> Iterator[dict]:
    """Versión generadora de responder() de V3: mismo flujo, pero emite eventos
    de progreso y streamea la respuesta final token a token."""
    t0 = time.time()

    # Fase 1: parámetros de búsqueda (sujeto + frases) extraídos con el LLM lite.
    yield {"type": "fase", "fase": "analisis", "label": "Analizando la consulta"}
    sujeto, frases_vectoriales = extraer_parametros_vectoriales(pregunta)
    if sujeto:
        yield {"type": "item", "texto": f"Sujeto identificado: {sujeto}"}

    ctx = ContextoAcumulado()

    # Fase 2: búsqueda vectorial. Se consulta cada frase (y la pregunta cruda) y
    # luego se filtra por sujeto; los duplicados alimentan la señal de frecuencia.
    yield {"type": "fase", "fase": "vectorial", "label": "Buscando artículos relevantes"}
    docs_raw = []
    for frase in frases_vectoriales + [pregunta]:
        for doc in retriever.invoke(frase):
            docs_raw.append(doc)

    docs_filtrados = filtrar_por_sujeto(docs_raw, sujeto)

    for doc in docs_filtrados:
        if ctx.agregar(doc.metadata.get("id", ""), doc.page_content):
            norma_display = doc.metadata.get('ley') or doc.metadata.get('norma_id', '?')
            yield {"type": "item", "texto": f"Art. {doc.metadata.get('art', '')} ({norma_display})"}

    # Fase 3.5 (primera pasada): remisiones explícitas desde lo recuperado en Fase 2.
    yield {"type": "fase", "fase": "remisiones", "label": "Siguiendo remisiones normativas"}
    yield from _agregar_remisiones(ctx.ids, ctx)

    # Gate: ¿el contexto vectorial + remisiones ya alcanza? Si sí, se omite el
    # Cypher dinámico (la operación más cara del pipeline).
    yield {"type": "fase", "fase": "evaluacion", "label": "Evaluando suficiencia del contexto"}
    suficiente, razon = _evaluar_suficiencia(pregunta, ctx.textos)
    yield {"type": "item", "texto": ("Contexto suficiente — " if suficiente else "Contexto insuficiente — ") + razon}

    # Fase 3: Cypher dinámico (solo si el gate dio insuficiente).
    if not suficiente:
        yield {"type": "fase", "fase": "grafo", "label": "Consultando el grafo de conocimiento"}
        ids_antes_fase3 = list(ctx.ids)
        arts_grafo = motor_cypher.consultar(pregunta)
        arts_grafo_nuevos = [a for a in arts_grafo if str(a.get("id", "")) and a.get("id") not in ctx]
        datos_grafo = _obtener_datos_articulos([str(a["id"]) for a in arts_grafo_nuevos])
        for art in arts_grafo_nuevos:
            art_id = str(art["id"])
            # La FUENTE es la norma real, no "Grafo Ontológico": el prompt de respuesta
            # exige citar la norma de cada afirmación y solo puede leerla de acá.
            norma = datos_grafo.get(art_id, {}).get("norma", "Norma no identificada")
            texto = _formato_articulo(norma, art.get("numero", ""), art.get("texto", ""))
            if ctx.agregar(art_id, texto):
                yield {"type": "item", "texto": f"Art. {art.get('numero', '')} ({norma})"}

        # Fase 3.5 (segunda pasada): remisiones desde los artículos nuevos del grafo.
        ids_nuevos_fase3 = [i for i in ctx.ids if i not in ids_antes_fase3]
        if ids_nuevos_fase3:
            yield from _agregar_remisiones(ids_nuevos_fase3, ctx)

    # Fase 4: vecindario ontológico (entidades) + generación de la respuesta final.
    entidades = obtener_entidades_relacionadas(ctx.ids)

    # Fuentes del contexto final, para que el frontend las muestre como citas.
    # El fallback cubre el caso en que un id del contexto no sea un :Articulo (el motor
    # Cypher puede devolver un :Jurisprudencia, que también tiene id y texto).
    datos_ctx = _obtener_datos_articulos(ctx.ids)
    fuentes = [
        {
            "id": art_id,
            "numero": datos_ctx.get(art_id, {}).get("numero") or art_id,
            "norma": datos_ctx.get(art_id, {}).get("norma") or "?",
        }
        for art_id in ctx.ids
    ]
    yield {"type": "fuentes", "articulos": fuentes}

    yield {"type": "fase", "fase": "redaccion", "label": "Redactando la respuesta"}
    context = "\n\n---\n\n".join(ctx.textos) + format_entidades(entidades)
    for chunk in answer_chain.stream({"context": context, "question": pregunta}):
        if chunk:
            yield {"type": "token", "texto": chunk}

    yield {"type": "fin", "articulos": len(ctx), "segundos": round(time.time() - t0, 1)}
