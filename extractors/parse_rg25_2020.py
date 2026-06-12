"""Divide 'RG 25-2020.txt' (Resolución General IGJ 25/2020) en archivos individuales por artículo.

Sin jerarquía LIBRO/TÍTULO/CAPÍTULO — 3 artículos planos.
Formato: 'Artículo N.-'
"""
import re, os

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_FILE = os.path.join(BASE_DIR, "input/normas/sociedades/RG/2020/RG 25-2020.txt")
OUTPUT_DIR = os.path.join(BASE_DIR, "input/normas/sociedades/RG/2020/articulos_RG25-2020")

os.makedirs(OUTPUT_DIR, exist_ok=True)

SEPARADOR = "-" * 50
HEADER    = "RG: Resolución General IGJ 25/2020"

# Acepta: 'Artículo 1.-'  'ARTÍCULO 1.-'
RE_ARTICULO = re.compile(r'^Art[ÍI]culo\s+(\d+)\s*\.-', re.IGNORECASE)

articulo_num    = None
articulo_lineas = []
articulos_ok    = 0


def guardar_articulo() -> None:
    global articulo_num, articulo_lineas, articulos_ok
    if articulo_num is None:
        return
    texto = '\n'.join(articulo_lineas).strip()
    if texto:
        ruta = os.path.join(OUTPUT_DIR, f"Articulo_{articulo_num}.txt")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(HEADER + "\n")
            f.write(SEPARADOR + "\n")
            f.write(texto + "\n")
        articulos_ok += 1
    articulo_num    = None
    articulo_lineas = []


with open(INPUT_FILE, "r", encoding="utf-8") as f:
    lineas = f.readlines()

for linea in lineas:
    stripped = linea.rstrip("\n").strip()

    if not stripped:
        if articulo_num is not None:
            articulo_lineas.append("")
        continue

    m = RE_ARTICULO.match(stripped)
    if m:
        guardar_articulo()
        articulo_num    = m.group(1)
        articulo_lineas = [stripped]
    elif articulo_num is not None:
        articulo_lineas.append(stripped)

guardar_articulo()
print(f"Total: {articulos_ok} artículos generados en:\n  {OUTPUT_DIR}")
