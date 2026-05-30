"""Suite de evaluación batch del pipeline GraphRAG sobre la LSC.
Ejecuta un conjunto curado de preguntas de referencia y persiste las respuestas en un
archivo .txt con timestamp para revisión manual de calidad. Implementa un pipeline de
dos etapas: answer_chain genera la respuesta inicial y review_chain la verifica para
detectar omisiones y contaminación cruzada entre tipos societarios."""
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
        logging.FileHandler(os.path.join(_logs_dir, f"judge_{_ts}.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("judge")

llm = get_gemini_llm()
embeddings = get_gemini_embeddings()
neo4j_driver = get_neo4j_driver()

# node.id en metadata para poder hacer el traversal posterior
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

retriever = vector_db.as_retriever(search_kwargs={"k": 3})


MAX_CONCEPTOS = 8


def _strip_markdown(content: str) -> str:
    if "```" in content:
        partes = content.split("```")
        content = partes[1] if len(partes) > 1 else content
        if content.startswith("json"):
            content = content[4:]
    return content.strip()


def normalizar(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii").lower()


def extraer_consulta(pregunta: str) -> tuple[str, list[str], list[str]]:
    prompt = f"""Eres un experto en derecho societario argentino y arquitecto de sistemas de búsqueda híbrida (RAG).
    Analizá la pregunta jurídica y extraé los términos de búsqueda optimizados para dos motores distintos: uno vectorial (semántico) y uno de grafos (ontológico).

    Devolvé un JSON con tres campos:
    - "sujeto": El tipo societario u objeto jurídico en lenguaje natural (ej: "sociedad anonima", "sociedad de responsabilidad limitada", "sociedad comercial").
    - "frases_vectoriales": Lista de 2 o 3 frases descriptivas en lenguaje natural para búsqueda semántica. CRÍTICO: Si la pregunta menciona un número de artículo específico, INCLÚYELO aquí (ej: ["requisitos instrumento constitutivo art 11", "contenido contrato social"]).
    - "nodos_grafo": Lista de hasta {MAX_CONCEPTOS} términos completamente ATÓMICOS (de 1 a 3 palabras máximo) en formato PascalCase para buscar en la ontología (ej: "InstrumentoConstitutivo", "CapitalSocial", "DenominacionSocial").

    Devuelve SOLO el JSON. Sin explicación, sin markdown.

    Pregunta: {pregunta}"""

    respuesta = llm.invoke(prompt)
    content = _strip_markdown(str(respuesta.content).strip())
    try:
        data = json.loads(content)
        sujeto = str(data.get("sujeto", ""))
        frases_vectoriales = data.get("frases_vectoriales", [pregunta])
        nodos_grafo = data.get("nodos_grafo", [])
        return sujeto, frases_vectoriales, nodos_grafo[:MAX_CONCEPTOS]
    except Exception:
        # Fallback de seguridad: usamos la pregunta entera para el vector y nada para el grafo
        return "", [pregunta], []


# Palabras genéricas que no sirven para distinguir tipos societarios
_STOPWORDS = {"sociedad", "capital", "social", "socios"}

def filtrar_por_sujeto(docs: list, sujeto: str) -> list:
    """Descarta artículos que no correspondan al sujeto principal.
    Verifica texto del artículo Y ubicacion (capítulo/sección) para no excluir
    artículos que mencionan 'la sociedad' en lugar del nombre completo.
    """
    if not sujeto:
        return docs
    words = [w for w in normalizar(sujeto).split() if len(w) > 4 and w not in _STOPWORDS]
    if not words:
        return docs
    # La palabra más larga suele ser la más distintiva del tipo societario
    # ej: "responsabilidad" para SRL, "anonima" para SA, "colectiva" para SC
    keyword = max(words, key=len)

    filtrados = [
        doc for doc in docs
        if keyword in normalizar(doc.page_content)
        or keyword in normalizar(str(doc.metadata.get("ubicacion", "")))
    ]
    # Fallback: si el filtro deja menos de 2 resultados, devolver sin filtrar
    return filtrados if len(filtrados) >= 2 else docs

def buscar_articulos_por_conceptos(conceptos: list[str], sujeto: str) -> list[dict]:
    if not conceptos:
        return []
    
    query = """
    UNWIND $terminos AS termino
    MATCH (entidad)
    // Búsqueda limpia y directa: solo por nombre de nodo o por su etiqueta (Label)
    WHERE (toLower(entidad.nombre) CONTAINS toLower(termino)
       OR toLower(labels(entidad)[0]) CONTAINS toLower(termino))
       AND NOT entidad:Articulo AND NOT entidad:Norma
    
    // Caminamos el grafo hacia los artículos
    MATCH (art:Articulo)-[r]-(entidad)
    WHERE type(r) IN ['REGULA', 'MENCIONA', 'AUTORIZA', 'ESTABLECE_REQUISITOS_DE', 'EXIGE_PUBLICACION_A', 'ES_SINONIMO_DE']
    
    RETURN DISTINCT 
        art.id AS id, 
        art.numero AS numero, 
        art.texto AS texto,
        count(DISTINCT entidad) AS relevancia
    ORDER BY relevancia DESC
    LIMIT 3
    """
    with neo4j_driver.session() as session:
        return [dict(row) for row in session.run(query, terminos=conceptos)]

def obtener_entidades_relacionadas(article_ids: list[str]) -> list[dict]:
    """Traversal del grafo: dado un conjunto de artículos, devuelve todas las entidades conectadas."""
    if not article_ids:
        return []
    query = """
    UNWIND $ids AS art_id
    MATCH (art:Articulo {id: art_id})-[r]-(entidad)
    WHERE NOT entidad:Norma AND NOT entidad:Articulo
    RETURN DISTINCT
        labels(entidad)[0] AS tipo,
        entidad.id        AS id,
        type(r)           AS relacion,
        art_id            AS articulo
    ORDER BY tipo, id
    """
    with neo4j_driver.session() as session:
        return [dict(row) for row in session.run(query, ids=article_ids)]


def format_docs(docs) -> str:
    return "\n\n---\n\n".join(doc.page_content for doc in docs)


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
- Usá ÚNICAMENTE el contexto provisto. No inventes.
- Sé EXHAUSTIVO: si el contexto menciona capital, dirección, gobierno, publicidad, constitución, etc., incluilos TODOS.
- Citá TODOS los artículos relevantes, no solo el principal.
- Si un artículo del contexto trata sobre un tipo societario DIFERENTE al preguntado, IGNORALO completamente.

CONTEXTO LEGAL RECUPERADO:
{context}

PREGUNTA DEL USUARIO:
{question}

RESPUESTA (exhaustiva, citando todos los artículos relevantes):
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


def responder(pregunta: str) -> str:
    # 1. Extraer sujeto y conceptos diferenciados
    sujeto, frases_vectoriales, nodos_grafo = extraer_consulta(pregunta)
    logger.info(f"\nSujeto (Filtro): '{sujeto}'")
    logger.info(f"Frases Vectoriales: {frases_vectoriales}")
    logger.info(f"Nodos Grafo: {nodos_grafo}")

    vistos = set()
    textos_contexto = []
    article_ids = []

    # 2. BÚSQUEDA VECTORIAL (Motor Principal - Usa las frases naturales)
    logger.info("\nBuscando en Base Vectorial...")
    docs_raw = []
    # También inyectamos la pregunta original directamente por seguridad
    terminos_semanticos = frases_vectoriales + [pregunta] 
    
    for i, frase in enumerate(terminos_semanticos, 1):
        logger.info(f"  [{i}/{len(terminos_semanticos)}] Buscando vector: '{frase}'")
        for doc in retriever.invoke(frase):
            docs_raw.append(doc)

    docs = filtrar_por_sujeto(docs_raw, sujeto)
    descartados = len(docs_raw) - len(docs)
    
    for doc in docs:
        doc_id = str(doc.metadata.get("id", ""))
        if doc_id and doc_id not in vistos:
            vistos.add(doc_id)
            article_ids.append(doc_id)
            textos_contexto.append(doc.page_content)
            logger.info(f"  • [Vector] Art. {doc.metadata.get('art', '')} recuperado.")

    if descartados:
        logger.info(f"  (+ {descartados} descartados por filtro de sujeto)")

    # 3. BÚSQUEDA EN GRAFO ONTOLÓGICO (El Rescatista - Usa los nodos PascalCase)
    logger.info("\nBuscando en Grafo Ontológico...")
    if nodos_grafo:
        articulos_grafo = buscar_articulos_por_conceptos(nodos_grafo, sujeto)
        for art in articulos_grafo:
            art_id = str(art["id"])
            if art_id not in vistos:
                vistos.add(art_id)
                article_ids.append(art_id)
                textos_contexto.append(f"ARTICULO: {art['numero']}\nTEXTO: {art['texto']}")
                print(f"  • [Grafo] Art. {art['numero']} recuperado (Rescate Ontológico).")

    logger.info(f"\n{'─'*50}")
    logger.info(f"Total Artículos únicos recuperados: {len(article_ids)}")

    # 4. ENTIDADES DEL GRAFO (Construcción del vecindario)
    entidades = obtener_entidades_relacionadas(article_ids)
    logger.info(f"Entidades relacionadas extraídas: {len(entidades)}")
    logger.info(f"{'─'*50}")

    # 5. Generar y revisar respuesta
    context = "\n\n---\n\n".join(textos_contexto) + format_entidades(entidades)
    logger.info("Generando respuesta...")
    respuesta_inicial = answer_chain.invoke({"context": context, "question": pregunta})
    logger.info("Revisando...")
    return review_chain.invoke({
        "context": context,
        "question": pregunta,
        "answer": respuesta_inicial,
    })


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
_txt_path = os.path.join(_logs_dir, f"resultados_{_ts}.txt")
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