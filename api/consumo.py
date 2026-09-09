"""REGISTRO DE CONSUMO — quién gastó qué, en qué nodo y cuánto costó.

Escribe en el esquema `notaria` de Postgres (ver `db/001_esquema_notaria.sql`): una fila por
llamada al modelo, más los mensajes de cada turno.

DOS REGLAS QUE ORDENAN TODO ESTE ARCHIVO
----------------------------------------
1. **Escribir contabilidad nunca puede tumbar una respuesta.** Si Postgres no está, si la
   conexión se cae, si una consulta falla: se loguea y se sigue. Se pierde una fila de
   contabilidad, no la consulta del usuario. Por eso cada función pública de acá está envuelta
   y ninguna propaga una excepción hacia arriba.
2. **Sin POSTGRES_URL, todo esto es un no-op silencioso.** El agente arranca y funciona igual,
   sin contabilidad. Es lo que permite desarrollar sin levantar una base.

POR QUÉ UN CALLBACK Y NO CÓDIGO EN LOS NODOS
--------------------------------------------
Un callback de LangChain se engancha a TODAS las llamadas al modelo de una corrida, incluidas
las que ocurren adentro de los especialistas —que no saben que existe LangGraph y mucho menos
una base de costos—. Si esto viviera en los nodos, cada especialista tendría que reportar su
propio consumo y el `MotorCypherDinamico` también. Así, ninguno se entera.

Y el callback no necesita que nadie le diga en qué nodo está: LangGraph pone `langgraph_node`
y `ls_model_name` en la metadata de cada llamada.

**Pero solo en el arranque.** Verificado con una sonda: `on_llm_start` trae la metadata y
`on_llm_end` trae los tokens, y no al revés. Por eso el nodo y el modelo se anotan al empezar
y se usan al terminar (ver `_anotar_inicio`).

    on_llm_start -> metadata = {'langgraph_node': 'sintetizar',
                                'ls_model_name': 'gemini-2.5-flash', ...}
    on_llm_end   -> usage_metadata = {'input_tokens': 315, 'output_tokens': 421,
                                      'output_token_details': {'reasoning': 400}}
"""
import logging
import os
import time
import uuid

from langchain_core.callbacks import BaseCallbackHandler

_log = logging.getLogger("consumo")

# Un solo pool para todo el proceso. Se crea perezosamente en la primera escritura: así importar
# este módulo no abre conexiones y el agente arranca aunque Postgres esté caído.
_pool = None
_pool_roto = False        # si falló una vez, no se reintenta en cada llamada

# Precios cacheados en memoria. Se leen de `notaria.precios_modelo` una vez por proceso: son
# datos que cambian dos veces al año, consultarlos en cada llamada al modelo sería absurdo.
_precios: dict[str, tuple[float, float]] | None = None

# Mientras no haya autenticación, todo cuelga de un usuario de desarrollo con id fijo. El id es
# constante a propósito: así reiniciar el servidor no genera un usuario nuevo cada vez y el
# consumo histórico se sigue acumulando bajo el mismo. Cuando llegue el IdP, este usuario queda
# como uno más y `usuarios.id_externo` se puebla con el "sub" que mande el proxy.
USUARIO_DESARROLLO = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _obtener_pool():
    """El pool de conexiones, o None si no hay base configurada o si ya falló antes."""
    global _pool, _pool_roto
    if _pool is not None or _pool_roto:
        return _pool
    url = os.getenv("POSTGRES_URL")
    if not url:
        _pool_roto = True
        return None
    try:
        from psycopg_pool import ConnectionPool
        _pool = ConnectionPool(url, min_size=1, max_size=4, open=True)
        return _pool
    except Exception as e:
        _log.warning(f"No se pudo abrir el pool de Postgres, la contabilidad queda apagada: {e}")
        _pool_roto = True
        return None


def _precios_de(modelo: str) -> tuple[float, float]:
    """(usd por millón de entrada, usd por millón de salida) del modelo, vigentes hoy.

    Un modelo que no esté en la tabla devuelve (0, 0) y su fila queda con costo 0. Es
    deliberado: prefiero una fila con costo cero y tokens correctos —que se puede recalcular
    después— antes que perder el registro de que la llamada existió.
    """
    global _precios
    if _precios is None:
        _precios = {}
        pool = _obtener_pool()
        if pool:
            try:
                with pool.connection() as conn:
                    filas = conn.execute(
                        "SELECT modelo, usd_entrada_por_millon, usd_salida_por_millon "
                        "FROM notaria.precios_modelo "
                        "WHERE desde <= current_date AND (hasta IS NULL OR hasta >= current_date)"
                    ).fetchall()
                _precios = {f[0]: (float(f[1]), float(f[2])) for f in filas}
            except Exception as e:
                _log.warning(f"No se pudieron leer los precios: {e}")
    return _precios.get(modelo, (0.0, 0.0))


