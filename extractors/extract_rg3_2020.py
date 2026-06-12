"""Pipeline de producción para ingestar artículos de la Resolución General IGJ 3/2020
en Neo4j. La RG establece los requisitos de publicación (edictos) del capital social
para SA y SRL (Ley 19550) y SAS (Ley 27349), exigiendo detallar acciones/cuotas por socio
en toda constitución o variación de capital. Modifica el art. 13 y el Anexo A3 de la
RG IGJ 6/2017 en lo referente a SAS.

Jerarquía normativa:
  Ley_19550  (SA / SRL)
  Ley_27349  (SAS)
  Ley_22315  (Ley Orgánica IGJ)
       ↑ REGLAMENTA_TRAMITES
  RG_3_2020
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
    "InspeccionGeneralDeJusticia",
    "SociedadAnonima",
    "SociedadDeResponsabilidadLimitada",
    "SociedadPorAccionesSimplificada",
    "SociedadAnonimaUnipersonal",
    "FuncionRegistral",
]

_CANONICOS: dict[str, str] = {
    "SOCIEDADES_POR_ACCIONES":                    "SOCIEDAD_ANONIMA",
    "SOCIEDADES_ANONIMAS":                        "SOCIEDAD_ANONIMA",
    "SOCIEDADES_DE_RESPONSABILIDAD_LIMITADA":     "SOCIEDAD_DE_RESPONSABILIDAD_LIMITADA",
    "SOCIEDADES_POR_ACCIONES_SIMPLIFICADAS":      "SOCIEDAD_POR_ACCIONES_SIMPLIFICADA",
    "SOCIEDADES_ANONIMAS_UNIPERSONALES":          "SOCIEDAD_ANONIMA_UNIPERSONAL",
    "SA":                                         "SOCIEDAD_ANONIMA",
    "SRL":                                        "SOCIEDAD_DE_RESPONSABILIDAD_LIMITADA",
    "SAS":                                        "SOCIEDAD_POR_ACCIONES_SIMPLIFICADA",
    "SAU":                                        "SOCIEDAD_ANONIMA_UNIPERSONAL",
    "IGJ":                                        "INSPECCION_GENERAL_DE_JUSTICIA",
    "INSPECCION_GENERAL":                         "INSPECCION_GENERAL_DE_JUSTICIA",
}

_ETIQUETAS_VALIDAS  = set(entidades_permitidas) | {"Articulo"}
_RELACIONES_VALIDAS = set(RELACIONES_PERMITIDAS)

# --- 2. CONFIGURACIÓN E INICIALIZACIÓN ---
os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
_log_file = os.path.join(BASE_DIR, "logs", f"rg3_2020_extract_{time.strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("RG_3_2020")

driver     = get_neo4j_driver()
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
            MERGE (n:Norma {id: 'RG_3_2020'})
            SET n.numero        = '3/2020',
                n.titulo        = 'Resolución General IGJ 3/2020 - Publicación de capital social en edictos de SA, SRL y SAS',
                n.fecha_sancion = '20/02/2020',
                n.jurisdiccion  = 'Ciudad Autónoma de Buenos Aires',
                n.tipo          = 'ResolucionGeneral',
                n.rama          = ['societario'],
                n.vigente       = true,
                n.modificada    = false
        """)
        for ley_id in ["Ley_22315", "Ley_19550", "Ley_27349"]:
            session.run("""
                MATCH (rg:Norma  {id: 'RG_3_2020'})
                MATCH (ley:Norma {id: $ley_id})
                MERGE (rg)-[:REGLAMENTA_TRAMITES]->(ley)
            """, ley_id=ley_id)
    logger.info("Nodo madre RG_3_2020 y vínculos normativos creados/verificados en Neo4j.")


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
                    MATCH (norma:Norma {id: 'RG_3_2020'})
                    MATCH (art {id: $art_id})
                    MERGE (norma)-[:CONTIENE]->(art)
                """, art_id=nodo.id)


crear_nodo_madre(driver)

# --- 4. LÓGICA DE PROCESAMIENTO ---
carpeta_archivos    = os.path.join(BASE_DIR, "input/normas/sociedades/RG/2020/articulos_RG3-2020/*.txt")
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
    articulo_id = f"Art_{numero}_RG_3_2020"

    if articulo_existe_en_neo4j(driver, articulo_id):
        logger.info(f"SALTADO (ya existe): {articulo_id}")
        archivos_saltados += 1
        continue

    logger.info(f"Procesando: {file_path}")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            texto_completo = f.read()

        partes = texto_completo.split("-" * 50, 1)
        texto_articulo_raw = partes[1].strip() if len(partes) > 1 else texto_completo.strip()

        prompt_extraccion = f"""
Eres un experto en derecho administrativo y societario argentino.
Devuelve ÚNICAMENTE un objeto JSON válido con esta estructura exacta, sin texto adicional:

{{
  "nodos": [
    {{
      "id": "Art_[Numero]_RG_3_2020",
      "etiqueta": "Articulo",
      "propiedades": {{
        "numero": "[numero del artículo]",
        "titulo": null,
        "texto": null,
        "ubicacion": "",
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
   Ejemplo: etiqueta="SociedadAnonima" → id="SOCIEDAD_ANONIMA"
   Ejemplo: etiqueta="SociedadPorAccionesSimplificada" → id="SOCIEDAD_POR_ACCIONES_SIMPLIFICADA"

2. RELACIONES — USA ÚNICAMENTE estos tipos exactos:
   {RELACIONES_PERMITIDAS}
   Si necesitas expresar algo que NO está en esa lista, NO lo incluyas.

3. SINGULAR OBLIGATORIO:
   Los IDs siempre en SINGULAR.

4. NODO ARTÍCULO:
   - ID: "Art_[Numero]_RG_3_2020"  (ej: "Art_1_RG_3_2020")
   - NO rellenes la propiedad 'texto' — quedará null.
   - 'ubicacion': dejar vacío (la norma no tiene estructura LIBRO/TÍTULO/CAPÍTULO).

5. Norma: Resolución General IGJ N° 3/2020. Regula los requisitos de publicación de
   capital social en edictos de constitución y variación de capital para SA y SRL
   (Ley 19550) y SAS (Ley 27349). Modifica la RG IGJ 6/2017.
   NO crees relaciones entre artículos de esta RG y artículos de otras normas.

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
