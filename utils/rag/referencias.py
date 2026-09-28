"""REFERENCIAS EXPLÍCITAS — «art. 36 de la Ley 27.349» resuelto sin pasar por un modelo.

Cuando la consulta cita artículos de una norma, lo que el escribano quiere es ESE texto. La
búsqueda vectorial no sirve para eso: los embeddings captan «artículo 36» pero no distinguen el
número de ley, y el 2026-09-28 «¿Qué dicen los artículos 36 y 37 de la ley 27349?» trajo los arts.
36 y 37 de la Ley 404, del Decreto 1493/82 y de la RG 2139/2006. El Text-to-Cypher, que era la red,
comparó `numero IN [36, 37]` como números cuando en el grafo es texto, y volvió vacío.

Acá la cita se resuelve con reglas fijas, en tres pasos:

    catalogo_normas(driver)          todas las normas del grafo, indexadas por clase y número
    buscar_referencias(texto, cat)   qué artículos de qué normas cita el texto (función pura)
    resolver_referencias(driver, r)  esos artículos, con una consulta fija; y cuáles no están

Lo que el analizador no reconoce NO se adivina: el grupo queda sin resolver y la consulta sigue
por la búsqueda de siempre. Una cita mal emparejada metería en el contexto el artículo de otra
norma, que es exactamente el error que esto viene a corregir.
"""
import re
from dataclasses import dataclass, field

from utils.rag.citas import NOMBRE_NORMA
from utils.rag.texto import normalizar

# Tope de artículos por norma. Un rango como «arts. 1 a 2000 del CCyCN» no puede volcar un código
# entero en el prompt.
MAX_ARTICULOS = 20

# Distancia máxima, en caracteres, entre un grupo de artículos y la norma a la que se refiere.
# Adelante alcanza con poco («arts. 36 y 37 de la ley…»); atrás se permite más, porque ahí suele
# haber una pregunta en el medio («En la Ley 404, ¿qué dice el art. 1º?»).
VENTANA_DESPUES = 40
VENTANA_ANTES = 60

# La clase con la que se nombra cada tipo de norma en el texto. Un código se cita como ley
# («Ley 26.994»), y las resoluciones de la IGJ y de la UIF comparten «RG»/«Resolución».
_CLASE_DE_TIPO = {
    "Ley": "ley", "Codigo": "ley", "Decreto": "decreto",
    "ResolucionGeneral": "resolucion", "Resolución": "resolucion",
    "DisposicionTecnicoRegistral": "dtr", "InstruccionDeTrabajo": "it",
}

# Normas que se citan por su nombre y no por su número. Solo se usan si el id existe en el grafo.
ALIAS = {
    "lsc": "Ley_19550",
    "ley general de sociedades": "Ley_19550",
    "ley de sociedades comerciales": "Ley_19550",
    "ley de sociedades": "Ley_19550",
    "ccycn": "CCyCN",
    "cccn": "CCyCN",
    "codigo civil y comercial de la nacion": "CCyCN",
    "codigo civil y comercial": "CCyCN",
    "codigo penal": "Ley_11179",
    "codigo fiscal": "Ley_6926",
    "ley organica notarial": "Ley_404",
}

_SUFIJOS = r"bis|ter|quater|quinquies|sexies"
# Un número de artículo ya normalizado: «36», «1o» (de «1º»), «94 bis», «3o bis».
_NUM = rf"\d+o?(?:\s+(?:{_SUFIJOS}))?"
_ARTICULOS = re.compile(
    rf"\bart(?:iculo|s)?s?\.?\s*((?:{_NUM})(?:\s*(?:,|y|e|a|al|hasta|-)\s*(?:{_NUM}))*)"
)
_NORMA = re.compile(
    r"\b(?P<clase>ley|decreto|resolucion(?:\s+general)?|rg"
    r"|disposicion(?:\s+tecnico\s*-?\s*registral)?|dtr|instruccion(?:\s+de\s+trabajo)?|it)"
    r"(?:\s+(?:igj|uif|afip|arca|rpi|dnrpi))?"
    r"\s*(?:n|no|nro|numero)?\.?\s*"
    r"(?P<num>\d[\d.]*(?:/\d{2,4})?)"
)
# Lo que puede haber entre dos grupos de artículos que se refieren a la misma norma:
# «art. 36 y art. 37», «art. 36, el art. 37».
_ENCADENADOS = re.compile(r"\s*(?:,|y|e)?\s*(?:el|la|los|del)?\s*")


@dataclass
class Referencia:
    norma_id: str
    nombre: str
    articulos: list[str] = field(default_factory=list)


