"""LOS NODOS DEL GRAFO — el único lugar del proyecto que conoce LangGraph.

Cinco nodos: `clasificar`, los tres envoltorios de especialista, y `sintetizar`. Todo lo que
sabe de LangGraph vive acá y en `grafo.py`; los especialistas de `api/especialistas/` son
generadores planos que no importan el framework. Esa separación es deliberada: si mañana
LangGraph se cambia por otra cosa, se reescriben estos dos archivos y los especialistas no se
tocan.

EL PUENTE, QUE ES LA PIEZA CENTRAL
----------------------------------
Un especialista emite eventos con `yield`. Un nodo de LangGraph no puede hacer `yield`: tiene
que devolver un diccionario. Entre las dos formas está `get_stream_writer()`, que devuelve una
función capaz de empujar cualquier objeto al stream de la corrida en curso.

Con eso, `_drenar()` traduce una forma en la otra sin perder nada: reenvía cada evento al
stream a medida que aparece —o sea que el frontend los ve llegar igual que hoy, en tiempo
real— y se queda con el `return` del generador.
"""

from langgraph.config import get_stream_writer

from api.agente.estado import EstadoAgente, RUTAS_VALIDAS, RUTA_POR_DEFECTO
from api.especialistas.particular import (
    particular, fuentes_particular, llm, llm_lite, neo4j_driver,
)
from api.especialistas.general import general, fuentes_general
from api.especialistas.determinista import determinista
from utils.connectors import get_gemini_llm
from utils.rag.grafo import entidades_relacionadas, format_entidades
from utils.rag.llm_io import json_del_llm
from langchain_core.messages import AIMessage, RemoveMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser


# ==========================================================================================
# EL PUENTE
# ==========================================================================================

def _drenar(generador, writer):
    """Reenvía cada evento del especialista al stream de LangGraph y devuelve su `return`.

    Es el equivalente exacto de `ctx = yield from recuperar_contexto(...)`, pero traducido a una función que puede vivir adentro de un nodo. Las dos mitades importan:

      - `writer(next(generador))` empuja el evento al stream **en el momento en que ocurre**.
        No se acumula nada: si el especialista tarda 14 segundos, el usuario ve los carteles
        avanzar durante esos 14 segundos.
      - `except StopIteration as fin: return fin.value` captura el valor de `return` del
        generador, que es donde el especialista deja su resultado. Sin esta parte, drenar el
        generador tiraría a la basura justamente lo que fuimos a buscar.
    """
    try:
        while True:
            writer(next(generador))
    except StopIteration as fin:
        return fin.value


# ==========================================================================================
# NODO 1: CLASIFICAR
# ==========================================================================================

# Se le pasan los últimos turnos y no solo la pregunta, y por eso «¿y para la SRL?» se
# entiende: la referencia se resuelve leyendo el historial, sin una llamada extra de
# condensación. Es justo el parche que la variante A del documento de articulación necesitaba
# y que acá sale gratis del estado.
_PROMPT_CLASIFICADOR = """Clasificá la consulta de un escribano argentino en una o más rutas.

RUTAS:
- "particular": pregunta por una norma, un artículo o un supuesto concreto del derecho.
  Ejemplos: "¿qué requisitos exige el art. 77 LSC?", "¿qué dice la ley sobre la fusión?",
  "¿Quienes no pueden ser testigos en un testamento?"
- "general": pregunta por un instituto jurídico en abstracto, su definición, sus
  características o su comparación con otro. Ejemplos: "diferencias entre la SA y la SRL",
  "¿qué es el usufructo?", "¿qué es la sucesión intestada?"
- "determinista": pide un cálculo con resultado exacto: dígito verificador, CUIL, o el
  vencimiento de un certificado, de un ingreso al RPI o de una prórroga de inscripción.

Se puede elegir más de una si la consulta tiene partes de distinto tipo.

CONVERSACIÓN PREVIA (para resolver referencias como "¿y para la SRL?"):
{historial}

CONSULTA A CLASIFICAR:
{pregunta}

Devolvé SOLO un JSON con dos claves:
{{"rutas": ["..."],
  "consulta": "la consulta reescrita de forma autocontenida, resolviendo con la conversación
               previa cualquier referencia como 'y para la SRL', 'ese derecho', 'el primero'.
               Si la consulta ya se entiende sola, copiala tal cual."}}"""


