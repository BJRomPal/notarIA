"""Propone con Qwen a qué entidad de ontología debería conectarse cada artículo huérfano.

Un artículo sin ninguna entidad conectada es invisible para la vía ontológica del RAG: solo
se lo puede alcanzar por búsqueda vectorial. Este script recorre los artículos vigentes en
esa situación y le pide al modelo una recomendación, respetando la ontología cerrada: se le
pasan las etiquetas y relaciones existentes y se descarta por validación dura todo lo que
proponga fuera de esas listas.

Los artículos derogados quedan afuera: no son derecho vigente y no necesitan entidad.

NO escribe nada en Neo4j. Vuelca un .txt a input/entidades/ para revisión manual; las
vinculaciones que se acepten se crean aparte y después se regenera el resumen de la entidad
afectada con regenerar_resumen_entidad.py.

Resumible: si se corta, una nueva corrida retoma desde el checkpoint sin repetir ni pisar.

Uso:
    python exploration/recomendar_entidad_articulos.py [limite]
"""
import json
import os
import re
import sys
import time
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "exploration"))

import generar_resumenes_entidades as g
from langchain_ollama import ChatOllama
from utils.connectors import get_neo4j_driver, enviar_alerta
from utils.extractor_base import RELACIONES_PERMITIDAS

SUFIJO = time.strftime("%Y%m%d")
RUTA_SALIDA = os.path.join(g.DIR_SALIDA, f"articulos_sin_entidad_{SUFIJO}.txt")
RUTA_CHECKPOINT = os.path.join(g.DIR_SALIDA, f"_checkpoint_sin_entidad_{SUFIJO}.json")

_log = os.path.join(BASE_DIR, "logs", f"recomendar_entidad_{time.strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(_log, encoding="utf-8"), logging.StreamHandler()],
    force=True,
)
logger = logging.getLogger("RecomendarEntidad")
logging.getLogger("httpx").setLevel(logging.WARNING)

driver = get_neo4j_driver()

HUERFANOS = """
MATCH (norma:Norma)-[:CONTIENE]->(a:Articulo)
WHERE a.vigente = true
  AND NOT EXISTS { (a)-[]-(e) WHERE NOT e:Norma AND NOT e:Articulo AND NOT e:VersionHistorica }
RETURN a.id AS art, a.numero AS numero, a.texto AS texto, a.ubicacion AS ubicacion,
       norma.tipo AS tipo, norma.numero AS norma_numero,
       norma.titulo AS norma_titulo, norma.id AS norma_id
ORDER BY norma.id, toInteger(a.numero)
"""

ETIQUETAS = """
MATCH (n) WHERE NOT n:Articulo AND NOT n:Norma
            AND NOT n:VersionHistorica AND NOT n:Jurisprudencia
RETURN DISTINCT labels(n)[0] AS label ORDER BY label
"""