@dataclass
class Catalogo:
    """Las normas del grafo, indexadas como se las cita: por (clase, número) y por nombre."""
    por_numero: dict[tuple[str, str], list[str]]
    alias: dict[str, str]
    nombres: dict[str, str]

    @classmethod
    def desde_filas(cls, filas: list[dict]) -> "Catalogo":
        """`filas`: dicts con id, tipo, numero y nombre (el de NOMBRE_NORMA)."""
        por_numero: dict[tuple[str, str], list[str]] = {}
        for f in filas:
            clase = _CLASE_DE_TIPO.get(f.get("tipo") or "")
            if not clase or not f.get("numero"):
                continue
            for variante in _variantes_numero(str(f["numero"])):
                por_numero.setdefault((clase, variante), []).append(f["id"])
        nombres = {f["id"]: f.get("nombre") or f["id"] for f in filas}
        alias = {nombre: nid for nombre, nid in ALIAS.items() if nid in nombres}
        return cls(por_numero, alias, nombres)


def catalogo_normas(driver) -> Catalogo:
    """El catálogo armado desde el grafo. Conviene cachearlo: cambia solo cuando entra una norma."""
    consulta = f"""
    MATCH (norma:Norma)
    RETURN norma.id AS id, norma.tipo AS tipo, norma.numero AS numero, {NOMBRE_NORMA} AS nombre
    """
    with driver.session() as session:
        return Catalogo.desde_filas([dict(r) for r in session.run(consulta)])


def _variantes_numero(numero: str) -> set[str]:
    """Las formas en que se escribe el número de una norma: sin puntos y, si lleva año, con el año
    en dos y en cuatro cifras («2080/80» y «2080/1980», que es como está en el id)."""
    n = numero.replace(".", "").replace(" ", "").strip()
    m = re.fullmatch(r"(\d+)/(\d{2}|\d{4})", n)
    if not m:
        return {n}
    num, anio = m.groups()
    if len(anio) == 2:
        return {f"{num}/{anio}", f"{num}/{'19' if int(anio) >= 30 else '20'}{anio}"}
    return {f"{num}/{anio}", f"{num}/{anio[2:]}"}


def _canonico(numero: str) -> str:
    """«1o» -> «1», «94  bis» -> «94 bis». La «o» viene de «1º» después de normalizar()."""
    m = re.fullmatch(rf"(\d+)o?(?:\s+({_SUFIJOS}))?", numero.strip())
    return m.group(1) + (f" {m.group(2)}" if m.group(2) else "")


def _numeros_de(lista: str) -> list[str]:
    """«36 y 37» -> [36, 37]; «3 a 5» -> [3, 4, 5]; con tope de MAX_ARTICULOS."""
    resultado: list[str] = []
    rango = False
    for parte in re.findall(rf"{_NUM}|\b(?:a|al|hasta)\b|-", lista):
        if parte in ("a", "al", "hasta", "-"):
            rango = True
            continue
        n = _canonico(parte)
        if rango and resultado and resultado[-1].isdigit() and n.isdigit() and int(n) > int(resultado[-1]):
            desde = int(resultado[-1]) + 1
            hasta = min(int(n), desde + MAX_ARTICULOS)
            resultado.extend(str(i) for i in range(desde, hasta + 1))
        else:
            resultado.append(n)
        rango = False
    unicos = list(dict.fromkeys(resultado))
    return unicos[:MAX_ARTICULOS]


def _menciones_de_normas(texto: str, catalogo: Catalogo) -> list[tuple[int, int, str]]:
    """(inicio, fin, norma_id) de cada norma nombrada en el texto que existe en el catálogo."""
    menciones = []
    for m in _NORMA.finditer(texto):
        clase = m.group("clase")
        clase = ("resolucion" if clase.startswith("resolucion") or clase == "rg"
                 else "dtr" if clase.startswith("disposicion") or clase == "dtr"
                 else "it" if clase.startswith("instruccion") or clase == "it"
                 else clase)
        ids = set()
        for variante in _variantes_numero(m.group("num").rstrip(".")):
            ids.update(catalogo.por_numero.get((clase, variante), []))
        if len(ids) == 1:                # ambiguo o inexistente: no se adivina
            menciones.append((m.start(), m.end(), ids.pop()))
    if catalogo.alias:
        nombres = sorted(catalogo.alias, key=len, reverse=True)
        for m in re.finditer(r"\b(" + "|".join(re.escape(n) for n in nombres) + r")\b", texto):
            menciones.append((m.start(), m.end(), catalogo.alias[m.group(1)]))
    return sorted(menciones)