def clasificar(estado: EstadoAgente) -> dict:
    """Decide qué especialistas atienden el turno y limpia el contexto del turno anterior.

    Emite la fase `clasificar`, que el frontend muestra como «Analizando la pregunta». El id
    de la fase y el cartel son cosas distintas a propósito: el id nos sirve para la telemetría
    (es el campo `nodo` de la tabla de consumo), el cartel es lo único que ve el usuario, y el
    usuario no tiene por qué enterarse de que existen nodos distintos.

    LA LIMPIEZA NO ES DECORATIVA. `contexto` y `fuentes` se acumulan con un reducer, y el
    checkpointer persiste el estado entero entre turnos: si nadie los vacía, el contexto del
    turno 1 sigue en el prompt del turno 7. Devolver `[]` no alcanza —el reducer concatena, y
    `viejo + [] == viejo`—, por eso el reducer `acumular` de estado.py entiende `None` como
    "vaciá esto". Es la única vez por turno que se usa esa convención.
    """
    writer = get_stream_writer()
    writer({"type": "fase", "fase": "clasificar", "label": "Analizando la pregunta"})

    historial = _historial_corto(estado.get("mensajes", []), estado.get("resumen", ""))
    rutas, consulta = _clasificar_y_resolver(estado["pregunta"], historial)

    return {
        "rutas": rutas,
        "consulta": consulta,
        "contexto": None,   # None = vaciar (ver acumular() en estado.py)
        "fuentes": None,
        "respuesta": "",
    }


def _clasificar_y_resolver(pregunta: str, historial: str) -> tuple[list[str], str]:
    """Una sola llamada a flash-lite que devuelve las rutas Y la consulta autocontenida.

    Las dos cosas salen juntas porque las dos necesitan lo mismo —la pregunta y el historial—
    y separarlas costaría una segunda llamada para releer exactamente el mismo texto.

    NUNCA LEVANTA EXCEPCIÓN. Si el modelo falla, devuelve algo ilegible o inventa una ruta que
    no existe, se cae a la ruta por defecto y a la pregunta cruda. Un clasificador roto tiene
    que degradar al comportamiento viejo —buscar en el articulado con lo que el usuario
    escribió—, nunca cortar la consulta.
    """
    try:
        respuesta = llm_lite.invoke(_PROMPT_CLASIFICADOR.format(pregunta=pregunta, historial=historial))
        datos = json_del_llm(str(respuesta.content))
        rutas = [r for r in datos.get("rutas", []) if r in RUTAS_VALIDAS]
        consulta = str(datos.get("consulta", "")).strip()
    except Exception:
        rutas, consulta = [], ""
    return (rutas or [RUTA_POR_DEFECTO]), (consulta or pregunta)


def _historial_corto(mensajes: list, resumen: str) -> str:
    """El contexto conversacional que recibe el clasificador: el resumen de lo viejo más los
    turnos recientes textuales.

    Es la mitad de lectura del mecanismo que describe MENSAJES_VERBATIM. El clasificador solo
    necesita saber de qué se venía hablando para resolver «¿y para la SRL?»; no necesita la
    transcripción. Cada turno se corta en 300 caracteres por lo mismo: mandar la respuesta
    completa multiplicaría el costo del nodo más barato del grafo sin cambiar la etiqueta que
    devuelve.
    """
    partes = []
    if resumen:
        partes.append(f"Resumen de lo hablado antes: {resumen}")
    for mensaje in mensajes[-MENSAJES_VERBATIM:]:
        rol = "Usuario" if mensaje.type == "human" else "Asistente"
        partes.append(f"{rol}: {str(mensaje.content)[:300]}".replace("\n", " "))
    return "\n".join(partes) if partes else "(no hay turnos previos)"


def _consulta(estado: EstadoAgente) -> str:
    """La consulta autocontenida que dejó `clasificar`, con la pregunta cruda como red.

    El fallback importa: si por lo que sea `consulta` viene vacía, se usa lo que escribió el
    usuario. Buscar con la pregunta original es peor que buscar con la resuelta, pero es
    infinitamente mejor que buscar con una cadena vacía.
    """
    return estado.get("consulta") or estado["pregunta"]


