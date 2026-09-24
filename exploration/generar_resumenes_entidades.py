"""Genera un texto descriptivo (síntesis, no repetición literal) para cada entidad de
ontología (etiqueta ≠ Articulo/Norma/VersionHistorica) usando Qwen, a partir de todos los
artículos conectados directamente más los alcanzados por REMITE_A desde esos artículos.
No escribe nada en Neo4j — vuelca todo a dos archivos únicos (resúmenes / contexto) para
revisión manual antes de decidir si esto pasa a ser el pipeline definitivo.

Resumible: si se corta a mitad de camino, una nueva corrida retoma desde el checkpoint
(`_CHECKPOINT`) sin repetir entidades ya resueltas ni pisar lo ya escrito.

MODO_CALIBRACION=True corre solo sobre una muestra chica/mediana/grande (11 entidades,
incluida la más grande del grafo — SociedadAnonima, 264 artículos) para medir tiempos
reales y validar que num_ctx evita el truncamiento silencioso antes de lanzar la corrida
completa (~526 entidades, estimada en el orden de días).
"""
import json
import os
import sys
import time
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from langchain_ollama import ChatOllama
from utils.connectors import get_neo4j_driver, enviar_alerta
from utils.rag.citas import citar
from utils.rag.grafo import etiquetas_ontologia

MODELO = "qwen3.8:latest"

# num_ctx dinámico por entidad en vez de un valor fijo: pagar un contexto grande (con su
# costo de reserva de KV-cache) en las ~520 entidades chicas sería un desperdicio; y un
# valor fijo chico trunca en silencio a las ~13 entidades gigantes (SociedadAnonima llega
# a ~86.000 tokens reales). ~4.1 caracteres/token medido empíricamente con este modelo;
# se usa /4 (más conservador) más margen para el output y el overhead del prompt.
NUM_CTX_TIERS = [8192, 16384, 32768, 65536, 131072, 200000]


def calcular_num_ctx(prompt: str) -> int:
    tokens_estimados = len(prompt) // 4 + 4096
    for tier in NUM_CTX_TIERS:
        if tokens_estimados <= tier:
            return tier
    return NUM_CTX_TIERS[-1]

MODO_CALIBRACION = False
ENTIDADES_CALIBRACION = [
    "ActivoVirtual",              # 1 articulo
    "AbandonoDePersonas",         # 3
    "AccionDirecta",              # 6 (mediana)
    "Accesion",                   # 12 (p75)
    "AdscriptoNotarial",          # 23 (p90)
    "Compraventa",                # 63
    "ColegioDeEscribanos",        # 79
    "SujetoObligado",             # 86
    "Contrato",                   # 122
    "SociedadPorAccionesSimplificada",  # 145
    "SociedadAnonima",            # 264 (la mas grande del grafo)
]

SUFIJO = "calibracion" if MODO_CALIBRACION else "completo"
DIR_SALIDA = os.path.join(BASE_DIR, "input", "entidades")
os.makedirs(DIR_SALIDA, exist_ok=True)
RUTA_RESUMENES = os.path.join(DIR_SALIDA, f"resumenes_entidades_{SUFIJO}.txt")
RUTA_CONTEXTO = os.path.join(DIR_SALIDA, f"contexto_entidades_{SUFIJO}.txt")
RUTA_CHECKPOINT = os.path.join(DIR_SALIDA, f"_checkpoint_{SUFIJO}.json")

os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
_log_file = os.path.join(BASE_DIR, "logs", f"resumenes_entidades_{SUFIJO}_{time.strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(_log_file, encoding="utf-8"), logging.StreamHandler()],
)
logger = logging.getLogger("ResumenesEntidades")

driver = get_neo4j_driver()


