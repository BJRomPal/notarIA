"""Pipeline de producción para ingestar artículos de la Ley Orgánica de la IGJ (22.315)
en Neo4j. Lee archivos .txt del directorio de entrada, invoca al LLM local (Ollama/gemma4)
con un prompt JSON libre, valida la salida contra la ontología definida, genera embeddings
con Gemini y persiste en Neo4j. Es idempotente: saltea artículos que ya existen en el grafo.

Vínculos normativos creados en crear_nodo_madre():
  (Ley_22315)-[:REGLAMENTA]->(Ley_19550)   — IGJ aplica la LSC
  (Ley_22315)-[:REGLAMENTA]->(Ley_27349)   — IGJ aplica también la Ley de SAS
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
entidades_permitidas = [
    # Organismo de aplicación
    "InspeccionGeneralDeJusticia",
    "ComisionNacionalDeValores",
    "RegistroPublicoDeComercio",

    # Personas jurídicas sujetas a control
    "SociedadPorAcciones",
    "SociedadConstituidaEnElExtranjero",
    "SociedadDeCapitalizacion",
    "AsociacionCivil",
    "Fundacion",

    # Roles institucionales
    "InspectorGeneral",
    "Director",
    "Sindico",
    "Administrador",

    # Actos y procesos administrativos
    "FuncionFiscalizadora",
    "FuncionRegistral",
    "SancionAdministrativa",
    "RecursoAdministrativo",
    "InspeccionAuditoria",
]

_CANONICOS: dict[str, str] = {
    "ASOCIACIONES_CIVILES":                "ASOCIACION_CIVIL",
    "FUNDACIONES":                         "FUNDACION",
    "DIRECTORES":                          "DIRECTOR",
    "SINDICOS":                            "SINDICO",
    "ADMINISTRADORES":                     "ADMINISTRADOR",
    "SOCIEDADES_POR_ACCIONES":             "SOCIEDAD_POR_ACCIONES",
    "INSPECCION_GENERAL":                  "INSPECCION_GENERAL_DE_JUSTICIA",
    "IGJ":                                 "INSPECCION_GENERAL_DE_JUSTICIA",
}

_ETIQUETAS_VALIDAS  = set(entidades_permitidas) | {"Articulo"}
_RELACIONES_VALIDAS = set(RELACIONES_PERMITIDAS)

# --- 2. CONFIGURACIÓN E INICIALIZACIÓN ---
os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
_log_file = os.path.join(BASE_DIR, "logs", f"22315_extract_{time.strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("22315")

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
    """Crea el nodo Norma para Ley_22315 y establece los vínculos con las normas
    que reglamenta (Ley_19550 y Ley_27349)."""
    with db_driver.session() as session:
        # Nodo raíz de la ley
        session.run("""
            MERGE (n:Norma {id: 'Ley_22315'})
            SET n.numero        = '22.315',
                n.titulo        = 'Ley Orgánica de la Inspección General de Justicia',
                n.fecha_sancion = '31/10/1980',
                n.jurisdiccion  = 'Ciudad Autónoma de Buenos Aires',
                n.tipo          = 'Ley',
                n.rama          = ['societario', 'civil'],
                n.vigente       = true,
                n.modificada    = true
        """)

        # Ley 22315 REGLAMENTA la aplicación de la LSC por parte de la IGJ
        session.run("""
            MATCH (n22315:Norma {id: 'Ley_22315'})
            MATCH (n19550:Norma {id: 'Ley_19550'})
            MERGE (n22315)-[:REGLAMENTA]->(n19550)
        """)

        # Ley 22315 REGLAMENTA también la aplicación de la Ley 27349 (SAS)
        session.run("""
            MATCH (n22315:Norma {id: 'Ley_22315'})
            MATCH (n27349:Norma {id: 'Ley_27349'})
            MERGE (n22315)-[:REGLAMENTA]->(n27349)
        """)

        # Nodo de entidad para la IGJ, vinculado como autoridad
        session.run("""
            MERGE (igj:InspeccionGeneralDeJusticia {id: 'INSPECCION_GENERAL_DE_JUSTICIA'})
            SET igj.titulo = 'Inspección General de Justicia'
        """)
        session.run("""
            MATCH (igj:InspeccionGeneralDeJusticia {id: 'INSPECCION_GENERAL_DE_JUSTICIA'})
            MATCH (n19550:Norma {id: 'Ley_19550'})
            MERGE (igj)-[:ES_AUTORIDAD_DE]->(n19550)
        """)
        session.run("""
            MATCH (igj:InspeccionGeneralDeJusticia {id: 'INSPECCION_GENERAL_DE_JUSTICIA'})
            MATCH (n27349:Norma {id: 'Ley_27349'})
            MERGE (igj)-[:ES_AUTORIDAD_DE]->(n27349)
        """)

    logger.info("Nodo madre Ley_22315 y vínculos normativos creados/verificados en Neo4j.")


def guardar_en_neo4j(grafo_extraido: GrafoLegalExtraido, db_driver, embedder):
    with db_driver.session() as session:
        # A. Insertar Nodos
        for nodo in grafo_extraido.nodos:
            vector_embedding = None
            if nodo.propiedades.texto:
                vector_embedding = embed_con_reintento(embedder, nodo.propiedades.texto)

            if nodo.etiqueta == "Articulo":
                query_nodo = """
                MERGE (n:Articulo {id: $id})
                SET n.numero    = $numero,
                    n.ubicacion = $ubicacion,
                    n.vigente   = true,
                    n.modificado = false,
                    n.texto     = $texto
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

        # B. Insertar Relaciones extraídas por el LLM
        for rel in grafo_extraido.relaciones:
            query_rel = f"""
            MATCH (a {{id: $inicio}})
            MATCH (b {{id: $fin}})
            MERGE (a)-[r:{rel.tipo}]->(b)
            """
            session.run(query_rel, inicio=rel.inicio, fin=rel.fin)

        # C. Vincular Artículos al nodo madre
        for nodo in grafo_extraido.nodos:
            if nodo.etiqueta == "Articulo":
                session.run("""
                    MATCH (norma:Norma {id: 'Ley_22315'})
                    MATCH (art {id: $art_id})
                    MERGE (norma)-[:CONTIENE]->(art)
                """, art_id=nodo.id)


