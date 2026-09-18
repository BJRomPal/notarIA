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

    Devuelve una lista vacía solo si el modelo no llamó ninguna herramienta NI dijo por qué
    ("¿cuál es el DV de mi partida?", sin número, a veces cae así). Eso NO es un error: el
    nodo `sintetizar` recibe el resto del contexto y contesta lo que pueda; devolver una
    excepción acá cortaría toda la respuesta por una parte de ella.

    CUANDO NO LLAMA NINGUNA HERRAMIENTA, NO SIEMPRE ESTÁ VACÍO. El modelo, al abstenerse,
    normalmente explica por qué en `respuesta.content` —"la fecha está incompleta, necesito
    el año"—, y esa explicación se convierte en un bloque igual que un cálculo resuelto.
    Sin este bloque, `sintetizar` recibía una lista vacía sin ninguna pista de que faltaba un
    dato, y como su prompt es "contestá con el contexto provisto", ante un contexto vacío
    terminaba respondiendo con su propio conocimiento general en vez de decir que faltaba
    algo: inventaba una fecha, a veces un plazo distinto al real (15 días hábiles o 5 días
    hábiles en vez de los 45 corridos que calcula la herramienta) y siempre una cita a un
    artículo de la Ley 17.801 —un número distinto en cada corrida— que no salió de ningún
    contexto real. Medido sobre 5 preguntas sin fecha o con fecha incompleta (día+mes sin año,
    día+año sin mes, mes+año sin día, solo día, sin ninguna fecha), 2 corridas cada una, de
    punta a punta por el grafo completo: 10/10 alucinaba una fecha y/o una cita antes de este
    bloque, 0/10 después.
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

    if not bloques and respuesta.content:
        yield {"type": "item", "texto": str(respuesta.content)}
        bloques.append(_bloque_sin_calculo(str(respuesta.content)))

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
#
# FECHA INCOMPLETA = DATO FALTANTE, Y ESO NO ERA OBVIO. "Si la consulta no trae todos los datos,
# no la llames" ya estaba y no alcanzó: ante una fecha con el año, el mes o el día ausente, el
# modelo no se abstenía, completaba el hueco (el año con 2024, el mes con enero, o —con "agosto
# de 2026" sin día— llamando la herramienta dos veces, una con el 01/08 y otra con el 31/08).
# Solo se abstenía cuando la pregunta no traía ninguna fecha. Decirlo en abstracto ("una fecha
# solo está completa si...") no alcanzó tampoco: recién funcionó con los ejemplos explícitos de
# abajo, uno por cada forma de fecha incompleta que se probó.
#
# Medido sobre 4 preguntas con fecha parcial (día+mes sin año, día+año sin mes, mes+año sin día,
# solo día), 2 corridas cada una, LLAMANDO A LA HERRAMIENTA a través del grafo completo: 0/8 se
# abstenía antes de estos dos párrafos, 8/8 después. (El efecto sobre la respuesta que termina
# viendo el usuario depende además del bloque de abajo — ver el docstring de `determinista()`.)
#
# "RESOLVÉ TODOS LOS CÁLCULOS" CHOCABA CON "SI FALTA UN DATO, NO LA LLAMES" cuando la consulta
# pedía dos cálculos y a uno le faltaba un dato: el modelo, para poder "resolver todo", completaba
# el que faltaba en vez de dejarlo afuera — y no siempre con un valor inventado de la nada. En
# «el CUIL de una persona con DNI 12345678, y el dígito verificador de la partida 1180431» el
# género faltante salía siempre "femenino"; en «el CUIL de una mujer, y el dígito verificador de
# la partida 1180431» —sin DNI para el CUIL— el modelo tomó el 1180431 de LA PARTIDA, que es un
# número de otro cálculo en la misma frase, y lo usó como si fuera el DNI. Las dos veces el CUIL
# fabricado se presentó como si fuera real.
#
# PEDIRLE QUE NO LLAME LA HERRAMIENTA NO ALCANZÓ ACÁ, a diferencia de las fechas: varias
# redacciones de "no la llames si falta un dato" para este caso mixto arreglaban una de las dos
# preguntas de prueba y rompían la otra, dando vueltas en círculo. Lo que sí funcionó fue bajar la
# exigencia: en vez de pedir que NO llame, pedirle que si igual llama, que deje el parámetro que
# falta como cadena vacía en lugar de inventarlo. Eso no depende de la instrucción para ser
# seguro: `calcular_cuil` y `calcular_dv_partida` ya rechazan un DNI, un género o una partida
# vacíos con un mensaje propio (ver `cuil.py` y `dv_partida.py`), así que un parámetro vacío
# termina en un "no se pudo calcular" honesto en vez de un resultado inventado.
#
# LA EXCEPCIÓN TIENE QUE SER UNA FRASE, NO UN PÁRRAFO, O ROMPE LO DE ARRIBA. La primera versión
# la explicaba en un párrafo propio de cuatro líneas, con su propio ejemplo — y no importaba
# dónde lo pusiera (antes o después de la sección de fechas, como excepción marcada o no): en
# cuanto ese párrafo entraba al prompt, «el 20 de agosto» (sin año) volvía a fabricar 2026, 6/6.
# El bloque de fechas no cambió una palabra; alcanzó con que el prompt creciera. Todo volvió a
# 0/6 en cuanto la excepción se convirtió en UNA frase pegada al final de la regla general de
# arriba ("...no la llames. EXCEPCIÓN: a calcular_cuil...") en vez de un párrafo aparte.
#
# Medido sobre 2 preguntas mixtas (género dado y DNI ausente, DNI dado y género ausente) más 1
# pregunta de fecha sin año, 5 corridas cada una: con la excepción en párrafo propio, 0/5 se
# abstenía en la fecha (fabricaba 2026) aunque las 2 mixtas de CUIL ya daban bien; con la
# excepción en una frase, 5/5 en las tres.
_PROMPT_HERRAMIENTAS = """Resolvé TODOS los cálculos que pida la consulta usando las herramientas disponibles.

La consulta puede pedir más de un cálculo, y puede además preguntar otras cosas que NO son
cálculos. Ignorá esas partes y llamá a una herramienta por cada cálculo que sí pida.

Transcribí los números y las fechas EXACTAMENTE como los escribió el usuario. No agregues ni
saques ceros a la izquierda, no cambies el formato y no los "corrijas": una partida de seis
dígitos es válida tal cual, y completarla o recortarla cambia el resultado. Si la consulta no
trae todos los datos que una herramienta necesita, no la llames. EXCEPCIÓN: a calcular_cuil, si
le falta el dni o el genero, llamala igual con "" en lo que falte, nunca con un valor inventado
ni con un número que la consulta dio para otro cálculo (una partida no es un DNI).

Una fecha solo está completa si trae día, mes Y año explícitos en la consulta. Si falta
cualquiera de los tres, la fecha está incompleta: es un dato faltante como cualquier otro, así
que NO llames a la herramienta que la necesita. No completes el año con el actual ni con
ningún otro, no supongas el mes ni el día, y no llames la herramienta más de una vez para
cubrir varias fechas posibles.

Ejemplos de fecha incompleta, donde NO hay que llamar ninguna herramienta:
"el 20 de agosto" (falta el año), "el 20 de 2026" (falta el mes), "en agosto de 2026" (falta
el día), "el día 20" (falta el mes y el año).

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
    "calcular_itgb": "Impuesto a la Transmisión Gratuita de Bienes (ITGB)",
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


def _bloque_sin_calculo(observacion: str) -> str:
    """Bloque de contexto para cuando el modelo no llamó ninguna herramienta pero explicó
    por qué (típicamente un dato faltante o ambiguo).

    Sin este bloque el redactor recibe un contexto vacío y, para no dejar la pregunta sin
    respuesta, completa el hueco con su propio conocimiento general — inventando una fecha,
    un plazo o una cita legal que no vinieron de ningún cálculo real. La INSTRUCCIÓN se lo
    prohíbe explícitamente, a diferencia del bloque de CÁLCULO donde no hace falta porque ahí
    sí hay un resultado real para transcribir.
    """
    return (
        f"CÁLCULO: no se pudo realizar\n"
        f"MOTIVO: {observacion}\n"
        f"INSTRUCCIÓN: no se ejecutó ningún cálculo porque falta un dato. Transmitile el "
        f"MOTIVO al usuario en una frase directa, pidiéndole el dato que falta. No inventes "
        f"una fecha, un plazo ni una norma para completar lo que falta: no hay ningún cálculo "
        f"que transcribir, y no menciones este bloque ni la palabra contexto."
    )
