"""Divide 'RG 15-2024.txt' en archivos individuales por artículo.

Estructura jerárquica: LIBRO > TÍTULO > CAPÍTULO (opcional) > SECCIÓN (opcional)
Formato de artículo: 'Artículo N.-' siempre al inicio de línea.
El epígrafe se detecta con lookahead: si la siguiente línea no vacía es un artículo
(o un marcador estructural seguido de artículo), la línea actual es el epígrafe.
Dos líneas del archivo combinan dos marcadores en una sola línea:
  - 'CAPÍTULO IV ASAMBLEAS SECCIÓN PRIMERA ...'
  - 'LIBRO VII OTRAS MATRÍCULAS TÍTULO I ...'
Se manejan dividiéndolas en sus marcadores componentes.
"""
import re, os

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_FILE = os.path.join(BASE_DIR, "input/normas/sociedades/RG/RG 15-2024.txt")
OUTPUT_DIR = os.path.join(BASE_DIR, "input/normas/sociedades/RG/articulos_RG15-2024")

os.makedirs(OUTPUT_DIR, exist_ok=True)

SEPARADOR = "-" * 50

RE_LIBRO    = re.compile(r'^LIBRO\s+[IVXLCDM]+\b')
RE_TITULO   = re.compile(r'^TÍTULO\s+[IVXLCDM]+\b')
RE_CAPITULO = re.compile(r'^CAPÍTULO\s+[IVXLCDM]+\b')
RE_SECCION  = re.compile(r'^SECCIÓN\s+\S+')
# Acepta: 'Artículo N.-'  'Artículo N. -'  'Artículo N-'  'Articulo N.-'
#         'Artículo N bis.—'   (también sin tilde: 'Articulo')
RE_ARTICULO = re.compile(r'^Art[íi]culo\s+(\d+(?:\s+bis|\s+ter)?)\s*\.?\s*[-–—]')

# Detecta marcadores secundarios embebidos dentro de una línea que ya tiene otro marcador
RE_TITULO_EMBEBIDO   = re.compile(r'\bTÍTULO\s+[IVXLCDM]+\b')
RE_SECCION_EMBEBIDA  = re.compile(r'\bSECCIÓN\s+\S+')


def separar_epigrafe_embebido(linea: str) -> tuple[str, str]:
    """
    Separa la parte ALL-CAPS de un marcador estructural de la parte en
    minúsculas que podría ser el epígrafe del siguiente artículo.
    Ej: 'TÍTULO VIII RECURSOS Recurso directo' →
        ('TÍTULO VIII RECURSOS', 'Recurso directo')
    Si no hay parte en minúsculas, devuelve (linea, '').
    """
    words = linea.split()
    # Omitir las dos primeras palabras (keyword + numeral/ordinal) y buscar
    # la primera palabra que tenga alguna letra minúscula.
    for i, w in enumerate(words):
        if i < 2:
            continue
        if any(c.islower() for c in w):
            nombre = ' '.join(words[:i]).strip()
            epi    = ' '.join(words[i:]).strip()
            return nombre, epi
    return linea.strip(), ''


def dividir_linea_combinada(linea: str) -> list[str]:
    """
    Divide una línea que contiene dos marcadores estructurales:
      'LIBRO VII OTRAS MATRÍCULAS TÍTULO I IGLESIAS ...' →
        ['LIBRO VII OTRAS MATRÍCULAS', 'TÍTULO I IGLESIAS ...']
      'CAPÍTULO IV ASAMBLEAS SECCIÓN PRIMERA ...' →
        ['CAPÍTULO IV ASAMBLEAS', 'SECCIÓN PRIMERA ...']
    Si no hay marcador secundario, devuelve [linea].
    """
    for patron_sec in [RE_TITULO_EMBEBIDO, RE_SECCION_EMBEBIDA]:
        m = patron_sec.search(linea)
        if m and m.start() > 0:
            return [linea[:m.start()].strip(), linea[m.start():].strip()]
    return [linea]


def es_marcador_estructural(linea: str) -> bool:
    return bool(RE_LIBRO.match(linea) or RE_TITULO.match(linea) or
                RE_CAPITULO.match(linea) or RE_SECCION.match(linea))


# --- Estado global ---
libro    = ''
titulo   = ''
capitulo = ''
seccion  = ''