def cargar_checkpoint() -> set:
    if os.path.exists(RUTA_CHECKPOINT):
        with open(RUTA_CHECKPOINT, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def guardar_checkpoint(hechos: set):
    with open(RUTA_CHECKPOINT, "w", encoding="utf-8") as f:
        json.dump(sorted(hechos), f, ensure_ascii=False, indent=2)


def armar_prompt(art: dict, etiquetas: list[str]) -> str:
    return f"""Sos un jurista argentino experto en derecho notarial, civil, societario, registral, penal y tributario.

En una base de conocimiento jurídico, cada artículo se conecta con las entidades jurídicas que trata. Este artículo quedó sin ninguna conexión y hay que decidir cuál le corresponde.

ARTÍCULO: {g.citar(art)}
UBICACIÓN EN LA NORMA: {art.get('ubicacion') or '(sin ubicación)'}

TEXTO:
{art['texto']}

ENTIDADES DISPONIBLES (lista cerrada, no podés inventar ninguna):
{' | '.join(etiquetas)}

TIPOS DE RELACIÓN DISPONIBLES (lista cerrada):
{' | '.join(RELACIONES_PERMITIDAS)}

TAREA: Indicá a qué entidad debería conectarse este artículo y con qué relación.

Reglas estrictas:
1. La entidad TIENE que estar escrita exactamente como figura en la lista de entidades disponibles. Si no está en la lista, no la propongas.
2. La relación TIENE que estar en la lista de tipos de relación.
3. Elegí la entidad que el artículo realmente regula, define o menciona, no una temáticamente cercana. Si el artículo trata un instituto que no está en la lista, devolvé "NINGUNA".
4. Muchos artículos legítimamente no corresponden a ninguna entidad: cláusulas de derogación, de vigencia, de forma, remisiones puras, encabezados. Para esos devolvé "NINGUNA" sin forzar.
5. Podés proponer una segunda entidad solo si el artículo trata claramente dos institutos distintos.

Devolvé SOLO un JSON con este formato exacto, sin texto adicional:
{{"entidad": "NombreDeLaEntidad o NINGUNA", "relacion": "TIPO_DE_RELACION o null", "entidad_secundaria": "NombreDeLaEntidad o null", "confianza": "alta|media|baja", "motivo": "una línea explicando por qué"}}"""


def parsear(contenido: str) -> dict | None:
    texto = contenido.strip()
    if "```" in texto:
        partes = texto.split("```")
        texto = partes[1] if len(partes) > 1 else texto
        texto = re.sub(r"^json\s*", "", texto.strip())
    if (m := re.search(r"\{.*\}", texto, re.DOTALL)):
        texto = m.group(0)
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        return None


def validar(data: dict, etiquetas: set) -> tuple[str, str | None, str | None, str]:
    """Aplica la ontología cerrada: lo que no esté en las listas se descarta."""
    entidad = str(data.get("entidad") or "NINGUNA").strip()
    relacion = data.get("relacion")
    secundaria = data.get("entidad_secundaria")
    nota = ""

    if entidad.upper() == "NINGUNA" or entidad not in etiquetas:
        if entidad.upper() != "NINGUNA":
            nota = f"  [descartada: '{entidad}' no está en la ontología]"
        entidad, relacion = "NINGUNA", None

    if relacion and relacion not in RELACIONES_PERMITIDAS:
        nota += f"  [relación '{relacion}' no permitida, descartada]"
        relacion = None

    if secundaria and secundaria not in etiquetas:
        secundaria = None

    return entidad, relacion, secundaria, nota


def main():
    limite = int(sys.argv[1]) if len(sys.argv) > 1 else None

    with driver.session() as s:
        articulos = [dict(r) for r in s.run(HUERFANOS)]
        etiquetas = [r["label"] for r in s.run(ETIQUETAS)]
    validas = set(etiquetas)

    hechos = cargar_checkpoint()
    pendientes = [a for a in articulos if a["art"] not in hechos]
    if limite:
        pendientes = pendientes[:limite]

    logger.info(f"Artículos vigentes sin entidad: {len(articulos)} | "
                f"ya procesados: {len(hechos)} | a procesar ahora: {len(pendientes)}")
    logger.info(f"Entidades disponibles: {len(etiquetas)} | modelo: {g.MODELO}")
    logger.info(f"Salida -> {RUTA_SALIDA}")
    enviar_alerta(f"🔎 Recomendación de entidades para artículos huérfanos\n"
                  f"A procesar: {len(pendientes)} artículos")

    conteo = {"con_recomendacion": 0, "ninguna": 0, "fallidos": 0}
    tiempos = []

    for i, art in enumerate(pendientes, 1):
        t0 = time.time()
        try:
            prompt = armar_prompt(art, etiquetas)
            num_ctx = g.calcular_num_ctx(prompt)
            respuesta = ChatOllama(model=g.MODELO, temperature=0.1, num_ctx=num_ctx,
                                   reasoning=False).invoke(prompt).content
            data = parsear(str(respuesta))
            if data is None:
                raise ValueError("el modelo no devolvió un JSON parseable")

            entidad, relacion, secundaria, nota = validar(data, validas)
            if entidad == "NINGUNA":
                conteo["ninguna"] += 1
            else:
                conteo["con_recomendacion"] += 1

            with open(RUTA_SALIDA, "a", encoding="utf-8") as f:
                f.write(f"ARTICULO: {g.citar(art)}  ({art['art']})\n")
                f.write(f"NORMA: {art.get('norma_titulo') or art['norma_id']}\n")
                f.write(f"UBICACION: {art.get('ubicacion') or '(sin ubicación)'}\n")
                f.write("=" * 70 + "\n\n")
                f.write(f"{art['texto'].strip()}\n\n")
                f.write("RECOMENDACION:\n")
                f.write(f"  entidad:    {entidad}\n")
                f.write(f"  relacion:   {relacion or '-'}\n")
                if secundaria:
                    f.write(f"  secundaria: {secundaria}\n")
                f.write(f"  confianza:  {data.get('confianza', '?')}\n")
                f.write(f"  motivo:     {data.get('motivo', '')}\n")
                if nota:
                    f.write(f"  nota:      {nota.strip()}\n")
                f.write("-" * 70 + "\n\n")

            hechos.add(art["art"])
            guardar_checkpoint(hechos)

            tiempos.append(time.time() - t0)
            promedio = sum(tiempos) / len(tiempos)
            eta = (len(pendientes) - i) * promedio / 60
            logger.info(f"[{i}/{len(pendientes)}] {g.citar(art)} -> {entidad}"
                        f" ({data.get('confianza','?')}){nota} | "
                        f"{time.time()-t0:.0f}s | ETA {eta:.0f} min")

        except Exception as e:
            conteo["fallidos"] += 1
            logger.error(f"[{i}/{len(pendientes)}] FALLO en {art['art']}: {e}")
            continue

    resumen = (f"Procesados: {len(hechos)}/{len(articulos)} | "
               f"con recomendación: {conteo['con_recomendacion']} | "
               f"NINGUNA: {conteo['ninguna']} | fallidos: {conteo['fallidos']}")
    logger.info(f"\n{resumen}")
    logger.info(f"Salida: {RUTA_SALIDA}")
    enviar_alerta(f"✅ Recomendación de entidades completada.\n{resumen}\n{RUTA_SALIDA}")


if __name__ == "__main__":
    main()
