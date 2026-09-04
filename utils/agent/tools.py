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
