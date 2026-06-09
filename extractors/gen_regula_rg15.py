"""Genera relaciones REGULA entre artículos de la RG 15/2024 y
entidades ontológicas, basándose en la sección estructural (LIBRO/TÍTULO)
del encabezado de cada archivo — sin usar el LLM.

Lógica: el LIBRO y el TÍTULO determinan a qué tipo de entidad "regula" cada artículo.
Un artículo del LIBRO VI (Asociaciones Civiles y Fundaciones) no debe contaminar
resultados de búsquedas sobre SA/SRL/SAS.
"""
import os, re, glob

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR   = os.path.join(BASE_DIR, "input/normas/sociedades/RG/articulos_RG15-2024")
OUTPUT_FILE = os.path.join(BASE_DIR, "extractors/regula_rg15.cypher")

# ── Reglas de clasificación ────────────────────────────────────────────────────
# IMPORTANTE: verificar LIBRO y TITULO por separado.
# "LIBRO III SOCIEDADES, CONTRATOS ASOCIATIVOS..." contiene "CONTRATOS ASOCIATIVOS"
# aunque el artículo sea de TÍTULO I SOCIEDADES — la concatenación causaría falsos positivos.

# Reglas que se evalúan contra el LIBRO solamente (orden importa)
REGLAS_LIBRO = [
    ("ASOCIACIONES CIVILES",    [("AsociacionCivil", "ASOCIACION_CIVIL"),
                                 ("Fundacion",       "FUNDACION")]),
    ("MATRICULAS INDIVIDUALES", [("Martillero",             "MARTILLERO"),
                                 ("CorredorNoInmobiliario", "CORREDOR_NO_INMOBILIARIO"),
                                 ("Empresario",             "EMPRESARIO")]),
    ("LAVADO DE ACTIVOS",       [("BeneficiarioFinal",      "BENEFICIARIO_FINAL")]),
]

# Reglas que se evalúan contra el TITULO solamente (orden importa)
REGLAS_TITULO = [
    # LIBRO III TÍTULO I ─ Sociedades comerciales
    ("TÍTULO I SOCIEDADES",                    [("SociedadAnonima",                  "SOCIEDAD_ANONIMA"),
                                                ("SociedadDeResponsabilidadLimitada","SOCIEDAD_DE_RESPONSABILIDAD_LIMITADA"),
                                                ("SociedadPorAccionesSimplificada",  "SOCIEDAD_POR_ACCIONES_SIMPLIFICADA"),
                                                ("SociedadColectiva",                "SOCIEDAD_COLECTIVA")]),
    # LIBRO III TÍTULO II ─ Sociedades extranjeras
    ("SOCIEDADES CONSTITUIDAS EN EL EXTRANJERO",[("SociedadConstituidaEnElExtranjero","SOCIEDAD_CONSTITUIDA_EN_EL_EXTRANJERO")]),
    # LIBRO III TÍTULO III ─ Contratos asociativos
    ("CONTRATOS ASOCIATIVOS",                  [("ContratoAsociativo",  "CONTRATO_ASOCIATIVO")]),
    # LIBRO III TÍTULO IV ─ Contratos de fideicomiso
    ("CONTRATOS DE FIDEICOMISO",               [("ContratoFideicomiso", "CONTRATO_FIDEICOMISO")]),
    # LIBRO VII TÍTULO III ─ Persona humana no empresaria
    ("PERSONA HUMANA NO EMPRESARIA",           [("Empresario",          "EMPRESARIO")]),
]

RE_LIBRO  = re.compile(r'^LIBRO:\s*(.+)$',  re.MULTILINE)
RE_TITULO = re.compile(r'^TITULO:\s*(.+)$', re.MULTILINE)


def clasificar(libro: str, titulo: str) -> list[tuple[str, str]]:
    libro_u  = libro.upper()
    titulo_u = titulo.upper()
    for patron, entidades in REGLAS_LIBRO:
        if patron in libro_u:
            return entidades
    for patron, entidades in REGLAS_TITULO:
        if patron in titulo_u:
            return entidades
    return []


archivos = sorted(glob.glob(os.path.join(INPUT_DIR, "*.txt")))
relaciones: list[tuple[str, str, str]] = []  # (art_id, label, entidad_id)

for path in archivos:
    nombre = os.path.basename(path)
    numero = nombre.replace("Articulo_", "").replace(".txt", "")
    art_id = f"Art_{numero}_RG_15_2024"

    with open(path, encoding="utf-8") as f:
        header = f.read().split("---", 1)[0]

    m_libro  = RE_LIBRO.search(header)
    m_titulo = RE_TITULO.search(header)
    libro    = m_libro.group(1).strip()  if m_libro  else ""
    titulo   = m_titulo.group(1).strip() if m_titulo else ""

    for label, ent_id in clasificar(libro, titulo):
        relaciones.append((art_id, label, ent_id))

# ── Generar Cypher ─────────────────────────────────────────────────────────────
por_entidad: dict[str, int] = {}
for _, label, eid in relaciones:
    por_entidad[eid] = por_entidad.get(eid, 0) + 1

lineas = [
    "// Relaciones REGULA: artículos RG 15/2024 → entidades ontológicas",
    "// Generado por gen_regula_rg15.py — basado en estructura de LIBRO/TÍTULO",
    f"// Total: {len(relaciones)} relaciones",
]
for eid, cnt in sorted(por_entidad.items()):
    lineas.append(f"//   {eid}: {cnt} artículos")
lineas.append("")

ultimo_label = None
for art_id, label, ent_id in relaciones:
    if label != ultimo_label:
        lineas.append(f"// ── {label} ──")
        ultimo_label = label
    lineas.append(f"MATCH  (a:Articulo   {{id: '{art_id}' }})")
    lineas.append(f"MERGE  (e:{label} {{id: '{ent_id}'}})")
    lineas.append( "MERGE  (a)-[:REGULA]->(e);")
    lineas.append("")

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(lineas))

print(f"Generadas {len(relaciones)} relaciones → {OUTPUT_FILE}")
for eid, cnt in sorted(por_entidad.items()):
    print(f"  {eid:50s}: {cnt:3d} artículos")
