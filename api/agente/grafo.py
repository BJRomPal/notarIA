"""EL GRAFO — la topología del agente y su compilación.

Define en qué orden corren los nodos y con qué checkpointer se guarda el estado. Junto con
`nodos.py`, es uno de los dos únicos archivos del proyecto que importan LangGraph.

LA TOPOLOGÍA: UNA CADENA LINEAL
-------------------------------
    __start__ -> clasificar -> esp_particular -> esp_general -> esp_determinista
              -> sintetizar -> __end__

Sin una sola arista condicional. Los tres especialistas corren siempre, en orden fijo, y cada
uno se saltea solo si su ruta no está en `estado["rutas"]` (ver nodos.py).

POR QUÉ ASÍ, Y NO CON RAMAS EN PARALELO. La primera versión usaba `add_conditional_edges` con
fan-out, que es lo que promete el documento de articulación. Se probó y falla de una manera
que no se ve venir leyendo el código: con dos especialistas activos, los dos eventos `fase`
salen pegados y después **todos los `item` caen bajo la última fase abierta**. En la prueba,
los cálculos del determinista aparecían bajo «Buscando información» y una fase entera quedaba
invisible. El frontend atribuye cada item a la última fase que recibió, y en paralelo eso deja
de ser cierto.

La cadena lineal lo resuelve de raíz y encima es más simple: cero aristas condicionales, cero
funciones de ruteo. Lo que se paga: en una consulta mixta el reloj es la suma y no el máximo.
Es una corrección a lo que el documento de articulación vendía como ventaja de esta variante.
Se puede recuperar el día que el evento `item` lleve su fase encima, pero eso pide cambiar el
frontend y hoy no lo vale.
"""
from langgraph.graph import StateGraph, START, END

from api.agente.estado import EstadoAgente
from api.agente.nodos import (
    clasificar, esp_particular, esp_general, esp_determinista, sintetizar,
)
from utils.connectors import get_checkpointer


def construir_grafo() -> StateGraph:
    """Arma el grafo sin compilarlo.

    Está separado de la compilación para poder dibujarlo o inspeccionarlo sin levantar el
    checkpointer, que necesita una conexión a Postgres. Es lo que usa el script que genera el
    diagrama de la documentación.
    """
    grafo = StateGraph(EstadoAgente)

    grafo.add_node("clasificar", clasificar)
    grafo.add_node("esp_particular", esp_particular)
    grafo.add_node("esp_general", esp_general)
    grafo.add_node("esp_determinista", esp_determinista)
    grafo.add_node("sintetizar", sintetizar)

    # El orden de los especialistas no es arbitrario: es de más caro a más barato en el peor
    # caso, para que en una consulta mixta el usuario vea primero el trabajo largo (la búsqueda
    # en el articulado, que puede tardar 14 s) y después los aportes rápidos, en vez de quedarse
    # mirando un cartel de "Calculando" que ya terminó.
    grafo.add_edge(START, "clasificar")
    grafo.add_edge("clasificar", "esp_particular")
    grafo.add_edge("esp_particular", "esp_general")
    grafo.add_edge("esp_general", "esp_determinista")
    grafo.add_edge("esp_determinista", "sintetizar")
    grafo.add_edge("sintetizar", END)

    return grafo


# Se compila una sola vez, al importar el módulo, y se reusa en todos los requests. Compilar
# por request tiraría el pool de conexiones del checkpointer en cada consulta.
#
# `checkpointer` es lo que convierte al grafo en multi-turno: guarda el estado bajo el
# thread_id de cada conversación y lo restaura en el turno siguiente. Sin él, `mensajes`
# arrancaría vacío siempre y «¿y para la SRL?» no tendría contra qué resolverse.
APP = construir_grafo().compile(checkpointer=get_checkpointer())