# ==========================================================================================
# NODOS 2, 3 y 4: LOS ESPECIALISTAS
# ==========================================================================================
# Los tres tienen la misma forma y corren SIEMPRE, en el orden fijo que define grafo.py. El
# que no fue elegido se saltea solo devolviendo {} — un diccionario vacío no cambia nada del
# estado.
#
# POR QUÉ UNA CADENA LINEAL Y NO TRES RAMAS EN PARALELO: se probaron las dos. Con fan-out, los
# eventos de dos especialistas se intercalan y el frontend atribuye TODOS los `item` a la
# última `fase` abierta, así que los cálculos aparecían bajo "Buscando información" y una fase
# quedaba invisible. En cadena, cada item cae bajo su fase. Se paga que los especialistas ya no
# corren en paralelo; se gana que la pantalla dice la verdad.

def esp_particular(estado: EstadoAgente) -> dict:
    """Envuelve al especialista particular. Aporta contexto y fuentes de tipo artículo y fallo."""
    if "particular" not in estado["rutas"]:
        return {}
    ctx = _drenar(particular(_consulta(estado)), get_stream_writer())
    return {"contexto": ctx.textos, "fuentes": fuentes_particular(ctx)}


def esp_general(estado: EstadoAgente) -> dict:
    """Envuelve al especialista general. Aporta los resúmenes de los institutos involucrados."""
    if "general" not in estado["rutas"]:
        return {}
    ctx = _drenar(general(_consulta(estado)), get_stream_writer())
    return {"contexto": ctx.textos, "fuentes": fuentes_general(ctx)}


def esp_determinista(estado: EstadoAgente) -> dict:
    """Envuelve al especialista determinista.

    Devuelve `contexto` pero NO `fuentes`: un cálculo no tiene una norma que citar. El
    resultado es autoridad por sí mismo — lo produjo el código, no un modelo leyendo un texto.
    """
    if "determinista" not in estado["rutas"]:
        return {}
    bloques = _drenar(determinista(_consulta(estado)), get_stream_writer())
    return {"contexto": bloques}


# ==========================================================================================
# NODO 5: SINTETIZAR
# ==========================================================================================

# El prompt viene tal cual de api/pipeline.py, sin tocar una coma. Es el que está calibrado
# contra las evaluaciones de tests/lmjudge_dinamico.py, así que cambiarlo acá mezclaría dos
# causas de regresión: la articulación nueva y una redacción distinta.
template_respuesta = """Eres un asistente legal experto en derecho argentino.

PASO PREVIO OBLIGATORIO: Antes de escribir la respuesta, identificá mentalmente cuáles artículos del contexto responden DIRECTAMENTE a la pregunta. Los demás artículos deben ser descartados por completo, aunque sean temáticamente cercanos.

INSTRUCCIONES:
1. Respondé EXCLUSIVAMENTE sobre el sujeto y el supuesto que se pregunta. Si el contexto incluye artículos que tratan un caso similar pero para un sujeto distinto al preguntado, esos artículos son irrelevantes: no los mencionés, no los cités ni los uses como apoyo.
2. Si la norma enumera condiciones, requisitos o excepciones aplicables al sujeto y supuesto preguntado, incluilos TODOS sin omitir ninguno.
3. Usá ÚNICAMENTE el contexto provisto. No inventes.
4. Citá siempre el número de artículo y la norma de la que proviene cada afirmación.

CONTEXTO LEGAL RECUPERADO:
{context}

PREGUNTA:
{question}

RESPUESTA:"""

_prompt_respuesta = ChatPromptTemplate.from_template(template_respuesta)

# La cadena normal: flash con su pensamiento por defecto. Es la que redacta cuando hay que
# leer artículos, compararlos y decidir cuáles responden la pregunta.
answer_chain = _prompt_respuesta | llm | StrOutputParser()

# La cadena para los turnos que solo transcriben un cálculo. Mismo modelo y mismo prompt, con
# el razonamiento apagado.
#
# POR QUÉ SOLO ACÁ. Cuando la única ruta es la determinista, el contexto que llega es un bloque
# de tres líneas con un número que el código ya calculó, y redactar es ponerlo en una frase.
# No hay artículos que comparar ni nada que decidir: el pensamiento se gasta entero en un
# problema que no existe.
#
# Medido sobre «¿Cuál es el dígito verificador de la partida 1180431?», con el mismo contexto:
#
#     flash como estaba          2.140 ms   432 tokens de salida, 411 de pensamiento   US$ 0,001174
#     flash + thinking_budget=0    668 ms    21 tokens de salida,   0 de pensamiento   US$ 0,000147
#
# **La respuesta salió idéntica, carácter por carácter**, 8 veces más barata y 3,2 veces más
# rápida. Se descartó flash-lite, que es otras 3,7 veces más barato pero tarda 1.185 ms: la
# diferencia de costo es una décima de centavo y la de latencia se nota en pantalla.
answer_chain_directa = (
    _prompt_respuesta | get_gemini_llm("gemini-2.5-flash", thinking_budget=0) | StrOutputParser()
)


