# NotarIA — Frontend

Interfaz de chat (estilo ChatGPT/Gemini) para el asistente legal notarial.
Next.js 15 + TypeScript + Tailwind CSS v4. Consume la API FastAPI del proyecto vía SSE.

## Arquitectura

```
Navegador ──> Next.js (puerto 3000)
                 └── /api/chat (route handler, proxy streaming)
                        └──> FastAPI (puerto 8000) ──> pipeline RAG (Neo4j + Gemini)
```

El backend emite eventos SSE (`fase`, `item`, `fuentes`, `token`, `fin`, `error`) que la UI
muestra como una línea de tiempo del proceso de búsqueda + respuesta en streaming con citas.

## Ejecución

1. **Backend** (desde la raíz del proyecto, con el venv):

   ```bash
   .venv/bin/uvicorn api.server:app --host 0.0.0.0 --port 8000
   ```

2. **Frontend** (desde `frontend/`):

   ```bash
   npm install        # solo la primera vez
   npm run dev        # desarrollo en http://localhost:3000
   # o producción:
   npm run build && npm run start
   ```

Si la API corre en otra máquina/puerto, configurar `NOTARIA_API_URL` (por defecto
`http://localhost:8000`) en el entorno del proceso Next.js.

## Estructura

```
src/app/page.tsx            — Estado de conversaciones (persistidas en localStorage)
src/app/api/chat/route.ts   — Proxy SSE hacia FastAPI
src/app/api/health/route.ts — Chequeo de conexión con la API
src/lib/useNotariaChat.ts   — Hook: fetch + parsing del stream SSE
src/lib/types.ts            — Tipos de eventos, mensajes y conversaciones
src/components/             — Sidebar, Chat, MessageBubble, PhaseTimeline, Sources, ChatInput
```
