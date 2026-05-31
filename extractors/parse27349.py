"""Divide 27349.txt en archivos individuales por artículo.
Cada archivo incluye un encabezado con la fuente jerárquica (Ley / Título / Capítulo)
separado del texto del artículo por una línea de guiones, igual al formato de articulos_lsc."""
import os
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_FILE = os.path.join(BASE_DIR, "input/normas/sociedades/Ley/27349.txt")
OUTPUT_DIR = os.path.join(BASE_DIR, "input/normas/sociedades/Ley/articulos_27349")

os.makedirs(OUTPUT_DIR, exist_ok=True)

SEPARADOR = "-" * 50

# --- Patrones estructurales ---
RE_TITULO   = re.compile(r'^Título\s+[IVXLCDM]+\s*$')
RE_CAPITULO = re.compile(r'^Capítulo\s+[IVXLCDM]+\s*$')
RE_ARTICULO = re.compile(r'^Artículo\s+(\d+)[\.\-]')

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    lines = f.readlines()

# --- Estado del parser ---
titulo_actual   = None
titulo_desc     = None
capitulo_actual = None
capitulo_desc   = None
pending_titulo   = None
pending_capitulo = None

articulo_num    = None
articulo_header = None
articulo_buffer = []
articulos_guardados = 0


def build_header():
    partes = ["LEY: Ley 27349"]
    if titulo_actual and titulo_desc:
        partes.append(f"TITULO: {titulo_actual} - {titulo_desc}")
    if capitulo_actual and capitulo_desc:
        partes.append(f"CAPITULO: {capitulo_actual} - {capitulo_desc}")
    return "\n".join(partes)


def guardar_articulo(numero, header, buffer):
    global articulos_guardados
    texto = "\n".join(buffer).strip()
    if not texto:
        return
    ruta = os.path.join(OUTPUT_DIR, f"Articulo_{numero}.txt")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(header)
        f.write(f"\n{SEPARADOR}\n")
        f.write(texto)
        f.write("\n")
    print(f"  Creado: Articulo_{numero}.txt")
    articulos_guardados += 1


for line in lines:
    raw  = line.rstrip("\n")
    stripped = raw.strip()

    # 1. Artículo: inicia un nuevo bloque
    m = RE_ARTICULO.match(stripped)
    if m:
        if articulo_num is not None:
            guardar_articulo(articulo_num, articulo_header, articulo_buffer)
        articulo_num    = m.group(1)
        articulo_header = build_header()
        articulo_buffer = [stripped]
        pending_titulo  = None
        pending_capitulo = None
        continue

    # 2. Título: marca inicio de sección jerárquica superior
    if RE_TITULO.match(stripped):
        pending_titulo   = stripped
        pending_capitulo = None
        continue

    # 3. Capítulo
    if RE_CAPITULO.match(stripped):
        pending_capitulo = stripped
        continue

    # 4. Línea no vacía: puede ser descripción de título o capítulo pendiente
    if stripped:
        if pending_titulo is not None:
            titulo_actual   = pending_titulo
            titulo_desc     = stripped
            pending_titulo  = None
            capitulo_actual = None
            capitulo_desc   = None
            continue
        if pending_capitulo is not None:
            capitulo_actual  = pending_capitulo
            capitulo_desc    = stripped
            pending_capitulo = None
            continue

    # 5. Cualquier otra línea (incluyendo sub-títulos internos y líneas en blanco):
    #    se agrega al artículo en curso si hay uno abierto.
    if articulo_num is not None:
        articulo_buffer.append(raw)

# Guardar el último artículo
if articulo_num is not None:
    guardar_articulo(articulo_num, articulo_header, articulo_buffer)

print(f"\nTotal: {articulos_guardados} artículos generados en:\n  {OUTPUT_DIR}")
