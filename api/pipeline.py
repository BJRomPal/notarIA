"""
Pipeline RAG Híbrido con Text-to-Cypher dinámico — versión streaming para la API.

Adaptación de tests/RagDinamicoOriginal.py (misma lógica y mismo orden de fases) en la
que responder() se convierte en el generador responder_stream(): en lugar de imprimir
el progreso por consola, emite eventos que el servidor FastAPI reenvía por SSE y el
frontend muestra como indicadores de avance. La respuesta final se streamea token a
token con answer_chain.stream() en vez de invoke().

Las fases 1 a 6 (recuperación de contexto: análisis, vectorial, remisiones, evaluación
de suficiencia y grafo) viven en api/recuperacion.py; acá solo queda la fase 7
(redacción de la respuesta) y el armado de los eventos SSE.

Eventos emitidos (dicts serializables a JSON):
  {"type": "fase",    "fase": str, "label": str}    — comienza una fase del pipeline
  {"type": "item",    "texto": str}                 — detalle dentro de la fase actual
  {"type": "fuentes", "articulos": [{id, numero, norma}]} — artículos del contexto final
  {"type": "token",   "texto": str}                 — fragmento de la respuesta final
  {"type": "fin",     "articulos": int, "segundos": float}
  {"type": "error",   "mensaje": str}
"""
import time
from typing import Iterator

from utils.rag.grafo import datos_articulos, entidades_relacionadas, format_entidades
from api.recuperacion import recuperar_contexto, llm, neo4j_driver
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

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


def _agotar(generador):
    """Consume un generador hasta el final y devuelve su `return`."""
    try:
        while True:
            next(generador)
    except StopIteration as fin:
        return fin.value


def _armar_fuentes_y_entidades(ctx):
    """Fuentes del contexto final (para que el frontend las muestre como citas) y
    entidades relacionadas (para el contexto que recibe el LLM de redacción).

    El fallback en "norma" cubre el caso en que un id del contexto no sea un
    :Articulo (el motor Cypher puede devolver un :Jurisprudencia, que también
    tiene id y texto).
    """
    entidades = entidades_relacionadas(neo4j_driver, ctx.ids)
    datos_ctx = datos_articulos(neo4j_driver, ctx.ids)
    fuentes = [
        {
            "id": art_id,
            "numero": datos_ctx.get(art_id, {}).get("numero") or art_id,
            "norma": datos_ctx.get(art_id, {}).get("norma") or "?",
        }
        for art_id in ctx.ids
    ]
    return fuentes, entidades


def responder_stream(pregunta: str) -> Iterator[dict]:
    """Versión generadora de responder() de V3: mismo flujo, pero emite eventos
    de progreso y streamea la respuesta final token a token."""
    t0 = time.time()

    ctx = yield from recuperar_contexto(pregunta)

    fuentes, entidades = _armar_fuentes_y_entidades(ctx)
    yield {"type": "fuentes", "articulos": fuentes}

    yield {"type": "fase", "fase": "redaccion", "label": "Redactando la respuesta"}
    context = "\n\n---\n\n".join(ctx.textos) + format_entidades(entidades)
    for chunk in answer_chain.stream({"context": context, "question": pregunta}):
        if chunk:
            yield {"type": "token", "texto": chunk}

    yield {"type": "fin", "articulos": len(ctx), "segundos": round(time.time() - t0, 1)}


def responder(pregunta: str) -> dict:
    """Versión sin streaming de responder_stream(), para tests: la misma
    recuperación de contexto y la misma respuesta final, sin eventos SSE."""
    t0 = time.time()

    ctx = _agotar(recuperar_contexto(pregunta))

    _, entidades = _armar_fuentes_y_entidades(ctx)
    context = "\n\n---\n\n".join(ctx.textos) + format_entidades(entidades)
    respuesta = answer_chain.invoke({"context": context, "question": pregunta})

    return {
        "respuesta": respuesta,
        "ids": ctx.ids,
        "textos": ctx.textos,
        "segundos": round(time.time() - t0, 1),
    }
