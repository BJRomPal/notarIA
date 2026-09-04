from langchain_core.tools import tool

from utils.cuil import obtener_cuil
from utils.digito_verificador import obtener_dv


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
