"""EL ADAPTADOR — traduce una corrida del grafo al contrato SSE que espera el frontend.

Es la única puerta de entrada al agente. `api/server.py` importa `responder_stream()` de acá
y no sabe nada más: ni que hay un grafo, ni que hay tres especialistas, ni que existe
LangGraph. Ese aislamiento es el que permitió reescribir toda la articulación tocando **un
solo import** del resto del proyecto.

Reemplaza a `api/pipeline.py`, que era donde vivía esta función antes. El nombre y la firma
pública se mantienen a propósito: `responder_stream(pregunta)` sigue siendo un generador de
dicts. Lo único que cambia es que ahora acepta un `thread_id`.

EL CONTRATO SSE, que no cambió ni una coma:
    {"type": "fase",    "fase": str, "label": str}   — arranca una fase
    {"type": "item",    "texto": str}                — detalle dentro de la fase actual
    {"type": "fuentes", "articulos": [...]}          — las citas (REEMPLAZA, no acumula)
    {"type": "token",   "texto": str}                — fragmento de la respuesta
    {"type": "fin",     "articulos": int, "segundos": float}
    {"type": "error",   "mensaje": str}
"""
import threading
import time
import uuid
from typing import Iterator
from weakref import WeakValueDictionary

from langchain_core.messages import HumanMessage

from api.agente.grafo import APP
from api.consumo import RegistroDeConsumo, alias_de, asegurar_conversacion, guardar_turno


# UN LOCK POR CONVERSACIÓN, para que dos preguntas del mismo hilo no se pisen (ver el detalle
# en `responder_stream`). Alcanza con uno sincrónico: FastAPI ya corre el endpoint —que es
# `def`, no `async def`— en un hilo del pool, así que bloquear acá no congela el event loop;
# frena a ese hilo, que es exactamente lo que se busca.
#
# WeakValueDictionary y no un dict común para que el registro se limpie solo: mientras un
# pedido tiene el lock en la mano lo mantiene vivo, y cuando la última referencia se va, la
# entrada desaparece. Con un dict común quedaría una entrada por conversación para siempre.
_locks_por_hilo: "WeakValueDictionary[str, threading.Lock]" = WeakValueDictionary()
_guardia_locks = threading.Lock()


def _lock_del_hilo(hilo: str) -> threading.Lock:
    """El lock de esa conversación, creándolo la primera vez.

    El `_guardia_locks` protege el hueco entre consultar y crear: sin él, dos pedidos
    simultáneos del mismo hilo podrían fabricar dos locks distintos y no excluirse entre sí,
    que es justo lo que se quiere evitar.
    """
    with _guardia_locks:
        lock = _locks_por_hilo.get(hilo)
        if lock is None:
            lock = threading.Lock()
            _locks_por_hilo[hilo] = lock
        return lock


