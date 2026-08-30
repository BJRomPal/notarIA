"""Carga en Neo4j los resúmenes de entidades de ontología compilados en
input/entidades/resumenes_entidades_completo.txt.

Para cada bloque "ENTIDAD: <etiqueta> (id: <ID>) — ..." del archivo:
  - Extrae el texto del resumen.
  - Calcula su embedding (Gemini, gemini-embedding-001) con reintentos.
  - Escribe e.resumen y e.embedding en el nodo correspondiente (MATCH por id).

No crea índice vectorial: por ahora nada consulta este embedding, se deja
solo la propiedad cruda lista para cuando se necesite.

Resumible vía checkpoint (input/entidades/_checkpoint_carga_resumenes.json),
guardado cada CHECKPOINT_CADA entidades y al finalizar/fallar.
"""
import os
import re
import sys
import time
import json
import logging
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from utils.connectors import get_neo4j_driver, get_gemini_embeddings

RUTA_ARCHIVO = os.path.join(BASE_DIR, "input", "entidades", "resumenes_entidades_completo.txt")
RUTA_CHECKPOINT = os.path.join(BASE_DIR, "input", "entidades", "_checkpoint_carga_resumenes.json")
CHECKPOINT_CADA = 50
REINTENTOS_EMBEDDING = 4
BACKOFF_SEGUNDOS = [5, 15, 45, 90]

# Correcciones puntuales: el id escrito en el archivo no coincide con el id
# real en el grafo (typo, o entidad renombrada/dividida después de generado
# el resumen). Se identifican por (id_en_archivo, etiqueta) para no confundir
# casos como PRESCRIPCION, que aparece dos veces con distinta etiqueta.
CORRECCIONES_ID = {
    ("BalanceGeneral", "BalanceGeneral"): "BALANCE_GENERAL",
    ("DESISTIMIENTO_VOLUNTARIO", "DesistimientoDelito"): "DESISTIMIENTO_DELITO",
    ("PRESCRIPCION", "PrescripcionCivil"): "PRESCRIPCION_CIVIL",
    ("PRESCRIPCION", "PrescripcionPenal"): "PRESCRIPCION_PENAL",
}

os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
_log_file = os.path.join(BASE_DIR, "logs", f"cargar_resumenes_entidades_{time.strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(_log_file, encoding="utf-8"), logging.StreamHandler()],
)
logger = logging.getLogger("CargarResumenesEntidades")

PATRON_HEADER = re.compile(
    r'^ENTIDAD:\s*(?P<etiqueta>.*?)\s*\(id:\s*(?P<id>[A-Za-z0-9_]+)\)\s*—.*$',
    re.MULTILINE,
)


def parsear_archivo():
    with open(RUTA_ARCHIVO, encoding="utf-8") as f:
        contenido = f.read()

    matches = list(PATRON_HEADER.finditer(contenido))
    bloques = []
    for i, m in enumerate(matches):
        etiqueta = m.group("etiqueta").strip()
        id_archivo = m.group("id")

        # separador "="*N justo despues del header
        resto = contenido[m.end():]
        sep_match = re.match(r'\s*=+\s*\n', resto)
        inicio_texto = m.end() + (sep_match.end() if sep_match else 0)

        fin_texto = matches[i + 1].start() if i + 1 < len(matches) else len(contenido)
        texto = contenido[inicio_texto:fin_texto].strip()

        entidad_id = CORRECCIONES_ID.get((id_archivo, etiqueta), id_archivo)
        bloques.append({"etiqueta": etiqueta, "id_archivo": id_archivo, "id": entidad_id, "texto": texto})

    return bloques


def deduplicar(bloques):
    """Si un id aparece mas de una vez (entidad regenerada varias veces),
    se queda con la ULTIMA ocurrencia (la mas reciente en el archivo)."""
    por_id = {}
    for b in bloques:
        por_id[b["id"]] = b
    return list(por_id.values())


