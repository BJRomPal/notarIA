"""Divide 'RG 45-2020.txt' (Resolución General IGJ 45/2020) en archivos individuales por artículo.

Sin jerarquía LIBRO/TÍTULO/CAPÍTULO — 2 artículos planos.
Formato: 'Artículo N°:' (con dos puntos, no punto-guion)
"""
import re, os

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_FILE = os.path.join(BASE_DIR, "input/normas/sociedades/RG/2020/RG 45-2020.txt")
OUTPUT_DIR = os.path.join(BASE_DIR, "input/normas/sociedades/RG/2020/articulos_RG45-2020")

os.makedirs(OUTPUT_DIR, exist_ok=True)

SEPARADOR = "-" * 50
HEADER    = "RG: Resolución General IGJ 45/2020"

# Acepta: 'Artículo 1°:'  'Artículo 1º:'  'ARTÍCULO 1:'
RE_ARTICULO = re.compile(r'Art[ÍI]culo\s+(\d+)\s*[°º]?\s*:', re.IGNORECASE)

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    contenido = f.read()

matches      = list(RE_ARTICULO.finditer(contenido))
articulos_ok = 0

for i, m in enumerate(matches):
    numero = m.group(1)
    inicio = m.start()
    fin    = matches[i + 1].start() if i + 1 < len(matches) else len(contenido)
    texto  = contenido[inicio:fin].strip()

    ruta = os.path.join(OUTPUT_DIR, f"Articulo_{numero}.txt")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(HEADER + "\n")
        f.write(SEPARADOR + "\n")
        f.write(texto + "\n")
    articulos_ok += 1

print(f"Total: {articulos_ok} artículos generados en:\n  {OUTPUT_DIR}")