def _cadena_para(rutas: list[str]):
    """Elige con qué cadena redactar según qué especialistas atendieron el turno.

    La condición es que la ruta determinista sea la ÚNICA. En una consulta mixta —«¿qué exige
    la IGJ para inscribir una transformación y cuál es el DV de la partida 1180431?»— el
    redactor tiene que leer articulado además de transcribir el número, y ahí el razonamiento
    sí hace falta. Por eso se compara la lista entera y no `"determinista" in rutas`.
    """
    return answer_chain_directa if rutas == ["determinista"] else answer_chain


def sintetizar(estado: EstadoAgente) -> dict:
    """Redacta la respuesta final con todo lo que aportaron los especialistas.

    Es común a las tres rutas, y esa es la razón por la que la redacción se sacó del
    especialista particular: no hay tres respuestas distintas, hay una sola.

    Hace cuatro cosas, en este orden:

    1. DEDUPLICA las fuentes. Cada especialista deduplica lo suyo, pero en una consulta mixta
       el particular y el general pueden traer el mismo id y `operator.add` los concatena sin
       mirar. Es una pasada por id, barata, que evita mostrar la cita repetida.
    2. EMITE `fuentes` una sola vez, con la lista ya completa. El evento REEMPLAZA la lista
       del cliente en vez de sumarse, así que emitirlo antes dejaría visibles solo las últimas.
       Va antes del primer token para que las citas aparezcan mientras se escribe la respuesta.
    3. STREAMEA la respuesta token a token por el writer, igual que hacía el pipeline viejo,
       con la cadena que corresponda a las rutas del turno (ver `_cadena_para`).
    4. GUARDA el turno en `mensajes`.
    5. COMPACTA la conversación si ya se hizo larga, para que el costo del turno 20 no sea el
       de los 19 anteriores sumados. Ver la sección de compactación al final del archivo.

    Emite la fase `redaccion` —no `sintetizar`— porque ese id ya existe en el frontend y
    significa exactamente lo mismo para quien mira la pantalla. El id de una fase no tiene por
    qué llamarse como el nodo que la emite.
    """
    writer = get_stream_writer()

    fuentes = _deduplicar_fuentes(estado.get("fuentes", []))
    writer({"type": "fuentes", "articulos": fuentes})

    writer({"type": "fase", "fase": "redaccion", "label": "Redactando la respuesta"})
    contexto = _armar_contexto(estado.get("contexto", []), fuentes)

    partes = []
    cadena = _cadena_para(estado.get("rutas", []))
    for fragmento in cadena.stream({"context": contexto, "question": _consulta(estado)}):
        if fragmento:
            partes.append(fragmento)
            writer({"type": "token", "texto": fragmento})
    respuesta = "".join(partes)

    # Sin `segundos`: este nodo no puede medir el turno, porque arranca cuando el clasificador
    # y los especialistas ya terminaron. Lo estampa `streaming.py`, que es quien lo ve entero.
    writer({"type": "fin", "articulos": len(fuentes)})

    # La compactación va DESPUÉS del evento `fin`, a propósito: para ese momento el usuario ya
    # leyó la respuesta completa, así que la llamada de resumen no le agrega un segundo de
    # espera. Es trabajo de cierre del turno, no del camino crítico.
    mensaje_nuevo = AIMessage(content=respuesta)
    compactado = _compactar(estado.get("mensajes", []) + [mensaje_nuevo],
                            estado.get("resumen", ""))

    # Los borrados se SUMAN al mensaje nuevo en la misma lista, no lo reemplazan: `add_messages`
    # procesa la lista en orden, así que primero suma la respuesta de este turno y después saca
    # los turnos viejos. Pisar la clave "mensajes" con la lista de borrados haría desaparecer
    # la respuesta que se acaba de escribir.
    salida = {"respuesta": respuesta, "mensajes": [mensaje_nuevo] + compactado.pop("mensajes", [])}
    salida.update(compactado)      # lo que queda es, a lo sumo, "resumen"
    return salida


