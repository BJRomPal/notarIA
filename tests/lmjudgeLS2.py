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
    # Preguntas sobre Disposiciones Generales y Requisitos (Extracción de listas y condiciones)
    "¿Cuáles son los requisitos ineludibles que debe contener el instrumento de constitución de cualquier sociedad según el artículo 11?",
    "¿Qué sucede con la responsabilidad de los socios frente a terceros si una sociedad se constituye omitiendo requisitos esenciales tipificantes (Sección IV)?",
    "¿Bajo qué condiciones excepcionales una sociedad puede tomar participaciones en otra sociedad por un monto superior a sus reservas libres y la mitad de su capital?",
    "¿Cuáles son las consecuencias jurídicas y responsabilidades patrimoniales para el socio aparente y el socio oculto?",
    "En caso de mora en la integración del aporte, ¿qué acciones legales específicas puede tomar la sociedad contra el socio incumplidor?",
    "¿En qué consisten las prestaciones accesorias, qué requisitos deben cumplir y por qué no integran el capital social?",
    "¿Cómo deben valuarse los aportes en especie en una Sociedad de Responsabilidad Limitada y quién asume la responsabilidad por una eventual sobrevaluación?",
    "¿Qué nivel de diligencia y responsabilidad asumen los administradores societarios, y cuál es el mecanismo exacto para eximirse de dicha responsabilidad?",

    # Preguntas sobre Procesos Complejos (Navegación de múltiples saltos en el grafo)
    "Según la ley, ¿cómo debe calcularse y qué límite porcentual tiene la constitución de la reserva legal obligatoria?",
    "¿Cuáles son los requisitos formales y de publicidad exigidos paso a paso para llevar a cabo la transformación de un tipo societario a otro?",
    "En un proceso de fusión, ¿qué información obligatoria y balances debe contener el compromiso previo de fusión firmado por los representantes?",
    "¿Qué plazos, condiciones y efectos establece la ley para que un socio disconforme ejerza su derecho de receso?",
    "¿Cuáles son las causales legales taxativas que provocan la disolución de una sociedad estipuladas en el artículo 94?",
    "¿Qué requisitos debe cumplir una sociedad constituida en el extranjero para establecer una sucursal y ejercer habitualmente su objeto social en Argentina?",

    # Preguntas Específicas de SRL (Filtro por tipo de entidad)
    "En una Sociedad de Responsabilidad Limitada, ¿qué mayorías exactas de capital se requieren para modificar el contrato social si el mismo no lo regula expresamente?",
    "¿Cuál es el procedimiento y los plazos legales si un socio de una SRL desea ceder sus cuotas a un tercero, pero el contrato limita dicha transmisibilidad y la sociedad ejerce su derecho de preferencia?",

    # Preguntas Específicas de SA (Conceptos jerárquicos y roles detallados)
    "¿Qué diferencias sustanciales existen entre el procedimiento de constitución de una Sociedad Anónima por acto único y por suscripción pública?",
    "¿Bajo qué circunstancias excepcionales permitidas por la ley puede una Sociedad Anónima adquirir las propias acciones que emitió?",
    "¿Qué materias y decisiones son de competencia exclusiva e indelegable de la Asamblea Extraordinaria en una Sociedad Anónima?",
    "¿Cómo funciona paso a paso el procedimiento de elección de directores por el sistema de voto acumulativo y qué proporción mínima de vacantes garantiza a la minoría?",
    "¿Qué personas están legalmente inhabilitadas o tienen prohibición absoluta para ejercer el cargo de director en una Sociedad Anónima?",
    "¿Cuáles son las atribuciones, deberes y obligaciones indelegables del síndico societario según el artículo 294?",
    "¿En qué supuestos específicos e incisos una Sociedad Anónima queda sujeta obligatoriamente a la fiscalización estatal permanente del artículo 299?",

    # Preguntas sobre Financiación (Conceptos muy específicos)
    "¿En qué se diferencian jurídicamente los debentures emitidos con garantía flotante de aquellos emitidos con garantía especial respecto a la disposición de los bienes afectados?",
    "¿Qué facultades procesales y administrativas asume el banco fiduciario como representante de los debenturistas si la sociedad emisora incurre en mora en el pago superior a 30 días?"
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