def calcular_costo(modelo: str, tokens_entrada: int, tokens_salida: int) -> float:
    """Costo en dólares de una llamada.

    `tokens_salida` ya incluye los de pensamiento, porque es como factura Google: "response
    pricing is the sum of output tokens and thinking tokens".

    Se calcula y se CONGELA en la fila al escribirla, nunca al consultarla. Si se calculara al
    consultar, el histórico mutaría solo cuando cambien los precios: una factura de octubre
    pasaría a decir otra cosa en enero.
    """
    entrada, salida = _precios_de(modelo)
    return (tokens_entrada / 1_000_000) * entrada + (tokens_salida / 1_000_000) * salida


# ==========================================================================================
# ALTA DE LA CONVERSACIÓN
# ==========================================================================================

def asegurar_conversacion(thread_id: str, titulo: str) -> bool:
    """Crea el usuario de desarrollo y la conversación si no existen. Devuelve si hay base.

    Se llama una vez por turno, antes de la primera llamada al modelo. Tiene que ir primero
    porque `llamadas_llm.conversacion_id` es NOT NULL y apunta acá: sin esta fila, ninguna
    fila de consumo se puede insertar.

    Es idempotente (ON CONFLICT DO NOTHING), así que llamarla en cada turno de una conversación
    de veinte turnos cuesta veinte consultas triviales y no ensucia nada.
    """
    pool = _obtener_pool()
    if not pool:
        return False
    try:
        with pool.connection() as conn:
            conn.execute(
                "INSERT INTO notaria.usuarios (id, nombre) VALUES (%s, %s) "
                "ON CONFLICT (id) DO NOTHING",
                (USUARIO_DESARROLLO, "Usuario de desarrollo"),
            )
            conn.execute(
                "INSERT INTO notaria.conversaciones (id, usuario_id, titulo) VALUES (%s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET actualizada_en = now()",
                (thread_id, USUARIO_DESARROLLO, titulo[:200]),
            )
        return True
    except Exception as e:
        _log.warning(f"No se pudo registrar la conversación {thread_id}: {e}")
        return False


# ==========================================================================================
# EL CALLBACK
# ==========================================================================================

class RegistroDeConsumo(BaseCallbackHandler):
    """Escribe una fila en `notaria.llamadas_llm` por cada llamada al modelo de un turno.

    Se instancia UNA POR TURNO —lleva adentro el id de la conversación y los cronómetros de
    las llamadas en vuelo— y se pasa en el config de la corrida:

        APP.stream(entrada, {"configurable": {...}, "callbacks": [RegistroDeConsumo(hilo)]})

    A partir de ahí engancha todas las llamadas al modelo de esa corrida, vengan del nodo que
    vengan, sin que ningún especialista tenga que colaborar.
    """

    def __init__(self, conversacion_id: str):
        self.conversacion_id = conversacion_id
        # run_id -> (timestamp de inicio, nodo, modelo). Ver _anotar_inicio() para por qué las
        # tres cosas se guardan juntas en el arranque y no se leen al final.
        self._en_vuelo: dict = {}
        self.ids_escritos: list[int] = []   # para completar mensaje_id al cerrar el turno

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        self._anotar_inicio(run_id, kwargs)

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        """Los modelos de chat disparan este, no on_llm_start. Se implementan los dos porque
        cuál de los dos llega depende de la integración, y perder uno es perder la fila."""
        self._anotar_inicio(run_id, kwargs)

    def _anotar_inicio(self, run_id, kwargs) -> None:
        """Guarda el reloj, el nodo y el modelo al ARRANCAR la llamada.

        POR QUÉ ACÁ Y NO AL TERMINAR, que es donde parecería natural: **la metadata solo llega
        en el arranque.** Medido con una sonda — `on_llm_start` recibe

            {'langgraph_node': 'sintetizar', 'ls_model_name': 'gemini-2.5-flash', ...}

        y `on_llm_end` recibe esa clave vacía. Leerla al final devolvía `None`, y todas las
        filas se habrían escrito con nodo 'desconocido': justamente la columna que justifica
        registrar por llamada en vez de un total por conversación.
        """
        metadata = kwargs.get("metadata") or {}
        self._en_vuelo[run_id] = (
            time.time(),
            metadata.get("langgraph_node") or "desconocido",
            metadata.get("ls_model_name") or "",
        )

    def on_llm_end(self, response, *, run_id, **kwargs):
        latencia, nodo, modelo = self._cerrar(run_id)
        try:
            generacion = response.generations[0][0]
            mensaje = getattr(generacion, "message", None)
            uso = getattr(mensaje, "usage_metadata", None) or {}
            self._escribir(
                nodo=nodo,
                modelo=modelo or self._modelo_de_respuesta(mensaje),
                tokens_entrada=uso.get("input_tokens", 0),
                tokens_salida=uso.get("output_tokens", 0),
                tokens_pensamiento=(uso.get("output_token_details") or {}).get("reasoning", 0),
                latencia_ms=latencia,
                error=None,
            )
        except Exception as e:
            _log.warning(f"No se pudo registrar el consumo de una llamada: {e}")

    def on_llm_error(self, error, *, run_id, **kwargs):
        """Una llamada que falla TAMBIÉN se registra, con costo 0 y el error.

        No es contabilidad de más: sin esta fila, un modelo que devuelve error de forma
        sistemática es invisible en las métricas —no aparece como gasto ni como latencia— y lo
        único que se ve es que el producto anda mal sin saber dónde.
        """
        try:
            latencia, nodo, modelo = self._cerrar(run_id)
            self._escribir(nodo=nodo, modelo=modelo or "desconocido",
                           tokens_entrada=0, tokens_salida=0, tokens_pensamiento=0,
                           latencia_ms=latencia, error=str(error)[:500])
        except Exception:
            pass

    # --- internos ---

    def _cerrar(self, run_id) -> tuple[int | None, str, str]:
        """Saca la llamada de las que están en vuelo y devuelve (latencia_ms, nodo, modelo)."""
        inicio, nodo, modelo = self._en_vuelo.pop(run_id, (None, "desconocido", ""))
        latencia = round((time.time() - inicio) * 1000) if inicio else None
        return latencia, nodo, modelo

    @staticmethod
    def _modelo_de_respuesta(mensaje) -> str:
        """Red para cuando el arranque no trajo el modelo: se lo pide a la respuesta."""
        if mensaje is None:
            return "desconocido"
        return (getattr(mensaje, "response_metadata", None) or {}).get("model_name") or "desconocido"

    def _escribir(self, *, nodo, modelo, tokens_entrada, tokens_salida,
                  tokens_pensamiento, latencia_ms, error):
        pool = _obtener_pool()
        if not pool:
            return
        costo = calcular_costo(modelo, tokens_entrada, tokens_salida)
        with pool.connection() as conn:
            fila = conn.execute(
                "INSERT INTO notaria.llamadas_llm "
                "(conversacion_id, nodo, modelo, tokens_entrada, tokens_salida, "
                " tokens_pensamiento, costo_usd, latencia_ms, error) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (self.conversacion_id, nodo, modelo, tokens_entrada, tokens_salida,
                 tokens_pensamiento, costo, latencia_ms, error),
            ).fetchone()
        if fila:
            self.ids_escritos.append(fila[0])