crear_nodo_madre(driver)

# --- 4. LÓGICA DE PROCESAMIENTO ---
carpeta_archivos  = os.path.join(BASE_DIR, "input/normas/sociedades/Ley/articulos_22315/*.txt")
archivos_a_procesar = glob.glob(carpeta_archivos)

logger.info(f"Archivo de log: {_log_file}")
logger.info(f"Archivos encontrados: {len(archivos_a_procesar)}")

start_time     = time.time()
archivos_ok    = 0
archivos_saltados = 0
archivos_error = 0

for file_path in archivos_a_procesar:
    nombre      = os.path.basename(file_path)                         # "Articulo_7.txt"
    numero      = nombre.replace("Articulo_", "").replace(".txt", "") # "7"
    articulo_id = f"Art_{numero}_Ley_22315"

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
      "id": "Art_[Numero]_Ley_22315",
      "etiqueta": "Articulo",
      "propiedades": {{
        "numero": "[numero del artículo]",
        "titulo": null,
        "texto": null,
        "ubicacion": "CAPITULO X - ...",
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
   Ejemplo: etiqueta="InspeccionGeneralDeJusticia" → id="INSPECCION_GENERAL_DE_JUSTICIA"

2. RELACIONES — USA ÚNICAMENTE estos tipos exactos:
   {RELACIONES_PERMITIDAS}
   Si necesitas expresar algo que NO está en esa lista, NO lo incluyas.

3. SINGULAR OBLIGATORIO:
   Los IDs siempre en SINGULAR.
   "AsociacionesCiviles" = "AsociacionCivil" → id="ASOCIACION_CIVIL"
   "Fundaciones" = "Fundacion" → id="FUNDACION"
   "Administradores" = "Administrador" → id="ADMINISTRADOR"

4. NODO ARTÍCULO:
   - NO rellenes la propiedad 'texto'.
   - Extrae 'ubicacion' desde el header CAPITULO separado por ' - '.
   - ID: "Art_[Numero]_Ley_22315"

5. Norma: Ley Orgánica de la Inspección General de Justicia 22.315

TEXTO:
{texto_completo}
"""

        try:
            respuesta      = llm.invoke(prompt_extraccion)
            data           = json.loads(respuesta.content)
            grafo_resultado = GrafoLegalExtraido.model_validate(data)
            grafo_resultado = validar_grafo(
                grafo_resultado, articulo_id, _ETIQUETAS_VALIDAS, _RELACIONES_VALIDAS, _CANONICOS, logger
            )
        except Exception as e:
            archivos_error += 1
            logger.error(f"  FALLO extracción LLM: {e}")
            enviar_alerta(f"❌ Fallo extracción LLM\nArchivo: {file_path}\n\n{e}")
            continue

        # Inyectar texto original (el LLM no lo rellena)
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
