"""Pipeline de producción para ingestar artículos de la Ley General de Sociedades (19.550)
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
    # Tipos Societarios
    "SociedadAnonima",
    "SociedadAnonimaUnipersonal",
    "SociedadDeResponsabilidadLimitada",
    "SociedadColectiva",
    "SociedadEnComanditaSimple",
    "SociedadEnComanditaPorAcciones",
    "SociedadDeCapitalEIndustria",
    "SociedadConstituidaEnElExtranjero",
    "SociedadConParticipacionEstatal",
    "SociedadPorAcciones",

    # Instrumentos, Documentos y Registros
    "EstatutoSocial",
    "ContratoSocial",
    "InstrumentoPublico",
    "InstrumentoPrivado",
    "RegistroPublico",
    "LegajoSocietario",
    "ActaDeAsamblea",
    "ActaDeDirectorio",
    "LibroDeRegistroDeAcciones",
    "BalanceGeneral",
    "EstadoDeResultados",

    # Órganos de Gobierno, Administración y Fiscalización
    "AsambleaOrdinaria",
    "AsambleaExtraordinaria",
    "AsambleaConstitutiva",
    "Directorio",
    "Gerencia",
    "ComisionFiscalizadora",
    "Sindicatura",
    "ConsejoDeVigilancia",

    # Roles y Sujetos
    "Socio",
    "Accionista",
    "Director",
    "Gerente",
    "Sindico",
    "Liquidador",
    "Fundador",
    "Promotor",
    "RepresentanteLegal",

    # Capital, Aportes y Participaciones
    "CapitalSocial",
    "Accion",
    "AccionOrdinaria",
    "AccionPreferida",
    "CuotaSocial",
    "ParteDeInteres",
    "AporteEnDinero",
    "AporteEnEspecie",
    "PrestacionAccesoria",
    "Dividendo",
    "ReservaLegal",
    "BonoDeGoce",
    "BonoDeParticipacion",
    "Debenture",

    # Procesos Societarios y Reorganización
    "ConstitucionSocietaria",
    "InscripcionRegistral",
    "AumentoDeCapital",
    "ReduccionDeCapital",
    "Transformacion",
    "Fusion",
    "Escision",
    "Disolucion",
    "Liquidacion",
    "IntervencionJudicial",
    "DerechoDeReceso",
    "DerechoDePreferencia",
    "OfertaPublica"
]

# Mapa de IDs plurales o variantes → ID canónico singular en MAYUSCULAS
_CANONICOS: dict[str, str] = {
    # Tipos societarios
    "SOCIEDADES_ANONIMAS":                    "SOCIEDAD_ANONIMA",
    "SOCIEDADES_ANONIMAS_UNIPERSONALES":      "SOCIEDAD_ANONIMA_UNIPERSONAL",
    "SOCIEDADES_DE_RESPONSABILIDAD_LIMITADA": "SOCIEDAD_DE_RESPONSABILIDAD_LIMITADA",
    "SOCIEDADES_COLECTIVAS":                  "SOCIEDAD_COLECTIVA",
    "SOCIEDADES_EN_COMANDITA_SIMPLE":         "SOCIEDAD_EN_COMANDITA_SIMPLE",
    "SOCIEDADES_EN_COMANDITA_POR_ACCIONES":   "SOCIEDAD_EN_COMANDITA_POR_ACCIONES",
    "SOCIEDADES_POR_ACCIONES":               "SOCIEDAD_POR_ACCIONES",
    # Roles
    "SOCIOS":       "SOCIO",
    "ACCIONISTAS":  "ACCIONISTA",
    "DIRECTORES":   "DIRECTOR",
    "GERENTES":     "GERENTE",
    "SINDICOS":     "SINDICO",
    "LIQUIDADORES": "LIQUIDADOR",
    "FUNDADORES":   "FUNDADOR",
    "PROMOTORES":   "PROMOTOR",
    # Capital e instrumentos
    "ACCIONES":        "ACCION",
    "CUOTAS_SOCIALES": "CUOTA_SOCIAL",
    "PARTES_DE_INTERES": "PARTE_DE_INTERES",
    "DIVIDENDOS":      "DIVIDENDO",
}

_ETIQUETAS_VALIDAS = set(entidades_permitidas) | {"Articulo"}
_RELACIONES_VALIDAS = set(RELACIONES_PERMITIDAS)

# --- 2. CONFIGURACIÓN E INICIALIZACIÓN ---
os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
_log_file = os.path.join(BASE_DIR, "logs", f"LSC_extract_{time.strftime('%Y%m%d_%H%M%S')}.log")
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

# Crea (o verifica con MERGE) el nodo raíz :Norma {id: 'Ley_19550'}.
# Sin este nodo la relación CONTIENE de los artículos queda huérfana y el grafo desconectado.
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


# Persiste en Neo4j el grafo extraído por el LLM en tres fases dentro de una sola sesión:
# A) upsert de nodos (MERGE + SET; genera embedding solo para Articulos),
# B) upsert de relaciones entre nodos ya existentes,
# C) vincula cada Articulo al nodo madre Ley_19550 con la relación CONTIENE.
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

# --- 4. LÓGICA DE PROCESAMIENTO ---
carpeta_archivos = os.path.join(BASE_DIR, "input/normas/sociedades/Ley/articulos_lsc/*.txt")
archivos_a_procesar = glob.glob(carpeta_archivos)

logger.info(f"Archivo de log: {_log_file}")
logger.info(f"Archivos encontrados: {len(archivos_a_procesar)}")

start_time = time.time()
archivos_ok = 0
archivos_saltados = 0
archivos_error = 0

for file_path in archivos_a_procesar:
    # Derivar el ID del artículo desde el nombre del archivo
    nombre = os.path.basename(file_path)                        # "Articulo_41.txt"
    numero = nombre.replace("Articulo_", "").replace(".txt", "") # "41"
    articulo_id = f"Art_{numero}_Ley_19550"

    if articulo_existe_en_neo4j(driver, articulo_id):
        logger.info(f"SALTADO (ya existe): {articulo_id}")
        archivos_saltados += 1
        continue

    logger.info(f"Procesando: {file_path}")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            texto_completo = f.read()

        # Los archivos .txt tienen una cabecera de contexto jerárquico separada del artículo
        # por una línea de guiones; el texto del artículo es todo lo que sigue al separador.
        partes = texto_completo.split("--------------------------------------------------", 1)
        texto_articulo_raw = partes[1].strip() if len(partes) > 1 else texto_completo.strip()

        prompt_extraccion = f"""
