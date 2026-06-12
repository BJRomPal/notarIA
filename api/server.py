"""
Servidor FastAPI de NotarIA: expone el pipeline RAG como un stream SSE.

Endpoints:
  GET  /api/health — chequeo de vida (lo usa el frontend para mostrar estado).
  POST /api/chat   — body {"pregunta": "..."}; responde text/event-stream con los
                     eventos JSON que emite responder_stream() (una línea "data: {...}"
                     por evento). El frontend Next.js consume este stream vía fetch.

Ejecución (desde la raíz del proyecto, con el venv activo):
  uvicorn api.server:app --host 0.0.0.0 --port 8000
"""
import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.pipeline import responder_stream

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
    pregunta: str


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
            for evento in responder_stream(pregunta):
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