def cargar_checkpoint() -> set:
    if os.path.exists(RUTA_CHECKPOINT):
        with open(RUTA_CHECKPOINT, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def guardar_checkpoint(hechas: set):
    with open(RUTA_CHECKPOINT, "w", encoding="utf-8") as f:
        json.dump(sorted(hechas), f, ensure_ascii=False, indent=2)


def listar_entidades():
    if MODO_CALIBRACION:
        return ENTIDADES_CALIBRACION
    return etiquetas_ontologia(driver, excluir={"Articulo", "Norma", "VersionHistorica"})


def reunir_contexto_con_reintento(etiqueta: str, intentos: int = 5, espera: int = 30):
    for intento in range(1, intentos + 1):
        try:
            return reunir_contexto(etiqueta)
        except Exception as e:
            if intento == intentos:
                raise
            logger.warning(f"  Reintento {intento}/{intentos} tras error de Neo4j en {etiqueta}: {e}")
            time.sleep(espera)


def reunir_contexto(etiqueta: str):
    with driver.session() as s:
        nodo = s.run(f"MATCH (n:{etiqueta}) RETURN n.id AS id").single()
        if not nodo:
            return None, [], []
        entidad_id = nodo["id"]

        directos = s.run(f"""
            MATCH (norma:Norma)-[:CONTIENE]->(a:Articulo)-[rel]->(n:{etiqueta} {{id: $eid}})
            RETURN DISTINCT a.id AS art, a.texto AS texto,
                   a.numero AS numero, norma.tipo AS tipo,
                   norma.numero AS norma_numero, norma.titulo AS norma_titulo,
                   norma.id AS norma_id
        """, eid=entidad_id).data()

        ids_directos = {d["art"] for d in directos}

        remisiones = s.run(f"""
            MATCH (a:Articulo)-[rel]->(n:{etiqueta} {{id: $eid}})
            MATCH (a)-[:REMITE_A]->(destino:Articulo)
            MATCH (norma:Norma)-[:CONTIENE]->(destino)
            RETURN DISTINCT destino.id AS art, destino.texto AS texto,
                   destino.numero AS numero, norma.tipo AS tipo,
                   norma.numero AS norma_numero, norma.titulo AS norma_titulo,
                   norma.id AS norma_id
        """, eid=entidad_id).data()

        adicionales = [r for r in remisiones if r["art"] not in ids_directos]

    return entidad_id, directos, adicionales


def calcular_extension_objetivo(directos, adicionales) -> str:
    """Escala la extensión pedida con la cantidad real de artículos de contexto, en vez de
    un tope fijo de 800-1000 palabras — una entidad con 50+ artículos conectados amerita un
    resumen bastante más largo que uno con 5."""
    total = len(directos) + len(adicionales)
    if total <= 5:
        return "300 a 500 palabras"
    if total <= 15:
        return "800 a 1000 palabras"
    if total <= 30:
        return "1200 a 1500 palabras"
    if total <= 60:
        return "1800 a 2200 palabras"
    return "2500 a 3000 palabras"


def armar_prompt(etiqueta: str, entidad_id: str, directos, adicionales) -> str:
    extension_objetivo = calcular_extension_objetivo(directos, adicionales)
    bloques = []
    for d in directos:
        bloques.append(f"[{citar(d)}]\n{d['texto']}")
    for a in adicionales:
        bloques.append(f"[{citar(a)} — remisión]\n{a['texto']}")
    contexto = "\n\n".join(bloques)

    return f"""Sos un jurista argentino experto en derecho notarial, civil, societario, registral y tributario.

Te paso a continuación el texto completo de todos los artículos legales conectados a la entidad "{etiqueta}" (id: {entidad_id}) en una base de conocimiento jurídico, incluyendo artículos a los que estos remiten.

ARTÍCULOS:
{contexto}

TAREA: Escribí un texto descriptivo sobre "{etiqueta}" que sirva como referencia general para responder preguntas del tipo "¿Cuáles son las características de {etiqueta}?" o "¿Qué es {etiqueta}?".

Reglas estrictas:
1. NO te limites a repetir o parafrasear un solo artículo. Sintetizá la información de TODOS los artículos provistos en un texto coherente, propio y bien explicativo.
2. Organizá el contenido en secciones temáticas bien diferenciadas, con un título claro para cada una (por ejemplo: Concepto, Naturaleza jurídica, Forma y requisitos, Quiénes intervienen, Efectos, Sanciones o consecuencias del incumplimiento, Remisiones a otras normas — adaptá o agregá secciones según lo que realmente esté respaldado por los artículos). No organices artículo por artículo.
3. Si distintos artículos aportan matices o requisitos complementarios sobre el mismo aspecto, integralos en una sola explicación dentro de la sección correspondiente.
4. Cuando corresponda, mencioná de qué norma y artículo sale cada afirmación relevante (cita breve entre paréntesis y sin usar guiones), pero el texto debe leerse como una explicación jurídica propia, no como una lista de citas. Cada artículo viene encabezado por su cita exacta entre corchetes (por ejemplo "[art. 82, Ley 404]"): usá ESA cita, tal cual, sin el corchete. NUNCA escribas el identificador interno del artículo (los de la forma Art_82_Ley_404 o Art_2128_CCyCN): no es una cita legal y no debe aparecer en el texto.
5. No inventes contenido que no esté respaldado por los artículos provistos.
6. Evita mencionar temas que no estén directamente relacionados con la "{etiqueta}", aunque aparezcan en los artículos.
7. Podés usar Markdown para estructurar el texto: títulos de sección con "##", y listas con viñetas o numeradas cuando ayuden a la claridad. No abuses del formato: usalo solo donde aporte claridad, el cuerpo de cada sección debe seguir siendo prosa explicativa.
8. Extensión objetivo: {extension_objetivo}. Es una guía proporcional a la cantidad de artículos provistos, no un relleno obligatorio — si el contenido real no da para tanto, preferí un texto más corto y ajustado a lo que realmente dicen los artículos antes que rellenar con contenido no respaldado.
"""


def guardar_resumen(etiqueta: str, entidad_id: str, n_directos: int, n_adicionales: int, texto: str):
    with open(RUTA_RESUMENES, "a", encoding="utf-8") as f:
        f.write(f"ENTIDAD: {etiqueta} (id: {entidad_id}) — {n_directos} directos + {n_adicionales} por remisión\n")
        f.write("=" * 70 + "\n\n")
        f.write(texto.strip())
        f.write("\n\n")


def avisar_progreso_si_corresponde(hechas: set, entidades, eta_min=None):
    """Envía el aviso de progreso cada 20 entidades resueltas, sea que la entidad se haya
    procesado con el LLM o se haya saltado (sin artículos conectados) — ambos casos suman
    al contador, así que ambos deben poder disparar el aviso."""
    if len(hechas) % 20 == 0:
        faltan = len(entidades) - len(hechas)
        eta_txt = f"\nETA restante ≈ {eta_min:.0f} min" if eta_min is not None else ""
        enviar_alerta(
            f"⏳ Progreso resúmenes de entidades ({SUFIJO})\n"
            f"Resueltas: {len(hechas)}/{len(entidades)} | Faltan: {faltan}{eta_txt}"
        )


def guardar_contexto(etiqueta: str, entidad_id: str, directos, adicionales):
    with open(RUTA_CONTEXTO, "a", encoding="utf-8") as f:
        f.write(f"ENTIDAD: {etiqueta} (id: {entidad_id}) — {len(directos)} directos + {len(adicionales)} por remisión\n")
        f.write("=" * 70 + "\n\n")
        for d in directos:
            f.write(f"[{citar(d)}]  ({d['art']})\n{d['texto']}\n\n")
        for a in adicionales:
            f.write(f"[{citar(a)} — remisión]  ({a['art']})\n{a['texto']}\n\n")
        f.write("-" * 70 + "\n\n")


def main():
    entidades = listar_entidades()
    hechas = cargar_checkpoint()
    pendientes = [e for e in entidades if e not in hechas]

    logger.info(f"Modo: {'CALIBRACION' if MODO_CALIBRACION else 'COMPLETO'}")
    logger.info(f"Total entidades: {len(entidades)} | Ya resueltas (checkpoint): {len(hechas)} | Pendientes: {len(pendientes)}")
    logger.info(f"Resúmenes -> {RUTA_RESUMENES}")
    logger.info(f"Contexto  -> {RUTA_CONTEXTO}")

    tiempos = []
    for i, etiqueta in enumerate(pendientes, 1):
        t0 = time.time()

        try:
            entidad_id, directos, adicionales = reunir_contexto_con_reintento(etiqueta)

            if entidad_id is None or (len(directos) == 0):
                logger.info(f"[{i}/{len(pendientes)}] SALTADA (sin artículos conectados): {etiqueta}")
                hechas.add(etiqueta)
                guardar_checkpoint(hechas)
                promedio_actual = (sum(tiempos) / len(tiempos) / 60) if tiempos else None
                eta_actual = (len(pendientes) - i) * promedio_actual if promedio_actual is not None else None
                avisar_progreso_si_corresponde(hechas, entidades, eta_actual)
                continue

            logger.info(f"[{i}/{len(pendientes)}] Procesando: {etiqueta} (id={entidad_id}, {len(directos)} directos + {len(adicionales)} remisión)")

            prompt = armar_prompt(etiqueta, entidad_id, directos, adicionales)
            num_ctx = calcular_num_ctx(prompt)
            llm = ChatOllama(model=MODELO, temperature=0.2, num_ctx=num_ctx, reasoning=False)
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

            avisar_progreso_si_corresponde(hechas, entidades, eta_min)

        except Exception as e:
            logger.error(f"  FALLO en {etiqueta}: {e}")
            enviar_alerta(f"❌ Fallo generando resumen de entidad ({SUFIJO})\nEntidad: {etiqueta}\n\n{e}")
            continue

    logger.info(f"\nProcesamiento completado. {len(hechas)}/{len(entidades)} entidades resueltas.")
    enviar_alerta(
        f"✅ Generación de resúmenes de entidades ({SUFIJO}) completada.\n"
        f"Resueltas: {len(hechas)}/{len(entidades)}\n"
        f"Resúmenes: {RUTA_RESUMENES}\n"
        f"Contexto: {RUTA_CONTEXTO}"
    )


if __name__ == "__main__":
    main()
