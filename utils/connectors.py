"""Funciones de fábrica centralizadas para los servicios externos del proyecto:
Neo4j (grafo), Gemini (embeddings y LLM de generación RAG) y Ollama (LLM de extracción).
Todas leen credenciales del .env en la raíz del proyecto."""
import os, time, requests, logging
from dotenv import load_dotenv
from neo4j import GraphDatabase
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_ollama import ChatOllama

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

_log = logging.getLogger("connectors")


def get_neo4j_driver():
    uri = os.getenv("NEO4J_URI") or ""
    user = os.getenv("NEO4J_USERNAME") or ""
    password = os.getenv("NEO4J_PASSWORD") or ""
    return GraphDatabase.driver(uri, auth=(user, password))


# Códigos HTTP que valen la pena reintentar. Es la misma lista que usa el SDK de Google en
# `google/genai/_api_client.py::_RETRY_HTTP_STATUS_CODES`, copiada acá porque es privada.
_CODIGOS_TRANSITORIOS = (408, 429, 500, 502, 503, 504)

# Cuatro intentos con espera 1s, 2s, 4s: en el peor caso agrega ~7 segundos antes de fallar.
# Está calibrado para el camino de CONSULTA, donde hay un usuario mirando la pantalla; no es el
# perfil de la ingesta, que puede permitirse esperar minutos (ver la nota de abajo).
_INTENTOS_EMBEDDING = 4
_ESPERA_INICIAL = 1.0


def _es_transitorio(error: Exception) -> bool:
    """Un fallo del que tiene sentido volver: servicio caído, saturado o corte de red.

    Un 400 por entrada inválida o un 403 por credencial mala no se reintentan: volver a
    llamar da exactamente el mismo error y solo agrega demora.
    """
    codigo = getattr(error, "code", None) or getattr(error, "status_code", None)
    if codigo in _CODIGOS_TRANSITORIOS:
        return True
    # Cortes de red y timeouts, que no traen código HTTP.
    return isinstance(error, (TimeoutError, ConnectionError))


class _EmbeddingsConReintento(GoogleGenerativeAIEmbeddings):
    """`GoogleGenerativeAIEmbeddings` que sobrevive a un 503 pasajero.

    POR QUÉ HACE FALTA, Y POR QUÉ SOLO ACÁ. El SDK de Google trae reintentos, pero
    **desactivados por defecto**: `retry_args(None)` devuelve `stop_after_attempt(1)`, o sea
    "nunca reintentar", y solo se activan si alguien pasa `HttpRetryOptions`.

      - `ChatGoogleGenerativeAI` los pasa solo: tiene `max_retries=6` y arma
        `HttpRetryOptions(attempts=6)` en CADA llamada. Las llamadas al LLM ya están cubiertas
        y no hay que tocarlas.
      - `GoogleGenerativeAIEmbeddings` **no tiene ese campo ni ninguna forma soportada de
        configurarlo**: construye su `HttpOptions` sin `retry_options` y no lo expone. De ahí
        esta subclase, en vez de una opción de configuración que no existe.

    Medido: tres corridas de `tests/test_jurisprudencia.py` se cayeron enteras por un
    `503 UNAVAILABLE` en `embed_query`. En producción eso no es un test perdido, es la
    respuesta del usuario que se cae — la excepción sube desde el especialista, atraviesa
    LangGraph y se lleva el turno completo.

    CONVIVE CON `utils/extractor_base.py::embed_con_reintento()`, que usan 165 extractores y
    que NO hay que sacar. Quedan en capas, y es lo correcto: acá adentro, reintentos rápidos
    para un hipo del servicio; allá afuera, tres intentos con 60 s de espera para el caso que
    esa función atiende, que es la cuota diaria agotada. Un backoff de 60 s adentro del camino
    de consulta sería inaceptable, y uno de 1 s en la ingesta no alcanzaría.
    """

    def _con_reintento(self, funcion, *args, **kwargs):
        espera = _ESPERA_INICIAL
        for intento in range(1, _INTENTOS_EMBEDDING + 1):
            try:
                return funcion(*args, **kwargs)
            except Exception as error:
                if intento == _INTENTOS_EMBEDDING or not _es_transitorio(error):
                    raise
                _log.warning(
                    "Embedding falló (intento %d/%d): %s. Reintentando en %.0fs...",
                    intento, _INTENTOS_EMBEDDING, error, espera,
                )
                time.sleep(espera)
                espera *= 2

    def embed_query(self, *args, **kwargs):
        return self._con_reintento(super().embed_query, *args, **kwargs)

    def embed_documents(self, *args, **kwargs):
        return self._con_reintento(super().embed_documents, *args, **kwargs)


def get_gemini_embeddings():
    return _EmbeddingsConReintento(model="models/gemini-embedding-001")


