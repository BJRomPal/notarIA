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
]

# Índice por nombre, para que el especialista determinista resuelva a qué función corresponde
# cada `tool_call` que devuelve el modelo. `.name` lo pone el decorador @tool a partir del
# nombre de la función, así que es la misma cadena con la que bind_tools la nombra.
POR_NOMBRE = {h.name: h for h in HERRAMIENTAS}
