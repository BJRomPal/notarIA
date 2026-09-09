"""EL ESTADO DEL AGENTE — la estructura que viaja entre los nodos del grafo.

Un `StateGraph` de LangGraph no pasa argumentos de un nodo al siguiente: cada nodo recibe el
estado completo y devuelve un diccionario **parcial** con lo que quiere cambiar. LangGraph
combina ese parcial con el estado que ya había. Cómo lo combina lo decide el reducer de cada
campo, y ahí está todo el diseño de este archivo.

LOS DOS COMPORTAMIENTOS QUE CONVIVEN ACÁ
----------------------------------------
- Campo SIN reducer (`pregunta`, `rutas`, `respuesta`): el valor nuevo PISA al viejo. Es lo
  que se quiere para un dato que pertenece a un turno.
- Campo CON reducer (`mensajes`, `contexto`, `fuentes`): el valor nuevo se COMBINA con el
  viejo. Es lo que permite que tres especialistas aporten contexto sin pisarse entre sí.

LA CONVERSACIÓN NO SE ACUMULA TEXTUALMENTE
------------------------------------------
Guardar los turnos enteros en el estado hace que el costo de una conversación crezca de forma
cuadrática: cada turno nuevo vuelve a mandar todo lo anterior. Una charla de veinte turnos
terminaría pagando el turno 1 veinte veces.

Por eso el estado guarda dos cosas distintas:

    resumen   texto condensado de los turnos viejos, que reemplaza a esos turnos
    mensajes  SOLO los últimos turnos, textuales (ver MENSAJES_VERBATIM en nodos.py)

**La conversación completa no vive acá.** Vive donde la ve el usuario: hoy en el localStorage
del frontend, mañana en la tabla `notaria.mensajes`. El estado del agente es lo que lee el
modelo, y el modelo no necesita la transcripción literal de lo que se habló hace diez turnos:
necesita saber de qué se venía hablando.


ACLARACIÓN IMPORTANTE
--------------------------------------------------------------------------
El checkpointer **persiste el estado entero**, todos los campos, no solo `mensajes`. Que el
contexto de un turno no aparezca en el siguiente no es una propiedad del framework: se
consigue limpiándolo a mano en el nodo `clasificar` al arrancar cada turno. Si nadie lo
limpiara, el reducer iría acumulando el contexto de toda la conversación y el prompt crecería
sin techo hasta reventar la ventana (y la factura). Por eso el reducer de este archivo no es
`operator.add` pelado: tiene que saber vaciar. Ver `acumular()`.
"""
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


def acumular(anterior: list, nuevo: list | None) -> list:
    """Reducer de `contexto` y `fuentes`: concatena, y vacía cuando el nodo devuelve None.

    POR QUÉ NO ALCANZA `operator.add`, que era lo que decía el plan. Un reducer que solo
    concatena no tiene forma de expresar "borrá lo que había": devolver `[]` deja el valor
    anterior intacto, porque `viejo + [] == viejo`. Y hay que poder borrar, porque el
    checkpointer persiste el estado ENTERO entre turnos — sin un borrado explícito, el
    contexto del turno 1 seguiría en el prompt del turno 7, multiplicando el costo y
    ensuciando la respuesta con material de otra pregunta.

    La convención es mínima y explícita: `None` significa vaciar, una lista significa sumar.
    La usa `clasificar` una vez por turno; todos los demás nodos solo suman.
    """
    if nuevo is None:
        return []
    return (anterior or []) + nuevo


class EstadoAgente(TypedDict):
    """El estado que comparten todos los nodos del grafo.

    Campo por campo:

    pregunta   La consulta del turno actual, TAL COMO la escribió el usuario. La pone el
               adaptador de streaming al arrancar. Se pisa en cada turno.

    consulta   La misma pregunta, pero AUTOCONTENIDA: con las referencias al historial ya
               resueltas. «¿Y para la SRL?» se convierte en «¿Qué requisitos tiene la SRL?».
               La escribe `clasificar` y es la que leen los tres especialistas y el redactor.

               No es un lujo: los especialistas buscan en el grafo con esta cadena, y una
               pregunta como «volviendo al primero, ¿ese derecho se puede transmitir?» no
               tiene nada que buscar. Medido: sin esto, ese turno devolvía una respuesta
               genérica sobre transmisibilidad en vez de hablar del usufructo.

               Sale de la MISMA llamada que las rutas, así que **no cuesta una llamada extra**.
               Es exactamente el paso de condensación que la variante A del documento de
               articulación tenía que agregar aparte.

    mensajes   El historial de la conversación. **Es el único campo que persiste entre
               turnos con sentido**, y el que hace que «¿y para la SRL?» se entienda sin una
               llamada extra de condensación: `clasificar` lo lee y resuelve la referencia.
               El reducer `add_messages` es de LangGraph y no es un simple append — hace
               dedup por id de mensaje y sabe reemplazar un mensaje por otro con el mismo id,
               que es lo que permite reanudar una ejecución sin duplicar el historial.

    rutas      Qué especialistas atienden este turno: ["particular"], ["general"],
               ["determinista"] o una combinación. La llena `clasificar` y la leen los tres
               nodos de especialista para decidir si corren o se saltean.

    contexto   El material recuperado, ya formateado como bloques de texto listos para el
               prompt. El reducer `acumular` concatena las listas, así que si corren dos
               especialistas el contexto de los dos queda junto, en el orden del grafo, y
               `clasificar` lo vacía al arrancar cada turno devolviendo None.

               Son `list[str]` y no objetos ContextoAcumulado por dos razones que se suman:
               (1) ContextoAcumulado tiene un `set` adentro y **no es serializable**, así que
               el checkpointer no podría guardarlo; (2) el reducer sabe concatenar listas, no
               fusionar objetos. El desenvuelto lo hace cada nodo (ver nodos.py).

    fuentes    Las citas que ve el usuario, [{id, tipo, numero, norma}]. Mismo reducer y misma
               lógica que `contexto`. Se emiten al frontend una sola vez, desde `sintetizar`,
               porque el evento `fuentes` REEMPLAZA la lista del cliente en vez de sumarse:
               emitirlo por especialista dejaría visibles solo las del último.

    resumen    El resumen corrido de la conversación, para los turnos que ya salieron de la
               ventana textual. Ver "LA CONVERSACIÓN NO SE ACUMULA TEXTUALMENTE" arriba.

    respuesta  El texto final. Lo escribe `sintetizar`. Hoy lo consume el propio nodo para
               guardarlo en `mensajes`; queda en el estado porque es lo que se persistirá en
               `notaria.mensajes` cuando exista esa tabla.
    """
    pregunta: str
    consulta: str
    mensajes: Annotated[list[AnyMessage], add_messages]
    rutas: list[str]
    resumen: str
    contexto: Annotated[list[str], acumular]
    fuentes: Annotated[list[dict], acumular]
    respuesta: str


# Las tres rutas posibles. Se define acá y no en el clasificador porque la usan los dos: el
# clasificador para validar lo que devolvió el modelo, y los nodos para preguntar si les toca.
RUTAS_VALIDAS = ("particular", "general", "determinista")

# A qué ruta se cae cuando el clasificador falla o devuelve algo que no se entiende. Es la
# particular porque es la que más cubre: ante la duda, buscar en el articulado es la conducta
# correcta de un sistema legal, y además es lo que el pipeline hacía antes de que existiera
# el agente. Un fallo del clasificador degrada al comportamiento viejo, no a un error.
RUTA_POR_DEFECTO = "particular"
