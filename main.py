"""Script original de referencia para ingesta de la LSC en Neo4j.
NO usar en producción; usar extractors/extractLS.py en su lugar.
Diferencias con extractLS.py: usa structured_output del LLM en lugar de JSON libre,
no tiene lógica de skip para artículos ya existentes, y lee credenciales directamente
sin pasar por utils/connectors."""
from neo4j import GraphDatabase
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_ollama import ChatOllama
from dotenv import load_dotenv
import os, time, glob, requests, logging
from typing import List, Optional, cast
from pydantic import BaseModel, Field

# --- 1. MODELOS PYDANTIC ---
class PropiedadesNodo(BaseModel):
    numero: Optional[str] = Field(None, description="Número de artículo, capítulo o sección")
    titulo: Optional[str] = Field(None, description="Título o sumario del nodo")
    texto: Optional[str] = Field(None, description="Contenido textual completo (especialmente para artículos)")
    ubicacion: Optional[str] = Field(None, description="Ubicación en la ley, concatenando CAPITULO > SECCION > SUBSECCION si existe (ej: 'CAPITULO I - DISPOSICIONES GENERALES > SECCION I - De la existencia de sociedad')")
    ley_nombre: Optional[str] = Field(None, description="Nombre de la norma (ej: Código Civil)")
    ley_numero: Optional[str] = Field(None, description="Número de la ley")

class NodoLegal(BaseModel):
    id: str = Field(..., description="Identificador único (ej: 'Art_1_LGS')")
    etiqueta: str = Field(..., description="Tipo de nodo: Articulo, Capitulo, Seccion, etc.")
    propiedades: PropiedadesNodo

class RelacionLegal(BaseModel):
    inicio: str = Field(..., description="ID del nodo de origen")
    fin: str = Field(..., description="ID del nodo de destino")
    tipo: str = Field(..., description="Tipo de relación: CONTIENE, REMITE_A, EXCEPCIONA_A, etc.")

class GrafoLegalExtraido(BaseModel):
    nodos: List[NodoLegal]
    relaciones: List[RelacionLegal]

# --- 2. CONFIGURACIÓN E INICIALIZACIÓN ---
load_dotenv()

os.makedirs("./logs", exist_ok=True)
_log_file = f"./logs/LSC_{time.strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("LSC")

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")

# --- NUEVO: PRUEBA DE CONECTIVIDAD (Fail-Fast) ---
try:
    driver.verify_connectivity()
    logger.info("Conexión a Neo4j establecida correctamente.")
except Exception as e:
    logger.error("ERROR FATAL: No se pudo conectar a Neo4j. Verifica tus credenciales en el .env")
    logger.error(f"Detalle del error: {e}")
    exit() # Detiene el script inmediatamente

# LLM configurado con salida estructurada y límite alto de tokens
llm = ChatOllama(
    model="gemma4:e4b",
    temperature=0.0
)
llm_estructurado = llm.with_structured_output(GrafoLegalExtraido)

# --- 3. REGLAS ONTOLÓGICAS ---
entidades_permitidas = [
    "Norma", "Titulo", "Capitulo", "Seccion", "Articulo",
    "Jurisprudencia", "SujetoDeDerecho", "ConceptoJuridico", 
    "Organismo", "RequisitoLegal"
]

relaciones_permitidas = [
    "CONTIENE", "APLICA_A", "EXCLUYE_A", "REQUIERE_INTERVENCION_DE", 
    "EXIGE", "REMITE_A", "EXCEPCIONA_A", "MODIFICO_TEXTO_DE", 
    "DEROGA_TEXTO_DE", "INTERPRETA_A", "DECLARA_INCONSTITUCIONAL", 
    "SIENTA_PRECEDENTE_SOBRE"
]

