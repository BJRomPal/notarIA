"""Divide 22315.txt en archivos individuales por artículo.
Estructura de la ley: CAPITULO → descripción → epígrafe (opcional) → ARTICULO.
El epígrafe se detecta con lookahead: si la siguiente línea no vacía es un ARTICULO,
la línea actual es el epígrafe de ese artículo y se incluye al inicio de su texto."""
import re, os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_FILE = os.path.join(BASE_DIR, "input/normas/sociedades/Ley/22315.txt")
OUTPUT_DIR = os.path.join(BASE_DIR, "input/normas/sociedades/Ley/articulos_22315")

os.makedirs(OUTPUT_DIR, exist_ok=True)

SEPARADOR = "-" * 50

# CAPITULO I, CAPITULO II, etc. — solo el marcador, sin descripción en la misma línea
RE_CAPITULO = re.compile(r'^CAPITULO\s+[IVXLCDM]+\s*$', re.IGNORECASE)

# Acepta: ARTICULO 1° –   ARTICULO 2. –   ARTICULO 10 -
RE_ARTICULO = re.compile(r'^ARTICULO\s+(\d+)\s*[°º\.]?\s*[-–]', re.IGNORECASE)

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    lineas = f.readlines()

# Estado jerárquico
capitulo_actual  = ""
capitulo_desc    = ""
ultimo_marcador  = None   # 'CAPITULO' cuando esperamos la descripción del capítulo

# Estado del artículo en curso
articulo_num     = None
articulo_header  = None
articulo_buffer  = []
epigrafe_pend    = None   # epígrafe detectado por lookahead, pendiente de asignar
articulos_ok     = 0


def build_header() -> str:
    partes = ["LEY: Ley 22315"]
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
    articulo_num  = None
    articulo_buffer = []


i = 0
while i < len(lineas):
    linea   = lineas[i].rstrip("\n")
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
        ultimo_marcador  = "CAPITULO"
        epigrafe_pend    = None
        i += 1
        continue

    # --- 2. Descripción del capítulo (línea inmediata tras el marcador CAPITULO) ---
    if ultimo_marcador == "CAPITULO":
        capitulo_desc   = stripped
        ultimo_marcador = None
        i += 1
        continue

    # --- 3. Inicio de artículo ---
    m = RE_ARTICULO.match(stripped)
    if m:
        guardar_articulo()
        articulo_num    = m.group(1)
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

# Guardar el último artículo
guardar_articulo()
print(f"\nTotal: {articulos_ok} artículos generados en:\n  {OUTPUT_DIR}")
