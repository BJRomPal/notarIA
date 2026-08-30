"""Audita las remisiones REMITE_A de las DTR que la lógica actual de ingest_dtr.py no
reproduce, para distinguir las legítimas (creadas por versiones anteriores o a mano) de
las erróneas.

Para cada relación busca en el texto del artículo de origen una cita a la norma de destino
y verifica si el número de artículo de destino aparece efectivamente asociado a esa cita.
NO modifica nada: solo clasifica y reporta.
"""
import os
import re
import sys
import glob
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "extractors"))
import ingest_dtr as ing

RUTA_INFORME = os.path.join(BASE_DIR, "input", "normas", "registral", "dtr",
                            "informe_remisiones_dtr.md")

# Cómo se cita en el texto cada norma de destino
PATRON_NORMA = {
    "Ley_17801":           r'17[\.\s]?801',
    "Ley_19550":           r'19[\.\s]?550',
    "Ley_25246":           r'25[\.\s]?246',
    "Decreto_2080_1980":   r'2080',
    "CCyCN":               r'C[óo]d(?:igo)?\.?\s*Civil\s+y\s+Comercial|CCyC|C\.?C\.?C\.?N',
}
VENTANA = 200


def norma_de(art_id: str) -> str:
    return art_id.split("_", 2)[-1]


def numero_de(art_id: str) -> str:
    return art_id.split("_")[1]


def patron_para(norma: str) -> str | None:
    if norma in PATRON_NORMA:
        return PATRON_NORMA[norma]
    m = re.match(r'DTR_(\d+)_(\d{4})', norma)
    if m:
        n, a = m.group(1), m.group(2)
        return (r'(?:D\.?\s?T\.?\s?R\.?|Disposici[óo]n\s+T[ée]cnico\s+Registral)'
                rf'[^\d]{{0,20}}{n}\s*[/\-]\s*(?:{a}|{a[-2:]})')
    return None


def cargar_textos() -> dict:
    textos = {}
    for anio in sorted([d for d in os.listdir(ing.DTR_DIR)
                        if os.path.isdir(os.path.join(ing.DTR_DIR, d))], key=int):
        for path in sorted(glob.glob(os.path.join(ing.DTR_DIR, anio, "*.txt"))):
            m = re.match(r'dtr\s+(\d+)-(\d+)\.txt', os.path.basename(path), re.IGNORECASE)
            if not m:
                continue
            norma = f"DTR_{m.group(1)}_{anio}"
            crudo = open(path, encoding="utf-8").read()
            if not crudo.strip():
                continue
            for numero, txt in ing.parsear_dtr(crudo)[2]:
                textos[f"Art_{numero}_{norma}"] = txt
    return textos


def auditar(origen: str, destino: str, textos: dict) -> tuple[str, str]:
    """Devuelve (clasificacion, evidencia)."""
    texto = textos.get(origen)
    if texto is None:
        return "SIN_FUENTE", "no se pudo recuperar el texto del artículo de origen"

    norma_dest, num_dest = norma_de(destino), numero_de(destino)
    patron = patron_para(norma_dest)
    if patron is None:
        return "NORMA_NO_MAPEADA", f"sin patrón de cita para {norma_dest}"

    apariciones = list(re.finditer(patron, texto, re.IGNORECASE))
    if not apariciones:
        return "NORMA_NO_CITADA", f"'{norma_dest}' no aparece citada en el texto"

    # ¿el número de destino aparece cerca de alguna cita a esa norma?
    # El ordinal ("8º", "8°") cuenta como carácter de palabra en Unicode, así que un
    # \b final no matchea; se admite el marcador ordinal como cierre.
    num_re = re.compile(rf'(?<!\d){re.escape(num_dest)}(?:\s*(?:bis|ter))?(?![\d])')
    for m in apariciones:
        win = texto[max(0, m.start() - VENTANA): m.end() + VENTANA]
        if num_re.search(win):
            frag = re.sub(r'\s+', ' ', win).strip()
            return "OK", f"...{frag[:190]}..."
    frag = re.sub(r'\s+', ' ', texto[max(0, apariciones[0].start() - 120):
                                     apariciones[0].end() + 120]).strip()
    return "NUMERO_AUSENTE", f"art. {num_dest} no aparece cerca de la cita: ...{frag[:170]}..."


def main():
    textos = cargar_textos()

    # Lo que produce la lógica corregida
    cache, pend = {}, defaultdict(set)
    reproducibles = set()
    for art_id, txt in textos.items():
        anio = int(norma_de(art_id).split("_")[-1])
        for o, d in ing.resolver_remisiones(art_id, txt, anio, cache, pend):
            reproducibles.add((o, d))

    with ing.driver.session() as s:
        en_grafo = {(r["o"], r["d"]) for r in s.run(
            "MATCH (a:Articulo)-[:REMITE_A]->(b:Articulo) WHERE a.id CONTAINS '_DTR_' "
            "RETURN a.id AS o, b.id AS d")}

    huerfanas = sorted(en_grafo - reproducibles)
    resultados = [(o, d, *auditar(o, d, textos)) for o, d in huerfanas]

    por_clase = defaultdict(list)
    for o, d, clase, ev in resultados:
        por_clase[clase].append((o, d, ev))

    ORDEN = ["OK", "NUMERO_AUSENTE", "NORMA_NO_CITADA", "NORMA_NO_MAPEADA", "SIN_FUENTE"]
    ETIQUETA = {
        "OK": "LEGÍTIMAS — la norma está citada y el número de artículo aparece junto a la cita",
        "NUMERO_AUSENTE": "SOSPECHOSAS — la norma está citada, pero ese número de artículo no aparece cerca",
        "NORMA_NO_CITADA": "SOSPECHOSAS — la norma de destino no aparece citada en el texto del artículo",
        "NORMA_NO_MAPEADA": "NO EVALUABLES — no hay patrón de cita definido para esa norma",
        "SIN_FUENTE": "NO EVALUABLES — no se recuperó el texto de origen",
    }

    print(f"Remisiones desde DTR en el grafo      : {len(en_grafo)}")
    print(f"Reproducibles por la lógica actual    : {len(en_grafo & reproducibles)}")
    print(f"NO reproducibles (objeto de auditoría): {len(huerfanas)}\n")
    for clase in ORDEN:
        if por_clase[clase]:
            print(f"  {clase:18} {len(por_clase[clase]):>3}   {ETIQUETA[clase]}")

    with open(RUTA_INFORME, "w", encoding="utf-8") as f:
        f.write("# Informe — remisiones de DTR no reproducibles\n\n")
        f.write("Relaciones `REMITE_A` presentes en el grafo que la lógica actual de "
                "`extractors/ingest_dtr.py` no vuelve a generar. Se verificó, para cada una, "
                "si la norma de destino está citada en el texto del artículo de origen y si "
                "el número de artículo de destino aparece junto a esa cita.\n\n")
        f.write(f"- Remisiones desde DTR en el grafo: {len(en_grafo)}\n")
        f.write(f"- Reproducibles por la lógica actual: {len(en_grafo & reproducibles)}\n")
        f.write(f"- **No reproducibles (auditadas): {len(huerfanas)}**\n\n")
        for clase in ORDEN:
            if not por_clase[clase]:
                continue
            f.write(f"\n## {clase} ({len(por_clase[clase])})\n\n{ETIQUETA[clase]}\n\n")
            for o, d, ev in sorted(por_clase[clase]):
                f.write(f"- `{o}` → `{d}`\n  - {ev}\n")
    print(f"\nInforme escrito en {os.path.relpath(RUTA_INFORME, BASE_DIR)}")


if __name__ == "__main__":
    main()