def cargar_checkpoint() -> set:
    if os.path.exists(RUTA_CHECKPOINT):
        with open(RUTA_CHECKPOINT, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def guardar_checkpoint(hechas: set):
    with open(RUTA_CHECKPOINT, "w", encoding="utf-8") as f:
        json.dump(sorted(hechas), f, ensure_ascii=False, indent=2)


def embed_con_reintento(embeddings, texto, etiqueta):
    for intento in range(1, REINTENTOS_EMBEDDING + 1):
        try:
            return embeddings.embed_query(texto)
        except Exception as e:
            if intento == REINTENTOS_EMBEDDING:
                raise
            espera = BACKOFF_SEGUNDOS[intento - 1]
            logger.warning(f"  Embedding falló para {etiqueta} (intento {intento}/{REINTENTOS_EMBEDDING}): {e}. Reintentando en {espera}s...")
            time.sleep(espera)


def main():
    bloques = parsear_archivo()
    logger.info(f"Bloques ENTIDAD encontrados en el archivo: {len(bloques)}")

    bloques = deduplicar(bloques)
    logger.info(f"Entidades únicas tras deduplicar (última ocurrencia gana): {len(bloques)}")

    driver = get_neo4j_driver()
    embeddings = get_gemini_embeddings()

    # Verificar existencia en el grafo antes de arrancar, para no descubrir
    # ids inválidos a mitad de la corrida.
    validos, invalidos = [], []
    with driver.session() as session:
        for b in bloques:
            res = session.run(
                "MATCH (e {id: $id}) WHERE NOT e:Norma AND NOT e:Articulo AND NOT e:VersionHistorica RETURN e.id AS id",
                id=b["id"],
            ).single()
            (validos if res else invalidos).append(b)

    if invalidos:
        logger.warning(f"IDs sin nodo correspondiente en el grafo (se omiten): {len(invalidos)}")
        for b in invalidos:
            logger.warning(f"  - etiqueta={b['etiqueta']!r} id_archivo={b['id_archivo']!r} id_resuelto={b['id']!r}")

    logger.info(f"Entidades a cargar: {len(validos)}")

    hechas = cargar_checkpoint()
    pendientes = [b for b in validos if b["id"] not in hechas]
    logger.info(f"Ya cargadas (checkpoint previo): {len(hechas & {b['id'] for b in validos})} | Pendientes: {len(pendientes)}")

    fallidas = []
    tiempos = []

    with driver.session() as session:
        for i, b in enumerate(pendientes, 1):
            t0 = time.time()
            try:
                vector = embed_con_reintento(embeddings, b["texto"], b["etiqueta"])
                session.run(
                    "MATCH (e {id: $id}) SET e.resumen = $texto, e.embedding = $vector",
                    id=b["id"], texto=b["texto"], vector=vector,
                )
                hechas.add(b["id"])

                dt = time.time() - t0
                tiempos.append(dt)
                promedio = sum(tiempos) / len(tiempos)
                restantes = len(pendientes) - i
                eta_min = (restantes * promedio) / 60
                logger.info(f"[{i}/{len(pendientes)}] OK {b['etiqueta']} (id={b['id']}, {len(b['texto'])} chars, {dt:.1f}s) | ETA restante ≈ {eta_min:.0f} min")

            except Exception as e:
                logger.error(f"[{i}/{len(pendientes)}] FALLO {b['etiqueta']} (id={b['id']}): {e}")
                fallidas.append(b)
                continue

            if i % CHECKPOINT_CADA == 0:
                guardar_checkpoint(hechas)
                logger.info(f"--- checkpoint guardado en {i}/{len(pendientes)} ({len(hechas)} entidades totales cargadas) ---")

    guardar_checkpoint(hechas)

    logger.info(f"Proceso terminado. Cargadas OK: {len(hechas)}/{len(validos)}. Fallidas: {len(fallidas)}. IDs sin nodo: {len(invalidos)}.")
    if fallidas:
        logger.error("Entidades que fallaron tras agotar reintentos:")
        for b in fallidas:
            logger.error(f"  - {b['etiqueta']} (id={b['id']})")


if __name__ == "__main__":
    main()