articulo_num    = None
articulo_lineas = []
articulo_epi    = ''   # epígrafe asignado al artículo en curso
epigrafe_pend   = ''   # candidato a epígrafe (detectado por lookahead)
articulos_ok    = 0


def build_header() -> str:
    partes = ["RG: Resolución General IGJ 15/2024",
              f"LIBRO: {libro}",
              f"TITULO: {titulo}"]
    if capitulo:
        partes.append(f"CAPITULO: {capitulo}")
    if seccion:
        partes.append(f"SECCION: {seccion}")
    if articulo_epi:
        partes.append(f"EPIGRAFE: {articulo_epi}")
    return '\n'.join(partes)


def guardar_articulo() -> None:
    global articulo_num, articulo_lineas, articulos_ok
    if articulo_num is None:
        return
    texto = '\n'.join(articulo_lineas).strip()
    if texto:
        ruta = os.path.join(OUTPUT_DIR, f"Articulo_{articulo_num}.txt")
        with open(ruta, 'w', encoding='utf-8') as f:
            f.write(build_header())
            f.write(f'\n{SEPARADOR}\n')
            f.write(texto)
            f.write('\n')
        articulos_ok += 1
    articulo_num    = None
    articulo_lineas = []


def aplicar_marcador(linea: str) -> None:
    """Actualiza el estado jerárquico según el marcador detectado."""
    global libro, titulo, capitulo, seccion, epigrafe_pend
    nombre, epi = separar_epigrafe_embebido(linea)
    if RE_LIBRO.match(linea):
        libro    = nombre
        titulo   = ''
        capitulo = ''
        seccion  = ''
        epigrafe_pend = epi
    elif RE_TITULO.match(linea):
        titulo   = nombre
        capitulo = ''
        seccion  = ''
        epigrafe_pend = epi
    elif RE_CAPITULO.match(linea):
        capitulo = nombre
        seccion  = ''
        epigrafe_pend = epi
    elif RE_SECCION.match(linea):
        seccion  = nombre
        epigrafe_pend = epi


# --- Procesamiento principal ---
with open(INPUT_FILE, 'r', encoding='utf-8') as f:
    lineas_raw = f.readlines()

i = 0
while i < len(lineas_raw):
    linea    = lineas_raw[i].rstrip('\n')
    stripped = linea.strip()

    # --- Línea vacía ---
    if not stripped:
        if articulo_num is not None:
            articulo_lineas.append(linea)
        i += 1
        continue

    # --- Marcador estructural (puede ser combinado) ---
    if es_marcador_estructural(stripped):
        guardar_articulo()
        for sub in dividir_linea_combinada(stripped):
            aplicar_marcador(sub)
        i += 1
        continue

    # --- Inicio de artículo ---
    m = RE_ARTICULO.match(stripped)
    if m:
        guardar_articulo()
        articulo_num = m.group(1)
        # El epígrafe es epigrafe_pend acumulado hasta ahora
        # Normalizar "354 bis" → "354_bis" para nombre de archivo
        globals()['articulo_epi'] = epigrafe_pend
        epigrafe_pend = ''
        articulo_num = m.group(1).strip().replace(' ', '_')
        articulo_lineas = [stripped]
        i += 1
        continue

    # --- Lookahead: ¿esta línea es el epígrafe del próximo artículo? ---
    # Avanzamos buscando la siguiente línea no vacía
    j = i + 1
    while j < len(lineas_raw) and not lineas_raw[j].strip():
        j += 1
    if j < len(lineas_raw):
        proxima = lineas_raw[j].strip()
        if RE_ARTICULO.match(proxima) or es_marcador_estructural(proxima):
            # Es epígrafe solo si la línea es corta: los párrafos cuerpo de
            # artículo que accidentalmente preceden al marcador siguiente son
            # líneas largas (>= 200 chars), mientras los epígrafes reales son
            # frases breves (título del artículo, < 200 chars).
            if len(stripped) < 200:
                if articulo_num is not None:
                    guardar_articulo()
                epigrafe_pend = stripped
                i += 1
                continue
            # Línea larga → es cuerpo del artículo en curso, cae al caso 5

    # --- Cuerpo del artículo en curso ---
    if articulo_num is not None:
        articulo_lineas.append(linea)

    i += 1

# Guardar el último artículo
guardar_articulo()
print(f"Total: {articulos_ok} artículos generados en:\n  {OUTPUT_DIR}")
