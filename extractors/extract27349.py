"""Pipeline de producción para ingestar artículos de la Ley de Apoyo al Capital Emprendedor (27.349)
en Neo4j. Lee archivos .txt del directorio de entrada, invoca al LLM local (Ollama/gemma4)
con un prompt JSON libre, valida la salida contra la ontología definida, genera embeddings
con Gemini y persiste en Neo4j. Es idempotente: saltea artículos que ya existen en el grafo."""
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
    # Instrumentos, Documentos y Registros
    "EstatutoSocial",
    "InstrumentoPublico",
    "InstrumentoPrivado",
    "RegistroPublico",

    # Órganos de Gobierno y Administración
    "Administracion",
    "ReunionesSocios",

    # Roles y Sujetos
    "Socio",

    # Capital e Instrumentos Financieros
    "CapitalSocial",
    "Acciones",
    "Denominacion",
]

_CANONICOS: dict[str, str] = {
    "SOCIEDADES_POR_ACCIONES_SIMPLIFICADAS": "SOCIEDAD_POR_ACCIONES_SIMPLIFICADA",
    "SAS": "SOCIEDAD_POR_ACCIONES_SIMPLIFICADA",
    "SOCIOS": "SOCIO",
}

_ETIQUETAS_VALIDAS = set(entidades_permitidas) | {"Articulo"}
_RELACIONES_VALIDAS = set(RELACIONES_PERMITIDAS)

# --- 2. CONFIGURACIÓN E INICIALIZACIÓN ---
os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
_log_file = os.path.join(BASE_DIR, "logs", f"27349_extract_{time.strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("27349")

driver = get_neo4j_driver()
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
    with db_driver.session() as session:
        session.run("""
            MERGE (n:Norma {id: 'Ley_27349'})
            SET n.numero = '27349',
                n.titulo = 'Ley de Apoyo al Capital Emprendedor',
                n.fecha_sancion = '29/03/2017',
                n.fecha_publicacion = '12/04/2017',
                n.jurisdiccion = 'nacional',
                n.vigente = true,
                n.modificada = true
        """)
        session.run("""
            MATCH (n27349:Norma {id: 'Ley_27349'})
            MATCH (n19550:Norma {id: 'Ley_19550'})
            MERGE (n27349)-[:APLICA_SUPLETORIAMENTE]->(n19550)
        """)
        session.run("""
            MERGE (n:SociedadPorAccionesSimplificada {id: 'SOCIEDAD_POR_ACCIONES_SIMPLIFICADA'})
            SET n.titulo = 'Sociedad por Acciones Simplificada'
        """)
        session.run("""
            MATCH (sas:SociedadPorAccionesSimplificada {id: 'SOCIEDAD_POR_ACCIONES_SIMPLIFICADA'})
            MATCH (sc:SociedadComercial)
            MERGE (sas)-[:ES_TIPO_DE]->(sc)
        """)
        session.run("""
            MATCH (sas:SociedadPorAccionesSimplificada {id: 'SOCIEDAD_POR_ACCIONES_SIMPLIFICADA'})
            MATCH (srl:SociedadDeResponsabilidadLimitada)
            MERGE (srl)-[:APLICA_SUPLETORIAMENTE]->(sas)
        """)
    logger.info("Nodo madre Ley_27349 y nodo SociedadPorAccionesSimplificada creados/verificados en Neo4j.")


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
                SET n.numero = $numero,
                    n.ubicacion = $ubicacion,
                    n.vigente = true,
                    n.modificado = false,
                    n.texto = $texto
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
                SET n.numero = $numero,
                    n.titulo = $titulo,
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

        # C. Vincular Artículos al nodo madre y a SociedadPorAccionesSimplificada
        for nodo in grafo_extraido.nodos:
            if nodo.etiqueta == "Articulo":
                session.run("""
                    MATCH (norma:Norma {id: 'Ley_27349'})
                    MATCH (art {id: $art_id})
                    MERGE (norma)-[:CONTIENE]->(art)
                """, art_id=nodo.id)
                session.run("""
                    MATCH (art {id: $art_id})
                    MATCH (sas:SociedadPorAccionesSimplificada {id: 'SOCIEDAD_POR_ACCIONES_SIMPLIFICADA'})
                    MERGE (art)-[:REGULA]->(sas)
                """, art_id=nodo.id)


crear_nodo_madre(driver)

# --- 4. LÓGICA DE PROCESAMIENTO ---
carpeta_archivos = os.path.join(BASE_DIR, "input/normas/sociedades/Ley/articulos_27349/*.txt")
archivos_a_procesar = glob.glob(carpeta_archivos)

logger.info(f"Archivo de log: {_log_file}")
logger.info(f"Archivos encontrados: {len(archivos_a_procesar)}")

start_time = time.time()
archivos_ok = 0
archivos_saltados = 0
archivos_error = 0

for file_path in archivos_a_procesar:
    nombre = os.path.basename(file_path)
    numero = nombre.replace("Articulo_", "").replace(".txt", "")
    articulo_id = f"Art_{numero}_Ley_27349"

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
Eres un experto en derecho notarial y societario argentino.
Devuelve ÚNICAMENTE un objeto JSON válido con esta estructura exacta, sin texto adicional:

{{
  "nodos": [
    {{
      "id": "Art_[Numero]_Ley_27349",
      "etiqueta": "Articulo",
      "propiedades": {{
        "numero": "[numero del artículo]",
        "titulo": null,
        "texto": null,
        "ubicacion": "TITULO X - ... > CAPITULO X - ...",
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
   La etiqueta del nodo ('etiqueta') debe ser el nombre PascalCase exacto de la lista.
   El ID del nodo ('id') debe ser el mismo nombre pero en MAYUSCULAS_SIN_TILDES con guiones bajos.
   PROHIBIDO: NO extraigas ningún nodo con etiqueta "SociedadPorAccionesSimplificada" ni con
   ninguna variante (SAS, SociedadSimplificada, etc.). Esa entidad se gestiona fuera del LLM.

2. RELACIONES — USA ÚNICAMENTE estos tipos exactos:
   {RELACIONES_PERMITIDAS}
   Si necesitas expresar algo que NO está en esa lista, NO lo incluyas.

3. SINGULAR OBLIGATORIO:
   Los IDs siempre en SINGULAR. "SAS" y "Sociedades por Acciones Simplificadas" son la MISMA entidad:
   id="SOCIEDAD_POR_ACCIONES_SIMPLIFICADA"

4. NODO ARTÍCULO:
   - NO rellenes la propiedad 'texto'.
   - Extrae 'ubicacion' desde los headers TITULO/CAPITULO separados por ' > '.
   - ID: "Art_[Numero]_Ley_27349"

5. Norma: Ley de Apoyo al Capital Emprendedor 27.349

TEXTO:
{texto_completo}
"""

        try:
            respuesta = llm.invoke(prompt_extraccion)
            data = json.loads(respuesta.content)
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
