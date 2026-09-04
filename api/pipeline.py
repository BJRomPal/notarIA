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
import sys
import time
from typing import Iterator

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from utils.connectors import get_neo4j_driver, get_gemini_embeddings, get_gemini_llm
from utils.citas import NOMBRE_NORMA
from utils.texto import normalizar, formato_articulo
from utils.llm_io import json_del_llm
from utils.grafo import etiquetas_ontologia, seguir_remite_a, datos_articulos, entidades_relacionadas, format_entidades
from api.cypher import MotorCypherDinamico
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
# 2. CONTEXTO ACUMULADO
# ==========================================

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
        data = json_del_llm(str(respuesta.content))
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

# Inicialización única al cargar el módulo: carga las etiquetas reales desde Neo4j.
_etiquetas_entidades = etiquetas_ontologia(neo4j_driver)
print(f"[Init] Etiquetas ontológicas cargadas: {_etiquetas_entidades}")
motor_cypher = MotorCypherDinamico(neo4j_driver, llm, _etiquetas_entidades)

# ==========================================
# 5. VECINDARIO ONTOLÓGICO
# ==========================================

def _agregar_remisiones(ids_origen: list[str], ctx: ContextoAcumulado) -> Iterator[dict]:
    """Sigue REMITE_A desde `ids_origen`, agrega al contexto los artículos nuevos
    y emite un evento por cada uno."""
    for art in seguir_remite_a(neo4j_driver, ids_origen):
        origen_num = art.get("origen_numero", "")
        norma_ref  = art.get("norma", "")
        texto = formato_articulo(
            f"{norma_ref} (referenciada por Art. {origen_num})",
            art.get("numero", ""),
            art.get("texto", ""),
        )
        if ctx.agregar(art.get("id", ""), texto):
            yield {"type": "item", "texto": f"Art. {art.get('numero', '')} ({norma_ref}) — citado por el Art. {origen_num}"}

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
        data = json_del_llm(str(respuesta.content))
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
        datos_grafo = datos_articulos(neo4j_driver, [str(a["id"]) for a in arts_grafo_nuevos])
        for art in arts_grafo_nuevos:
            art_id = str(art["id"])
            # La FUENTE es la norma real, no "Grafo Ontológico": el prompt de respuesta
            # exige citar la norma de cada afirmación y solo puede leerla de acá.
            norma = datos_grafo.get(art_id, {}).get("norma", "Norma no identificada")
            texto = formato_articulo(norma, art.get("numero", ""), art.get("texto", ""))
            if ctx.agregar(art_id, texto):
                yield {"type": "item", "texto": f"Art. {art.get('numero', '')} ({norma})"}

        # Fase 3.5 (segunda pasada): remisiones desde los artículos nuevos del grafo.
        ids_nuevos_fase3 = [i for i in ctx.ids if i not in ids_antes_fase3]
        if ids_nuevos_fase3:
            yield from _agregar_remisiones(ids_nuevos_fase3, ctx)

    # Fase 4: vecindario ontológico (entidades) + generación de la respuesta final.
    entidades = entidades_relacionadas(neo4j_driver, ctx.ids)

    # Fuentes del contexto final, para que el frontend las muestre como citas.
    # El fallback cubre el caso en que un id del contexto no sea un :Articulo (el motor
    # Cypher puede devolver un :Jurisprudencia, que también tiene id y texto).
    datos_ctx = datos_articulos(neo4j_driver, ctx.ids)
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
