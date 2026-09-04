"""
Cálculo del Código Único de Identificación Laboral (CUIL) de una persona física.

Reglas de validación:
    * El DNI debe ser numérico (solo dígitos 0-9).
    * Debe tener como máximo 8 dígitos.
    * Si tiene menos de 8, se completa con ceros a la izquierda.
    * El género determina el prefijo de partida: "20" (masculino) o "27" (femenino).
    * El CUIL se devuelve siempre como texto con formato "PP-DDDDDDDD-D".

Regla especial: si el dígito verificador calculado da 10, el prefijo se reasigna
a "23" y el dígito pasa a ser "9" (si se partió de masculino) o "4" (si se partió
de femenino).
"""

from __future__ import annotations

PESOS: tuple[int, ...] = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)

LARGO_DNI: int = 8
MODULO: int = 11

PREFIJO_MASCULINO: str = "20"
PREFIJO_FEMENINO: str = "27"
PREFIJO_REASIGNADO: str = "23"

_GENEROS_MASCULINOS: frozenset[str] = frozenset({"m", "masculino", "hombre", "varon", "varón"})
_GENEROS_FEMENINOS: frozenset[str] = frozenset({"f", "femenino", "mujer"})


class CuilInvalido(ValueError):
    """Se levanta cuando el DNI o el género no cumplen las reglas de validación."""


def normalizar_dni(dni: str | int) -> str:
    """Valida el DNI y lo devuelve como texto de 8 dígitos.

    Levanta CuilInvalido con una explicación si no es válido.
    """
    if isinstance(dni, bool):  # bool es subclase de int: lo descartamos
        raise CuilInvalido(
            "El DNI debe ser un número o una cadena de dígitos; "
            f"se recibió un booleano ({dni!r})."
        )

    if isinstance(dni, int):
        if dni < 0:
            raise CuilInvalido(f"El DNI no puede ser negativo; se recibió {dni}.")
        texto = str(dni)
    elif isinstance(dni, str):
        texto = dni.strip()
    else:
        raise CuilInvalido(
            "El DNI debe ser un entero o una cadena de texto; "
            f"se recibió un valor de tipo {type(dni).__name__}."
        )

    if texto == "":
        raise CuilInvalido("El DNI está vacío: no hay ningún dígito para procesar.")

    if not texto.isdecimal():
        raise CuilInvalido(
            f"El DNI '{texto}' no es un número: solo se admiten dígitos del 0 al 9 "
            "(sin espacios, puntos, guiones ni letras)."
        )

    if len(texto) > LARGO_DNI:
        raise CuilInvalido(
            f"El DNI '{texto}' tiene {len(texto)} dígitos y el máximo permitido "
            f"es {LARGO_DNI}."
        )

    return texto.zfill(LARGO_DNI)


def normalizar_genero(genero: str) -> str:
    """Valida el género y devuelve el prefijo de partida ("20" o "27").

    Levanta CuilInvalido con una explicación si no es válido.
    """
    if not isinstance(genero, str):
        raise CuilInvalido(
            "El género debe ser una cadena de texto; "
            f"se recibió un valor de tipo {type(genero).__name__}."
        )

    texto = genero.strip().lower()

    if texto in _GENEROS_MASCULINOS:
        return PREFIJO_MASCULINO
    if texto in _GENEROS_FEMENINOS:
        return PREFIJO_FEMENINO

    raise CuilInvalido(
        f"El género '{genero}' no es reconocido; use 'masculino'/'M' o 'femenino'/'F'."
    )


def calcular_cuil(dni: str | int, genero: str) -> str:
    """Devuelve el CUIL de una persona física, como texto "PP-DDDDDDDD-D".

    >>> calcular_cuil("12345678", "femenino")
    '27-12345678-0'

    Levanta CuilInvalido si el DNI o el género no son válidos.
    """
    dni_normalizado = normalizar_dni(dni)
    prefijo = normalizar_genero(genero)

    base = prefijo + dni_normalizado
    suma = sum(int(digito) * peso for digito, peso in zip(base, PESOS))
    resto = suma % MODULO

    dv = MODULO - resto

    if dv == MODULO:
        dv = 0
    elif dv == MODULO - 1:
        dv = 9 if prefijo == PREFIJO_MASCULINO else 4
        prefijo = PREFIJO_REASIGNADO

    return f"{prefijo}-{dni_normalizado}-{dv}"


def obtener_cuil(dni: str | int, genero: str) -> tuple[bool, str]:
    """Variante sin excepciones.

    Devuelve (True, "27-12345678-0") si los datos son válidos,
    o (False, "explicación del rechazo") si no lo son.
    """
    try:
        return True, calcular_cuil(dni, genero)
    except CuilInvalido as error:
        return False, str(error)


if __name__ == "__main__":
    ejemplos = [("12345678", "femenino"), ("01000000", "masculino")]
    for dni, genero in ejemplos:
        ok, resultado = obtener_cuil(dni, genero)
        estado = "OK    " if ok else "RECHAZO"
        print(f"{estado} {dni!r:>12} ({genero}) -> {resultado}")
