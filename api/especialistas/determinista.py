"""ESPECIALISTA DETERMINISTA — cálculos con respuesta exacta.

Uno de los tres especialistas del agente notarial. Atiende las preguntas que no se contestan
buscando en un corpus sino ejecutando una cuenta: el dígito verificador de una partida, el
CUIL de una persona, el vencimiento de un certificado registral.

Es el único de los tres que **no recupera nada del grafo**, y por eso es el único que no
devuelve un ContextoAcumulado: no hay ids que deduplicar ni fuentes que citar. Su salida es
un bloque de texto con el resultado del cálculo.

UN SOLO CAMINO: EL MODELO ELIGE, EL CÓDIGO CALCULA
--------------------------------------------------
`bind_tools` con flash-lite. El modelo **solo elige la herramienta y transcribe los
parámetros**; la cuenta la hace el código, adentro de la @tool. Una llamada de US$0,00005 y
~600 ms por turno determinista.

HUBO UN ATAJO POR REGEX Y SE SACÓ (08/09/2026). Reconocía la herramienta y el parámetro sin
llamar al modelo, lo que era gratis y exacto cuando acertaba. El problema no era su precisión
sino su lugar en el flujo: **no era un atajo, era una compuerta**. Si matcheaba algo, devolvía
y el camino largo no corría nunca — y un regex no puede saber que se le escapó algo. Medido
sobre «Dime qué es un ROS, cuándo vence un certificado de dominio en CABA solicitado el
24/07/2026 y el dígito verificador de la partida 3726188»: el patrón del DV matcheó, la
función volvió con ese único cálculo, y el vencimiento del certificado terminó calculándolo el
LLM redactor sobre el texto de un resumen. Dio bien —07/08/2026, idéntico a la herramienta—
pero por aritmética de un modelo, que es exactamente lo que este especialista existe para
evitar. Dos defectos más lo acompañaban: `_resolver_por_regex` devolvía el PRIMER match y
cortaba, así que nunca podía resolver dos cálculos; y el patrón del certificado exigía la
fecha antes que la jurisdicción, de modo que «en CABA solicitado el 24/07/2026» no matcheaba
en ningún caso.

Con el regex afuera, el modelo resuelve los dos cálculos de esa consulta, 4 de 4 corridas.

Esto NO es un agente ReAct: no hay bucle, no hay decisión de "seguir pensando". El
clasificador ya fijó la ruta, acá se resuelve en un paso y se vuelve.

CONTRATO CON EL AGENTE:
    determinista(pregunta) -> Generator[dict, None, list[str]]

Devuelve `list[str]` y no ContextoAcumulado. El puente vive en `api/agente/nodos.py`.
"""
from utils.connectors import get_gemini_llm
from utils.agent.tools import HERRAMIENTAS, POR_NOMBRE

# flash-lite alcanza de sobra: la tarea es elegir entre cinco opciones y copiar un número.
# Medido en la §10 del plan: acierta igual que flash a 1/49 del costo.
llm_herramientas = get_gemini_llm().bind_tools(HERRAMIENTAS)

def determinista(pregunta: str):
    """Resuelve una consulta determinista ejecutando la herramienta que corresponda.

    Generador: emite eventos de progreso ("fase"/"item") y su `return` es una lista de
    bloques de texto con los resultados, lista para entrar al prompt de redacción.

    Devuelve una lista vacía si no pudo resolver nada. Eso NO es un error: puede pasar que el
    clasificador haya marcado la ruta y la pregunta no traiga los datos ("¿cuál es el DV de mi
    partida?", sin número). El nodo `sintetizar` recibe el resto del contexto y contesta lo que
    pueda; devolver una excepción acá cortaría toda la respuesta por una parte de ella.
    """
    yield {"type": "fase", "fase": "herramientas", "label": "Calculando"}

    respuesta = llm_herramientas.invoke(_PROMPT_HERRAMIENTAS.format(pregunta=pregunta))

    bloques = []
    for llamada in getattr(respuesta, "tool_calls", []) or []:
        herramienta = POR_NOMBRE.get(llamada["name"])
        if herramienta is None:
            # El modelo inventó un nombre de herramienta. No debería pasar con bind_tools,
            # pero si pasa se ignora en silencio en vez de romper el turno entero.
            continue
        argumentos = llamada.get("args", {})
        resultado = herramienta.invoke(argumentos)
        yield {"type": "item", "texto": f"{_titulo(llamada['name'], argumentos)}: {resultado}"}
        bloques.append(_bloque(llamada["name"], argumentos, resultado))

    return bloques