# --- 4. FUNCIONES ---
def enviar_alerta(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram: TELEGRAM_TOKEN o TELEGRAM_CHAT_ID no están en el .env — notificación omitida.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje}, timeout=10)
        if not resp.ok:
            logger.error(f"Telegram respondió con error {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"Error enviando notificación Telegram: {e}")


def crear_nodo_madre(db_driver):
    with db_driver.session() as session:
        session.run("""
            MERGE (n:Norma {id: 'Ley_19550'})
            SET n.numero = '19.550',
                n.titulo = 'Ley General de Sociedades',
                n.fecha_sancion = '22/12/1972',
                n.vigente = true,
                n.modificada = true
        """)
    logger.info("Nodo madre Ley_19550 creado/verificado en Neo4j.")

def guardar_en_neo4j(grafo_extraido: GrafoLegalExtraido, db_driver, embedder):
    with db_driver.session() as session:
        # A. Insertar Nodos
        for nodo in grafo_extraido.nodos:
            vector_embedding = None
            if nodo.propiedades.texto:
                vector_embedding = embedder.embed_query(nodo.propiedades.texto)

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

        # B. Insertar Relaciones
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
                    MATCH (norma:Norma {id: 'Ley_19550'})
                    MATCH (art {id: $art_id})
                    MERGE (norma)-[:CONTIENE]->(art)
                """, art_id=nodo.id)

crear_nodo_madre(driver)

# --- 5. LÓGICA DE PROCESAMIENTO POR LOTES (BATCH) ---
carpeta_archivos = "./input/normas/sociedades/Ley/articulos_lsc/*.txt"
archivos_a_procesar = glob.glob(carpeta_archivos)

logger.info(f"Archivo de log: {_log_file}")
logger.info(f"Se encontraron {len(archivos_a_procesar)} archivos para procesar.")

start_time = time.time()
archivos_ok = 0
archivos_error = 0

for file_path in archivos_a_procesar:
    logger.info(f"Procesando: {file_path}")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            texto_completo = f.read()

        partes = texto_completo.split("--------------------------------------------------", 1)
        texto_articulo_raw = partes[1].strip() if len(partes) > 1 else texto_completo.strip()

        prompt_extraccion = f"""
            Eres un experto en derecho notarial y societario argentino. Tu objetivo es estructurar el texto legal provisto en un Knowledge Graph.

            REGLAS ESTRICTAS DE EXTRACCIÓN:
            - Extrae todas las entidades jurídicas relevantes. Etiquetas permitidas: {entidades_permitidas}
            - Extrae cómo se conectan. Relaciones permitidas: {relaciones_permitidas}
            - CRÍTICO - OPTIMIZACIÓN DE TOKENS: NO rellenes la propiedad 'texto' en ningún nodo, el texto se cargará directamente. Para todos los nodos usa solo el 'titulo'.
            - CRÍTICO - UBICACION: Para nodos 'Articulo', extrae la propiedad 'ubicacion' concatenando los headers CAPITULO, SECCION y SUBSECCION (si existe) separados por ' > ' (ej: 'CAPITULO I - DISPOSICIONES GENERALES > SECCION I - De la existencia de sociedad'). Si no hay headers, deja null.
            - CRÍTICO - CONTROL DE GRANULARIDAD: NO extraigas sustantivos comunes ni acciones genéricas (como "PRODUCCION", "PERSONAS", "BIENES", "INTERCAMBIO"). Limítate ÚNICAMENTE a los Sujetos de Derecho principales y Conceptos/Requisitos Registrales o Societarios clave (ej: "SOCIEDAD_ANONIMA", "INSTRUMENTO_PUBLICO", "CAPITAL_SOCIAL", "REGISTRO_PUBLICO").
            - CRÍTICO: Asegúrate de completar el esquema JSON en su totalidad.

            REGLAS DE NOMENCLATURA DE IDs (CRÍTICO PARA UNIR EL GRAFO):
            Para la propiedad 'id' de los nodos, DEBES usar estas convenciones:
            1. Artículos: "Art_[Numero]_Ley_[Numero]" (Ej: "Art_10_Ley_19550").
            2. Sujetos, Conceptos y Organismos: Usa el nombre en MAYÚSCULAS, con guiones bajos y SIN tildes (Ej: "SOCIEDAD_ANONIMA").

            CONTEXTO DE LA NORMA:
            - Nombre de la norma: Ley General de Sociedades
            - Número de la norma: 19.550

            TEXTO A ANALIZAR:
            {texto_completo}
            """

        try:
            grafo_resultado = cast(GrafoLegalExtraido, llm_estructurado.invoke(prompt_extraccion))
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
print("\n🎉 ¡Procesamiento masivo completado! Revisa tu base de datos Neo4j.")
enviar_alerta(
    f"✅ Procesamiento completado.\n"
    f"✔ OK: {archivos_ok} | ✘ Errores: {archivos_error}\n"
    f"Duración: {duracion:.2f} min."
)