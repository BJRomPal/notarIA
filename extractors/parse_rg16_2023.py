"""Divide 'RG 16-2023.txt' (Resolución General IGJ 16/2023) en archivos individuales por artículo.

Sin jerarquía LIBRO/TÍTULO/CAPÍTULO — 2 artículos planos.
Formato: 'ARTÍCULO N°:' (con tilde, con colon)
"""
import re, os

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_FILE = os.path.join(BASE_DIR, "input/normas/sociedades/RG/2023/RG 16-2023.txt")
OUTPUT_DIR = os.path.join(BASE_DIR, "input/normas/sociedades/RG/2023/articulos_RG16-2023")

os.makedirs(OUTPUT_DIR, exist_ok=True)

SEPARADOR = "-" * 50
HEADER    = "RG: Resolución General IGJ 16/2023"

# Acepta: 'ARTÍCULO 1°:'  'ARTÍCULO 1º:'  'ARTICULO 1:'
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
