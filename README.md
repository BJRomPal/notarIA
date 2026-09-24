# NotarIA

Chat de consultas legales para el ámbito notarial argentino. Responde apoyándose en legislación y
jurisprudencia argentina, recuperadas de un grafo de conocimiento (GraphRAG) en Neo4j, y cita las
fuentes que consultó.

> **Software propietario.** Ver [LICENSE](LICENSE). Este repositorio no incluye el grafo de
> conocimiento ni el material con el que se construye: sin una instancia Neo4j cargada, el agente
> no tiene con qué responder.

## Cómo funciona

Un agente LangGraph clasifica cada consulta y la deriva a uno de tres especialistas. Una síntesis
final redacta la respuesta con sus citas.

| Ruta | Para qué sirve | Cómo recupera |
|---|---|---|
| `particular` | Articulado concreto («¿qué exige el art. 77 LSC?») | Búsqueda vectorial, remisiones entre artículos, jurisprudencia y Text-to-Cypher condicional |
| `general` | Institutos jurídicos («diferencias entre la SA y la SRL») | El resumen del instituto guardado en el grafo, más jurisprudencia |
| `determinista` | Cálculos exactos (dígito verificador de partida, CUIL, plazos registrales, herencia, ITGB) | Herramientas en código: el modelo elige y transcribe, el código calcula |

El principio de diseño es que el modelo no inventa: la cita y la vigencia de cada norma se
resuelven en la recuperación, y el modelo solo las transcribe.

La conversación es multi-turno (el checkpointer la guarda por `thread_id` en Postgres) y la
respuesta llega por streaming SSE.

## Stack

Neo4j · LangChain y LangGraph · Gemini (embeddings y LLM) · Postgres · FastAPI ·
Next.js 15, TypeScript y Tailwind v4 · Identity-Aware Proxy de Google para la identidad.

## Requisitos

- Python 3.12
- Node.js 18.18 o superior (Next.js 15)
- Una instancia Neo4j con el grafo cargado (privada, no incluida)
- Una clave de la API de Gemini
- Docker, solo si querés el Postgres local

## Configuración

Un archivo `.env` en la raíz (no se versiona):

| Variable | Obligatoria | Para qué |
|---|---|---|
| `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` | Sí | Conexión al grafo |
| `GOOGLE_API_KEY` | Sí | La lee `langchain-google-genai` |
| `POSTGRES_URL` | No | Sin ella no hay historial en servidor ni contabilidad de consumo, y la conversación no sobrevive al reinicio |
| `IAP_AUDIENCE` | No | Sin ella la autenticación está **apagada** y todo se atribuye al usuario de desarrollo. Solo para desarrollo |
| `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` | No | Alertas de la ingesta |

## Ejecución

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Opcional: Postgres local con el esquema `notaria`. Imprime el POSTGRES_URL para el .env.
bash db/levantar_postgres_local.sh

# API (puerto 8000)
.venv/bin/uvicorn api.server:app --host 0.0.0.0 --port 8000

# Frontend (http://localhost:3000)
cd frontend
npm install
npm run dev
```

El detalle del frontend está en [frontend/README.md](frontend/README.md).

## Tests

Son scripts sueltos, sin pytest, y cada uno sale con código 1 si falla alguno:

```bash
.venv/bin/python tests/test_filtro_cypher.py
```

| Script | Necesita |
|---|---|
| `tests/test_filtro_cypher.py` | Nada. Es el límite de seguridad del Text-to-Cypher: correrlo al tocar `api/cypher.py` |
| `tests/test_clasificador.py` | Gemini. Correrlo siempre que se toque el prompt del clasificador |
| `tests/test_api_catalogo.py` | Neo4j |
| `tests/test_api_cuenta.py` | Postgres |
| `tests/test_jurisprudencia.py` | Neo4j y Gemini (`--recuperacion` corre solo la recuperación) |

## Estructura

```
api/            El agente y su API (FastAPI). Solo api/agente/ conoce LangGraph.
  agente/       Grafo del agente, nodos y streaming SSE
  especialistas/  Los tres especialistas, como generadores planos sin LangGraph
  rutas/        Cuenta del usuario y catálogo
utils/          Conectores compartidos, helpers del RAG y herramientas deterministas
db/             Migraciones de Postgres, numeradas y cargadas en orden
frontend/       Chat en Next.js
tests/          Verificaciones sueltas
exploration/    Mantenimiento de los resúmenes de entidades del grafo
docs/           Documentación de arquitectura
```

## Lo que no está en el repositorio

Por diseño no se versionan: el grafo de conocimiento y sus copias de respaldo, los pipelines de
ingesta (`extractors/`), las fuentes en texto (`input/`) y los logs de evaluación (`logs/`).

## Licencia

Software propietario. Todos los derechos reservados. Ver [LICENSE](LICENSE).
