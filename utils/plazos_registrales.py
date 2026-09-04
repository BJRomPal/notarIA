"""
Cálculo de vencimientos registrales para escrituras y certificados del RPI.

Convención de conteo: en los tres plazos, el día de partida (solicitud del
certificado, otorgamiento de la escritura, o ingreso al registro) cuenta como
día 1. El último día válido es fecha_partida + (días - 1).

Plazos:
    * Certificado de dominio/inhibición: 15 días si es RPI CABA, 30 días si es
      RPI Pcia. de Bs. As. Se cuentan desde la fecha de solicitud.
    * Ingreso de la escritura al RPI: 45 días desde la fecha de la escritura,
      sin importar la jurisdicción del Registro.
    * Prórroga de la inscripción (título observado): 180 días desde la fecha
      de ingreso del título al registro.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

FORMATO_FECHA: str = "%d/%m/%Y"

DIAS_CERTIFICADO_CABA: int = 15
DIAS_CERTIFICADO_PBA: int = 30
DIAS_INGRESO_RPI: int = 45
DIAS_PRORROGA_INSCRIPCION: int = 180

_JURISDICCIONES_CABA: frozenset[str] = frozenset({"caba", "capital federal", "capital"})
_JURISDICCIONES_PBA: frozenset[str] = frozenset(
    {"pba", "provincia de buenos aires", "pcia de buenos aires", "pcia. de buenos aires", "buenos aires"}
)


class FechaInvalida(ValueError):
    """Se levanta cuando la fecha o la jurisdicción no cumplen las reglas de validación."""


def normalizar_fecha(fecha: str | date) -> date:
    """Valida la fecha y la devuelve como date.

    Acepta un texto en formato DD/MM/AAAA o un objeto date.
    Levanta FechaInvalida con una explicación si no es válida.
    """
    if isinstance(fecha, date):
        return fecha

    if not isinstance(fecha, str):
        raise FechaInvalida(
            "La fecha debe ser un texto 'DD/MM/AAAA' o un date; "
            f"se recibió un valor de tipo {type(fecha).__name__}."
        )

    texto = fecha.strip()
    try:
        return datetime.strptime(texto, FORMATO_FECHA).date()
    except ValueError as error:
        raise FechaInvalida(
            f"La fecha '{texto}' no tiene el formato DD/MM/AAAA (ej: 04/09/2026)."
        ) from error


def _dias_por_jurisdiccion(jurisdiccion: str) -> int:
    """Valida la jurisdicción y devuelve los días de vigencia del certificado."""
    if not isinstance(jurisdiccion, str):
        raise FechaInvalida(
            "La jurisdicción debe ser una cadena de texto; "
            f"se recibió un valor de tipo {type(jurisdiccion).__name__}."
        )

    texto = jurisdiccion.strip().lower()

    if texto in _JURISDICCIONES_CABA:
        return DIAS_CERTIFICADO_CABA
    if texto in _JURISDICCIONES_PBA:
        return DIAS_CERTIFICADO_PBA

    raise FechaInvalida(
        f"La jurisdicción '{jurisdiccion}' no es reconocida; use 'CABA' o 'PBA' "
        "(Provincia de Buenos Aires)."
    )


def _ultimo_dia(fecha_partida: date, dias: int) -> date:
    return fecha_partida + timedelta(days=dias - 1)


def vencimiento_certificado(fecha_solicitud: str | date, jurisdiccion: str) -> date:
    """Último día para usar un certificado de dominio/inhibición del RPI.

    >>> vencimiento_certificado("04/09/2026", "CABA")
    datetime.date(2026, 9, 18)

    Levanta FechaInvalida si la fecha o la jurisdicción no son válidas.
    """
    fecha = normalizar_fecha(fecha_solicitud)
    dias = _dias_por_jurisdiccion(jurisdiccion)
    return _ultimo_dia(fecha, dias)


def vencimiento_ingreso_rpi(fecha_escritura: str | date) -> date:
    """Último día para ingresar la escritura en término en el RPI (45 días desde el otorgamiento).

    Levanta FechaInvalida si la fecha no es válida.
    """
    fecha = normalizar_fecha(fecha_escritura)
    return _ultimo_dia(fecha, DIAS_INGRESO_RPI)


def vencimiento_prorroga_inscripcion(fecha_ingreso: str | date) -> date:
    """Último día para pedir prórroga de la inscripción de un título observado (180 días desde el ingreso).

    Levanta FechaInvalida si la fecha no es válida.
    """
    fecha = normalizar_fecha(fecha_ingreso)
    return _ultimo_dia(fecha, DIAS_PRORROGA_INSCRIPCION)


def obtener_vencimiento_certificado(fecha_solicitud: str | date, jurisdiccion: str) -> tuple[bool, str]:
    """Variante sin excepciones de vencimiento_certificado.

    Devuelve (True, "18/09/2026") si los datos son válidos,
    o (False, "explicación del rechazo") si no lo son.
    """
    try:
        return True, vencimiento_certificado(fecha_solicitud, jurisdiccion).strftime(FORMATO_FECHA)
    except FechaInvalida as error:
        return False, str(error)


def obtener_vencimiento_ingreso_rpi(fecha_escritura: str | date) -> tuple[bool, str]:
    """Variante sin excepciones de vencimiento_ingreso_rpi."""
    try:
        return True, vencimiento_ingreso_rpi(fecha_escritura).strftime(FORMATO_FECHA)
    except FechaInvalida as error:
        return False, str(error)


def obtener_vencimiento_prorroga_inscripcion(fecha_ingreso: str | date) -> tuple[bool, str]:
    """Variante sin excepciones de vencimiento_prorroga_inscripcion."""
    try:
        return True, vencimiento_prorroga_inscripcion(fecha_ingreso).strftime(FORMATO_FECHA)
    except FechaInvalida as error:
        return False, str(error)


if __name__ == "__main__":
    print(obtener_vencimiento_certificado("04/09/2026", "CABA"))
    print(obtener_vencimiento_certificado("04/09/2026", "PBA"))
    print(obtener_vencimiento_ingreso_rpi("04/09/2026"))
    print(obtener_vencimiento_prorroga_inscripcion("04/09/2026"))
