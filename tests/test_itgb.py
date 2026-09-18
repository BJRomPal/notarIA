"""Regresión del cálculo del ITGB (utils/agent/itgb.py).

POR QUÉ EXISTE
--------------
La escala de 48 tramos (4 categorías × 12 tramos) se transcribió a mano desde una tabla, y un
solo dígito mal copiado cambia el impuesto sin que nada lo note en el uso normal. El propio
módulo ya corre un chequeo de consistencia al importarse (`_validar_consistencia`, con un
`assert` que frena todo el proceso si algo no cierra); este script repite ese chequeo con un
reporte tramo por tramo en vez de fallar en el primero, y además cubre lo que el `assert` de
import no puede: que el mapeo de parentesco rechace los vínculos ambiguos (hijastro,
conviviente, yerno) en vez de adivinar una categoría, y que la validación de montos sea
correcta en los bordes (negativo, cero, vacío, con letras).

Se corre a mano, sin pytest (el repo no lo usa):

    .venv/bin/python tests/test_itgb.py

Sale con código 1 si algún caso falla.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal

from utils.agent.itgb import ESCALA_2026, ItgbInvalido, calcular_itgb, obtener_itgb

TOLERANCIA = Decimal("2")  # ver la calibración en utils/agent/itgb.py: diff real máximo $0,50


def consistencia_por_tramo() -> list[str]:
    """Repite el chequeo de `_validar_consistencia` pero reportando cada transición, no solo
    la primera que falle."""
    fallos = []
    categorias = (
        ("A", ESCALA_2026.categoria_a), ("B", ESCALA_2026.categoria_b),
        ("C", ESCALA_2026.categoria_c), ("D", ESCALA_2026.categoria_d),
    )
    for nombre, tramos in categorias:
        if tramos[0].mayor_a != 0:
            fallos.append(f"categoría {nombre}: el primer tramo no arranca en 0")
        if tramos[-1].menor_o_igual_a is not None:
            fallos.append(f"categoría {nombre}: el último tramo no está abierto")
        for i in range(len(tramos) - 1):
            actual, siguiente = tramos[i], tramos[i + 1]
            ok_limite = actual.menor_o_igual_a == siguiente.mayor_a
            predicho = actual.cuota_fija + (
                actual.menor_o_igual_a - actual.mayor_a
            ) * actual.porcentaje / Decimal(100)
            diff = abs(predicho - siguiente.cuota_fija)
            ok_cuota = diff <= TOLERANCIA
            estado = "OK   " if (ok_limite and ok_cuota) else "FALLA"
            print(f"  {estado}  {nombre} tramo {i + 1}->{i + 2}  diff=${diff}")
            if not ok_limite:
                fallos.append(f"categoría {nombre}, tramo {i + 1}->{i + 2}: hueco o solape de límites")
            if not ok_cuota:
                fallos.append(
                    f"categoría {nombre}, tramo {i + 1}->{i + 2}: cuota fija inconsistente "
                    f"(predicha {predicho}, transcripta {siguiente.cuota_fija}, diff {diff})"
                )
    return fallos


# (valuación, parentesco, impuesto esperado, categoría esperada) — un caso por categoría,
# verificado a mano contra la escala transcripta.
CASOS_CONOCIDOS = [
    ("5000000", "hijo", Decimal("80150"), "A"),
    ("150000000", "nieto", Decimal("4008758"), "B"),
    ("20000000", "hermano", Decimal("643789"), "C"),
    ("5000000", "sobrino", Decimal("200300"), "D"),
]

# Vínculos deliberadamente fuera de las cuatro listas (ver utils/agent/itgb.py): deben
# rechazar, no adivinar una categoría.
PARENTESCOS_AMBIGUOS = ["hijastro", "conviviente", "yerno", "cuñado", "padrastro"]

# (valor, motivo) — deben rechazar por la valuación, no por el parentesco.
VALUACIONES_INVALIDAS = [
    ("-100", "negativa"),
    ("0", "cero"),
    ("", "vacía"),
    ("abc", "no numérica"),
]


def main() -> int:
    fallos: list[str] = []

    print("--- consistencia de la escala, tramo por tramo ---")
    fallos += consistencia_por_tramo()

    print("--- casos conocidos, un impuesto exacto por categoría ---")
    for valuacion, parentesco, esperado, categoria_esperada in CASOS_CONOCIDOS:
        try:
            r = calcular_itgb(valuacion, parentesco)
            ok = r.impuesto == esperado and r.categoria == categoria_esperada
        except ItgbInvalido as error:
            ok = False
            r = error
        print(f"  {'OK   ' if ok else 'FALLA'}  {parentesco} / ${valuacion} -> {r}")
        if not ok:
            fallos.append(f"caso conocido {parentesco}/{valuacion}: esperado ${esperado} cat {categoria_esperada}, dio {r}")

    print("--- parentescos ambiguos: deben rechazar, no adivinar ---")
    for parentesco in PARENTESCOS_AMBIGUOS:
        ok, resultado = obtener_itgb("5000000", parentesco)
        exito = not ok
        print(f"  {'OK   ' if exito else 'FALLA'}  '{parentesco}' -> {resultado}")
        if not exito:
            fallos.append(f"parentesco ambiguo '{parentesco}' no fue rechazado: dio {resultado}")

    print("--- valuaciones inválidas: deben rechazar ---")
    for valor, motivo in VALUACIONES_INVALIDAS:
        ok, resultado = obtener_itgb(valor, "hijo")
        exito = not ok
        print(f"  {'OK   ' if exito else 'FALLA'}  valuación {motivo} ('{valor}') -> {resultado}")
        if not exito:
            fallos.append(f"valuación {motivo} ('{valor}') no fue rechazada: dio {resultado}")

    print(f"\n{len(fallos)} fallos")
    for f in fallos:
        print(f"  - {f}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
