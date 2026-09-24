"""
Servidor FastAPI de NotarIA: expone el agente notarial como un stream SSE.

Endpoints de este archivo:
  GET  /api/health — chequeo de vida (lo usa el frontend para mostrar estado).
  POST /api/chat   — body {"pregunta": "...", "thread_id": "..."}; responde
                     text/event-stream con los eventos JSON que emite responder_stream()
                     (una línea "data: {...}" por evento). El frontend Next.js consume
                     este stream vía fetch.

El resto de la API vive en `api/rutas/` y se monta acá con include_router: la cuenta del
usuario (alias, conversaciones, consumo) en `cuenta.py`. Este archivo se queda solo con lo
que toca al agente.

Este archivo no sabe que existe un agente. Importa `responder_stream` y recorre el
generador, igual que cuando del otro lado había un pipeline lineal: **toda la
reestructuración de la articulación cambió exactamente este import**. Ese aislamiento
era el objetivo, y es lo que deja la decisión de usar LangGraph reversible.

Ejecución (desde la raíz del proyecto, con el venv activo):
  uvicorn api.server:app --host 0.0.0.0 --port 8000
"""
import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.agente.streaming import responder_stream
from api.auth import IdentidadInvalida, autenticacion_activa, identidad
from api.consumo import obtener_pool
from api.rutas import catalogo, cuenta

app = FastAPI(title="NotarIA API")

# El resto de los endpoints vive en api/rutas/, uno por origen de datos: `cuenta` lee Postgres
# (alias, conversaciones, consumo) y `catalogo` lee Neo4j (el inventario y el contenido de una
# fuente citada). Ninguno tiene que ver con el agente, que es de lo único que habla este archivo.
app.include_router(cuenta.router)
app.include_router(catalogo.router)

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
    """Estado del servicio. Expone si la autenticación está encendida, que es la forma de
    darse cuenta de un despliegue sin `IAP_AUDIENCE` antes de que lo descubra un tercero.

    `base` dice si hay Postgres. El frontend lo necesita para saber de dónde leer el historial:
    sin base no hay conversaciones del lado del servidor y se queda con su localStorage. Es una
    pregunta sobre la infraestructura, no sobre el usuario, así que va acá y no en /api/usuario.
    """
    return {
        "status": "ok",
        "autenticacion": autenticacion_activa(),
        "base": obtener_pool() is not None,
    }


@app.post("/api/chat")
def chat(req: ChatRequest, request: Request):
    pregunta = req.pregunta.strip()

    # LA IDENTIDAD SE RESUELVE ACÁ Y NO MÁS ADENTRO, porque es lo único del sistema que ve un
    # request HTTP. El agente recibe una identidad ya verificada o None; no sabe qué es un
    # header ni qué es IAP.
    #
    # El 401 sale ANTES de abrir el stream: un error dentro de un `text/event-stream` ya salió
    # con código 200 y el cliente tendría que interpretar un evento de error para darse cuenta.
    # Un pedido sin identidad válida no es un problema de la respuesta, es un pedido que no se
    # atiende.
    try:
        quien = identidad(request.headers)
    except IdentidadInvalida as e:
        raise HTTPException(status_code=401, detail=str(e))

    def sse():
        if not pregunta:
            yield f"data: {json.dumps({'type': 'error', 'mensaje': 'La consulta está vacía.'}, ensure_ascii=False)}\n\n"
            return
        try:
            for evento in responder_stream(pregunta, req.thread_id, quien):
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
