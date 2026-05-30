"""Suite de evaluación batch del pipeline GraphRAG sobre la LSC — versión con
recuperación híbrida (ontológica + vectorial). Adapta lmjudgeLS.py incorporando
la búsqueda por grafo (buscar_articulos_por_conceptos) y los conceptos atómicos
en PascalCase de testLS2.py, manteniendo la estructura de evaluación batch y el
logging persistente a archivo de lmjudgeLS.py."""
import os, sys, json, unicodedata, logging, time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from utils.connectors import get_neo4j_driver, get_gemini_embeddings, get_gemini_llm
from langchain_neo4j import Neo4jVector
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

_ts = time.strftime("%Y%m%d_%H%M%S")
_logs_dir = os.path.join(BASE_DIR, "logs")
os.makedirs(_logs_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(os.path.join(_logs_dir, f"judge2_{_ts}.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("judge2")

llm = get_gemini_llm()
embeddings = get_gemini_embeddings()
neo4j_driver = get_neo4j_driver()

# node.id se incluye en metadata para poder hacer el traversal del grafo en pasos posteriores.
retrieval_query = """
OPTIONAL MATCH (norma:Norma)-[:CONTIENE]->(node)
RETURN
    "FUENTE: " + coalesce(norma.titulo, 'Ley General de Sociedades') + " (Ley " + coalesce(norma.numero, '19.550') + ")\n" +
    "ARTICULO: " + coalesce(node.numero, '') + "\n" +
    "TEXTO: " + coalesce(node.texto, '') AS text,
    score,
    {ley: coalesce(norma.titulo, ''), art: coalesce(node.numero, ''), id: node.id, ubicacion: coalesce(node.ubicacion, '')} AS metadata
"""

vector_db = Neo4jVector.from_existing_index(
    embeddings,
    url=os.getenv("NEO4J_URI"),
    username=os.getenv("NEO4J_USERNAME"),
    password=os.getenv("NEO4J_PASSWORD"),
    index_name="index_articulos",
    retrieval_query=retrieval_query
)

# score_threshold=0.85 descarta artículos con baja similitud semántica para reducir
# ruido en el contexto; k=2 limita resultados por concepto para no saturar el prompt.
retriever = vector_db.as_retriever(search_type="similarity_score_threshold", search_kwargs={"score_threshold": 0.85, "k": 2})

MAX_CONCEPTOS = 8


# Elimina bloques de código markdown (```json ... ```) que el LLM puede incluir en
# su respuesta, dejando solo el JSON puro apto para json.loads().
def _strip_markdown(content: str) -> str:
    if "```" in content:
        partes = content.split("```")
        content = partes[1] if len(partes) > 1 else content
        if content.startswith("json"):
            content = content[4:]
    return content.strip()


# Normaliza a ASCII minúsculas para comparaciones insensibles a tildes y mayúsculas.
def normalizar(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii").lower()


# Descompone la pregunta en un sujeto jurídico principal (PascalCase) y una lista de
# sub-temas atómicos para guiar la búsqueda. Los conceptos son atómicos (sin el sujeto
# concatenado) para maximizar la coincidencia flexible de la fase ontológica en Cypher.
def extraer_consulta(pregunta: str) -> tuple[str, list[str]]:
    prompt = f"""Eres un experto en derecho societario argentino y arquitecto de bases de datos de grafos.
    Analizá la pregunta jurídica e identificá el sujeto principal y los conceptos legales involucrados.

    Devolvé un JSON con dos campos:
    - "sujeto": El tipo societario u objeto jurídico principal (ej: "SociedadAnonima", "SociedadDeResponsabilidadLimitada") convertido a PascalCase.
    - "conceptos": Lista de hasta {MAX_CONCEPTOS} términos o entidades legales completamente ATÓMICOS y breves (de 1 a 3 palabras máximo) que describan los sub-temas (ej: "ReservaLegal", "CapitalSocial", "CondicionExcepcional", "ParticipacionesSociales").

    CRÍTICO: No concatenes el sujeto dentro de los conceptos. Deben ser conceptos puros y aislados.

    Devuelve SOLO el JSON. Sin explicación, sin markdown.

    Ejemplo entrada: "¿Cuáles son las características de la sociedad anónima?"
    Ejemplo salida:
    {{"sujeto": "SociedadAnonima", "conceptos": ["EstatutoSocial", "Directorio", "AsambleaAccionistas", "ConstitucionSocietaria", "Publicidad", "CapitalSocial", "Accion"]}}

    Pregunta: {pregunta}"""

    respuesta = llm.invoke(prompt)
    content = _strip_markdown(str(respuesta.content).strip())
    try:
        data = json.loads(content)
        sujeto = str(data.get("sujeto", ""))
        conceptos = data.get("conceptos", [])
        if isinstance(conceptos, list):
            return sujeto, conceptos[:MAX_CONCEPTOS]
        return sujeto, [pregunta]
    except Exception:
        return "", [pregunta]


# Palabras genéricas que no sirven para distinguir tipos societarios entre sí.
_STOPWORDS = {"sociedad", "capital", "social", "socios"}


# Descarta documentos recuperados que no correspondan al tipo societario de la pregunta.
# Usa la palabra más larga del sujeto como discriminador (ej: "responsabilidad" para SRL,
# "anonima" para SA) y verifica tanto el texto del artículo como su ubicación jerárquica.
# Fallback: si el filtro deja menos de 2 resultados, devuelve todos para no vaciar el contexto.
def filtrar_por_sujeto(docs: list, sujeto: str) -> list:
    if not sujeto:
        return docs
    words = [w for w in normalizar(sujeto).split() if len(w) > 4 and w not in _STOPWORDS]
    if not words:
        return docs
    # La palabra más larga suele ser la más distintiva del tipo societario.
    keyword = max(words, key=len)
    filtrados = [
        doc for doc in docs
        if keyword in normalizar(doc.page_content)
        or keyword in normalizar(str(doc.metadata.get("ubicacion", "")))
    ]
    return filtrados if len(filtrados) >= 2 else docs


# Fase ontológica del pipeline híbrido: navega el grafo desde los nodos de entidad
# hacia los artículos que los regulan usando coincidencia flexible por nombre, etiqueta
# o alias. Ordena los resultados por cantidad de entidades coincidentes (relevancia).
def buscar_articulos_por_conceptos(conceptos: list[str], sujeto: str) -> list[dict]:
    # Combinamos sujeto y conceptos en una sola lista de búsqueda.
    terminos_busqueda = conceptos + [sujeto]

    query = """
    UNWIND $terminos AS termino
    MATCH (entidad)
    // Buscamos coincidencia flexible por nombre o por los alias que creamos
    WHERE toLower(entidad.nombre) CONTAINS toLower(termino)
       OR toLower(labels(entidad)[0]) CONTAINS toLower(termino)
       OR any(alias IN coalesce(entidad.alias, []) WHERE toLower(alias) CONTAINS toLower(termino))

    // Caminamos el grafo hacia los artículos que regulan o mencionan ese concepto
    MATCH (art:Articulo)-[r]->(entidad)
    WHERE type(r) IN ['REGULA', 'MENCIONA', 'AUTORIZA', 'ESTABLECE_REQUISITOS_DE']

    RETURN DISTINCT
        art.id AS id,
        art.numero AS numero,
        art.texto AS texto,
        count(entidad) AS relevancia
    ORDER BY relevancia DESC
    """
    with neo4j_driver.session() as session:
        return [dict(row) for row in session.run(query, terminos=terminos_busqueda)]


# Traversal del grafo: dado un conjunto de artículos, devuelve todas las entidades
# ontológicas conectadas (roles, tipos societarios, procesos, etc.) para enriquecer
# el contexto del LLM con relaciones explícitas del grafo más allá del texto plano.
# Usa coalesce para tolerar nodos que usen 'nombre' en lugar de 'id' como identificador.
def obtener_entidades_relacionadas(article_ids: list[str]) -> list[dict]:
    if not article_ids:
        return []
    query = """
    UNWIND $ids AS art_id
    MATCH (art:Articulo {id: art_id})-[r]-(entidad)
    WHERE NOT entidad:Norma AND NOT entidad:Articulo
    RETURN DISTINCT
        labels(entidad)[0] AS tipo,
        coalesce(entidad.nombre, entidad.id, 'Sin Nombre') AS id,
        type(r)           AS relacion,
        art_id            AS articulo
    ORDER BY tipo, id
    """
    with neo4j_driver.session() as session:
        return [dict(row) for row in session.run(query, ids=article_ids)]


# Concatena el contenido de los documentos recuperados separados por un divisor visual.
def format_docs(docs) -> str:
    return "\n\n---\n\n".join(doc.page_content for doc in docs)


# Formatea las entidades del grafo como una sección legible para incluir al final del
# contexto del LLM, indicando tipo, relación y artículo de origen de cada entidad.
def format_entidades(entidades: list[dict]) -> str:
    if not entidades:
        return ""
    lines = ["\n\nENTIDADES JURÍDICAS RELACIONADAS:"]
    for e in entidades:
        lines.append(f"  [{e['tipo']}] {e['id']}  —  {e['relacion']}  →  Art. {e['articulo']}")
    return "\n".join(lines)


template_respuesta = """
Eres un asistente legal experto en derecho notarial y societario argentino.

INSTRUCCIONES CRÍTICAS:
1. Responde DIRECTAMENTE y de forma precisa a la pregunta del usuario.
2. Si la ley enumera excepciones o condiciones, lístalas TODAS sin omitir ninguna.
3. Usá ÚNICAMENTE el contexto provisto. No inventes.
4. Si un artículo del contexto trata sobre un tipo societario o tema diferente al preguntado, IGNORALO completamente.

CONTEXTO LEGAL RECUPERADO:
{context}

PREGUNTA DEL USUARIO:
{question}

RESPUESTA:
"""

template_revision = """
Eres un revisor legal experto en derecho societario argentino.
Tu tarea es revisar la respuesta generada y corregirla si es necesario.

VERIFICÁ que la respuesta:
1. Cubra TODOS los aspectos relevantes presentes en el contexto (capital, órganos de gobierno, constitución, publicidad, etc.)
2. No confunda ni mezcle el tipo societario preguntado con otro tipo societario
3. No incluya información de artículos que hablan de otro tipo societario distinto al preguntado

Si la respuesta está incompleta, completala con el contexto disponible.
Si incluye información incorrecta de otro tipo societario, eliminala.
Si es correcta y completa, devolvela tal cual.

CONTEXTO LEGAL:
{context}

PREGUNTA ORIGINAL:
{question}

RESPUESTA A REVISAR:
{answer}

RESPUESTA FINAL (corregida y completa):
"""

prompt_respuesta = ChatPromptTemplate.from_template(template_respuesta)
prompt_revision = ChatPromptTemplate.from_template(template_revision)
answer_chain = prompt_respuesta | llm | StrOutputParser()
review_chain = prompt_revision | llm | StrOutputParser()


# Pipeline completo de respuesta con recuperación híbrida y revisión automática en dos etapas.
# Fase 2A (ontológica): navega el grafo desde entidades semánticas hacia artículos que las regulan.
# Fase 2B (vectorial): complementa con búsqueda por similitud de embedding sobre el índice.
# Ambas fases se deduplicán por ID para evitar que el mismo artículo aparezca dos veces en el contexto.
def responder(pregunta: str) -> str:
    # 1. Extraer sujeto principal y sub-temas de búsqueda
    sujeto, conceptos = extraer_consulta(pregunta)
    logger.info(f"Sujeto: '{sujeto}'")
    logger.info(f"Conceptos extraídos: {conceptos}")

    vistos: set[str] = set()
    textos_contexto = []
    article_ids = []

    # 2A. BÚSQUEDA HÍBRIDA - Fase Ontológica (Grafo)
    logger.info("Buscando en Grafo Ontológico...")
    articulos_grafo = buscar_articulos_por_conceptos(conceptos, sujeto)
    for art in articulos_grafo:
        art_id = str(art["id"])
        if art_id not in vistos:
            vistos.add(art_id)
            article_ids.append(art_id)
            textos_contexto.append(f"ARTICULO: {art['numero']}\nTEXTO: {art['texto']}")
            logger.info(f"  [Grafo] Art. {art['numero']} recuperado.")

    # 2B. BÚSQUEDA HÍBRIDA - Fase Semántica (Vectorial LangChain)
    logger.info("Buscando en Base Vectorial...")
    docs_raw = []
    for i, concepto in enumerate(conceptos, 1):
        logger.info(f"  Buscando {i}/{len(conceptos)}: '{concepto}'...")
        for doc in retriever.invoke(concepto):
            docs_raw.append(doc)

    # 3. Filtrar artículos de la fase vectorial que no correspondan al sujeto principal
    docs = filtrar_por_sujeto(docs_raw, sujeto)
    descartados = len(docs_raw) - len(docs)
    if descartados:
        logger.info(f"  Descartados {descartados} artículo(s) de otros tipos societarios.")

    for doc in docs:
        doc_id = str(doc.metadata.get("id", ""))
        if doc_id and doc_id not in vistos:
            vistos.add(doc_id)
            article_ids.append(doc_id)
            textos_contexto.append(doc.page_content)
            logger.info(f"  [Vector] Art. {doc.metadata.get('art', '')} recuperado.")

    logger.info(f"Artículos recuperados: {article_ids}")

    # 4. Traversal del grafo para obtener entidades relacionadas a los artículos recuperados
    entidades = obtener_entidades_relacionadas(article_ids)
    logger.info(f"Entidades relacionadas: {len(entidades)}")

    # 5. Generar respuesta inicial
    context = "\n\n---\n\n".join(textos_contexto) + format_entidades(entidades)
    respuesta_inicial = answer_chain.invoke({"context": context, "question": pregunta})
    logger.info(f"Respuesta inicial generada ({len(respuesta_inicial)} chars)")

    # 6. Revisar completitud y corregir mezclas de tipos societarios
    logger.info("Revisando respuesta...")
    respuesta_final = review_chain.invoke({
        "context": context,
        "question": pregunta,
        "answer": respuesta_inicial,
    })
    logger.info(f"Revisión completada ({len(respuesta_final)} chars)")
    return respuesta_final


# --- Ejecución ---
preguntas_test_graphrag = [
    # 1. Prueba de Sociedad de Responsabilidad Limitada (Arts. 146-162)
    "¿Qué mayorías exactas de capital se requieren en una Sociedad de Responsabilidad Limitada para modificar el contrato social si el mismo no lo regula expresamente?",
    
    # 2. Prueba del conflictivo Art. 94 bis y transformación de pleno derecho
    "Si una sociedad en comandita simple sufre la reducción a uno del número de socios, ¿entra automáticamente en causal de disolución o qué sucede legalmente?",
    
    # 3. Prueba del nuevo nodo: Sociedad Constituida en el Extranjero (Arts. 118-124)
    "Si una sociedad constituida en el extranjero desea establecer una sucursal en Argentina para ejercer habitualmente su objeto, ¿qué requisitos documentales y de domicilio debe cumplir?",
    
    # 4. Prueba del nuevo nodo: Debentures + Sociedad Anónima (Arts. 325-360)
    "¿Cuáles son las facultades procesales y de administración que asume el banco fiduciario si la sociedad emisora entra en mora por más de 30 días en el pago de debentures con garantía flotante?",
    
    # 5. Prueba del nuevo nodo: SAPEM (Arts. 308-314)
    "En una Sociedad Anónima con Participación Estatal Mayoritaria, cuando la minoría ejerce su derecho a elegir directores, ¿quiénes tienen prohibición absoluta de ser directores por el capital privado?",
    
    # 6. Prueba de Sociedad de Capital e Industria (Arts. 141-145)
    "En una sociedad de capital e industria, si el contrato constitutivo guarda silencio sobre la parte de los beneficios que le corresponde al socio industrial, ¿cómo debe determinarse?",
    
    # 7. Prueba de Sociedad en Comandita por Acciones (Arts. 315-324)
    "¿Puede el socio comanditario en una Sociedad en Comandita por Acciones solicitar judicialmente la remoción del administrador? ¿Qué porcentaje de capital mínimo necesita para hacerlo?",
    
    # 8. Prueba de Sociedad Colectiva (Arts. 125-133)
    "Si el contrato social no exige justa causa, ¿es posible remover al administrador de una sociedad colectiva en cualquier tiempo? ¿Qué derechos tienen los socios disconformes?",
    
    # 9. Prueba de Parte General - Nulidades y Subsanación (Arts. 16-26)
    "Si una sociedad se constituye omitiendo un requisito tipificante esencial, ¿es nula definitivamente o los socios tienen algún mecanismo legal para subsanar el error?",
    
    # 10. Prueba de Sociedad Anónima - Incompatibilidades (Arts. 163-307)
    "¿Puede un funcionario de la administración pública actual ejercer el cargo de director en una Sociedad Anónima convencional si su área de gobierno se relaciona con el objeto de la empresa?"
]

# --- Ejecución batch ---
_txt_path = os.path.join(_logs_dir, f"resultados2_{_ts}.txt")
_sep = "=" * 80

logger.info(f"Iniciando evaluación de {len(preguntas_test_graphrag)} preguntas.")
logger.info(f"Resultados → {_txt_path}")

with open(_txt_path, "w", encoding="utf-8") as txt:
    for i, pregunta in enumerate(preguntas_test_graphrag, 1):
        logger.info(f"\n{'─'*60}\nPREGUNTA {i}/{len(preguntas_test_graphrag)}: {pregunta}")
        try:
            respuesta = responder(pregunta)
        except Exception as e:
            logger.error(f"ERROR en pregunta {i}: {e}")
            respuesta = f"[ERROR: {e}]"

        bloque = (
            f"{_sep}\n"
            f"PREGUNTA {i} de {len(preguntas_test_graphrag)}:\n"
            f"{pregunta}\n\n"
            f"RESPUESTA:\n"
            f"{respuesta}\n\n"
        )
        txt.write(bloque)
        txt.flush()
        logger.info(f"Pregunta {i} completada y guardada.")

logger.info(f"Evaluación finalizada. Resultados en: {_txt_path}")
neo4j_driver.close()