def _deduplicar_fuentes(fuentes: list[dict]) -> list[dict]:
    """Quita repetidos por id conservando el orden de aparición."""
    vistos, unicas = set(), []
    for fuente in fuentes:
        if fuente["id"] not in vistos:
            vistos.add(fuente["id"])
            unicas.append(fuente)
    return unicas


def _armar_contexto(bloques: list[str], fuentes: list[dict]) -> str:
    """Une los bloques de los especialistas y les suma el vecindario ontológico.

    Las entidades relacionadas se consultan solo para las fuentes de tipo artículo: es una
    consulta por ids de `:Articulo` y pasarle ids de fallo o de instituto no devolvería nada,
    solo trabajo. Esto reproduce lo que hacía `_armar_fuentes_y_entidades()` en el pipeline
    viejo, que es de donde sale.
    """
    ids_articulos = [f["id"] for f in fuentes if f.get("tipo") == "articulo"]
    entidades = entidades_relacionadas(neo4j_driver, ids_articulos) if ids_articulos else []
    return "\n\n---\n\n".join(bloques) + format_entidades(entidades)

# ==========================================================================================
# COMPACTACIÓN DE LA CONVERSACIÓN
# ==========================================================================================
# El problema que resuelve: si el estado guardara todos los turnos textuales, el costo de una
# conversación crecería de forma cuadrática — cada turno nuevo vuelve a mandar todo lo
# anterior, así que una charla de veinte turnos paga el turno 1 veinte veces.
#
# La solución es la de siempre en un chat largo: una ventana textual de los últimos turnos más
# un resumen corrido de todo lo que quedó atrás. Cuando el historial pasa el umbral, los
# mensajes viejos se condensan en el resumen y se borran del estado.
#
# LO QUE SE BORRA ACÁ NO SE PIERDE. La conversación completa —la que el usuario lee y puede
# releer— vive en el frontend y, cuando exista, en la tabla `notaria.mensajes`. Lo que se
# compacta es únicamente lo que lee el modelo.

MENSAJES_VERBATIM = 4    # los últimos 2 turnos (pregunta + respuesta) quedan textuales
UMBRAL_COMPACTAR = 8     # a partir de 4 turnos se empieza a compactar

_PROMPT_RESUMEN = """Vas a resumir una conversación entre un escribano y un asistente legal, para
que el asistente pueda seguir el hilo en los turnos siguientes sin releerla entera.

Escribí un párrafo de 120 palabras como máximo. Incluí los temas jurídicos tratados y las normas
o institutos que se mencionaron, porque de eso dependen las referencias futuras («¿y para la
SRL?»). No incluyas el detalle de las respuestas ni citas textuales.

{resumen_previo}

CONVERSACIÓN A RESUMIR:
{conversacion}

RESUMEN:"""


def _compactar(mensajes: list, resumen_actual: str) -> dict:
    """Condensa los turnos viejos en el resumen y los saca del estado.

    Devuelve el parcial de estado que hay que aplicar, o {} si todavía no hace falta compactar.

    El borrado se hace con `RemoveMessage`, que es cómo el reducer `add_messages` de LangGraph
    entiende "sacá este mensaje": se le devuelve un RemoveMessage con el id del mensaje a
    eliminar. Por eso los mensajes viejos tienen que tener id — se los asigna LangChain al
    construirlos, así que en la práctica siempre lo tienen; los que no, se dejan estar.

    Si la llamada de resumen falla, se devuelve {} y **no se borra nada**. Perder el historial
    porque el resumen no salió sería el peor de los dos mundos: se paga igual y encima se
    olvida la conversación.
    """
    if len(mensajes) <= UMBRAL_COMPACTAR:
        return {}

    viejos = mensajes[:-MENSAJES_VERBATIM]
    conversacion = "\n".join(
        f"{'Usuario' if m.type == 'human' else 'Asistente'}: {str(m.content)[:1500]}"
        for m in viejos
    )
    previo = (f"RESUMEN ANTERIOR (incorporalo al nuevo, no lo repitas aparte):\n{resumen_actual}"
              if resumen_actual else "")
    try:
        respuesta = llm_lite.invoke(_PROMPT_RESUMEN.format(
            resumen_previo=previo, conversacion=conversacion))
        resumen = str(respuesta.content).strip()
    except Exception:
        return {}
    if not resumen:
        return {}

    borrados = [RemoveMessage(id=m.id) for m in viejos if getattr(m, "id", None)]
    return {"resumen": resumen, "mensajes": borrados}
