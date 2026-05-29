"""Test de consulta RAG híbrida sobre la LSC: combina búsqueda ontológica en el grafo
(Fase 2A, Cypher) con búsqueda semántica vectorial (Fase 2B). La fase ontológica navega
desde conceptos legales hasta los artículos que los regulan; la fase vectorial captura
artículos relacionados semánticamente que el grafo podría no alcanzar. Es la versión más
completa del pipeline; testLS.py solo implementa la fase vectorial."""
import os, sys, json, unicodedata

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from utils.connectors import get_neo4j_driver, get_gemini_embeddings, get_gemini_llm
from langchain_neo4j import Neo4jVector
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

llm = get_gemini_llm()
embeddings = get_gemini_embeddings()
neo4j_driver = get_neo4j_driver()

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

retriever = vector_db.as_retriever(search_kwargs={"k": 4})

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


def responder(pregunta: str) -> str:
    # 1. Extraer sujeto y conceptos
    sujeto, conceptos = extraer_consulta(pregunta)
    print(f"\nSujeto:    '{sujeto}'")
    print(f"Conceptos: {conceptos}")

    vistos = set()
    textos_contexto = []
    article_ids = []

    # 2A. BÚSQUEDA HÍBRIDA - Fase Ontológica (Grafo)
    # Aquí es donde Neo4j atrapa el Artículo 31 usando los nodos puente
    print("\nBuscando en Grafo Ontológico...")
    articulos_grafo = buscar_articulos_por_conceptos(conceptos, sujeto)
    for art in articulos_grafo:
        art_id = str(art["id"])
        if art_id not in vistos:
            vistos.add(art_id)
            article_ids.append(art_id)
            textos_contexto.append(f"ARTICULO: {art['numero']}\nTEXTO: {art['texto']}")
            print(f"  • [Grafo] Art. {art['numero']} recuperado.")

    # 2B. BÚSQUEDA HÍBRIDA - Fase Semántica (Vectorial LangChain)
    print("\nBuscando en Base Vectorial...")
    docs_raw = []
    for i, concepto in enumerate(conceptos, 1):
        for doc in retriever.invoke(concepto):
            docs_raw.append(doc)

    docs = filtrar_por_sujeto(docs_raw, sujeto)
    
    for doc in docs:
        doc_id = str(doc.metadata.get("id", ""))
        if doc_id and doc_id not in vistos:
            vistos.add(doc_id)
            article_ids.append(doc_id)
            textos_contexto.append(doc.page_content)
            print(f"  • [Vector] Art. {doc.metadata.get('art', '')} recuperado.")

    print(f"\n{'─'*50}")
    print(f"Total Artículos únicos recuperados: {len(article_ids)}")

    # 3. Entidades del grafo (Construcción del vecindario)
    entidades = obtener_entidades_relacionadas(article_ids)
    print(f"Entidades relacionadas extraídas: {len(entidades)}")
    print(f"{'─'*50}")

    # 4. Generar y revisar respuesta
    context = "\n\n---\n\n".join(textos_contexto) + format_entidades(entidades)
    print("Generando respuesta...")
    respuesta_inicial = answer_chain.invoke({"context": context, "question": pregunta})
    
    print("Revisando...")
    return review_chain.invoke({
        "context": context,
        "question": pregunta,
        "answer": respuesta_inicial,
    })


# --- Ejecución ---
pregunta = "¿Cuáles son los requisitos ineludibles que debe contener el instrumento de constitución de cualquier sociedad según el artículo 11?"

print(f"\nPREGUNTA: {pregunta}")
respuesta = responder(pregunta)
print("\n--- RESPUESTA ---")
print(respuesta)

neo4j_driver.close()
