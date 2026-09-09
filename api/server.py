"""
Servidor FastAPI de NotarIA: expone el agente notarial como un stream SSE.

Endpoints:
  GET  /api/health — chequeo de vida (lo usa el frontend para mostrar estado).
  POST /api/chat   — body {"pregunta": "...", "thread_id": "..."}; responde
                     text/event-stream con los eventos JSON que emite responder_stream()
                     (una línea "data: {...}" por evento). El frontend Next.js consume
                     este stream vía fetch.

Este archivo no sabe que existe un agente. Importa `responder_stream` y recorre el
generador, igual que cuando del otro lado había un pipeline lineal: **toda la
reestructuración de la articulación cambió exactamente este import**. Ese aislamiento
era el objetivo, y es lo que deja la decisión de usar LangGraph reversible.

Ejecución (desde la raíz del proyecto, con el venv activo):
  uvicorn api.server:app --host 0.0.0.0 --port 8000
"""
import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.agente.streaming import responder_stream

app = FastAPI(title="NotarIA API")

# El frontend corre en otro puerto (Next.js en 3000); en desarrollo se permite todo
# origen porque la API no maneja credenciales.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    """Body del POST /api/chat.

    `thread_id` identifica la conversación y es lo que hace que el agente entienda «¿y para
    la SRL?»: dos requests con el mismo id comparten historial. Lo manda el frontend, donde
    ya existía como `conversation.id` en localStorage.

    Tiene default None a propósito: un cliente viejo que no lo mande sigue funcionando, con
    cada consulta en su propio hilo. Es exactamente el comportamiento que había antes del
    agente, así que la actualización del frontend puede ir después y por separado.
    """
    pregunta: str
    thread_id: str | None = None


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/chat")
def chat(req: ChatRequest):
    pregunta = req.pregunta.strip()

    def sse():
        if not pregunta:
            yield f"data: {json.dumps({'type': 'error', 'mensaje': 'La consulta está vacía.'}, ensure_ascii=False)}\n\n"
            return
        try:
            for evento in responder_stream(pregunta, req.thread_id):
                yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'mensaje': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # evita buffering si hay un proxy nginx delante
        },
    )
