"""Divide 'RG 6-2017.txt' en archivos individuales por artículo.

Estructura: TITULO (I–IX) → epígrafe opcional → Artículo.
Epígrafes se detectan con lookahead: si la línea siguiente no vacía es un Artículo,
la línea actual es el epígrafe de ese artículo.
Caso especial: la línea 'I.- Requisitos... Artículo 14.-...' combina epígrafe y artículo
en una sola línea; se pre-divide antes del procesamiento principal.
"""
import re, os

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_FILE = os.path.join(BASE_DIR, "input/normas/sociedades/RG/RG 6-2017.txt")
OUTPUT_DIR = os.path.join(BASE_DIR, "input/normas/sociedades/RG/articulos_RG6-2017")

os.makedirs(OUTPUT_DIR, exist_ok=True)

SEPARADOR = "-" * 50

RE_TITULO   = re.compile(r'^TITULO\s+[IVXLCDM]+\b')
RE_ARTICULO = re.compile(r'^Art[íi]culo\s+(\d+)\s*\.-')
# Línea que tiene texto antes de 'Artículo N.-' (caso inline como "I.- Epígrafe Artículo 14.-...")
RE_SPLIT    = re.compile(r'^(.+?)\s+(Art[íi]culo\s+\d+\s*\.-.*)')

# --- Pre-procesamiento: separar epígrafes embebidos en la misma línea que el artículo ---
with open(INPUT_FILE, 'r', encoding='utf-8') as f:
    raw_lines = f.readlines()

lineas: list[str] = []
for raw in raw_lines:
    s = raw.rstrip('\n')
    if not RE_ARTICULO.match(s.strip()):
        m = RE_SPLIT.match(s.strip())
        if m:
            lineas.append(m.group(1))
            lineas.append(m.group(2))
            continue
    lineas.append(s)

# --- Estado global ---
titulo        = ''
epigrafe_pend = ''
articulo_num  = None
articulo_epi  = ''
articulo_buf: list[str] = []
articulos_ok  = 0


def build_header() -> str:
    partes = ["RG: Resolución General IGJ 6/2017"]
    if titulo:
        partes.append(f"TITULO: {titulo}")
    if articulo_epi:
        partes.append(f"EPIGRAFE: {articulo_epi}")
    return '\n'.join(partes)


def guardar_articulo() -> None:
    global articulo_num, articulo_buf, articulos_ok
    if articulo_num is None:
        return
    texto = '\n'.join(articulo_buf).strip()
    if texto:
        ruta = os.path.join(OUTPUT_DIR, f"Articulo_{articulo_num}.txt")
        with open(ruta, 'w', encoding='utf-8') as f:
            f.write(build_header())
            f.write(f'\n{SEPARADOR}\n')
            f.write(texto)
            f.write('\n')
        articulos_ok += 1
    articulo_num = None
    articulo_buf = []


i = 0
while i < len(lineas):
    linea    = lineas[i]
    stripped = linea.strip()

    # --- Línea vacía ---
    if not stripped:
        if articulo_num is not None:
            articulo_buf.append(linea)
        i += 1
        continue

    # --- Marcador TITULO ---
    if RE_TITULO.match(stripped):
        guardar_articulo()
        titulo        = stripped
        epigrafe_pend = ''
        i += 1
        continue

    # --- Inicio de artículo ---
    m = RE_ARTICULO.match(stripped)
    if m:
        guardar_articulo()
        articulo_num  = m.group(1)
        articulo_epi  = epigrafe_pend
        epigrafe_pend = ''
        articulo_buf  = [stripped]
        i += 1
        continue

    # --- Lookahead: ¿es epígrafe del próximo artículo? ---
    j = i + 1
    while j < len(lineas) and not lineas[j].strip():
        j += 1
    if j < len(lineas) and RE_ARTICULO.match(lineas[j].strip()) and len(stripped) < 200:
        if articulo_num is not None:
            guardar_articulo()
        epigrafe_pend = stripped
        i += 1
        continue

    # --- Cuerpo del artículo en curso ---
    if articulo_num is not None:
        articulo_buf.append(linea)

    i += 1

guardar_articulo()
print(f"Total: {articulos_ok} artículos generados en:\n  {OUTPUT_DIR}")
