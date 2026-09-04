"""
Cálculo del dígito verificador (DV) de un número de partida.

Reglas de validación:
    * La partida debe ser numérica (solo dígitos 0-9).
    * Debe tener como máximo 7 dígitos.
    * Si tiene menos de 7, se completa con ceros a la izquierda.
    * El DV se devuelve siempre como texto de 2 caracteres, con un 0 adelante.
"""

from __future__ import annotations

# Pesos por posición (posición 1 = dígito más a la izquierda de la partida
# ya completada a 7 dígitos). 
PESOS: tuple[int, ...] = (7, 2, 3, 4, 5, 6, 7)

LARGO_PARTIDA: int = 7
MODULO: int = 11


class PartidaInvalida(ValueError):
    """Se levanta cuando la partida no cumple las reglas de validación."""


def normalizar_partida(partida: str | int) -> str:
    """Valida la partida y la devuelve como texto de 7 dígitos.

    Levanta PartidaInvalida con una explicación si no es válida.
    """
    if isinstance(partida, bool):  # bool es subclase de int: lo descartamos
        raise PartidaInvalida(
            "La partida debe ser un número o una cadena de dígitos; "
            f"se recibió un booleano ({partida!r})."
        )

    if isinstance(partida, int):
        if partida < 0:
            raise PartidaInvalida(
                f"La partida no puede ser negativa; se recibió {partida}."
            )
        texto = str(partida)
    elif isinstance(partida, str):
        texto = partida.strip()
    else:
        raise PartidaInvalida(
            "La partida debe ser un entero o una cadena de texto; "
            f"se recibió un valor de tipo {type(partida).__name__}."
        )

    if texto == "":
        raise PartidaInvalida("La partida está vacía: no hay ningún dígito para procesar.")

    if not texto.isdecimal():
        raise PartidaInvalida(
            f"La partida '{texto}' no es un número: solo se admiten dígitos del 0 al 9 "
            "(sin espacios, puntos, guiones ni letras)."
        )

    if len(texto) > LARGO_PARTIDA:
        raise PartidaInvalida(
            f"La partida '{texto}' tiene {len(texto)} dígitos y el máximo permitido "
            f"es {LARGO_PARTIDA}."
        )

    return texto.zfill(LARGO_PARTIDA)


def calcular_dv(partida: str | int) -> str:
    """Devuelve el dígito verificador de la partida, como texto de 2 caracteres.

    >>> calcular_dv("1180431")
    '01'
    >>> calcular_dv(1180431)
    '01'

    Levanta PartidaInvalida si la partida no es numérica o supera los 7 dígitos.
    """
    normalizada = normalizar_partida(partida)

    suma = sum(int(digito) * peso for digito, peso in zip(normalizada, PESOS))
    resto = suma % MODULO

    # Igual que la planilla: =SI(RESIDUO(suma;11)=10; 1; RESIDUO(suma;11))
    dv = 1 if resto == 10 else resto

    return f"0{dv}"


def obtener_dv(partida: str | int) -> tuple[bool, str]:
    """Variante sin excepciones.

    Devuelve (True, "01") si la partida es válida,
    o (False, "explicación del rechazo") si no lo es.
    """
    try:
        return True, calcular_dv(partida)
    except PartidaInvalida as error:
        return False, str(error)


def partida_completa(partida: str | int) -> str:
    """Devuelve la partida de 7 dígitos concatenada con su DV (9 caracteres)."""
    return normalizar_partida(partida) + calcular_dv(partida)


if __name__ == "__main__":
    ejemplos = ["1675980"]
    for ejemplo in ejemplos:
        ok, resultado = obtener_dv(ejemplo)
        estado = "OK    " if ok else "RECHAZO"
        print(f"{estado} {ejemplo!r:>12} -> {resultado}")