Eres un experto en derecho notarial y societario argentino.
Devuelve ÚNICAMENTE un objeto JSON válido con esta estructura exacta, sin texto adicional:

{{
  "nodos": [
    {{
      "id": "Art_[Numero]_Ley_19550",
      "etiqueta": "Articulo",
      "propiedades": {{
        "numero": "[numero del artículo]",
        "titulo": null,
        "texto": null,
        "ubicacion": "CAPITULO X - ... > SECCION X - ...",
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
   Ejemplo: etiqueta="SociedadAnonima" → id="SOCIEDAD_ANONIMA"

2. RELACIONES — USA ÚNICAMENTE estos tipos exactos:
   {RELACIONES_PERMITIDAS}
   Si necesitas expresar algo que NO está en esa lista, NO lo incluyas.

3. SINGULAR OBLIGATORIO:
   Los IDs siempre en SINGULAR. Plural y singular son la MISMA entidad.
   "SociedadesAnonimas" = "SociedadAnonima" → id="SOCIEDAD_ANONIMA"
   "Directores" = "Director" → id="DIRECTOR"
   "Accionistas" = "Accionista" → id="ACCIONISTA"
   "Gerentes" = "Gerente" → id="GERENTE"
   Regla general: si ves un plural, usa siempre el SINGULAR canónico.

4. JERARQUÍA SOCIETARIA — CRÍTICO:
   SociedadAnonima y SociedadEnComanditaPorAcciones son ambas "sociedades por acciones".
   Si el artículo regula algo para "sociedades por acciones" en general, crea relaciones
   con AMBAS entidades: SOCIEDAD_ANONIMA y SOCIEDAD_EN_COMANDITA_POR_ACCIONES.

5. NODO ARTÍCULO:
   - NO rellenes la propiedad 'texto'.
   - Extrae 'ubicacion' desde los headers CAPITULO/SECCION/SUBSECCION separados por ' > '.
   - ID: "Art_[Numero]_Ley_19550"

6. Norma: Ley General de Sociedades 19.550

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

        # El LLM no rellena 'texto' (ver prompt); se inyecta aquí desde el archivo original
        # para preservar el texto íntegro sin alteraciones del modelo.
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
