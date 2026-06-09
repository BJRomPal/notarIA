"""Pipeline de producción para ingestar artículos de la Resolución General IGJ 6/2017
en Neo4j. La RG fue dictada por la IGJ en uso de las facultades de la Ley 22315 y regula
exclusivamente los trámites de constitución y funcionamiento de las SAS ante el organismo.

Jerarquía normativa:
  Ley_27349 (SAS)  ←  RG_6_2017  →  Ley_22315 (Ley Orgánica IGJ)

Vínculos creados en crear_nodo_madre():
  (RG_6_2017)-[:REGLAMENTA_TRAMITES]->(Ley_27349)  — regula operativamente la Ley SAS
  (RG_6_2017)-[:REGLAMENTA_TRAMITES]->(Ley_22315)  — dictada bajo sus atribuciones
"""
import os, sys, time, glob, logging, json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from utils.connectors import get_neo4j_driver, get_gemini_embeddings, get_ollama_llm, enviar_alerta
from utils.extractor_base import (
    GrafoLegalExtraido,
    RELACIONES_PERMITIDAS,
    embed_con_reintento,
    articulo_existe_en_neo4j,
    validar_grafo,
)

# --- 1. REGLAS ONTOLÓGICAS ---
# Ontología cerrada enfocada en SAS y su operatoria ante IGJ.
entidades_permitidas = [
    # Organismo de aplicación
    "InspeccionGeneralDeJusticia",
    "RegistroPublico",

    # Tipo societario principal
    "SociedadPorAccionesSimplificada",

    # Otros tipos societarios mencionados (transformación, requisitos)
    "SociedadAnonima",
    "SociedadDeResponsabilidadLimitada",
    "SociedadPorAcciones",

    # Actores societarios
    "Socio",
    "Administrador",
    "RepresentanteLegal",
    "ConsejoDeVigilancia",

    # Elementos patrimoniales y documentales
    "CapitalSocial",
    "InstrumentoConstitutivo",
    "AporteIrrevocable",

    # Registros y contabilidad
    "RegistroDigital",
    "EstadosContables",

    # Prevención de lavado
    "BeneficiarioFinal",
]

_CANONICOS: dict[str, str] = {
    "SOCIOS":                                    "SOCIO",
    "ADMINISTRADORES":                           "ADMINISTRADOR",
    "REPRESENTANTES_LEGALES":                    "REPRESENTANTE_LEGAL",
    "SOCIEDADES_POR_ACCIONES_SIMPLIFICADAS":     "SOCIEDAD_POR_ACCIONES_SIMPLIFICADA",
    "SAS":                                       "SOCIEDAD_POR_ACCIONES_SIMPLIFICADA",
    "S_A_S":                                     "SOCIEDAD_POR_ACCIONES_SIMPLIFICADA",
    "SOCIEDADES_POR_ACCIONES":                   "SOCIEDAD_POR_ACCIONES",
    "SOCIEDADES_ANONIMAS":                       "SOCIEDAD_ANONIMA",
    "SA":                                        "SOCIEDAD_ANONIMA",
    "SOCIEDADES_DE_RESPONSABILIDAD_LIMITADA":    "SOCIEDAD_DE_RESPONSABILIDAD_LIMITADA",
    "SRL":                                       "SOCIEDAD_DE_RESPONSABILIDAD_LIMITADA",
    "INSPECCION_GENERAL":                        "INSPECCION_GENERAL_DE_JUSTICIA",
    "IGJ":                                       "INSPECCION_GENERAL_DE_JUSTICIA",
    "INSPECTOR_GENERAL_DE_JUSTICIA":             "INSPECCION_GENERAL_DE_JUSTICIA",
    "REGISTRO_PUBLICO_DE_COMERCIO":              "REGISTRO_PUBLICO",
    "APORTES_IRREVOCABLES":                      "APORTE_IRREVOCABLE",
    "INSTRUMENTOS_CONSTITUTIVOS":                "INSTRUMENTO_CONSTITUTIVO",
    "REGISTROS_DIGITALES":                       "REGISTRO_DIGITAL",
    "CONSEJOS_DE_VIGILANCIA":                    "CONSEJO_DE_VIGILANCIA",
    "BENEFICIARIOS_FINALES":                     "BENEFICIARIO_FINAL",
}

_ETIQUETAS_VALIDAS  = set(entidades_permitidas) | {"Articulo"}
_RELACIONES_VALIDAS = set(RELACIONES_PERMITIDAS)

