"""Regenera el resumen (Qwen) de las entidades cuyo contexto cambió en esta sesión de
trabajo: clasificación retroactiva de DTR (361 arts.), IT (59 arts.) y los 100 artículos
nuevos del Decreto 2080/80, más 3 entidades del CCyCN conectadas a mano (ResponsabilidadCivil,
AccionPreventiva, AceptacionHerencia). Reutiliza toda la lógica de generar_resumenes_entidades.py
(prompt, num_ctx dinámico, extensión objetivo, reintento de Neo4j) pero:
  - Se limita a esta lista fija de 37 entidades en vez de recorrer todo el grafo.
  - Escribe en archivos NUEVOS y separados del master (resumenes_entidades_completo.txt),
    para que el usuario los revise y los integre a mano — no pisa nada del pipeline anterior.

Resumible vía checkpoint propio, igual que el pipeline completo.
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

ENTIDADES_SESION = [
    "AnotacionPreventiva", "AnotacionProvisional", "AsientoRegistral", "BoletoDeCompraventa",
    "CaducidadRegistral", "CancelacionRegistral", "CertificacionRegistral", "Condominio",
    "ConjuntoInmobiliario", "ConsejoFederalDeRegistros", "ContratoFideicomiso",
    "DerechoRealSobreInmueble", "DocumentoRegistrable", "Dominio", "EscrituraPublica",
    "Hipoteca", "Inhibicion", "Inmueble", "Inscripcion", "Leasing", "Matricula",
    "MedidaCautelar", "PersonaJuridica", "PrioridadRegistral", "PropiedadHorizontal",
    "PublicidadRegistral", "RectificacionDeAsiento", "RegistroDeLaPropiedadInmueble",
    "ReglamentacionLocal", "Servidumbre", "TiempoCompartido", "TractoSucesivo", "Usufructo",
    "Vivienda", "ResponsabilidadCivil", "AccionPreventiva", "AceptacionHerencia",
]

DIR_SALIDA = os.path.join(BASE_DIR, "input", "entidades")
os.makedirs(DIR_SALIDA, exist_ok=True)
RUTA_RESUMENES = os.path.join(DIR_SALIDA, "resumenes_entidades_regen_sesion.txt")
RUTA_CONTEXTO = os.path.join(DIR_SALIDA, "contexto_entidades_regen_sesion.txt")
RUTA_CHECKPOINT = os.path.join(DIR_SALIDA, "_checkpoint_regen_sesion.json")

os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
_log_file = os.path.join(BASE_DIR, "logs", f"regenerar_resumenes_sesion_{time.strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(_log_file, encoding="utf-8"), logging.StreamHandler()],
    force=True,  # generar_resumenes_entidades ya configuró el root logger al importarse arriba;
                 # sin force=True este basicConfig sería un no-op y todo iría a SU log, no al nuestro.
)
logger = logging.getLogger("RegenerarResumenesSesion")


def cargar_checkpoint() -> set:
    if os.path.exists(RUTA_CHECKPOINT):
        with open(RUTA_CHECKPOINT, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def guardar_checkpoint(hechas: set):
    with open(RUTA_CHECKPOINT, "w", encoding="utf-8") as f:
        json.dump(sorted(hechas), f, ensure_ascii=False, indent=2)


def guardar_resumen(etiqueta, entidad_id, n_directos, n_adicionales, texto):
    with open(RUTA_RESUMENES, "a", encoding="utf-8") as f:
        f.write(f"ENTIDAD: {etiqueta} (id: {entidad_id}) — {n_directos} directos + {n_adicionales} por remisión\n")
        f.write("=" * 70 + "\n\n")
        f.write(texto.strip())
        f.write("\n\n")


def guardar_contexto(etiqueta, entidad_id, directos, adicionales):
    with open(RUTA_CONTEXTO, "a", encoding="utf-8") as f:
        f.write(f"ENTIDAD: {etiqueta} (id: {entidad_id}) — {len(directos)} directos + {len(adicionales)} por remisión\n")
        f.write("=" * 70 + "\n\n")
        for d in directos:
            f.write(f"[{d['art']}]\n{d['texto']}\n\n")
        for a in adicionales:
            f.write(f"[{a['art']} — remisión]\n{a['texto']}\n\n")
        f.write("-" * 70 + "\n\n")


def avisar_progreso_si_corresponde(hechas: set, entidades, eta_min=None):
    if len(hechas) % 10 == 0:
        faltan = len(entidades) - len(hechas)
        eta_txt = f"\nETA restante ≈ {eta_min:.0f} min" if eta_min is not None else ""
        enviar_alerta(
            f"⏳ Progreso resúmenes (regen sesión DTR/IT/Decreto 2080)\n"
            f"Resueltas: {len(hechas)}/{len(entidades)} | Faltan: {faltan}{eta_txt}"
        )


def main():
    hechas = cargar_checkpoint()
    pendientes = [e for e in ENTIDADES_SESION if e not in hechas]

    logger.info(f"Total entidades de esta sesión: {len(ENTIDADES_SESION)} | Ya resueltas (checkpoint): {len(hechas)} | Pendientes: {len(pendientes)}")
    logger.info(f"Resúmenes -> {RUTA_RESUMENES}")
    logger.info(f"Contexto  -> {RUTA_CONTEXTO}")

    tiempos = []
    for i, etiqueta in enumerate(pendientes, 1):
        t0 = time.time()
        try:
            entidad_id, directos, adicionales = g.reunir_contexto_con_reintento(etiqueta)

            if entidad_id is None or len(directos) == 0:
                logger.info(f"[{i}/{len(pendientes)}] SALTADA (sin artículos conectados): {etiqueta}")
                hechas.add(etiqueta)
                guardar_checkpoint(hechas)
                avisar_progreso_si_corresponde(hechas, ENTIDADES_SESION)
                continue

            logger.info(f"[{i}/{len(pendientes)}] Procesando: {etiqueta} (id={entidad_id}, {len(directos)} directos + {len(adicionales)} remisión)")

            prompt = g.armar_prompt(etiqueta, entidad_id, directos, adicionales)
            num_ctx = g.calcular_num_ctx(prompt)
            llm = ChatOllama(model=g.MODELO, temperature=0.2, num_ctx=num_ctx, reasoning=False)
            respuesta = llm.invoke(prompt)
            texto = respuesta.content

            if not texto:
                raise ValueError(f"respuesta vacía del modelo (num_ctx={num_ctx})")

            guardar_contexto(etiqueta, entidad_id, directos, adicionales)
            guardar_resumen(etiqueta, entidad_id, len(directos), len(adicionales), texto)

            hechas.add(etiqueta)
            guardar_checkpoint(hechas)

            dt = time.time() - t0
            tiempos.append(dt)
            promedio = sum(tiempos) / len(tiempos)
            restantes = len(pendientes) - i
            eta_min = (restantes * promedio) / 60
            logger.info(f"  OK ({len(texto)} caracteres, {dt:.0f}s, num_ctx={num_ctx}) | promedio {promedio:.0f}s/entidad | ETA restante ≈ {eta_min:.0f} min")

            avisar_progreso_si_corresponde(hechas, ENTIDADES_SESION, eta_min)

        except Exception as e:
            logger.error(f"  FALLO en {etiqueta}: {e}")
            enviar_alerta(f"❌ Fallo regenerando resumen (regen sesión)\nEntidad: {etiqueta}\n\n{e}")
            continue

    logger.info(f"\nProcesamiento completado. {len(hechas)}/{len(ENTIDADES_SESION)} entidades resueltas.")
    enviar_alerta(
        f"✅ Regeneración de resúmenes (sesión DTR/IT/Decreto 2080) completada.\n"
        f"Resueltas: {len(hechas)}/{len(ENTIDADES_SESION)}\n"
        f"Resúmenes: {RUTA_RESUMENES}\n"
        f"Contexto: {RUTA_CONTEXTO}"
    )


if __name__ == "__main__":
    main()