# ==========================================================================================
# CIERRE DEL TURNO
# ==========================================================================================

def guardar_turno(conversacion_id: str, pregunta: str, respuesta: str,
                  rutas: list[str], fuentes: list[dict], registro: RegistroDeConsumo) -> None:
    """Escribe los dos mensajes del turno y les cuelga las filas de consumo.

    POR QUÉ AL FINAL Y NO AL EMPEZAR. El gasto ocurre antes de que exista la respuesta:
    `clasificar` ya llamó a Gemini cuando todavía no hay una palabra que guardar. Por eso
    `llamadas_llm.mensaje_id` es nullable: las filas de consumo nacen sin mensaje y se
    completan acá con un UPDATE.

    La alternativa era crear un mensaje vacío al abrir el turno, pero eso deja un mensaje vacío
    en la tabla cada vez que un turno se corta a la mitad —y la UI tendría que filtrarlos—.
    Así, `mensajes` solo tiene turnos completos, que es lo que la UI necesita, y un turno
    cortado deja consumo sin mensaje: exactamente lo que pasó.

    ESTA TABLA GUARDA LA CONVERSACIÓN COMPLETA. El estado del agente no: guarda los últimos
    turnos más un resumen (ver la compactación en api/agente/nodos.py). Son dos cosas
    distintas: esto es el registro que el usuario relee, aquello es la memoria de trabajo del
    modelo.
    """
    pool = _obtener_pool()
    if not pool:
        return
    try:
        import json
        with pool.connection() as conn:
            conn.execute(
                "INSERT INTO notaria.mensajes (conversacion_id, rol, contenido) VALUES (%s,'usuario',%s)",
                (conversacion_id, pregunta),
            )
            fila = conn.execute(
                "INSERT INTO notaria.mensajes (conversacion_id, rol, contenido, rutas, fuentes) "
                "VALUES (%s,'asistente',%s,%s,%s) RETURNING id",
                (conversacion_id, respuesta, rutas or None, json.dumps(fuentes or [])),
            ).fetchone()
            if fila and registro.ids_escritos:
                conn.execute(
                    "UPDATE notaria.llamadas_llm SET mensaje_id = %s WHERE id = ANY(%s)",
                    (fila[0], registro.ids_escritos),
                )
            conn.execute(
                "UPDATE notaria.conversaciones SET actualizada_en = now() WHERE id = %s",
                (conversacion_id,),
            )
    except Exception as e:
        _log.warning(f"No se pudo guardar el turno de {conversacion_id}: {e}")