# El prompt es corto a propósito: toda la información de qué hace cada herramienta y qué
# parámetros pide ya viaja en el esquema que arma bind_tools desde los docstrings de las @tool.
# Repetirla acá sería mantener la misma verdad en dos lugares.
#
# EL PLURAL NO ES ESTILO, ES EL ARREGLO. La versión anterior decía "Resolvé el cálculo", en
# singular y sin aclarar qué hacer con las partes que no son cálculos. Medido sobre la consulta
# mixta del ROS: devolvía CERO llamadas en 4 de 4 corridas — ante una pregunta que arranca con
# "Dime qué es un ROS", el modelo concluía que no había nada que calcular. Con este texto
# devuelve las dos herramientas, 4 de 4.
#
# LA TRANSCRIPCIÓN LITERAL cubre el otro riesgo de sacar el regex: un patrón no puede leer mal
# un número, un modelo sí. El caso concreto son las partidas de seis dígitos, que un usuario
# puede escribir 164360 y otro 0164360 sabiendo que el campo lleva siete. Las dos formas son
# correctas y dan el mismo DV —`normalizar_partida()` completa con zfill(7)—, pero solo si el
# modelo copia lo que recibió en vez de "arreglarlo".
_PROMPT_HERRAMIENTAS = """Resolvé TODOS los cálculos que pida la consulta usando las herramientas disponibles.

La consulta puede pedir más de un cálculo, y puede además preguntar otras cosas que NO son
cálculos. Ignorá esas partes y llamá a una herramienta por cada cálculo que sí pida.

Transcribí los números y las fechas EXACTAMENTE como los escribió el usuario. No agregues ni
saques ceros a la izquierda, no cambies el formato y no los "corrijas": una partida de seis
dígitos es válida tal cual, y completarla o recortarla cambia el resultado. Si la consulta no
trae todos los datos que una herramienta necesita, no la llames.

Consulta: {pregunta}"""


# Cómo se nombra cada cálculo en pantalla. Es un mapa explícito y no una transformación del
# nombre de la función porque esto lo lee el usuario: derivarlo daba "Dv partida" y
# "Vencimiento de prorroga inscripcion". Una tool nueva sin entrada acá cae al nombre crudo,
# que se ve mal pero no rompe nada.
_TITULOS = {
    "calcular_dv_partida": "Dígito verificador de la partida",
    "calcular_cuil": "CUIL",
    "vencimiento_certificado": "Vencimiento del certificado",
    "vencimiento_ingreso_rpi": "Vencimiento para ingresar al RPI",
    "vencimiento_prorroga_inscripcion": "Vencimiento de la prórroga de inscripción",
}


def _titulo(nombre: str, argumentos: dict) -> str:
    """Texto del evento `item` que ve el usuario. Nombra el cálculo, nunca la función:
    "Dígito verificador de la partida (1180431)", no "calcular_dv_partida(partida='1180431')"."""
    legible = _TITULOS.get(nombre, nombre.replace("_", " ").capitalize())
    datos = ", ".join(str(v) for v in argumentos.values())
    return f"{legible} ({datos})" if datos else legible


def _bloque(nombre: str, argumentos: dict, resultado: str) -> str:
    """Bloque de contexto para el prompt de redacción.

    Va con la etiqueta CÁLCULO en mayúsculas, siguiendo la misma forma que usan los otros dos
    especialistas (FUENTE/ARTICULO/TEXTO, INSTITUTO/DESCRIPCIÓN), para que el prompt de
    redacción lea siempre la misma estructura.

    La línea de INSTRUCCIÓN frena dos cosas distintas que el modelo hace si no se le dice:
    inventarse el algoritmo para "explicar" el cálculo, y delatar el andamiaje interno. La
    primera versión de este bloque terminaba en "no lo recalcules" y la respuesta salía
    diciendo «el dígito verificador es 01, según el RESULTADO del CÁLCULO proporcionado en el
    contexto». El usuario no tiene por qué enterarse de que existe un bloque llamado CÁLCULO.
    """
    datos = ", ".join(f"{k}={v}" for k, v in argumentos.items())
    return (
        f"CÁLCULO: {nombre}\n"
        f"DATOS: {datos}\n"
        f"RESULTADO: {resultado}\n"
        f"INSTRUCCIÓN: este resultado lo calculó el sistema con la fórmula oficial. Dá el "
        f"resultado como propio, en una frase directa. No expliques el algoritmo, no lo "
        f"recalcules, y no menciones este bloque ni la palabra contexto."
    )
