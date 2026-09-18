"""Herramientas deterministas expuestas al agente notarial como @tool de LangChain.

Cada función de acá envuelve un helper de `utils/agent/` con un contrato único: **nunca
levanta excepción**, siempre devuelve un string. El helper devuelve `(ok, resultado)` y
acá se traduce a texto plano, porque un modelo con `bind_tools` no sabe manejar un
traceback pero sí sabe leer "No se pudo calcular: ...".

El cálculo lo hace SIEMPRE el código, nunca el modelo: el LLM solo elige qué herramienta
usar y extrae los parámetros de la pregunta. Ese reparto es el mismo principio que el
proyecto aplica en la ingesta (el modelo extrae, el código valida y calcula).

Consumidor: `api/especialistas/determinista.py`, a través de la lista HERRAMIENTAS
del final del archivo.
"""
from langchain_core.tools import tool

from utils.agent.cuil import obtener_cuil
from utils.agent.dv_partida import obtener_dv
from utils.agent.herencia import obtener_porciones_herencia
from utils.agent.itgb import obtener_itgb
from utils.agent.plazos_registrales import (
    obtener_vencimiento_certificado,
    obtener_vencimiento_ingreso_rpi,
    obtener_vencimiento_prorroga_inscripcion,
)


@tool
def calcular_dv_partida(partida: str) -> str:
    """Calcula el dígito verificador de una partida inmobiliaria de hasta 7 dígitos.

    Ejemplos:
        calcular_dv_partida("1180431") -> "01"
        calcular_dv_partida("11a0431") -> "No se pudo calcular: La partida '11a0431' no es un número..."
    """
    ok, resultado = obtener_dv(partida)
    return resultado if ok else f"No se pudo calcular: {resultado}"


@tool
def calcular_cuil(dni: str, genero: str) -> str:
    """Calcula el CUIL de una persona física a partir de su DNI y su género.

    El prefijo de partida es "20" para masculino o "27" para femenino; si el
    dígito verificador da 10, se reasigna a prefijo "23".

    Ejemplos:
        calcular_cuil("12345678", "femenino") -> "27-12345678-0"
        calcular_cuil("01000000", "masculino") -> "23-01000000-9"
    """
    ok, resultado = obtener_cuil(dni, genero)
    return resultado if ok else f"No se pudo calcular: {resultado}"


@tool
def vencimiento_certificado(fecha_solicitud: str, jurisdiccion: str) -> str:
    """Calcula el último día para usar un certificado de dominio/inhibición del RPI.

    La fecha de solicitud (formato DD/MM/AAAA) cuenta como día 1. Jurisdicción
    "CABA" da 15 días de vigencia; "PBA" (Provincia de Buenos Aires) da 30 días.

    Ejemplos:
        vencimiento_certificado("04/09/2026", "CABA") -> "18/09/2026"
        vencimiento_certificado("04/09/2026", "PBA") -> "03/10/2026"
    """
    ok, resultado = obtener_vencimiento_certificado(fecha_solicitud, jurisdiccion)
    return resultado if ok else f"No se pudo calcular: {resultado}"


@tool
def vencimiento_ingreso_rpi(fecha_escritura: str) -> str:
    """Calcula el último día para ingresar una escritura en término en el RPI.

    Son 45 días desde la fecha de la escritura (formato DD/MM/AAAA), que cuenta
    como día 1, sin importar la jurisdicción del Registro.

    Ejemplos:
        vencimiento_ingreso_rpi("04/09/2026") -> "18/10/2026"
    """
    ok, resultado = obtener_vencimiento_ingreso_rpi(fecha_escritura)
    return resultado if ok else f"No se pudo calcular: {resultado}"


@tool
def vencimiento_prorroga_inscripcion(fecha_ingreso: str) -> str:
    """Calcula el último día para pedir prórroga de la inscripción de un título observado.

    Son 180 días desde la fecha de ingreso del título al registro (formato
    DD/MM/AAAA), que cuenta como día 1.

    Ejemplos:
        vencimiento_prorroga_inscripcion("04/09/2026") -> "02/03/2027"
    """
    ok, resultado = obtener_vencimiento_prorroga_inscripcion(fecha_ingreso)
    return resultado if ok else f"No se pudo calcular: {resultado}"


