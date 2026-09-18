"""
Cálculo de las fracciones que corresponden a cada heredero en una sucesión intestada,
según el orden de llamamiento de los arts. 2424 a 2440 del CCyCN (Libro Quinto, Título IX).

Los cuatro órdenes, en el orden de exclusión que fija el art. 2424 (cada uno excluye al
siguiente si tiene herederos):

    1. Descendientes (arts. 2426-2430, 2433): los hijos heredan por derecho propio y por
       partes iguales; si un hijo premurió, renunció o fue declarado indigno, sus propios
       descendientes heredan en su lugar por representación (arts. 2427-2429), dividiendo
       por estirpe. El cónyuge concurre con los descendientes (art. 2433): si el bien es
       propio del causante, hereda como un hijo más; si es ganancial, NO hereda la mitad
       del causante —esa mitad es de los descendientes solamente—, porque la muerte de un
       cónyuge extingue la comunidad de gananciales (art. 475 inc. a) y esa comunidad se
       liquida por mitades: la mitad del cónyuge supérstite es suya por partición, no por
       herencia, y los herederos solo reciben su parte sobre la mitad que le hubiese
       correspondido al causante (art. 498).
    2. Ascendientes (arts. 2431, 2434): a falta de descendientes. El cónyuge se lleva la
       mitad (art. 2434) y los ascendientes de grado más próximo se dividen la otra mitad
       por partes iguales (art. 2431). El texto de estos artículos no repite la excepción
       de gananciales del art. 2433, así que acá esa distinción NO se aplica.
    3. Cónyuge solo (art. 2435): a falta de descendientes y ascendientes, el cónyuge
       hereda la totalidad y excluye a los colaterales.
    4. Colaterales (arts. 2438-2440): a falta de descendientes, ascendientes y cónyuge.
       Implementado solo para hermanos (bilaterales y unilaterales): un unilateral hereda
       la mitad de lo que hereda un bilateral (art. 2440).

Fuera de alcance (no calculado acá):
    - Representación de sobrinos en la sucesión de colaterales, y colaterales de tercer y
      cuarto grado como tíos o primos (arts. 2438-2439).
    - Representación en más de un nivel dentro de una misma estirpe de descendientes
      (art. 2428, segundo párrafo: subdivisión dentro de la estirpe de un nieto premuerto).
      Acá cada estirpe de representación es un único nivel.
    - Exclusiones del cónyuge por matrimonio in extremis, divorcio o separación de hecho
      (arts. 2436-2437): quien llama a esta función ya debe haber resuelto si el cónyuge
      hereda o no.
    - Vacancia (arts. 2441-2443): no es un cálculo de fracciones.

Las fracciones que se devuelven son sobre EL BIEN indicado, no sobre la totalidad del
acervo si en la sucesión hay bienes de distinto origen (ganancial/propio).

CONDOMINIO PREVIO DEL CAUSANTE. Si el causante no era dueño de la totalidad del bien sino de una
parte indivisa (por ejemplo, un tercio adquirido en condominio con otras personas, ajeno a la
sociedad conyugal), esa parte se indica en `fraccion_causante`. Es una fracción DISTINTA de la
del art. 498: 498 reparte lo que el causante tenía DENTRO de la sociedad conyugal (la mitad del
bien ganancial); `fraccion_causante` acota CUÁNTO del bien era del causante para empezar. Las dos
se aplican en cadena cuando corresponden: si el causante tenía un tercio de un inmueble y ese
tercio era ganancial, el cónyuge se queda con la mitad de ese tercio por partición (1/6), y el
resto del cálculo (arts. 2426 y siguientes) reparte el otro sexto entre los descendientes. Todas
las fracciones que devuelve esta función ya están expresadas sobre el bien total, no sobre la
parte del causante.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction


class HerenciaInvalida(ValueError):
    """Se levanta cuando la combinación de herederos no respeta el orden de exclusión del art. 2424."""


@dataclass(frozen=True)
class PorcionHeredero:
    categoria: str
    fraccion: Fraction
    cantidad: int
    nota: str = ""


def _validar_no_negativos(**valores: int) -> None:
    for nombre, valor in valores.items():
        if valor < 0:
            raise HerenciaInvalida(f"{nombre} no puede ser negativo; se recibió {valor}.")


def _parsear_fraccion_causante(texto: str) -> Fraction:
    """La parte indivisa del bien que era del causante, como Fraction en (0, 1].

    Acepta el mismo formato "numerador/denominador" que ya usa `Fraction` (ej: "1/6"), para que
    el modelo transcriba "la sexta parte" tal como transcribe una fecha o una partida: sin hacer
    la cuenta él mismo.
    """
    try:
        fraccion = Fraction(str(texto).strip())
    except (ValueError, ZeroDivisionError) as error:
        raise HerenciaInvalida(
            f"La fracción del causante '{texto}' no es válida; use el formato "
            "'numerador/denominador' (ej: '1/6') o un número (ej: '0.5')."
        ) from error
    if not (0 < fraccion <= 1):
        raise HerenciaInvalida(
            f"La fracción del causante tiene que ser mayor que 0 y hasta 1; se recibió {fraccion}."
        )
    return fraccion


def _orden_descendientes(
    hijos_vivos: int,
    nietos_por_representacion: list[int],
    hay_conyuge: bool,
    tipo_bien: str,
) -> list[PorcionHeredero]:
    n_estirpes = hijos_vivos + len(nietos_por_representacion)

    if hay_conyuge:
        if tipo_bien not in ("ganancial", "propio"):
            raise HerenciaInvalida(f"tipo_bien debe ser 'ganancial' o 'propio'; se recibió '{tipo_bien}'.")
        if tipo_bien == "ganancial":
            fraccion_conyuge = Fraction(1, 2)
            fraccion_por_estirpe = Fraction(1, 2) / n_estirpes
            nota_conyuge = "es su parte propia por liquidación de la comunidad de gananciales, no hereda la del causante (arts. 498 y 2433)"
        else:
            fraccion_por_estirpe = Fraction(1, n_estirpes + 1)
            fraccion_conyuge = fraccion_por_estirpe
            nota_conyuge = "hereda como un hijo más (art. 2433)"
    else:
        fraccion_conyuge = None
        nota_conyuge = ""
        fraccion_por_estirpe = Fraction(1, n_estirpes)

    porciones = []
    if hijos_vivos:
        porciones.append(PorcionHeredero("hijo", fraccion_por_estirpe, hijos_vivos))
    for tamano in nietos_por_representacion:
        porciones.append(PorcionHeredero(
            f"descendiente por representación (estirpe de {tamano})",
            fraccion_por_estirpe / tamano,
            tamano,
        ))
    if fraccion_conyuge is not None:
        porciones.append(PorcionHeredero("cónyuge", fraccion_conyuge, 1, nota_conyuge))
    return porciones


def _orden_ascendientes(ascendientes: int, hay_conyuge: bool) -> list[PorcionHeredero]:
    porciones = []
    if hay_conyuge:
        porciones.append(PorcionHeredero("cónyuge", Fraction(1, 2), 1))
        fraccion_ascendiente = Fraction(1, 2) / ascendientes
    else:
        fraccion_ascendiente = Fraction(1, ascendientes)
    porciones.append(PorcionHeredero("ascendiente", fraccion_ascendiente, ascendientes))
    return porciones


def _orden_colaterales(bilaterales: int, unilaterales: int) -> list[PorcionHeredero]:
    denominador = 2 * bilaterales + unilaterales
    porciones = []
    if bilaterales:
        porciones.append(PorcionHeredero("hermano bilateral", Fraction(2, denominador), bilaterales))
    if unilaterales:
        porciones.append(PorcionHeredero("hermano unilateral", Fraction(1, denominador), unilaterales))
    return porciones


def porciones_herencia_intestada(
    hijos_vivos: int = 0,
    nietos_por_representacion: list[int] | None = None,
    hay_conyuge: bool = False,
    tipo_bien: str = "propio",
    ascendientes: int = 0,
    hermanos_bilaterales: int = 0,
    hermanos_unilaterales: int = 0,
    fraccion_causante: str = "1",
) -> list[PorcionHeredero]:
    """Fracciones de los herederos, respetando el orden de exclusión del art. 2424.

    Indicar solo los datos del orden que corresponde (arts. 2424/2438): descendientes
    (hijos_vivos y, si un hijo premurió, nietos_por_representacion con la cantidad de
    descendientes de esa estirpe), o ascendientes, o hermanos. El cónyuge (hay_conyuge)
    puede concurrir con cualquiera de esos tres, o heredar solo si no hay ninguno.

    `fraccion_causante` es la parte indivisa del bien que era del causante (ver la nota de
    condominio en el docstring del módulo); "1" —el valor por defecto— es titular pleno.

    Levanta HerenciaInvalida si los datos mezclan órdenes que se excluyen entre sí, si no se
    indicó ningún heredero, o si `fraccion_causante` no es una fracción válida entre 0 y 1.
    """
    nietos_por_representacion = nietos_por_representacion or []
    parte_causante = _parsear_fraccion_causante(fraccion_causante)

    _validar_no_negativos(
        hijos_vivos=hijos_vivos,
        ascendientes=ascendientes,
        hermanos_bilaterales=hermanos_bilaterales,
        hermanos_unilaterales=hermanos_unilaterales,
    )
    for tamano in nietos_por_representacion:
        if tamano < 1:
            raise HerenciaInvalida(
                f"Cada estirpe de representación debe tener al menos 1 descendiente; se recibió {tamano}."
            )

    tiene_descendientes = hijos_vivos > 0 or bool(nietos_por_representacion)
    tiene_ascendientes = ascendientes > 0
    tiene_colaterales = hermanos_bilaterales > 0 or hermanos_unilaterales > 0

    if tiene_descendientes:
        if tiene_ascendientes or tiene_colaterales:
            raise HerenciaInvalida(
                "Hay descendientes: no corresponde indicar ascendientes ni hermanos, "
                "porque los descendientes los excluyen (art. 2424)."
            )
        porciones = _orden_descendientes(hijos_vivos, nietos_por_representacion, hay_conyuge, tipo_bien)
    elif tiene_ascendientes:
        if tiene_colaterales:
            raise HerenciaInvalida(
                "Hay ascendientes: no corresponde indicar hermanos, porque los "
                "ascendientes los excluyen (art. 2438)."
            )
        porciones = _orden_ascendientes(ascendientes, hay_conyuge)
    elif hay_conyuge:
        nota = "hereda la totalidad y excluye a los colaterales (art. 2435)" if tiene_colaterales else ""
        porciones = [PorcionHeredero("cónyuge", Fraction(1, 1), 1, nota)]
    elif tiene_colaterales:
        porciones = _orden_colaterales(hermanos_bilaterales, hermanos_unilaterales)
    else:
        raise HerenciaInvalida(
            "No se indicó ningún heredero: se necesita al menos un hijo, un ascendiente, "
            "un hermano o un cónyuge supérstite."
        )

    total = sum(p.fraccion * p.cantidad for p in porciones)
    assert total == 1, f"Las porciones no suman el total del bien: {total}"

    if parte_causante != 1:
        porciones = [
            PorcionHeredero(p.categoria, p.fraccion * parte_causante, p.cantidad, p.nota)
            for p in porciones
        ]
    return porciones


def formatear_porciones(porciones: list[PorcionHeredero]) -> str:
    partes = []
    for p in porciones:
        etiqueta = f"{p.categoria}: {p.fraccion}"
        if p.cantidad > 1:
            etiqueta += f" cada uno (x{p.cantidad})"
        if p.nota:
            etiqueta += f" [{p.nota}]"
        partes.append(etiqueta)
    return "; ".join(partes)


def obtener_porciones_herencia(
    hijos_vivos: int = 0,
    nietos_por_representacion: list[int] | None = None,
    hay_conyuge: bool = False,
    tipo_bien: str = "propio",
    ascendientes: int = 0,
    hermanos_bilaterales: int = 0,
    hermanos_unilaterales: int = 0,
    fraccion_causante: str = "1",
) -> tuple[bool, str]:
    """Variante sin excepciones de porciones_herencia_intestada.

    Devuelve (True, "hijo: 1/3 cada uno (x3)") si los datos son válidos,
    o (False, "explicación del rechazo") si no lo son.
    """
    try:
        porciones = porciones_herencia_intestada(
            hijos_vivos=hijos_vivos,
            nietos_por_representacion=nietos_por_representacion,
            hay_conyuge=hay_conyuge,
            tipo_bien=tipo_bien,
            ascendientes=ascendientes,
            hermanos_bilaterales=hermanos_bilaterales,
            hermanos_unilaterales=hermanos_unilaterales,
            fraccion_causante=fraccion_causante,
        )
        texto = formatear_porciones(porciones)
        parte_causante = _parsear_fraccion_causante(fraccion_causante)
        if parte_causante != 1:
            texto = f"[el causante era titular de {parte_causante} del bien; fracciones ya sobre el bien total] {texto}"
        return True, texto
    except HerenciaInvalida as error:
        return False, str(error)
