"""Divide 1493-82.txt en archivos individuales por artículo.

Diferencias respecto a los parsers de leyes:
- Dos variantes de marcador de artículo en el mismo decreto:
    'Artículo 1° –'  (forma extendida, sólo el Art. 1)
    'Art. N° –' / 'Art. N. –'  (forma abreviada, resto)
- Nombre del capítulo en MAYÚSCULAS, puede abarcar varias líneas
  (CAPITULO IV y V están partidos en dos líneas).
- Epígrafes de artículo en minúsculas/mixto, detectados por lookahead.
"""
import re, os

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_FILE = os.path.join(BASE_DIR, "input/normas/sociedades/Decreto/1493-82.txt")
OUTPUT_DIR = os.path.join(BASE_DIR, "input/normas/sociedades/Decreto/articulos_1493-82")

os.makedirs(OUTPUT_DIR, exist_ok=True)

SEPARADOR = "-" * 50

RE_CAPITULO = re.compile(r'^CAPITULO\s+[IVXLCDM]+\s*$', re.IGNORECASE)
# Acepta: 'Artículo 1° –'  'Art. 2° –'  'Art. 10. –'  'Art. 39 –'
RE_ARTICULO = re.compile(r'^(Artículo|Art\.)\s+(\d+)\s*[°º\.]?\s*[-–]')

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    lineas = f.readlines()

# Estado jerárquico
capitulo_actual  = ""
capitulo_desc    = ""
leyendo_capitulo = False   # True mientras acumulamos líneas ALL CAPS del nombre del capítulo

# Estado del artículo en curso
articulo_num    = None
articulo_header = None
articulo_buffer = []
epigrafe_pend   = None
articulos_ok    = 0


def es_todo_mayusculas(texto: str) -> bool:
    """True si el texto tiene al menos una letra y todas están en mayúscula."""
    return texto == texto.upper() and any(c.isalpha() for c in texto)


def build_header() -> str:
    partes = ["DECRETO: Decreto 1493/82"]
    if capitulo_actual:
        cap = f"{capitulo_actual} - {capitulo_desc}" if capitulo_desc else capitulo_actual
        partes.append(f"CAPITULO: {cap}")
    return "\n".join(partes)


def guardar_articulo() -> None:
    global articulo_num, articulo_buffer, articulos_ok
    if articulo_num is None:
        return
    texto = "\n".join(articulo_buffer).strip()
    if texto:
        ruta = os.path.join(OUTPUT_DIR, f"Articulo_{articulo_num}.txt")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(articulo_header)
            f.write(f"\n{SEPARADOR}\n")
            f.write(texto)
            f.write("\n")
        print(f"  Creado: Articulo_{articulo_num}.txt")
        articulos_ok += 1
    articulo_num    = None
    articulo_buffer = []


i = 0
while i < len(lineas):
    linea    = lineas[i].rstrip("\n")
    stripped = linea.strip()

    # --- Línea vacía ---
    if not stripped:
        if articulo_num is not None:
            articulo_buffer.append(linea)
        i += 1
        continue

    # --- 1. Marcador CAPITULO ---
    if RE_CAPITULO.match(stripped):
        guardar_articulo()
        capitulo_actual  = stripped
        capitulo_desc    = ""
        leyendo_capitulo = True
        epigrafe_pend    = None
        i += 1
        continue

    # --- 2. Nombre del capítulo (ALL CAPS, puede ser multi-línea) ---
    if leyendo_capitulo:
        if es_todo_mayusculas(stripped):
            capitulo_desc = (capitulo_desc + " " + stripped).strip() if capitulo_desc else stripped
            i += 1
            continue
        else:
            # Terminó el nombre ALL CAPS: lo que sigue es epígrafe o artículo directo
            leyendo_capitulo = False
            # No hacemos continue: la línea actual se procesa en los pasos siguientes

    # --- 3. Inicio de artículo ---
    m = RE_ARTICULO.match(stripped)
    if m:
        guardar_articulo()
        articulo_num    = m.group(2)
        articulo_header = build_header()
        articulo_buffer = []
        if epigrafe_pend:
            articulo_buffer.append(epigrafe_pend)
            epigrafe_pend = None
        articulo_buffer.append(stripped)
        i += 1
        continue

    # --- 4. Lookahead: ¿esta línea es el epígrafe del próximo artículo? ---
    j = i + 1
    while j < len(lineas) and not lineas[j].strip():
        j += 1
    if j < len(lineas) and RE_ARTICULO.match(lineas[j].strip()):
        guardar_articulo()
        epigrafe_pend = stripped
        i += 1
        continue

    # --- 5. Cuerpo del artículo en curso ---
    if articulo_num is not None:
        articulo_buffer.append(linea)

    i += 1

guardar_articulo()
print(f"\nTotal: {articulos_ok} artículos generados en:\n  {OUTPUT_DIR}")
