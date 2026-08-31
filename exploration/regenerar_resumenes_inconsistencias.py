"""Regenera el resumen (Qwen) de las entidades cuyo contexto cambió al corregir los huecos
de vinculación registrados en `inconsistencias.md` (lotes A, B y C).

Reutiliza toda la lógica de generar_resumenes_entidades.py (prompt, num_ctx dinámico,
extensión objetivo, reintento de Neo4j, citas legibles) pero se limita a esta lista fija y
escribe en archivos nuevos, separados del master (resumenes_entidades_completo.txt), para
revisión manual antes de integrarlos con cargar_resumenes_entidades.py.

Resumible vía checkpoint propio.
"""
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "exploration"))

import json
import logging
import generar_resumenes_entidades as g
from langchain_ollama import ChatOllama
from utils.connectors import enviar_alerta

# Lote A: TractoSucesivo (+Arts. 36 y 37 Decreto 2080/80).
# Lote B: huecos huérfanos confirmados de Ley 404 y Código Penal.
# Lote C: Superficie (+Art. 2128 CCyCN).
ENTIDADES = [
    "TractoSucesivo",
    "ActaNotarial",
    "Certificado",
    "Rebelion",
    "Sedicion",
    "Superficie",
]

SUFIJO = "inconsistencias"
RUTA_RESUMENES = os.path.join(g.DIR_SALIDA, f"resumenes_entidades_{SUFIJO}.txt")
RUTA_CONTEXTO = os.path.join(g.DIR_SALIDA, f"contexto_entidades_{SUFIJO}.txt")
RUTA_CHECKPOINT = os.path.join(g.DIR_SALIDA, f"_checkpoint_{SUFIJO}.json")

_log_file = os.path.join(BASE_DIR, "logs", f"resumenes_{SUFIJO}_{time.strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(_log_file, encoding="utf-8"), logging.StreamHandler()],
    # Sin force, basicConfig no hace nada: el import de generar_resumenes_entidades ya
    # configuró el root logger y estos mensajes irían a parar al log del master.
    force=True,
)
logger = logging.getLogger("ResumenesInconsistencias")


def cargar_checkpoint() -> set:
    if os.path.exists(RUTA_CHECKPOINT):
        with open(RUTA_CHECKPOINT, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def guardar_checkpoint(hechas: set):
    with open(RUTA_CHECKPOINT, "w", encoding="utf-8") as f:
        json.dump(sorted(hechas), f, ensure_ascii=False, indent=2)


def guardar(ruta: str, cabecera: str, cuerpo: str):
    with open(ruta, "a", encoding="utf-8") as f:
        f.write(cabecera)
        f.write("=" * 70 + "\n\n")
        f.write(cuerpo)
        f.write("\n\n")


def main():
    hechas = cargar_checkpoint()
    pendientes = [e for e in ENTIDADES if e not in hechas]
    logger.info(f"Entidades: {len(ENTIDADES)} | Ya resueltas: {len(hechas)} | Pendientes: {len(pendientes)}")
    logger.info(f"Modelo: {g.MODELO}")
    logger.info(f"Resúmenes -> {RUTA_RESUMENES}")
    logger.info(f"Contexto  -> {RUTA_CONTEXTO}")

    for i, etiqueta in enumerate(pendientes, 1):
        t0 = time.time()
        try:
            entidad_id, directos, adicionales = g.reunir_contexto_con_reintento(etiqueta)
            if entidad_id is None or not directos:
                logger.info(f"[{i}/{len(pendientes)}] SALTADA (sin artículos conectados): {etiqueta}")
                hechas.add(etiqueta)
                guardar_checkpoint(hechas)
                continue

            logger.info(
                f"[{i}/{len(pendientes)}] Procesando: {etiqueta} (id={entidad_id}, "
                f"{len(directos)} directos + {len(adicionales)} remisión)"
            )

            prompt = g.armar_prompt(etiqueta, entidad_id, directos, adicionales)
            num_ctx = g.calcular_num_ctx(prompt)
            llm = ChatOllama(model=g.MODELO, temperature=0.2, num_ctx=num_ctx, reasoning=False)
            texto = llm.invoke(prompt).content
            if not texto:
                raise ValueError(f"respuesta vacía del modelo (num_ctx={num_ctx})")

            cabecera = (f"ENTIDAD: {etiqueta} (id: {entidad_id}) — "
                        f"{len(directos)} directos + {len(adicionales)} por remisión\n")
            contexto = "".join(
                f"[{g.citar(a)}]  ({a['art']})\n{a['texto']}\n\n"
                for a in directos + adicionales
            )
            guardar(RUTA_CONTEXTO, cabecera, contexto)
            guardar(RUTA_RESUMENES, cabecera, texto.strip())

            hechas.add(etiqueta)
            guardar_checkpoint(hechas)
            logger.info(f"  OK ({len(texto)} caracteres, {time.time()-t0:.0f}s, num_ctx={num_ctx})")

        except Exception as e:
            logger.error(f"  FALLO en {etiqueta}: {e}")
            enviar_alerta(f"❌ Fallo regenerando resumen (inconsistencias)\nEntidad: {etiqueta}\n\n{e}")
            continue

    logger.info(f"\nCompletado. {len(hechas)}/{len(ENTIDADES)} entidades resueltas.")
    enviar_alerta(
        f"✅ Regeneración de resúmenes (inconsistencias) completada.\n"
        f"Resueltas: {len(hechas)}/{len(ENTIDADES)}\n"
        f"Resúmenes: {RUTA_RESUMENES}"
    )


if __name__ == "__main__":
    main()
