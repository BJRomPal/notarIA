"""Test de consulta RAG exclusivamente vectorial sobre la LSC.
Pipeline: el LLM descompone la pregunta en sujeto + conceptos, se buscan artículos
por similitud semántica en el índice vectorial de Neo4j, se enriquece el contexto con
entidades del grafo y se genera una respuesta que luego es revisada por un segundo LLM.
Versión simplificada de testLS2.py: solo usa la fase vectorial, sin búsqueda ontológica."""
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


def extraer_consulta(pregunta: str) -> tuple[str, list[str]]:
    prompt = f"""Eres un experto en derecho societario argentino.
Analizá la pregunta y devolvé un JSON con dos campos:
- "sujeto": el tipo societario u objeto jurídico principal (ej: "sociedad anonima", "sociedad de responsabilidad limitada")
- "conceptos": lista de hasta {MAX_CONCEPTOS} sub-temas específicos para buscar en la ley, cada uno incluyendo el sujeto

Devuelve SOLO el JSON. Sin explicación, sin markdown.

Ejemplo entrada: "¿Cuáles son las características de la sociedad anónima?"
Ejemplo salida:
{{"sujeto": "sociedad anonima", "conceptos": ["definicion sociedad anonima", "directorio sociedad anonima", "asamblea accionistas sociedad anonima", "constitucion sociedad anonima", "publicidad edictos sociedad anonima", "capital acciones sociedad anonima", "fiscalizacion sociedad anonima", "responsabilidad socios sociedad anonima"]}}

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


def obtener_entidades_relacionadas(article_ids: list[str]) -> list[dict]:
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
    # 1. Extraer sujeto y conceptos
    sujeto, conceptos = extraer_consulta(pregunta)
    print(f"\nSujeto:    '{sujeto}'")
    print(f"Conceptos: {conceptos}")

    # 2. Búsqueda vectorial por concepto con deduplicación
    vistos: set[str] = set()
    docs_raw = []
    for i, concepto in enumerate(conceptos, 1):
        print(f"  [{i}/{len(conceptos)}] Buscando: '{concepto}'")
        for doc in retriever.invoke(concepto):
            doc_id = str(doc.metadata.get("id", ""))
            if doc_id and doc_id not in vistos:
                vistos.add(doc_id)
                docs_raw.append(doc)

    # 3. Filtrar por sujeto
    docs = filtrar_por_sujeto(docs_raw, sujeto)
    descartados = len(docs_raw) - len(docs)

    # 4. Mostrar artículos recuperados
    article_ids = [str(doc.metadata["id"]) for doc in docs if doc.metadata.get("id")]
    print(f"\n{'─'*50}")
    print(f"Artículos recuperados ({len(article_ids)}):")
    for art_id in article_ids:
        print(f"  • {art_id}")
    if descartados:
        print(f"  (+ {descartados} descartados por ser de otro tipo societario)")

    # 5. Entidades del grafo
    entidades = obtener_entidades_relacionadas(article_ids)
    print(f"Entidades relacionadas: {len(entidades)}")
    print(f"{'─'*50}")

    # 6. Generar y revisar respuesta
    context = format_docs(docs) + format_entidades(entidades)
    print("Generando respuesta...")
    respuesta_inicial = answer_chain.invoke({"context": context, "question": pregunta})
    print("Revisando...")
    return review_chain.invoke({
        "context": context,
        "question": pregunta,
        "answer": respuesta_inicial,
    })


# --- Ejecución ---
pregunta = "¿Qué sucede con la responsabilidad de los socios frente a terceros si una sociedad se constituye omitiendo requisitos esenciales tipificantes (Sección IV)?"

print(f"\nPREGUNTA: {pregunta}")
respuesta = responder(pregunta)
print("\n--- RESPUESTA ---")
print(respuesta)

neo4j_driver.close()
