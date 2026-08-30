"""Genera con Qwen el resumen de las 9 entidades nuevas del dominio de firma digital
(Ley 25.506) y lo carga directamente en Neo4j junto con su embedding.

Reutiliza el pipeline de `generar_resumenes_entidades.py` (contexto, prompt y num_ctx) y le
agrega el ajuste de extensión por volumen real de texto, no solo por cantidad de artículos.
A diferencia de aquel, no vuelca a archivo: escribe e.resumen y e.embedding en el nodo.
"""
import os
import re
import sys
import time
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from langchain_ollama import ChatOllama
import exploration.generar_resumenes_entidades as g
from utils.connectors import get_gemini_embeddings
from utils.extractor_base import embed_con_reintento

ENTIDADES = [
    ("FirmaDigital",                  "Firma digital"),
    ("FirmaElectronica",              "Firma electrónica"),
    ("DocumentoDigital",              "Documento digital"),
    ("CertificadoDigital",            "Certificado digital"),
    ("CertificadorLicenciado",        "Certificador licenciado"),
    ("TitularDelCertificado",         "Titular del certificado digital"),
    ("EnteLicenciante",               "Ente licenciante"),
    ("AutoridadDeAplicacion",         "Autoridad de aplicación"),
    ("InfraestructuraDeFirmaDigital", "Infraestructura de Firma Digital"),
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("ResumFirma")

_PATRON_CITA = re.compile(r'Art_(\d+)(_bis|_ter)?_([A-Za-z0-9_]+)')


def limpiar_citas(texto: str) -> str:
    def _sub(m):
        sufijo = {"_bis": " bis", "_ter": " ter"}.get(m.group(2), "")
        return f"art. {m.group(1)}{sufijo} {m.group(3).replace('_', ' ')}"
    return _PATRON_CITA.sub(_sub, texto)


def extension_por_volumen(directos, adicionales) -> str:
    chars = sum(len(d["texto"] or "") for d in directos) + \
            sum(len(a["texto"] or "") for a in adicionales)
    for tope, ext in ((3000, "300 a 500 palabras"), (8000, "800 a 1000 palabras"),
                      (20000, "1200 a 1500 palabras"), (40000, "1800 a 2200 palabras")):
        if chars <= tope:
            return ext, chars
    return "2500 a 3000 palabras", chars


def main():
    embeddings = get_gemini_embeddings()
    ok = fallos = 0

    for etiqueta, titulo in ENTIDADES:
        try:
            entidad_id, directos, adicionales = g.reunir_contexto_con_reintento(etiqueta)
            if entidad_id is None or not directos:
                logger.warning(f"SALTADA (sin artículos): {etiqueta}")
                continue

            prompt = g.armar_prompt(etiqueta, entidad_id, directos, adicionales)
            ext_vol, chars = extension_por_volumen(directos, adicionales)
            ext_cant = g.calcular_extension_objetivo(directos, adicionales)
            if ext_vol != ext_cant:
                prompt = prompt.replace(f"Extensión objetivo: {ext_cant}.",
                                        f"Extensión objetivo: {ext_vol}.")
            prompt += ('\n9. Al citar un artículo, usá SIEMPRE el formato "art. <número> '
                       '<norma>". NUNCA copies el id interno tipo "Art_5_Ley_25506".')

            num_ctx = g.calcular_num_ctx(prompt)
            t0 = time.time()
            llm = ChatOllama(model=g.MODELO, temperature=0.2, num_ctx=num_ctx, reasoning=False)
            texto = limpiar_citas(llm.invoke(prompt).content.strip())
            if not texto:
                raise ValueError("respuesta vacía del modelo")

            vector = embed_con_reintento(embeddings, texto)
            with g.driver.session() as s:
                s.run(f"""MATCH (e:`{etiqueta}` {{id:$id}})
                          SET e.titulo = $titulo, e.resumen = $texto, e.embedding = $vec""",
                      id=entidad_id, titulo=titulo, texto=texto, vec=vector)

            logger.info(f"OK {etiqueta:32} {len(directos)}+{len(adicionales)} arts, "
                        f"{chars} chars -> {len(texto.split())} palabras "
                        f"({time.time()-t0:.0f}s, num_ctx={num_ctx})")
            ok += 1
        except Exception as e:
            fallos += 1
            logger.error(f"FALLO en {etiqueta}: {e}")

    logger.info(f"\nCompletado. Cargadas: {ok} | Fallos: {fallos}")


if __name__ == "__main__":
    main()
