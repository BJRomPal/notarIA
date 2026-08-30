"""Regenera el resumen (Qwen) de las 64 entidades cuyo contexto cambió por dos trabajos
recientes: la conexión de los 137 artículos huérfanos del CCyCN, y la clasificación
retroactiva de los 126 artículos sin entidad de la RG 15/2024 (IGJ). Reutiliza toda la
lógica de generar_resumenes_entidades.py (prompt, num_ctx dinámico, extensión objetivo,
reintento de Neo4j, limpieza de citas con guion bajo) pero:
  - Se limita a esta lista fija de 64 entidades en vez de recorrer todo el grafo.
  - Escribe en archivos NUEVOS y separados del master, para que el usuario los revise y
    los integre a mano.

Resumible vía checkpoint propio.
"""
import os
import re
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
    "ActoJuridico", "Administrador", "AsociacionCivil", "Ausencia", "BienDelDominioPublico",
    "Capacidad", "ComisionNacionalDeValores", "ConcursoYQuiebra", "ContratoAsociativo",
    "ContratoFideicomiso", "CorredorNoInmobiliario", "Cosa", "Curatela",
    "DenunciaAdministrativa", "DerechosDeIncidenciaColectiva", "DerechosPersonalisimos",
    "Director", "Domicilio", "EmpresaBinacional", "Empresario", "EstatutoSocial",
    "FondoDeComercio", "FuncionFiscalizadora", "FuncionRegistral", "Fundacion", "Gerente",
    "InspeccionGeneralDeJusticia", "InspectorGeneral", "InstrumentoPrivado",
    "InstrumentoPublico", "Locacion", "Martillero", "MedidaCautelar", "Nombre", "Obligacion",
    "ObligacionAlternativa", "ObligacionDisyuntiva", "ObligacionDivisible",
    "ObligacionFacultativa", "ObligacionIndivisible", "ObligacionMancomunada", "Patrimonio",
    "PersonaHumana", "PersonaJuridica", "PresuncionDeFallecimiento", "PropiedadHorizontal",
    "RegimenContable", "RegistroEstadoCivilYCapacidadDeLasPersonas", "RegistroPublicoDeComercio",
    "RubricaDeLibros", "SancionAdministrativa", "SimpleAsociacion", "Sindico",
    "SociedadAnonima", "SociedadColectiva", "SociedadConstituidaEnElExtranjero",
    "SociedadDeResponsabilidadLimitada", "SociedadPorAcciones", "SociedadPorAccionesSimplificada",
    "Superficie", "TransmisionDeDerechos", "Tutela", "VicioDeLaVoluntad", "Vivienda",
]

DIR_SALIDA = os.path.join(BASE_DIR, "input", "entidades")
os.makedirs(DIR_SALIDA, exist_ok=True)
RUTA_RESUMENES = os.path.join(DIR_SALIDA, "resumenes_entidades_ccycn_rg15.txt")
RUTA_CONTEXTO = os.path.join(DIR_SALIDA, "contexto_entidades_ccycn_rg15.txt")
RUTA_CHECKPOINT = os.path.join(DIR_SALIDA, "_checkpoint_ccycn_rg15.json")

os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
_log_file = os.path.join(BASE_DIR, "logs", f"regenerar_resumenes_ccycn_rg15_{time.strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(_log_file, encoding="utf-8"), logging.StreamHandler()],
    force=True,
)
logger = logging.getLogger("RegenerarResumenesCCyCNRG15")

_PATRON_CITA = re.compile(
    r"Art_(?P<numero>\d+)(?P<sufijo>_bis|_ter|_quater|_quinquies)?_(?P<norma>CCyCN|Ley_\d+|RG_\d+_\d+|Decreto_\d+_\d+)"
)


def _limpiar_cita(m):
    numero = m.group("numero")
    sufijo = (m.group("sufijo") or "").replace("_", " ")
    norma = m.group("norma")
    if norma == "CCyCN":
        norma_fmt = "CCyCN"
    elif norma.startswith("Ley_"):
        norma_fmt = "Ley " + norma[len("Ley_"):]
    elif norma.startswith("RG_"):
        partes = norma[len("RG_"):].split("_")
        norma_fmt = "RG " + "/".join(partes) if len(partes) == 2 else "RG " + norma[len("RG_"):].replace("_", "/")
    elif norma.startswith("Decreto_"):
        partes = norma[len("Decreto_"):].split("_")
        norma_fmt = "Decreto " + "/".join(partes) if len(partes) == 2 else "Decreto " + norma[len("Decreto_"):].replace("_", "/")
    else:
        norma_fmt = norma.replace("_", " ")
    return f"art. {numero}{sufijo} {norma_fmt}"


def limpiar_citas(texto: str) -> str:
    return _PATRON_CITA.sub(_limpiar_cita, texto)


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
            f"⏳ Progreso resúmenes (CCyCN + RG 15/2024)\n"
            f"Resueltas: {len(hechas)}/{len(entidades)} | Faltan: {faltan}{eta_txt}"
        )


def main():
    hechas = cargar_checkpoint()
    pendientes = [e for e in ENTIDADES_SESION if e not in hechas]

    logger.info(f"Total entidades: {len(ENTIDADES_SESION)} | Ya resueltas (checkpoint): {len(hechas)} | Pendientes: {len(pendientes)}")
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
            prompt += (
                "\n9. Al citar un artículo, usá SIEMPRE el formato \"art. <número> <norma>\" "
                "con espacios (ej: \"art. 33 RG 15/2024\", \"art. 168 CCyCN\"). NUNCA copies "
                "el id interno tal cual (ej: \"Art_33_RG_15_2024\"): no uses guiones bajos ni "
                "el prefijo \"Art_\" en ninguna cita.\n"
            )
            num_ctx = g.calcular_num_ctx(prompt)
            llm = ChatOllama(model=g.MODELO, temperature=0.2, num_ctx=num_ctx, reasoning=False)
            respuesta = llm.invoke(prompt)
            texto = respuesta.content

            if not texto:
                raise ValueError(f"respuesta vacía del modelo (num_ctx={num_ctx})")

            texto = limpiar_citas(texto)

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
            enviar_alerta(f"❌ Fallo regenerando resumen (CCyCN + RG 15/2024)\nEntidad: {etiqueta}\n\n{e}")
            continue

    logger.info(f"\nProcesamiento completado. {len(hechas)}/{len(ENTIDADES_SESION)} entidades resueltas.")
    enviar_alerta(
        f"✅ Regeneración de resúmenes (CCyCN + RG 15/2024) completada.\n"
        f"Resueltas: {len(hechas)}/{len(ENTIDADES_SESION)}\n"
        f"Resúmenes: {RUTA_RESUMENES}\n"
        f"Contexto: {RUTA_CONTEXTO}"
    )


if __name__ == "__main__":
    main()