def buscar_referencias(texto: str, catalogo: Catalogo) -> list[Referencia]:
    """Los artículos que el texto cita expresamente, agrupados por norma y en orden de aparición.

    Cada grupo de artículos («arts. 36 y 37») se empareja con una norma, en este orden:
        1. la que viene inmediatamente después   («… de la ley 27349», «art. 77 LSC»)
        2. la que viene inmediatamente antes     («Ley 404, ¿qué dice el art. 1º?»)
        3. la del grupo encadenado siguiente o anterior («art. 36 y art. 37 de la ley 27349»)
    «Inmediatamente» quiere decir dentro de la ventana y sin otro grupo de artículos en el medio.
    """
    t = normalizar(texto)
    grupos = [(m.start(), m.end(), _numeros_de(m.group(1))) for m in _ARTICULOS.finditer(t)]
    if not grupos:
        return []
    menciones = _menciones_de_normas(t, catalogo)

    def despues(i):
        fin = grupos[i][1]
        limite = grupos[i + 1][0] if i + 1 < len(grupos) else len(t)
        for ini, _, nid in menciones:
            if fin <= ini < limite and ini - fin <= VENTANA_DESPUES:
                return nid
        return None

    def antes(i):
        ini = grupos[i][0]
        limite = grupos[i - 1][1] if i > 0 else 0
        candidatas = [(fin, nid) for m_ini, fin, nid in menciones if limite <= m_ini and fin <= ini]
        if candidatas:
            fin, nid = max(candidatas)
            if ini - fin <= VENTANA_ANTES:
                return nid
        return None

    def encadenado(i, j):
        a, b = sorted((i, j))
        return 0 <= a and b < len(grupos) and _ENCADENADOS.fullmatch(t[grupos[a][1]:grupos[b][0]]) is not None

    directas = [despues(i) or antes(i) for i in range(len(grupos))]
    normas = list(directas)
    for i in range(len(grupos)):
        if normas[i] is None and encadenado(i, i + 1):
            normas[i] = directas[i + 1]
    for i in range(len(grupos)):
        if normas[i] is None and encadenado(i - 1, i):
            normas[i] = normas[i - 1]

    referencias: dict[str, Referencia] = {}
    for (_, _, numeros), nid in zip(grupos, normas):
        if nid is None:
            continue
        ref = referencias.setdefault(nid, Referencia(nid, catalogo.nombres.get(nid, nid)))
        ref.articulos = list(dict.fromkeys(ref.articulos + numeros))[:MAX_ARTICULOS]
    return list(referencias.values())


def _variantes_articulo(numero: str) -> list[str]:
    """Cómo puede estar guardado el número en el grafo: «9», «9º» o «9°», con su sufijo si lo tiene."""
    base, _, sufijo = numero.partition(" ")
    resto = f" {sufijo}" if sufijo else ""
    return [f"{base}{resto}", f"{base}º{resto}", f"{base}°{resto}"]


def resolver_referencias(driver, referencias: list[Referencia]) -> tuple[list[dict], list[tuple[str, str]]]:
    """(encontrados, faltantes). Encontrados: dicts con id, numero, texto, vigente y norma (el
    nombre con que se cita), en el orden en que se pidieron. Faltantes: (nombre de la norma,
    número pedido) de lo que no está cargado en el grafo."""
    pedidos = [
        {"norma": r.norma_id, "pedido": n, "variantes": _variantes_articulo(n)}
        for r in referencias for n in r.articulos
    ]
    if not pedidos:
        return [], []
    consulta = f"""
    UNWIND $pedidos AS p
    MATCH (norma:Norma {{id: p.norma}})-[:CONTIENE]->(a:Articulo)
    WHERE a.numero IN p.variantes
    RETURN p.norma AS norma_id, p.pedido AS pedido, a.id AS id, a.numero AS numero,
           a.texto AS texto, coalesce(a.vigente, true) AS vigente, {NOMBRE_NORMA} AS norma
    """
    with driver.session() as session:
        filas = {}
        for r in session.run(consulta, pedidos=pedidos):
            filas.setdefault((r["norma_id"], r["pedido"]), dict(r))

    nombres = {r.norma_id: r.nombre for r in referencias}
    encontrados, faltantes = [], []
    for p in pedidos:
        fila = filas.get((p["norma"], p["pedido"]))
        if fila:
            encontrados.append({k: fila[k] for k in ("id", "numero", "texto", "vigente", "norma")})
        else:
            faltantes.append((nombres[p["norma"]], p["pedido"]))
    return encontrados, faltantes