@tool
def calcular_porciones_herencia(
    hijos_vivos: int = 0,
    nietos_por_representacion: list[int] | None = None,
    hay_conyuge: bool = False,
    tipo_bien: str = "propio",
    ascendientes: int = 0,
    hermanos_bilaterales: int = 0,
    hermanos_unilaterales: int = 0,
    fraccion_causante: str = "1",
) -> str:
    """Calcula la fracción de un bien que le corresponde a cada heredero en una sucesión
    intestada (arts. 2424 a 2440 CCyCN).

    Los herederos se agrupan en cuatro órdenes que se excluyen entre sí (indicar solo los
    datos del orden que corresponde, arts. 2424/2438): descendientes (hijos_vivos y, si un
    hijo premurió, nietos_por_representacion con la cantidad de nietos de esa estirpe), o
    ascendientes, o hermanos (bilaterales/unilaterales). El cónyuge (hay_conyuge) concurre
    con cualquiera de esos órdenes, o hereda solo si no hay ninguno.

    tipo_bien ("ganancial" o "propio") solo importa si hay cónyuge Y descendientes: si el
    bien es ganancial, la muerte extingue la comunidad y el cónyuge ya es dueño de su mitad
    por partición, no por herencia (arts. 475, 498) — esa mitad no entra en el cálculo y
    solo se reparte entre los descendientes la mitad del causante; si es propio, el cónyuge
    hereda como un hijo más (art. 2433).

    fraccion_causante es la parte indivisa del bien que tenía el causante, si no era dueño
    de la totalidad (un condominio previo, ajeno a la sociedad conyugal). Transcribila como
    fracción ("1/6", "1/3"), igual que una fecha o una partida: nunca hagas vos la cuenta de
    a cuánto equivale "la sexta parte". "1" (el valor por defecto) es titular pleno.

    Ejemplos:
        calcular_porciones_herencia(hijos_vivos=3)
            -> "hijo: 1/3 cada uno (x3)"
        calcular_porciones_herencia(hijos_vivos=3, hay_conyuge=True, tipo_bien="ganancial")
            -> "hijo: 1/6 cada uno (x3); cónyuge: 1/2 [...]"
        calcular_porciones_herencia(hijos_vivos=3, hay_conyuge=True, tipo_bien="propio")
            -> "hijo: 1/4 cada uno (x3); cónyuge: 1/4 [...]"
        calcular_porciones_herencia(hijos_vivos=4, fraccion_causante="1/10")
            -> "[el causante era titular de 1/10 del bien...] hijo: 1/40 cada uno (x4)"
    """
    ok, resultado = obtener_porciones_herencia(
        hijos_vivos=hijos_vivos,
        nietos_por_representacion=nietos_por_representacion,
        hay_conyuge=hay_conyuge,
        tipo_bien=tipo_bien,
        ascendientes=ascendientes,
        hermanos_bilaterales=hermanos_bilaterales,
        hermanos_unilaterales=hermanos_unilaterales,
        fraccion_causante=fraccion_causante,
    )
    return resultado if ok else f"No se pudo calcular: {resultado}"


@tool
def calcular_itgb(valuacion_fiscal: str, parentesco: str) -> str:
    """Calcula el Impuesto a la Transmisión Gratuita de Bienes (ITGB) de la Provincia de
    Buenos Aires sobre una donación o herencia, aplicando la escala progresiva por tramos que
    corresponde según el parentesco entre transmisor y receptor.

    valuacion_fiscal es la Valuación Fiscal al Acto ya determinada por el escribano —
    transcribila tal cual la dio la consulta, sin agregar ni sacar separadores. parentesco es
    el vínculo entre quien transmite y quien recibe, en una palabra ("hijo", "cónyuge",
    "nieto", "hermano", "tío", "primo", "sin parentesco", "persona jurídica", etc.): el
    sistema decide a qué categoría de la escala corresponde, nunca lo decidas vos. Si el
    vínculo es uno que no aparece en esos ejemplos (hijastro, conviviente, yerno, adoptivo,
    etc.), llamá igual a la herramienta con la palabra tal cual la dijo el usuario: el propio
    cálculo la va a rechazar si no está en la lista reconocida, en vez de asumir una categoría.

    No hay mínimo no imponible que restar: la valuación indicada ya es la base imponible neta.

    Ejemplos:
        calcular_itgb("5000000", "hijo")
            -> "$80.150 (categoría A: progenitores, hijos/as y cónyuge; ...)"
        calcular_itgb("20000000", "hermano")
            -> "$643.789 (categoría C: colaterales de 2° grado; ...)"
    """
    ok, resultado = obtener_itgb(valuacion_fiscal, parentesco)
    return resultado if ok else f"No se pudo calcular: {resultado}"


# ==========================================================================================
# EL REGISTRO
# ==========================================================================================
# El especialista determinista importa esta lista, nunca las funciones una por una. Sumar
# una herramienta nueva es definirla arriba y agregarla acá: el consumidor no se toca.
#
# El orden importa poco para el modelo, pero se mantiene agrupado por familia (cálculos de
# dígito verificador primero, plazos registrales después) para que se lea fácil.
HERRAMIENTAS = [
    calcular_dv_partida,
    calcular_cuil,
    vencimiento_certificado,
    vencimiento_ingreso_rpi,
    vencimiento_prorroga_inscripcion,
    calcular_porciones_herencia,
    calcular_itgb,
]

# Índice por nombre, para que el especialista determinista resuelva a qué función corresponde
# cada `tool_call` que devuelve el modelo. `.name` lo pone el decorador @tool a partir del
# nombre de la función, así que es la misma cadena con la que bind_tools la nombra.
POR_NOMBRE = {h.name: h for h in HERRAMIENTAS}
