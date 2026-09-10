# NotarIA — Frontend

Interfaz de chat (estilo ChatGPT/Gemini) para el asistente legal notarial.
Next.js 15 + TypeScript + Tailwind CSS v4. Consume la API FastAPI del proyecto vía SSE.

## Arquitectura

```
Navegador ──> Next.js (puerto 3000)
                 └── /api/[...ruta] (un solo proxy para toda la API)
                        └──> FastAPI (puerto 8000) ──> agente notarial (LangGraph)
                                                          └──> especialistas (Neo4j + Gemini)
```

**El proxy es uno solo y reenvía el header de IAP.** Con IAP adelante el navegador nunca habla
con FastAPI: habla con Next, y el JWT llega al route handler. Si el proxy no lo reenvía —que es
lo que pasaba cuando había un archivo por endpoint— FastAPI ve un pedido sin identidad y contesta
401 en producción, mientras en local todo anda. Un solo archivo hace que eso no pueda volver a
pasar de a un endpoint por vez.

El backend emite eventos SSE (`fase`, `item`, `fuentes`, `token`, `fin`, `error`) que la UI
muestra como una línea de tiempo del proceso de búsqueda + respuesta en streaming con citas.
Cada conversación viaja con un `thread_id` (el `conversation.id`), lo que le permite al agente
mantener contexto entre turnos ("¿y para la SRL?"). Ese mismo id es la clave en las tres capas:
el checkpointer de LangGraph, `notaria.conversaciones` y la lista del panel lateral.

**De dónde sale el historial.** `/api/health` devuelve `base: bool`. Con Postgres, la lista y los
mensajes vienen del servidor y siguen al usuario entre dispositivos; sin Postgres, queda el
`localStorage` de siempre. Es una sola rama, en `useConversations`, y existe porque el proyecto
sostiene a propósito que todo funcione sin `POSTGRES_URL`. Lo que ya esté guardado en un
navegador **no se migra**: queda ahí, sin aparecer en la lista del servidor.

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
src/app/page.tsx             — Solo el turno en curso: manda la pregunta y vuelca el stream
src/app/api/[...ruta]/route.ts — Proxy único hacia FastAPI (SSE y JSON), reenvía el JWT de IAP
src/lib/api.ts               — Cliente de la API: un lugar para las llamadas y sus errores
src/lib/useConversations.ts  — La lista: carga diferida, borrado y el modo sin Postgres
src/lib/useNotariaChat.ts    — Hook: fetch + parsing del stream SSE
src/lib/storage.ts           — Respaldo en localStorage, solo cuando no hay base
src/lib/types.ts             — Tipos de eventos, mensajes, conversaciones, usuario y consumo
src/components/              — Sidebar, Chat, MessageBubble, ThinkingStatus, Sources, ChatInput,
                               Logo, Modal, UserMenu, AliasDialog, ConsumoPanel, Inventario,
                               FuenteModal, GuiaPrompts
```

Los chips de "Fuentes consultadas" son botones: cada uno abre `FuenteModal` con el texto del
artículo (y su estado de vigencia), el resumen del instituto o la doctrina del fallo. Es la única
superficie navegable de una respuesta, y alcanza: esa lista la arma el retrieval y no el modelo,
así que cubre el 100% de lo que el sistema consultó. Las citas escritas DENTRO del párrafo quedan
como texto — no hay ninguna marca que las ate a un objeto `Fuente`.

`Inventario.tsx` contesta «¿está cargada tal norma?», que es una consulta puntual y no una
navegación: por eso el buscador va arriba y enfocado, y normaliza puntos y acentos («19550» y
«19.550» tienen que dar lo mismo, porque `Norma.numero` guarda las dos formas según la norma).

`Modal.tsx` es la primitiva de ventana de todo el proyecto: `<dialog>` nativo con `showModal()`,
que da Escape, foco atrapado, backdrop y capa superior sin escribirlos. Esa última parte importa
porque hay modales que abren otros modales.