def get_gemini_llm(model: str = "gemini-2.5-flash-lite", temperature: float = 0.0,
                   thinking_budget: int | None = None):
    """Fábrica del LLM de generación. `thinking_budget=0` apaga el razonamiento interno.

    POR QUÉ EXISTE ESE PARÁMETRO. `gemini-2.5-flash` trae el pensamiento ENCENDIDO por
    defecto; `flash-lite` lo trae apagado. Y Google factura así: "response pricing is the sum
    of output tokens and thinking tokens" — o sea que el razonamiento invisible se paga como
    salida.

    Medido sobre el prompt de redacción de este proyecto, con el mismo contexto:

        2.5-flash tal como estaba      2.790 ms   351 tokens de salida, 317 de pensamiento
        2.5-flash + thinking_budget=0  1.468 ms    36 tokens de salida,   0 de pensamiento

    **317 de 351 tokens eran pensamiento invisible: el 90% de ese renglón de la factura.** La
    respuesta visible fue la misma, 5,3 veces más barata y casi el doble de rápida.

    Se deja en None (o sea, el default del modelo) y no en 0 a propósito: apagar el
    pensamiento en todas las llamadas del proyecto de una sola vez sería cambiar el
    comportamiento de la ingesta y de los scripts de exploration/ sin haberlo medido ahí. Cada
    llamador decide.
    """
    if thinking_budget is None:
        return ChatGoogleGenerativeAI(model=model, temperature=temperature)
    return ChatGoogleGenerativeAI(model=model, temperature=temperature,
                                  thinking_budget=thinking_budget)


# format="json" fuerza a Ollama a emitir JSON puro sin texto adicional;
# imprescindible porque el pipeline parsea la respuesta con json.loads() directamente.
def get_ollama_llm(model: str = "gemma4:e4b", temperature: float = 0.0):
    return ChatOllama(model=model, temperature=temperature, format="json")


def enviar_alerta(mensaje: str) -> None:
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        _log.warning("Telegram: credenciales no configuradas en .env — notificación omitida.")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": mensaje}, timeout=10)
        if not resp.ok:
            _log.error(f"Telegram respondió con error {resp.status_code}: {resp.text}")
    except Exception as e:
        _log.error(f"Error enviando notificación Telegram: {e}")


# ==========================================================================================
# CHECKPOINTER DEL AGENTE (LangGraph)
# ==========================================================================================
# Guarda el estado de cada conversación bajo su thread_id, y es lo que hace que el agente sea
# multi-turno: sin esto, cada consulta arrancaría sin historial y «¿y para la SRL?» no tendría
# contra qué resolverse.
#
# Se cachea en módulo porque la conexión tiene que vivir tanto como el proceso: abrirla por
# request agotaría el pool.
_checkpointer = None


def get_checkpointer():
    """PostgresSaver si hay POSTGRES_URL en el entorno; InMemorySaver si no.

    POR QUÉ POSTGRES Y NO SQLITE. Esto va a correr en Cloud Run, que escala horizontalmente y
    tiene disco efímero. Un checkpointer en archivo local pierde la conversación en cada
    reinicio, y con más de una instancia devuelve respuestas distintas según cuál atienda el
    turno: el multi-turno se rompería de forma intermitente, que es la peor manera de
    romperse. Cloud SQL es el destino natural, la URL sale de Secret Manager, y en local es un
    contenedor — el mismo código de los dos lados.

    EN DESARROLLO, SIN POSTGRES, cae a InMemorySaver. Eso alcanza para probar el multi-turno
    en una sesión, pero **se pierde al reiniciar uvicorn**: no es un modo de producción, es un
    modo de que el agente arranque sin infraestructura.

    POR QUÉ UN POOL Y NO `from_conn_string()`, QUE ES LO QUE MUESTRA LA DOCUMENTACIÓN.
    `from_conn_string()` está decorado con @contextmanager: sirve para un script (`with ... as
    checkpointer:`) pero no para un proceso FastAPI de larga vida, porque al salir del bloque
    cierra la conexión.

    Y no alcanza con llamar a `__enter__()` y guardarse el saver: hay que guardar **el context
    manager**, porque si se lo lleva el recolector de basura corre su `__exit__` y la conexión
    queda cerrada igual. Ese es el error exacto que da:

        psycopg.OperationalError: the connection is closed

    ...en la primera consulta, no al arrancar, que es lo que lo hace confuso.

    Un pool resuelve las dos cosas de una vez: vive mientras viva el proceso y además sirve
    varias consultas a la vez, que es lo que hace falta con FastAPI atendiendo más de un chat.
    Los tres `kwargs` son los mismos que `from_conn_string()` usa por dentro y los tres son
    obligatorios: `autocommit` porque el checkpointer maneja sus propias transacciones,
    `prepare_threshold=0` para no dejar sentencias preparadas colgando entre conexiones del
    pool, y `dict_row` porque el checkpointer lee las filas por nombre de columna.
    """
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer

    url = os.getenv("POSTGRES_URL")
    if not url:
        from langgraph.checkpoint.memory import InMemorySaver
        _log.warning("POSTGRES_URL no configurada: el agente usa InMemorySaver "
                     "(la conversación se pierde al reiniciar el servidor).")
        _checkpointer = InMemorySaver()
        return _checkpointer

    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(
        conninfo=url,
        min_size=1,
        max_size=8,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=True,
    )
    _checkpointer = PostgresSaver(pool)
    _checkpointer.setup()   # idempotente: crea y migra sus tablas la primera vez
    return _checkpointer
