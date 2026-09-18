"""
Cálculo del Impuesto a la Transmisión Gratuita de Bienes (ITGB) de la Provincia de Buenos
Aires: grava los incrementos patrimoniales que una persona recibe a título gratuito, sea por
donación o por herencia.

Se calcula aplicando una escala progresiva por tramos sobre la Valuación Fiscal al Acto ya
determinada: ese valor lo resuelve ARBA al emitir la valuación, este módulo no deriva ningún
coeficiente, lo recibe como dato (igual que una fecha o una partida en las otras herramientas
deterministas). No hay mínimo no imponible que restar acá: la valuación que recibe esta
función ya es la base imponible neta que corresponde gravar.

La escala varía según el parentesco entre transmisor y receptor, en cuatro categorías:

    A — Progenitores, hijos/as y cónyuge
    B — Otros ascendientes y descendientes
    C — Colaterales de 2° grado
    D — Colaterales de 3° y 4° grado, otros parientes y extraños/as (incluye personas jurídicas)

Cada tramo fija una cuota fija más un porcentaje sobre el excedente por encima del límite
inferior del tramo:

    impuesto = cuota_fija + (base_imponible - límite_inferior) × porcentaje / 100

VIGENCIA. La escala la fija anualmente la Ley Impositiva de la Provincia (vía ARBA) y se
actualiza por inflación. Se versiona con el mismo criterio que `notaria.precios_modelo` (ver
db/002_precios_modelo.sql): nunca se pisa una escala vieja — cuando haya una actualización, se
agrega una constante nueva con su propio `desde` y se cierra la anterior con `hasta`.
`_escala_vigente()` elige la que corresponde a la fecha del cálculo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


class ItgbInvalido(ValueError):
    """Se levanta cuando la valuación fiscal o el parentesco no cumplen las reglas de validación."""


@dataclass(frozen=True)
class Tramo:
    """Un tramo de la escala: (mayor_a, menor_o_igual_a] con su cuota fija y el porcentaje
    que se aplica sobre el excedente por encima de `mayor_a`. `menor_o_igual_a=None` es el
    último tramo, sin tope."""
    mayor_a: Decimal
    menor_o_igual_a: Decimal | None
    cuota_fija: Decimal
    porcentaje: Decimal  # ej. Decimal("1.603") = 1,603%


@dataclass(frozen=True)
class EscalaItgb:
    """Una versión completa de la escala (las 4 categorías), vigente en [desde, hasta).
    `hasta=None` es la vigente hoy."""
    desde: date
    hasta: date | None
    categoria_a: tuple[Tramo, ...]
    categoria_b: tuple[Tramo, ...]
    categoria_c: tuple[Tramo, ...]
    categoria_d: tuple[Tramo, ...]


def _tramos(*filas: tuple[str, str | None, str, str]) -> tuple[Tramo, ...]:
    """Arma una tupla de Tramo a partir de (mayor_a, menor_o_igual_a, cuota_fija, porcentaje)
    en texto, para transcribir la tabla tal cual sin repetir `Decimal(...)` en cada fila."""
    return tuple(
        Tramo(
            Decimal(mayor_a),
            Decimal(menor_o_igual_a) if menor_o_igual_a is not None else None,
            Decimal(cuota_fija),
            Decimal(porcentaje),
        )
        for mayor_a, menor_o_igual_a, cuota_fija, porcentaje in filas
    )


ESCALA_2026 = EscalaItgb(
    desde=date(2026, 1, 1),
    hasta=None,
    categoria_a=_tramos(
        ("0", "10701413", "0", "1.603"),
        ("10701413", "21402794", "171544", "1.633"),
        ("21402794", "42805615", "346298", "1.693"),
        ("42805615", "85611202", "708648", "1.813"),
        ("85611202", "171222431", "1484713", "2.053"),
        ("171222431", "342444836", "3242312", "2.534"),
        ("342444836", "684889673", "7581088", "3.496"),
        ("684889673", "1369779370", "19552960", "5.419"),
        ("1369779370", "2994578125", "56667133", "6.380"),
        ("2994578125", "5989156250", "160329294", "6.514"),
        ("5989156250", "11978312500", "355396113", "6.753"),
        ("11978312500", None, "759843835", "7.008"),
    ),
    categoria_b=_tramos(
        ("0", "10701413", "0", "2.404"),
        ("10701413", "21402794", "257262", "2.434"),
        ("21402794", "42805615", "517734", "2.494"),
        ("42805615", "85611202", "1051520", "2.614"),
        ("85611202", "171222431", "2170458", "2.855"),
        ("171222431", "342444836", "4614659", "3.335"),
        ("342444836", "684889673", "10324926", "4.297"),
        ("684889673", "1369779370", "25039781", "6.220"),
        ("1369779370", "2994578125", "67639920", "7.181"),
        ("2994578125", "5989156250", "184316719", "7.524"),
        ("5989156250", "11978312500", "409628777", "7.754"),
        ("11978312500", None, "874027953", "8.191"),
    ),
    categoria_c=_tramos(
        ("0", "10701413", "0", "3.205"),
        ("10701413", "21402794", "342980", "3.235"),
        ("21402794", "42805615", "689170", "3.295"),
        ("42805615", "85611202", "1394393", "3.415"),
        ("85611202", "171222431", "2856204", "3.656"),
        ("171222431", "342444836", "5986151", "4.137"),
        ("342444836", "684889673", "13069622", "5.098"),
        ("684889673", "1369779370", "30527460", "7.021"),
        ("1369779370", "2994578125", "78613566", "7.983"),
        ("2994578125", "5989156250", "208321251", "8.259"),
        ("5989156250", "11978312500", "455643458", "8.519"),
        ("11978312500", None, "965859679", "8.753"),
    ),
    categoria_d=_tramos(
        ("0", "10701413", "0", "4.006"),
        ("10701413", "21402794", "428699", "4.036"),
        ("21402794", "42805615", "860607", "4.097"),
        ("42805615", "85611202", "1737481", "4.217"),
        ("85611202", "171222431", "3542593", "4.457"),
        ("171222431", "342444836", "7358285", "4.938"),
        ("342444836", "684889673", "15813247", "5.899"),
        ("684889673", "1369779370", "36014068", "7.822"),
        ("1369779370", "2994578125", "89586140", "8.784"),
        ("2994578125", "5989156250", "232308463", "9.024"),
        ("5989156250", "11978312500", "502539193", "9.255"),
        ("11978312500", None, "1056835604", "9.513"),
    ),
)

# Nunca se pisa una escala vieja: cuando ARBA actualice los montos, agregar la nueva acá y
# cerrar ESCALA_2026 con su `hasta` — mismo criterio que notaria.precios_modelo.
_ESCALAS: tuple[EscalaItgb, ...] = (ESCALA_2026,)


def _validar_consistencia(escala: EscalaItgb, tolerancia: Decimal = Decimal("2")) -> None:
    """Verifica que los 12 tramos de cada categoría sean contiguos y que la cuota fija de
    cada tramo coincida (dentro de una tolerancia de redondeo) con la del tramo anterior más
    lo que corresponde tributar sobre todo su rango. Corre una sola vez, al importar el
    módulo: si alguno de los 48 tramos se transcribió mal, falla acá y no en un cálculo real.

    La tolerancia se calibró contra la tabla real: el diff máximo observado entre la cuota
    predicha y la transcripta es de $0,50 en las cuatro categorías (redondeo normal de la
    tabla oficial). Un error de transcripción real se nota en cientos o miles de pesos, no en
    centavos.
    """
    categorias = (
        ("A", escala.categoria_a), ("B", escala.categoria_b),
        ("C", escala.categoria_c), ("D", escala.categoria_d),
    )
    for nombre, tramos in categorias:
        assert tramos[0].mayor_a == 0, f"Categoría {nombre}: el primer tramo no arranca en 0."
        assert tramos[-1].menor_o_igual_a is None, f"Categoría {nombre}: el último tramo debe ser abierto."
        for i in range(len(tramos) - 1):
            actual, siguiente = tramos[i], tramos[i + 1]
            assert actual.menor_o_igual_a == siguiente.mayor_a, (
                f"Categoría {nombre}, tramo {i + 1}->{i + 2}: hueco o solape entre límites "
                f"({actual.menor_o_igual_a} != {siguiente.mayor_a})."
            )
            predicho = actual.cuota_fija + (
                actual.menor_o_igual_a - actual.mayor_a
            ) * actual.porcentaje / Decimal(100)
            diff = abs(predicho - siguiente.cuota_fija)
            assert diff <= tolerancia, (
                f"Categoría {nombre}, tramo {i + 1}->{i + 2}: cuota fija inconsistente "
                f"(predicha {predicho}, transcripta {siguiente.cuota_fija}, diff {diff})."
            )


_validar_consistencia(ESCALA_2026)


def _escala_vigente(fecha: date) -> EscalaItgb:
    candidatas = [e for e in _ESCALAS if e.desde <= fecha and (e.hasta is None or fecha < e.hasta)]
    if not candidatas:
        raise ItgbInvalido(f"No hay una escala de ITGB vigente para la fecha {fecha}.")
    return max(candidatas, key=lambda e: e.desde)


# ==========================================================================================
# PARENTESCO -> CATEGORÍA
# ==========================================================================================
# Listas CERRADAS, sin fallback por defecto a "D" para lo no reconocido: aunque la categoría D
# es en la norma un cajón que incluye "otros parientes y extraños", decidir que una palabra no
# reconocida cae ahí sería una clasificación legal que hace el código en silencio. Mejor
# rechazar y que lo confirme quien lo usa.
_NOMBRES_CATEGORIA: dict[str, str] = {
    "A": "progenitores, hijos/as y cónyuge",
    "B": "otros ascendientes y descendientes",
    "C": "colaterales de 2° grado",
    "D": "colaterales de 3° y 4° grado, otros parientes y extraños/as",
}

_CATEGORIA_A: frozenset[str] = frozenset({
    "hijo", "hija", "hijos", "hijas",
    "padre", "madre", "papa", "mama", "papá", "mamá", "progenitor", "progenitora",
    "conyuge", "cónyuge", "esposo", "esposa", "marido", "mujer",
})
_CATEGORIA_B: frozenset[str] = frozenset({
    "nieto", "nieta", "abuelo", "abuela",
    "bisnieto", "bisnieta", "bisabuelo", "bisabuela",
    "tataranieto", "tataranieta", "tatarabuelo", "tatarabuela",
})
_CATEGORIA_C: frozenset[str] = frozenset({
    "hermano", "hermana",
    "hermano bilateral", "hermana bilateral", "hermano unilateral", "hermana unilateral",
    "medio hermano", "media hermana",
})
_CATEGORIA_D: frozenset[str] = frozenset({
    "tio", "tia", "tío", "tía", "sobrino", "sobrina",
    "primo", "prima", "primo hermano", "prima hermana",
    "sin parentesco", "extrano", "extrana", "extraño", "extraña",
    "persona juridica", "persona jurídica", "sociedad", "tercero", "tercera",
})

def _categoria_por_parentesco(parentesco: str) -> tuple[str, str]:
    """Valida el parentesco y devuelve (categoría, nombre de la categoría).

    Levanta ItgbInvalido si no es una de las palabras reconocidas.
    """
    if not isinstance(parentesco, str):
        raise ItgbInvalido(
            "El parentesco debe ser una cadena de texto; "
            f"se recibió un valor de tipo {type(parentesco).__name__}."
        )

    texto = parentesco.strip().lower()

    if texto in _CATEGORIA_A:
        return "A", _NOMBRES_CATEGORIA["A"]
    if texto in _CATEGORIA_B:
        return "B", _NOMBRES_CATEGORIA["B"]
    if texto in _CATEGORIA_C:
        return "C", _NOMBRES_CATEGORIA["C"]
    if texto in _CATEGORIA_D:
        return "D", _NOMBRES_CATEGORIA["D"]

    raise ItgbInvalido(
        f"El parentesco '{parentesco}' no es reconocido; use, por ejemplo: 'hijo/a', "
        "'padre/madre' o 'cónyuge' (categoría A), 'nieto/a' o 'abuelo/a' (categoría B), "
        "'hermano/a' (categoría C), o 'tío/a', 'sobrino/a', 'primo/a', 'sin parentesco' o "
        "'persona jurídica' (categoría D). Si es un vínculo distinto (hijastro, conviviente, "
        "yerno, adoptivo, etc.), confirmá antes la categoría que corresponde contra el Código "
        "Fiscal de la Provincia de Buenos Aires."
    )


# ==========================================================================================
# VALUACIÓN FISCAL
# ==========================================================================================

def _normalizar_monto(valor: str | int) -> Decimal:
    """Valida la valuación fiscal al acto y la devuelve como Decimal positivo.

    Acepta formato argentino con separador de miles y coma decimal (ej. "45.230.000,50").
    Si no hay coma, cualquier "." se toma como separador de miles y se descarta (ej.
    "5.000.000" -> 5000000).

    Levanta ItgbInvalido con una explicación si no es válido.
    """
    if isinstance(valor, bool):  # bool es subclase de int: lo descartamos
        raise ItgbInvalido(
            "La valuación fiscal debe ser un número o una cadena de dígitos; "
            f"se recibió un booleano ({valor!r})."
        )

    if isinstance(valor, int):
        texto = str(valor)
    elif isinstance(valor, str):
        texto = valor.strip().replace("$", "").strip()
    else:
        raise ItgbInvalido(
            "La valuación fiscal debe ser un entero o una cadena de texto; "
            f"se recibió un valor de tipo {type(valor).__name__}."
        )

    if texto == "":
        raise ItgbInvalido("La valuación fiscal está vacía: no hay ningún monto para procesar.")

    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    else:
        texto = texto.replace(".", "")

    try:
        monto = Decimal(texto)
    except InvalidOperation as error:
        raise ItgbInvalido(
            f"La valuación fiscal '{valor}' no es un monto válido: use solo dígitos, "
            "separadores de miles ('.') y coma decimal (ej. '45.230.000,50')."
        ) from error

    if monto <= 0:
        raise ItgbInvalido(f"La valuación fiscal tiene que ser mayor que 0; se recibió {monto}.")

    return monto


def _tramo_aplicable(tramos: tuple[Tramo, ...], base: Decimal) -> Tramo:
    for tramo in tramos:
        if tramo.menor_o_igual_a is None or base <= tramo.menor_o_igual_a:
            return tramo
    raise AssertionError("la escala no debería quedar sin un tramo abierto")  # no debería pasar


# ==========================================================================================
# CÁLCULO
# ==========================================================================================

@dataclass(frozen=True)
class ResultadoItgb:
    impuesto: Decimal
    categoria: str
    categoria_nombre: str
    parentesco_normalizado: str
    tramo: Tramo
    base_imponible: Decimal


def calcular_itgb(
    valuacion_fiscal: str | int,
    parentesco: str,
    fecha: date | None = None,
) -> ResultadoItgb:
    """Calcula el ITGB aplicando la escala de tramos que corresponde según el parentesco.

    `valuacion_fiscal` es la Valuación Fiscal al Acto ya determinada: no se deriva ningún
    coeficiente acá. `fecha` elige qué escala aplicar si en el futuro hay más de una vigente;
    por defecto es hoy.

    Levanta ItgbInvalido si la valuación no es un monto positivo válido o si el parentesco no
    es reconocido.
    """
    base = _normalizar_monto(valuacion_fiscal)
    categoria, nombre = _categoria_por_parentesco(parentesco)
    escala = _escala_vigente(fecha or date.today())
    tramos = getattr(escala, f"categoria_{categoria.lower()}")
    tramo = _tramo_aplicable(tramos, base)

    excedente = base - tramo.mayor_a
    impuesto = (tramo.cuota_fija + excedente * tramo.porcentaje / Decimal(100)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )

    return ResultadoItgb(impuesto, categoria, nombre, parentesco.strip().lower(), tramo, base)


def _formato_pesos(monto: Decimal) -> str:
    return f"${monto:,.0f}".replace(",", ".")


def formatear_resultado_itgb(r: ResultadoItgb) -> str:
    tope = _formato_pesos(r.tramo.menor_o_igual_a) if r.tramo.menor_o_igual_a is not None else "sin tope"
    excedente = r.base_imponible - r.tramo.mayor_a
    return (
        f"{_formato_pesos(r.impuesto)} "
        f"(categoría {r.categoria}: {r.categoria_nombre}; parentesco '{r.parentesco_normalizado}'; "
        f"tramo {_formato_pesos(r.tramo.mayor_a)}-{tope}: "
        f"cuota fija {_formato_pesos(r.tramo.cuota_fija)} + {r.tramo.porcentaje}% "
        f"sobre el excedente de {_formato_pesos(excedente)})"
    )


def obtener_itgb(
    valuacion_fiscal: str | int,
    parentesco: str,
    fecha: date | None = None,
) -> tuple[bool, str]:
    """Variante sin excepciones de calcular_itgb.

    Devuelve (True, "$80.150 (categoría A: ...)") si los datos son válidos,
    o (False, "explicación del rechazo") si no lo son.
    """
    try:
        resultado = calcular_itgb(valuacion_fiscal, parentesco, fecha)
        return True, formatear_resultado_itgb(resultado)
    except ItgbInvalido as error:
        return False, str(error)
