"""Suite de evaluación batch del pipeline RAG Híbrido con Text-to-Cypher dinámico.
Integra todas las mejoras de testRagDinamico.py:
  - Motor Cypher dinámico (Text-to-Cypher con gemini-2.5-flash)
  - Traversal de remisiones explícitas (REMITE_A)
  - Traversal de vecindario ontológico
  - Timing por fase y total
  - Log de artículos descartados por filtro de sujeto

Ejecuta 10 preguntas de referencia que cubren las 4 normas cargadas:
  Ley 19550 (LSC) · Ley 27349 (SAS) · Ley 22315 (IGJ) · Decreto 1493/82
"""
import os, sys, json, time, unicodedata, logging, re

_t_inicio_script = time.time()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from utils.connectors import get_neo4j_driver, get_gemini_embeddings, get_gemini_llm
from utils.extractor_base import RELACIONES_PERMITIDAS
from langchain_neo4j import Neo4jVector
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# ==========================================
# LOGGING
# ==========================================

_ts       = time.strftime("%Y%m%d_%H%M%S")
_logs_dir = os.path.join(BASE_DIR, "logs")
os.makedirs(_logs_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(os.path.join(_logs_dir, f"judge_dinamico_{_ts}.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("judge_dinamico")

# ==========================================
# CONECTORES Y MODELOS
# ==========================================

llm        = get_gemini_llm()                      # flash-lite: respuestas legales
llm_cypher = get_gemini_llm("gemini-2.5-flash")    # flash: generación de Cypher
embeddings = get_gemini_embeddings()
neo4j_driver = get_neo4j_driver()

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
retriever = vector_db.as_retriever(search_kwargs={"k": 3})

# ==========================================
# 2. UTILIDADES
# ==========================================

def _strip_markdown(content: str) -> str:
    if "```" in content:
        partes = content.split("```")
        content = partes[1] if len(partes) > 1 else content
        if content.startswith("json"):
            content = content[4:]
        elif content.startswith("cypher"):
            content = content[6:]
    return content.strip()

def normalizar(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii").lower()

# ==========================================
# 3. EXTRACCIÓN PARA FASE VECTORIAL
# ==========================================

def extraer_parametros_vectoriales(pregunta: str) -> tuple[str, list[str]]:
    prompt = f"""Analizá la pregunta jurídica y extraé parámetros para búsqueda semántica.
Devolvé un JSON con:
- "sujeto": El tipo societario u organismo en lenguaje natural (ej: "sociedad anonima", "IGJ", "SAS").
- "frases_vectoriales": Lista de 2 o 3 frases en lenguaje natural. Incluí el número de artículo si se menciona.
Devuelve SOLO el JSON.
Pregunta: {pregunta}"""
    try:
        respuesta = llm.invoke(prompt)
        data = json.loads(_strip_markdown(str(respuesta.content)))
        return str(data.get("sujeto", "")), data.get("frases_vectoriales", [pregunta])
    except Exception:
        return "", [pregunta]

_STOPWORDS = {"sociedad", "capital", "social", "socios"}

def filtrar_por_sujeto(docs: list, sujeto: str) -> list:
    if not sujeto:
        return docs
    words = [w for w in normalizar(sujeto).split() if len(w) > 4 and w not in _STOPWORDS]
    if not words:
        return docs
    keyword = max(words, key=len)
    filtrados = [
        doc for doc in docs
        if keyword in normalizar(doc.page_content)
        or keyword in normalizar(str(doc.metadata.get("ubicacion", "")))
    ]
    return filtrados if len(filtrados) >= 2 else docs

# ==========================================
# 4. MOTOR CYPHER DINÁMICO
# ==========================================

def _cargar_etiquetas_entidades(driver) -> list[str]:
    with driver.session() as session:
        result = session.run("""
            MATCH (n)
            WHERE NOT n:Articulo AND NOT n:Norma
            RETURN DISTINCT labels(n)[0] AS label
            ORDER BY label
        """)
        return [row["label"] for row in result if row["label"]]


class MotorCypherDinamico:
    _CLAUSULAS_ESCRITURA = {"DELETE", "DETACH", "REMOVE", "SET", "MERGE", "CREATE", "DROP", "CALL"}

    def __init__(self, driver, llm_model, etiquetas_entidades: list[str], log=None):
        self.driver = driver
        self.llm    = llm_model
        self.log    = log or logging.getLogger(__name__)

        relaciones_fmt = "\n  ".join(RELACIONES_PERMITIDAS)
        etiquetas_fmt  = " | ".join(etiquetas_entidades) if etiquetas_entidades else "(ninguna cargada)"

        self._esquema = f"""
NODOS Y PROPIEDADES REALES:
  (:Norma        {{id: "Ley_19550",             numero: "19.550", titulo: "Ley General de Sociedades"}})
  (:Norma        {{id: "Decreto_1493_82",        numero: "1493/82", titulo: "Reglamentación Ley 22.315"}})
  (:Articulo     {{id: "Art_163_Ley_19550",     numero: "163", texto: "...", ubicacion: "..."}})
  (:<Etiqueta>   {{id: "NOMBRE_EN_MAYUSCULAS_CON_GUIONES"}})
    — La propiedad de búsqueda es SIEMPRE "id", nunca "nombre".
    — Etiquetas de entidades ontológicas presentes en la DB:
      {etiquetas_fmt}

RELACIONES ENTRE NORMAS:
  (:Norma)-[:CONTIENE]->(:Articulo)
  (:Norma)-[:APLICA_SUPLETORIAMENTE]->(:Norma)   // Ley_27349 → Ley_19550
  (:Norma)-[:REGLAMENTA]->(:Norma)               // Ley_22315 → Ley_19550 y Ley_27349
                                                 // Decreto_1493_82 → Ley_22315
  (:Articulo)-[:REMITE_A]->(:Articulo)           // remisiones explícitas entre artículos

RELACIONES ARTÍCULO ↔ ENTIDAD:
  Tipos disponibles:
  {relaciones_fmt}
"""

        self._ejemplo = """
EJEMPLO — supletoriedad (Ley 27349 aplica Ley 19550 supletoriamente):
Pregunta: "¿Cuáles son los deberes del administrador de una SAS?"
Cypher:
OPTIONAL MATCH (art_sas:Articulo)-[r]-(sas:SociedadPorAccionesSimplificada)
WHERE type(r) IN ['REGULA', 'DEFINE', 'MENCIONA']

MATCH (norma_sas:Norma)-[:CONTIENE]->(art_sas)
OPTIONAL MATCH (norma_sas)-[:APLICA_SUPLETORIAMENTE]->(norma_sup:Norma)-[:CONTIENE]->(art_sup:Articulo)
WHERE toLower(art_sup.texto) CONTAINS 'administrador' OR toLower(art_sup.texto) CONTAINS 'deber'

WITH collect(DISTINCT art_sas) + collect(DISTINCT art_sup) AS todos
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
4. Para supletoriedad: (norma)-[:APLICA_SUPLETORIAMENTE]->(norma_sup)-[:CONTIENE]->(art).
5. Para decreto reglamentario: (decreto)-[:REGLAMENTA]->(ley)-[:CONTIENE]->(art).
6. Retorná exactamente estas columnas: id, numero, texto.
7. LIMIT 5.

PREGUNTA:
{pregunta}
Cypher:"""

    @staticmethod
    def _postprocesar(cypher: str) -> str:
        """Corrige el patrón inválido UNWIND x AS y \\n WHERE → UNWIND x AS y \\n WITH y WHERE."""
        return re.sub(
            r'(UNWIND\s+\S+\s+AS\s+(\w+))(\s*\n\s*)WHERE',
            lambda m: f"{m.group(1)}{m.group(3)}WITH {m.group(2)} WHERE",
            cypher,
            flags=re.IGNORECASE,
        )

    def consultar(self, pregunta: str) -> list[dict]:
        self.log.info("  [Grafo] Generando Cypher dinámicamente...")
        try:
            respuesta_llm = self.llm.invoke(self._generar_prompt(pregunta))
            cypher = _strip_markdown(str(respuesta_llm.content))
            cypher = self._postprocesar(cypher)

            palabras = set(cypher.upper().split())
            if palabras & self._CLAUSULAS_ESCRITURA:
                self.log.warning(f"  [Grafo] Cypher rechazado: {palabras & self._CLAUSULAS_ESCRITURA}")
                return []

            self.log.info(f"  [Grafo] Cypher:\n{'-'*30}\n{cypher}\n{'-'*30}")

            with self.driver.session() as session:
                records = session.execute_read(lambda tx: tx.run(cypher).data())
                return [r for r in records if r.get("id") and r.get("texto")]

        except Exception as e:
            self.log.error(f"  [Grafo] Error: {e}")
            return []


_etiquetas_entidades = _cargar_etiquetas_entidades(neo4j_driver)
logger.info(f"[Init] Etiquetas ontológicas cargadas: {_etiquetas_entidades}")
motor_cypher = MotorCypherDinamico(neo4j_driver, llm_cypher, _etiquetas_entidades, log=logger)

# ==========================================
# 5. TRAVERSALS DE GRAFO
# ==========================================

def seguir_remite_a(article_ids: list[str]) -> list[dict]:
    """Traversa relaciones REMITE_A artículo → artículo para traer artículos referenciados."""
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

template_respuesta = """Eres un asistente legal experto en derecho notarial y societario argentino.

INSTRUCCIONES CRÍTICAS:
- Usá ÚNICAMENTE el contexto provisto. No inventes.
- Sé EXHAUSTIVO: si el contexto menciona capital, dirección, gobierno, publicidad, sanciones, plazos, etc., incluilos TODOS.
- Citá TODOS los artículos relevantes con su número y norma de origen.
- Si un artículo del contexto trata sobre un tipo societario u organismo DIFERENTE al preguntado, IGNORALO completamente.

CONTEXTO LEGAL RECUPERADO:
{context}

PREGUNTA DEL USUARIO:
{question}

RESPUESTA (exhaustiva, citando todos los artículos relevantes):
"""

template_revision = """Eres un revisor legal experto en derecho societario argentino.
Tu tarea es corregir la respuesta si es necesario y devolverla como texto final.

Verificá que la respuesta:
1. Cubra TODOS los aspectos relevantes del contexto.
2. Si la pregunta requiere normativas subsidiarias o jerárquicamente inferiores (ej. SAS aplicando LSC, decreto reglamentando ley), explicá la conexión si el contexto lo avala.
3. No incluya información de tipos societarios u organismos distintos al preguntado.

Si la respuesta es correcta y completa, devolvela exactamente igual.
Si necesita correcciones o completarla, devolvé la versión corregida.

CRÍTICO: Devolvé ÚNICAMENTE el texto de la respuesta legal. Sin análisis, sin evaluaciones, sin comentarios sobre la calidad de la respuesta.

CONTEXTO LEGAL:
{context}

PREGUNTA ORIGINAL:
{question}

RESPUESTA A REVISAR:
{answer}

RESPUESTA FINAL (solo el texto de la respuesta, sin meta-comentarios):"""

answer_chain = ChatPromptTemplate.from_template(template_respuesta) | llm | StrOutputParser()
review_chain = ChatPromptTemplate.from_template(template_revision) | llm | StrOutputParser()


def responder(pregunta: str) -> str:
    t0 = time.time()

    sujeto, frases_vectoriales = extraer_parametros_vectoriales(pregunta)
    logger.info(f"  [Fase 1] Sujeto extraído: '{sujeto}' ({time.time()-t0:.1f}s)")

    vistos = set()
    textos_contexto = []
    article_ids = []

    # Fase 2: búsqueda vectorial
    logger.info("  [Fase 2] Buscando en Base Vectorial...")
    docs_raw = []
    for frase in frases_vectoriales + [pregunta]:
        for doc in retriever.invoke(frase):
            docs_raw.append(doc)

    docs_filtrados = filtrar_por_sujeto(docs_raw, sujeto)
    ids_aceptados = {str(d.metadata.get("id", "")) for d in docs_filtrados}
    descartados_por_id: dict = {}
    for d in docs_raw:
        doc_id = str(d.metadata.get("id", ""))
        if doc_id and doc_id not in ids_aceptados and doc_id not in descartados_por_id:
            descartados_por_id[doc_id] = d

    for doc in docs_filtrados:
        doc_id = str(doc.metadata.get("id", ""))
        if doc_id and doc_id not in vistos:
            vistos.add(doc_id)
            article_ids.append(doc_id)
            textos_contexto.append(doc.page_content)
            logger.info(f"    • [Vector] Art. {doc.metadata.get('art', '')} [{doc.metadata.get('norma_id', '')}]")
    if descartados_por_id:
        logger.info(f"    (+ {len(descartados_por_id)} descartados por filtro de sujeto):")
        for doc in descartados_por_id.values():
            norma = doc.metadata.get('norma_id') or doc.metadata.get('ley', '?')
            logger.info(f"      ✗ Art. {doc.metadata.get('art', '?')} [{norma}]")
    logger.info(f"  [Fase 2 completada en {time.time()-t0:.1f}s]")

    # Fase 3: Cypher dinámico
    logger.info("  [Fase 3] Buscando en Grafo Dinámico (Text-to-Cypher)...")
    for art in motor_cypher.consultar(pregunta):
        art_id = str(art.get("id", ""))
        if art_id and art_id not in vistos:
            vistos.add(art_id)
            article_ids.append(art_id)
            textos_contexto.append(
                f"FUENTE: Grafo Ontológico\nARTICULO: {art.get('numero', '')}\nTEXTO: {art.get('texto', '')}"
            )
            logger.info(f"    • [Grafo] Art. {art.get('numero', '')} [{art_id.split('_Ley_')[-1] if '_Ley_' in art_id else art_id}]")
    logger.info(f"  [Fase 3 completada en {time.time()-t0:.1f}s]")

    # Fase 3.5: traversal REMITE_A
    logger.info("  [Fase 3.5] Siguiendo remisiones explícitas (REMITE_A)...")
    for art in seguir_remite_a(article_ids):
        art_id = str(art.get("id", ""))
        if art_id and art_id not in vistos:
            vistos.add(art_id)
            article_ids.append(art_id)
            origen_num = art["citado_desde"].replace("Art_", "").split("_Ley_")[0]
            norma_ref  = art_id.split("_Ley_")[-1]
            textos_contexto.append(
                f"FUENTE: Ley {norma_ref} (referenciada por Art. {origen_num})\n"
                f"ARTICULO: {art.get('numero', '')}\n"
                f"TEXTO: {art.get('texto', '')}"
            )
            logger.info(f"    • [Remisión] Art. {art.get('numero', '')} [Ley {norma_ref}] ← Art. {origen_num}")
    logger.info(f"  [Fase 3.5 completada en {time.time()-t0:.1f}s]")

    logger.info(f"  Total artículos únicos: {len(vistos)}")

    # Fase 4: vecindario ontológico
    entidades = obtener_entidades_relacionadas(article_ids)
    logger.info(f"  Entidades relacionadas: {len(entidades)}")

    # Fase 5: generar y revisar respuesta
    context = "\n\n---\n\n".join(textos_contexto) + format_entidades(entidades)
    logger.info("  Generando respuesta...")
    respuesta_inicial = answer_chain.invoke({"context": context, "question": pregunta})
    logger.info("  Revisando...")
    resultado = review_chain.invoke({
        "context": context,
        "question": pregunta,
        "answer": respuesta_inicial,
    })

    logger.info(f"  Tiempo de respuesta: {time.time()-t0:.1f}s")
    return resultado


# ==========================================
# 7. PREGUNTAS DE REFERENCIA (4 NORMAS)
# ==========================================

preguntas = [
    # --- Ley 19550 (LSC) ---
    # 1. Constitución SA
    "¿Cuáles son los requisitos mínimos que debe contener el estatuto de una Sociedad Anónima "
    "al momento de su constitución y qué órganos son obligatorios?",

    # 2. SRL - administración y decisiones
    "¿Cuál es el régimen de administración de la Sociedad de Responsabilidad Limitada "
    "y cómo se adoptan las decisiones en la reunión de socios?",

    # --- Ley 27349 (SAS) ---
    # 3. SAS - limitaciones y transformación (testea REMITE_A → Art. 299 LSC)
    "Si una SAS comienza a realizar actividades que la encuadran en los supuestos del "
    "artículo 299 de la Ley General de Sociedades, ¿qué obligación le impone la Ley 27349 "
    "y en qué plazo debe cumplirla? ¿Qué responsabilidad asumen los socios si no lo hace?",

    # 4. SAS - deberes del administrador (testea REMITE_A → Art. 157 LSC)
    "¿Cuáles son los deberes, obligaciones y responsabilidades de los administradores "
    "de una SAS? ¿Qué artículo de la LSC se aplica supletoriamente y qué establece?",

    # --- Ley 22315 (IGJ orgánica) ---
    # 5. IGJ - fiscalización SA
    "¿Cuáles son las funciones específicas que ejerce la IGJ sobre las sociedades por "
    "acciones en materia de constitución, capital, disolución y debentures según la Ley 22315?",

    # 6. IGJ - sanciones y recursos (testea cruce 22315 + 19550)
    "¿Qué sanciones puede aplicar la IGJ a directores de una SA que incumplan sus "
    "obligaciones, ante qué tribunal se apelan esas resoluciones y en qué plazo?",

    # --- Decreto 1493/82 ---
    # 7. Decreto - comunicaciones obligatorias
    "¿Qué situaciones deben comunicar obligatoriamente las entidades sujetas a "
    "fiscalización de la IGJ según el Decreto 1493/82 y en qué plazo?",

    # 8. Decreto - documentación de asambleas
    "¿Con qué anticipación mínima deben las sociedades comunicar a la IGJ la convocatoria "
    "de sus asambleas y qué documentación deben presentar después de su celebración "
    "según el Decreto 1493/82?",

    # --- Preguntas transversales (múltiples normas) ---
    # 9. LSC + 22315 + Decreto - SA fiscalización permanente
    "¿Qué sociedades anónimas quedan bajo fiscalización permanente de la IGJ según el "
    "artículo 299 de la LSC, qué funciones ejerce la IGJ sobre ellas según la Ley 22315 "
    "y qué recaudos exige el Decreto 1493/82 para sus asambleas?",

    # 10. SAS + 22315 + Decreto - inscripción y control de una SAS en CABA
    "¿Puede una persona humana constituir una SAS unipersonal en la Ciudad de Buenos Aires? "
    "¿Qué pasos debe seguir ante la IGJ para inscribirla, qué controla el organismo "
    "en ese proceso y qué plazos fija el Decreto 1493/82?",
]

# ==========================================
# 8. EJECUCIÓN BATCH
# ==========================================

_txt_path = os.path.join(_logs_dir, f"resultados_dinamico_{_ts}.txt")
_sep      = "=" * 80

logger.info(f"Iniciando evaluación de {len(preguntas)} preguntas.")
logger.info(f"Resultados → {_txt_path}")

with open(_txt_path, "w", encoding="utf-8") as txt:
    for i, pregunta in enumerate(preguntas, 1):
        logger.info(f"\n{'─'*60}\nPREGUNTA {i}/{len(preguntas)}: {pregunta}")
        try:
            respuesta = responder(pregunta)
        except Exception as e:
            logger.error(f"ERROR en pregunta {i}: {e}")
            respuesta = f"[ERROR: {e}]"

        bloque = (
            f"{_sep}\n"
            f"PREGUNTA {i} de {len(preguntas)}:\n"
            f"{pregunta}\n\n"
            f"RESPUESTA:\n"
            f"{respuesta}\n\n"
        )
        txt.write(bloque)
        txt.flush()
        logger.info(f"Pregunta {i} completada y guardada.")

logger.info(f"\nEvaluación finalizada. Resultados en: {_txt_path}")
logger.info(f"Tiempo total de ejecución (incluyendo carga): {time.time() - _t_inicio_script:.1f}s")

neo4j_driver.close()