# --- 2. CONFIGURACIÓN E INICIALIZACIÓN ---
os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
_log_file = os.path.join(BASE_DIR, "logs", f"rg6_extract_{time.strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("RG_6_2017")

driver    = get_neo4j_driver()
embeddings = get_gemini_embeddings()

try:
    driver.verify_connectivity()
    logger.info("Conexión a Neo4j establecida correctamente.")
except Exception as e:
    logger.error(f"ERROR FATAL: No se pudo conectar a Neo4j: {e}")
    exit()

llm = get_ollama_llm()

# --- 3. FUNCIONES ---

def crear_nodo_madre(db_driver):
    """Crea el nodo Norma para RG_6_2017 y los vínculos con las normas que reglamenta."""
    with db_driver.session() as session:
        session.run("""
            MERGE (n:Norma {id: 'RG_6_2017'})
            SET n.numero        = '6/2017',
                n.titulo        = 'Resolución General IGJ 6/2017 - Sociedades por Acciones Simplificadas',
                n.fecha_sancion = '26/07/2017',
                n.jurisdiccion  = 'Ciudad Autónoma de Buenos Aires',
                n.tipo          = 'ResolucionGeneral',
                n.rama          = ['societario'],
                n.vigente       = true,
                n.modificada    = true
        """)

        session.run("""
            MATCH (rg:Norma  {id: 'RG_6_2017'})
            MATCH (ley:Norma {id: 'Ley_27349'})
            MERGE (rg)-[:REGLAMENTA_TRAMITES]->(ley)
        """)
        session.run("""
            MATCH (rg:Norma  {id: 'RG_6_2017'})
            MATCH (ley:Norma {id: 'Ley_22315'})
            MERGE (rg)-[:REGLAMENTA_TRAMITES]->(ley)
        """)

    logger.info("Nodo madre RG_6_2017 y vínculos normativos creados/verificados en Neo4j.")


def guardar_en_neo4j(grafo_extraido: GrafoLegalExtraido, db_driver, embedder):
    with db_driver.session() as session:
        for nodo in grafo_extraido.nodos:
            vector_embedding = None
            if nodo.propiedades.texto:
                vector_embedding = embed_con_reintento(embedder, nodo.propiedades.texto)

            if nodo.etiqueta == "Articulo":
                query_nodo = """
                MERGE (n:Articulo {id: $id})
                SET n.numero     = $numero,
                    n.ubicacion  = $ubicacion,
                    n.vigente    = true,
                    n.modificado = false,
                    n.texto      = $texto
                """
                if vector_embedding:
                    query_nodo += "\nSET n.embedding = $embedding"
                session.run(query_nodo,
                            id=nodo.id,
                            numero=nodo.propiedades.numero,
                            ubicacion=nodo.propiedades.ubicacion,
                            texto=nodo.propiedades.texto,
                            embedding=vector_embedding)
            else:
                query_nodo = f"""
                MERGE (n:{nodo.etiqueta} {{id: $id}})
                SET n.numero     = $numero,
                    n.titulo     = $titulo,
                    n.ley_nombre = $ley_nombre,
                    n.ley_numero = $ley_numero
                """
                session.run(query_nodo,
                            id=nodo.id,
                            numero=nodo.propiedades.numero,
                            titulo=nodo.propiedades.titulo,
                            ley_nombre=nodo.propiedades.ley_nombre,
                            ley_numero=nodo.propiedades.ley_numero)

        for rel in grafo_extraido.relaciones:
            query_rel = f"""
            MATCH (a {{id: $inicio}})
            MATCH (b {{id: $fin}})
            MERGE (a)-[r:{rel.tipo}]->(b)
            """
            session.run(query_rel, inicio=rel.inicio, fin=rel.fin)

        for nodo in grafo_extraido.nodos:
            if nodo.etiqueta == "Articulo":
                session.run("""
                    MATCH (norma:Norma {id: 'RG_6_2017'})
                    MATCH (art {id: $art_id})
                    MERGE (norma)-[:CONTIENE]->(art)
                """, art_id=nodo.id)


crear_nodo_madre(driver)

# --- 4. LÓGICA DE PROCESAMIENTO ---
carpeta_archivos    = os.path.join(BASE_DIR, "input/normas/sociedades/RG/articulos_RG6-2017/*.txt")
archivos_a_procesar = sorted(glob.glob(carpeta_archivos))

logger.info(f"Archivo de log: {_log_file}")
logger.info(f"Archivos encontrados: {len(archivos_a_procesar)}")

start_time        = time.time()
archivos_ok       = 0
archivos_saltados = 0
archivos_error    = 0

for file_path in archivos_a_procesar:
    nombre      = os.path.basename(file_path)
    numero      = nombre.replace("Articulo_", "").replace(".txt", "")
    articulo_id = f"Art_{numero}_RG_6_2017"

    if articulo_existe_en_neo4j(driver, articulo_id):
        logger.info(f"SALTADO (ya existe): {articulo_id}")
        archivos_saltados += 1
        continue

    logger.info(f"Procesando: {file_path}")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            texto_completo = f.read()

        partes = texto_completo.split("--------------------------------------------------", 1)
        texto_articulo_raw = partes[1].strip() if len(partes) > 1 else texto_completo.strip()

        prompt_extraccion = f"""
Eres un experto en derecho administrativo y societario argentino.
Devuelve ÚNICAMENTE un objeto JSON válido con esta estructura exacta, sin texto adicional:

{{
  "nodos": [
    {{
      "id": "Art_[Numero]_RG_6_2017",
      "etiqueta": "Articulo",
      "propiedades": {{
        "numero": "[numero del artículo]",
        "titulo": null,
        "texto": null,
        "ubicacion": "[TITULO / EPIGRAFE según el encabezado]",
        "ley_nombre": null,
        "ley_numero": null
      }}
    }}
  ],
  "relaciones": [
    {{
      "inicio": "[id_nodo_origen]",
      "fin": "[id_nodo_destino]",
      "tipo": "[TIPO_RELACION]"
    }}
  ]
}}

REGLAS OBLIGATORIAS:

1. ENTIDADES — USA ÚNICAMENTE estas etiquetas exactas (PascalCase):
   {entidades_permitidas}
   Si el texto menciona algo que NO tiene etiqueta en esa lista, NO lo extraigas.
   La etiqueta ('etiqueta') debe ser el nombre PascalCase exacto de la lista.
   El ID ('id') debe ser el mismo nombre en MAYUSCULAS_SIN_TILDES con guiones bajos.
   Ejemplo: etiqueta="SociedadPorAccionesSimplificada" → id="SOCIEDAD_POR_ACCIONES_SIMPLIFICADA"
   Ejemplo: etiqueta="InspeccionGeneralDeJusticia" → id="INSPECCION_GENERAL_DE_JUSTICIA"

2. RELACIONES — USA ÚNICAMENTE estos tipos exactos:
   {RELACIONES_PERMITIDAS}
   Si necesitas expresar algo que NO está en esa lista, NO lo incluyas.

3. SINGULAR OBLIGATORIO:
   Los IDs siempre en SINGULAR.
   "SociedadesPorAccionesSimplificadas" → id="SOCIEDAD_POR_ACCIONES_SIMPLIFICADA"
   "Administradores" → id="ADMINISTRADOR"

4. NODO ARTÍCULO:
   - ID: "Art_[Numero]_RG_6_2017"  (ej: "Art_7_RG_6_2017")
   - NO rellenes la propiedad 'texto' — quedará null.
   - Para 'ubicacion': combina TITULO + EPIGRAFE (si existe) del encabezado,
     separados por ' / '.
     Ejemplo: "TITULO IV. Constitución / Capacidad. Socios"

5. Norma: Resolución General IGJ N° 6/2017 — regula los trámites de SAS ante la IGJ.
   NO crees relaciones entre artículos de esta RG y artículos de otras normas:
   esas remisiones se gestionan en scripts Cypher separados.

TEXTO:
{texto_completo}
"""

        try:
            respuesta       = llm.invoke(prompt_extraccion)
            data            = json.loads(respuesta.content)
            grafo_resultado = GrafoLegalExtraido.model_validate(data)
            grafo_resultado = validar_grafo(
                grafo_resultado, articulo_id, _ETIQUETAS_VALIDAS, _RELACIONES_VALIDAS, _CANONICOS, logger
            )
        except Exception as e:
            archivos_error += 1
            logger.error(f"  FALLO extracción LLM: {e}")
            enviar_alerta(f"❌ Fallo extracción LLM\nArchivo: {file_path}\n\n{e}")
            continue

        for nodo in grafo_resultado.nodos:
            if nodo.etiqueta == "Articulo":
                nodo.propiedades.texto = texto_articulo_raw

        logger.info(f"  Nodos extraídos    : {len(grafo_resultado.nodos)}")
        logger.info(f"  Relaciones extraídas: {len(grafo_resultado.relaciones)}")
        for nodo in grafo_resultado.nodos:
            logger.info(f"    [{nodo.etiqueta}] {nodo.id}")
        for rel in grafo_resultado.relaciones:
            logger.info(f"    {rel.inicio} -[{rel.tipo}]-> {rel.fin}")

        try:
            guardar_en_neo4j(grafo_resultado, driver, embeddings)
        except Exception as e:
            archivos_error += 1
            logger.error(f"  FALLO guardado Neo4j: {e}")
            enviar_alerta(f"❌ Fallo guardado Neo4j\nArchivo: {file_path}\n\n{e}")
            continue

        logger.info("  Guardado en Neo4j correctamente.")
        archivos_ok += 1

    except Exception as e:
        archivos_error += 1
        logger.error(f"ERROR leyendo {file_path}: {e}")
        enviar_alerta(f"❌ Error leyendo archivo\nArchivo: {file_path}\n\n{e}")

duracion = (time.time() - start_time) / 60
logger.info(f"\nProcesamiento completado. OK: {archivos_ok} | Saltados: {archivos_saltados} | Errores: {archivos_error} | Duración: {duracion:.2f} min.")
enviar_alerta(
    f"✅ Procesamiento completado.\n"
    f"✔ OK: {archivos_ok} | ⏭ Saltados: {archivos_saltados} | ✘ Errores: {archivos_error}\n"
    f"Duración: {duracion:.2f} min."
)