def responder_stream(pregunta: str, thread_id: str | None = None, identidad=None) -> Iterator[dict]:
    """Corre el agente y va emitiendo los eventos SSE a medida que ocurren.

    `thread_id` identifica la conversación en las tres capas a la vez: el checkpointer de
    LangGraph, la tabla `notaria.conversaciones` y el `conversation.id` del frontend. Una sola
    clave, sin traducciones.

    Dos llamadas con el mismo id comparten historial,
    y es lo que hace que «¿y para la SRL?» se entienda. Viene del frontend, donde ya existe
    como `conversation.id` en localStorage. Si no llega, se genera uno al vuelo: el turno
    funciona igual, simplemente no se acumula historial — que es exactamente el comportamiento
    que tenía el sistema antes del agente.

    POR QUÉ `stream_mode="custom"` Y NADA MÁS
    -----------------------------------------
    Es un pasamanos puro: lo que un nodo empuja con el writer sale de acá tal cual, sin
    envoltorio. Por eso el `yield evento` de abajo no transforma nada.

    Y por eso mismo hay una trampa que conviene dejar escrita. Los ejemplos de la
    documentación de LangGraph usan `stream(..., stream_mode="custom", version="v2")`, y ese
    parámetro **cambia la forma de lo que llega**:

        sin version   -> {'type': 'fase', 'fase': 'vectorial', ...}          <- el dict crudo
        version="v2"  -> {'type': 'custom', 'ns': (), 'data': {'type': ...}} <- envuelto

    Si alguien copia el ejemplo de la doc, el fallo es de los peores: los eventos llegan
    envueltos, el `applyEvent` del frontend no reconoce `type: "custom"`, cae en su
    `default: return msg` y **la pantalla deja de actualizarse sin lanzar un solo error**.

    Tampoco se usa `stream_events(version="v3")`, que es lo que la documentación recomienda
    "for most application and frontend use cases". Existe en la versión instalada, pero emite
    `LangChainBetaWarning: The v3 streaming protocol on Pregel is experimental`. Poner la
    columna vertebral del streaming de un chat legal sobre un protocolo experimental es mal
    negocio, sobre todo porque el modo de falla es silencioso. Cuando salga de beta conviene
    volver a mirarlo: trae `params.node` en cada evento, que es justo el metadato que le falta
    hoy al evento `item` para poder volver a paralelizar los especialistas.
    """
    # EL CRONÓMETRO DEL TURNO. Va acá y no en `sintetizar` porque esta función es lo único que
    # ve el turno entero: el nodo de redacción arranca cuando ya pasaron el clasificador y los
    # especialistas, que en una consulta al grafo son la mayor parte de la espera. Medido sobre
    # una consulta real: `sintetizar` tardó 9,9 s y el turno completo 28,3 s. Con el reloj
    # adentro del nodo, el usuario leía 10,2 s — subestimando casi tres veces.
    t0 = time.time()
    hilo = thread_id or str(uuid.uuid4())

    # SERIALIZADO POR CONVERSACIÓN. Sin esto, dos preguntas seguidas sobre el mismo `thread_id`
    # se pisan: el evento `fin` puede llegarle al usuario ANTES de que el estado del turno quede
    # persistido, porque LangGraph vacía el writer en tiempo real mientras el nodo sigue
    # corriendo (`sintetizar` todavía tiene que compactar la conversación, que a veces llama al
    # modelo, y recién después devuelve y se escribe el checkpoint). Si en esa ventana entra una
    # pregunta nueva, el clasificador del turno siguiente lee `mensajes` sin la respuesta que el
    # usuario acaba de leer, y una referencia como «¿y eso qué significa?» no se resuelve.
    #
    # Se toma DESPUÉS del cronómetro a propósito: si el turno tuvo que esperar su lugar en la
    # fila, esa espera es parte de lo que el usuario esperó y tiene que verse en `segundos`.
    #
    # LÍMITE CONOCIDO: esto serializa dentro de UN proceso. En Cloud Run con varias instancias,
    # dos pedidos del mismo hilo pueden caer en instancias distintas y el lock no los ve. Para
    # ese escenario hace falta afinidad de sesión o un lock en la base; queda anotado y no se
    # resuelve acá porque hoy corre en un proceso.
    with _lock_del_hilo(hilo):

        # LA CONTABILIDAD VIVE ACÁ Y NO EN LOS NODOS. Esta es la capa que ya habla con el mundo de
        # afuera; los nodos y los especialistas siguen sin saber que existe una base de costos.
        # Si no hay POSTGRES_URL, las tres funciones de consumo son no-ops y esto no cambia nada.
        # `identidad` viene de api/auth.py y la pone server.py: es None mientras la
        # autenticación esté apagada, y entonces todo se atribuye al usuario de desarrollo.
        hay_base = asegurar_conversacion(hilo, pregunta, identidad)
        registro = RegistroDeConsumo(hilo)

        # El alias va DESPUÉS de asegurar la conversación, que es la que crea la fila del
        # usuario: así `alias_de` es un SELECT y no tiene que volver a resolver la identidad.
        # Sin base devuelve None y el prompt de redacción queda igual al de siempre.
        alias = alias_de(identidad) or ""

        # El callback se instala SOLO si la conversación quedó registrada. Sin esa fila, cada
        # llamada al modelo intentaría insertar contra una clave foránea que no existe: seis
        # viajes fallidos a Postgres por turno, seis warnings, y ninguna fila escrita igual.
        # Es lo que pasa, por ejemplo, si el thread_id no es un UUID válido — `conversaciones.id`
        # es uuid, y el frontend siempre manda un crypto.randomUUID(), pero el body lo puede
        # mandar cualquiera.
        config = {"configurable": {"thread_id": hilo}}
        if hay_base:
            config["callbacks"] = [registro]
        entrada = {
            "pregunta": pregunta,
            "mensajes": [HumanMessage(content=pregunta)],
            "alias": alias,
        }

        # Se acumulan los tokens y las fuentes al pasar, para poder guardar el turno al cerrar sin
        # volver a pedirle nada al grafo. Es leer lo que ya está saliendo, no trabajo extra.
        respuesta, fuentes = [], []
        for evento in APP.stream(entrada, config, stream_mode="custom"):
            if evento.get("type") == "token":
                respuesta.append(evento["texto"])
            elif evento.get("type") == "fuentes":
                fuentes = evento["articulos"]
            elif evento.get("type") == "fin":
                # `sintetizar` emite el evento con lo que sabe —cuántas fuentes— y el tiempo se
                # completa acá, que es donde está el reloj del turno. Se copia el dict en vez de
                # mutarlo: el objeto viene del stream de LangGraph y no es nuestro.
                evento = {**evento, "segundos": round(time.time() - t0, 1)}
            yield evento

        if hay_base:
            # Las rutas no viajan por el stream —son un detalle interno— así que se leen del estado
            # ya persistido por el checkpointer, que es su lugar natural.
            try:
                rutas = APP.get_state(config).values.get("rutas", [])
            except Exception:
                rutas = []
            guardar_turno(hilo, pregunta, "".join(respuesta), rutas, fuentes, registro)
