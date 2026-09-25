"""Benchmark del reranker para los especialistas particular y general.

Compara sobre lo que hoy hace el pipeline:
    vectorial    : el orden actual (coseno de Gemini) — la línea base
    bge          : BAAI/bge-reranker-v2-m3
    qwen3        : Qwen/Qwen3-Reranker-0.6B
    vertex...    : el Ranking API de Vertex AI (ver más abajo)
bge y qwen3 van por sentence-transformers (CrossEncoder), en la GPU o, con --cpu, en CPU. Ollama no sirve
para puntuar rerankers: ver la memoria del proyecto.

VERTEX (SIN VERIFICAR CONTRA EL SERVICIO REAL)
    --modelos vertex        semantic-ranker-default-004 (el default actual)
    --modelos vertex-fast   semantic-ranker-fast-004
    --modelos vertex-005    semantic-ranker-default-005 (preview)
    --modelos vertex-fast-005
Es el ranker de producción, pero solo se puede llamar desde el entorno de Vertex, así que esta clase se
escribió sin poder ejecutarla contra el servicio. Los nombres de clases y campos SÍ se verificaron contra el
cliente oficial construyendo el pedido en local; lo que falta es una respuesta real. Necesita:
    uv pip install google-cloud-discoveryengine       (solo para el benchmark: NO está en requirements.txt)
    GOOGLE_CLOUD_PROJECT en el entorno, la API de Discovery Engine habilitada y credenciales de aplicación.
Cada llamada al Ranking API se factura; una corrida completa hace unas 130. Los puntajes de Vertex van de 0 a
1 pero la doc no aclara si son comparables entre consultas: por eso los cortes por margen y por umbral de
--general dependen de esa escala, y los de top-N fijo no. Como el ranker vive en la nube, este benchmark
necesita además alcanzar Neo4j y la API de embeddings de Gemini desde donde se corra.

Tres experimentos, uno por punto donde el reranker podría entrar:
    --fallos      jurisprudencia: ¿el fallo esperado entra al k de producción (3)? Ground truth completo: los
                  14 casos de tests/test_jurisprudencia.py, que se importan y no se copian.
    --particular  artículos: el pool de candidatos se reduce a N y se mide contra `esperados`/`utiles`.
    --general     institutos: se rerankea sobre una representación CORTA del resumen (los resúmenes miden hasta
                  20.700 caracteres) pero se devuelve siempre el resumen completo.
Sin ninguno de los tres corren los tres. El golden set de particular y general vive en
tests/golden_reranker.json; mientras haya casos con validado=false los números son PROVISORIOS.

USO
    .venv/bin/python tests/bench_reranker.py --verificar        # solo valida el golden set (sin GPU ni LLM)
    .venv/bin/python tests/bench_reranker.py                    # los tres experimentos, ambos modelos
    .venv/bin/python tests/bench_reranker.py --fallos --modelos bge
    .venv/bin/python tests/bench_reranker.py --cpu --limite 6   # latencia en CPU sobre una muestra
    .venv/bin/python tests/bench_reranker.py --modelos bge,qwen3,vertex   # los locales contra Vertex

Los vectores de las preguntas y el análisis de cada consulta se guardan en logs/bench_reranker_cache.json:
la API de embeddings de Gemini da 429 si se la martilla, y el análisis es un LLM (no determinista), así que
sin caché dos corridas no serían comparables. Cada corrida deja además su detalle en
logs/bench_reranker_<fecha>.json.
"""
import os
# El sistema no tiene python3.12-dev (falta Python.h) y Triton no puede compilar su stub: sin esto torch
# 2.14 falla en la primera operación de la GPU.
os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")

import json
import statistics
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

GOLDEN = os.path.join(RAIZ, "tests", "golden_reranker.json")
CACHE = os.path.join(RAIZ, "logs", "bench_reranker_cache.json")
TIPOS = ("particular", "general")

# --- Parámetros de los experimentos -------------------------------------------------------------
POOLS_FALLOS = (10, 20, 30)   # candidatos que recibe el reranker; el k de producción es K_JURISPRUDENCIA (3)
K_CAND_ARTICULOS = 10         # candidatos por consulta (hoy K_VECTORIAL = 5)
TOPES_ARTICULOS = (5, 8)      # cuántos se dejan pasar tras rerankear
K_CAND_ENTIDADES = 15         # candidatos de instituto (hoy K_ENTIDADES = 5)
LARGOS_ENTIDAD = (600, 1200, 2500)   # caracteres del resumen que ve el reranker
MAX_TOKENS = 1024             # el p95 de un artículo son ~450 tokens: solo se recortan los más largos
INSTRUCCION_QWEN = ("Given a legal question from an Argentine notary, retrieve the legal text "
                    "that answers it")


# ==================================================================================================
# GOLDEN SET Y VERIFICACIÓN
# ==================================================================================================

def cargar_golden() -> list[dict]:
    with open(GOLDEN, encoding="utf-8") as f:
        return json.load(f)["casos"]


def problemas_de_forma(casos: list[dict]) -> list[str]:
    problemas, vistos = [], set()
    for c in casos:
        cid = c.get("id", "?")
        if cid in vistos:
            problemas.append(f"{cid}: id de caso repetido")
        vistos.add(cid)
        if c.get("tipo") not in TIPOS:
            problemas.append(f"{cid}: tipo {c.get('tipo')!r} no es {TIPOS}")
        if not c.get("pregunta", "").strip():
            problemas.append(f"{cid}: pregunta vacía")
        if not c.get("esperados"):
            problemas.append(f"{cid}: sin esperados")
        solapados = set(c.get("esperados", [])) & set(c.get("utiles", []))
        if solapados:
            problemas.append(f"{cid}: {sorted(solapados)} figura en esperados y en utiles")
    return problemas


def problemas_de_grafo(driver, casos: list[dict]) -> list[str]:
    """Que cada id exista donde el especialista lo va a buscar: los artículos como :Articulo vigentes,
    y los institutos con el mismo filtro que usa entidades_similares() (resumen y embedding cargados)."""
    ids_art = sorted({i for c in casos if c["tipo"] == "particular" for i in c["esperados"] + c.get("utiles", [])})
    ids_ent = sorted({i for c in casos if c["tipo"] == "general" for i in c["esperados"] + c.get("utiles", [])})
    with driver.session() as s:
        arts = {r["id"]: r["vigente"] for r in s.run(
            "MATCH (a:Articulo) WHERE a.id IN $ids RETURN a.id AS id, a.vigente AS vigente", ids=ids_art)}
        ents = {r["id"] for r in s.run(
            "MATCH (e) WHERE e.id IN $ids AND e.resumen IS NOT NULL AND e.embedding IS NOT NULL "
            "AND NOT e:Articulo AND NOT e:Norma AND NOT e:VersionHistorica AND NOT e:Jurisprudencia "
            "RETURN e.id AS id", ids=ids_ent)}
    problemas = [f"artículo {i}: no existe en el grafo" for i in ids_art if i not in arts]
    problemas += [f"artículo {i}: existe pero no está vigente" for i, v in arts.items() if v is not True]
    problemas += [f"instituto {i}: no existe o no tiene resumen y embedding" for i in ids_ent if i not in ents]
    print(f"  artículos: {len(ids_art)} ids referenciados, {len(arts)} existen")
    print(f"  institutos: {len(ids_ent)} ids referenciados, {len(ents)} existen")
    return problemas


def verificar() -> int:
    from utils.connectors import get_neo4j_driver
    from tests.test_jurisprudencia import CASOS, verificar_casos

    casos = cargar_golden()
    por_tipo = {t: sum(c["tipo"] == t for c in casos) for t in TIPOS}
    validados = sum(bool(c.get("validado")) for c in casos)
    print(f"Golden set: {por_tipo['particular']} particular + {por_tipo['general']} general = {len(casos)} casos "
          f"| validados por Mariano: {validados}/{len(casos)}")
    print(f"Más {len(CASOS)} fallos importados de tests/test_jurisprudencia.py")

    problemas = problemas_de_forma(casos)
    driver = get_neo4j_driver()
    try:
        problemas += problemas_de_grafo(driver, casos)
        faltan_fallos = verificar_casos(driver)
        print(f"  fallos: {len(CASOS) - len(faltan_fallos)}/{len(CASOS)} existen")
        problemas += [f"fallo {i}: no existe en el grafo" for i in faltan_fallos]
    finally:
        driver.close()

    if validados < len(casos):
        print(f"\nAVISO: {len(casos) - validados} casos siguen en borrador (validado=false).")
    if problemas:
        print(f"\n{len(problemas)} PROBLEMAS:")
        for p in problemas:
            print(f"  - {p}")
        return 1
    print("\nOK: el golden set está bien armado y todos los ids existen.")
    return 0


# ==================================================================================================
# CACHÉ: vectores de las preguntas y análisis de cada consulta
# ==================================================================================================

_cache: dict | None = None


def _cache_datos() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(CACHE, encoding="utf-8") as f:
                _cache = json.load(f)
        except (OSError, ValueError):
            _cache = {"emb": {}, "analisis": {}}
    return _cache


def guardar_cache() -> None:
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(_cache_datos(), f, ensure_ascii=False, separators=(",", ":"))


def embed(texto: str) -> list[float]:
    """Vector de una consulta, de la caché o de Gemini. Ante un 429 espera y reintenta: la cuota es por
    minuto y el reintento corto de utils.connectors (1-2-4 s) no alcanza a que se libere."""
    emb = _cache_datos()["emb"]
    if texto not in emb:
        from utils.connectors import get_gemini_embeddings
        for intento in range(6):
            try:
                emb[texto] = get_gemini_embeddings().embed_query(texto)
                break
            except Exception as e:
                if "RESOURCE_EXHAUSTED" not in str(e) and "429" not in str(e):
                    raise
                espera = 20 * (intento + 1)
                print(f"    (cuota de embeddings: espero {espera}s)", flush=True)
                time.sleep(espera)
        else:
            raise RuntimeError("Gemini sigue dando 429 tras 6 intentos")
    return emb[texto]


def analisis(pregunta: str) -> tuple[str, list[str]]:
    """(sujeto, frases) que extrae el especialista particular. Es un LLM, así que se cachea."""
    cache = _cache_datos()["analisis"]
    if pregunta not in cache:
        from api.especialistas.particular import extraer_parametros_vectoriales
        sujeto, frases = extraer_parametros_vectoriales(pregunta)
        cache[pregunta] = {"sujeto": sujeto, "frases": [str(f) for f in frases]}
    return cache[pregunta]["sujeto"], cache[pregunta]["frases"]


# ==================================================================================================
# RERANKERS
# ==================================================================================================

class Reranker:
    """Un CrossEncoder de sentence-transformers que devuelve probabilidades de relevancia en [0, 1].

    Los dos modelos dan un logit; el Sigmoid los pone en la misma escala para poder cortar por margen o por
    umbral sin que un modelo sature distinto del otro.
    """
    REPOS = {"bge": "BAAI/bge-reranker-v2-m3", "qwen3": "Qwen/Qwen3-Reranker-0.6B"}

    def __init__(self, clave: str, cpu: bool = False):
        import torch
        from sentence_transformers import CrossEncoder
        self.clave, self.torch, self.cpu = clave, torch, cpu
        kw = dict(device="cpu" if cpu else "cuda", max_length=MAX_TOKENS,
                  model_kwargs={"dtype": torch.float32 if cpu else torch.float16})
        if clave == "qwen3":
            kw.update(prompts={"notarial": INSTRUCCION_QWEN}, default_prompt_name="notarial")
        self.modelo = CrossEncoder(self.REPOS[clave], **kw)
        self.donde = "CPU" if cpu else "GPU (GB10)"
        self.ms: list[float] = []     # latencia de cada llamada a puntuar()
        self.pares: list[int] = []    # cuántos pares tenía cada llamada

    def puntuar(self, consulta: str, docs: list[str]) -> list[float]:
        if not docs:
            return []
        t = time.perf_counter()
        sc = self.modelo.predict([(consulta, d) for d in docs], batch_size=32, show_progress_bar=False,
                                 activation_fn=self.torch.nn.Sigmoid())
        if not self.cpu:
            self.torch.cuda.synchronize()
        self.ms.append((time.perf_counter() - t) * 1000)
        self.pares.append(len(docs))
        return [float(x) for x in sc]

    def calentar(self) -> None:
        self.puntuar("¿Qué requisitos exige la ley?", ["Artículo de prueba sobre requisitos legales."] * 4)
        self.ms.clear(); self.pares.clear()


class VertexRanker:
    """El Ranking API de Vertex AI, con la misma interfaz que Reranker (clave, puntuar, calentar, ms, pares).

    NO SE PUDO EJECUTAR CONTRA EL SERVICIO. Ver el docstring del módulo: los nombres de clases y campos se
    verificaron con el cliente oficial, y `entender_respuesta` se probó con un cliente falso.
    """
    MODELOS = {
        "vertex": "semantic-ranker-default-004",
        "vertex-fast": "semantic-ranker-fast-004",
        "vertex-005": "semantic-ranker-default-005",
        "vertex-fast-005": "semantic-ranker-fast-005",
    }

    def __init__(self, clave: str):
        try:
            from google.cloud import discoveryengine_v1 as discoveryengine
        except ImportError as e:
            raise SystemExit("Falta el cliente de Vertex: uv pip install google-cloud-discoveryengine") from e
        proyecto = os.getenv("GOOGLE_CLOUD_PROJECT")
        if not proyecto:
            raise SystemExit("Falta GOOGLE_CLOUD_PROJECT en el entorno para llamar al Ranking API")
        self.clave, self.modelo, self.donde = clave, self.MODELOS[clave], "Vertex (con la red incluida)"
        self.de = discoveryengine
        self.cliente = discoveryengine.RankServiceClient()
        self.config = f"projects/{proyecto}/locations/global/rankingConfigs/default_ranking_config"
        self.ms: list[float] = []
        self.pares: list[int] = []

    def puntuar(self, consulta: str, docs: list[str]) -> list[float]:
        if not docs:
            return []
        pedido = self.de.RankRequest(
            ranking_config=self.config, model=self.modelo, query=consulta, top_n=len(docs),
            records=[self.de.RankingRecord(id=str(i), content=d) for i, d in enumerate(docs)],
            ignore_record_details_in_response=True,   # solo hace falta id y puntaje
        )
        t = time.perf_counter()
        respuesta = self.cliente.rank(request=pedido)
        self.ms.append((time.perf_counter() - t) * 1000)
        self.pares.append(len(docs))
        return entender_respuesta(respuesta, len(docs))

    def calentar(self) -> None:
        self.puntuar("¿Qué requisitos exige la ley?", ["Artículo de prueba sobre requisitos legales."] * 4)
        self.ms.clear(); self.pares.clear()


def entender_respuesta(respuesta, n: int) -> list[float]:
    """Puntajes en el orden de los docs enviados. El API devuelve los registros ordenados por relevancia,
    no en el orden del pedido, así que se reubican por id. Un id ausente puntúa 0 en vez de romper."""
    por_id = {r.id: float(r.score) for r in respuesta.records}
    return [por_id.get(str(i), 0.0) for i in range(n)]


def crear_reranker(clave: str, cpu: bool):
    if clave in VertexRanker.MODELOS:
        return VertexRanker(clave)
    if clave in Reranker.REPOS:
        return Reranker(clave, cpu=cpu)
    raise SystemExit(f"Modelo desconocido: {clave!r}. Opciones: {sorted([*Reranker.REPOS, *VertexRanker.MODELOS])}")


# ==================================================================================================
# MÉTRICAS
# ==================================================================================================

def posicion(ranking: list[str], objetivo: str) -> int | None:
    return ranking.index(objetivo) + 1 if objetivo in ranking else None


def mrr(ranking: list[str], esperados: set[str]) -> float:
    for i, x in enumerate(ranking, 1):
        if x in esperados:
            return 1 / i
    return 0.0


def ndcg(ranking: list[str], esperados: set[str], utiles: set[str], k: int = 10) -> float:
    """nDCG@k con relevancia 2 para los esperados y 1 para los útiles."""
    import math
    ganancia = lambda x: 2 if x in esperados else (1 if x in utiles else 0)
    dcg = sum(ganancia(x) / math.log2(i + 1) for i, x in enumerate(ranking[:k], 1))
    ideal = sorted([2] * len(esperados) + [1] * len(utiles), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 1) for i, g in enumerate(ideal, 1))
    return dcg / idcg if idcg else 0.0


def metricas_conjunto(seleccion: list[str], esperados: set[str], utiles: set[str]) -> dict:
    """Lo que llega al redactor: ¿están los esperados, y cuánto ruido viene con ellos?"""
    hay = len(esperados & set(seleccion))
    relevantes = len((esperados | utiles) & set(seleccion))
    return {"recall": hay / len(esperados), "todos": float(hay == len(esperados)),
            "precision": relevantes / len(seleccion) if seleccion else 0.0, "n": float(len(seleccion))}


def promediar(filas: list[dict]) -> dict:
    return {k: statistics.mean(f[k] for f in filas) for k in filas[0]} if filas else {}


def imprimir_tabla(titulo: str, columnas: list[str], filas: list[tuple]) -> None:
    print(f"\n{titulo}")
    ancho = max(len(str(f[0])) for f in filas) if filas else 10
    print("  " + "sistema".ljust(ancho) + "".join(f"{c:>11}" for c in columnas))
    for nombre, *vals in filas:
        print("  " + str(nombre).ljust(ancho) + "".join(f"{v:>11.3f}" if isinstance(v, float) else f"{v!s:>11}" for v in vals))


# ==================================================================================================
# EXPERIMENTO 1: JURISPRUDENCIA (verdad de referencia completa)
# ==================================================================================================

def exp_fallos(rerankers: list[Reranker], limite: int | None) -> dict:
    from tests.test_jurisprudencia import CASOS
    from api.especialistas.particular import _obtener_retriever_jurisprudencia, K_JURISPRUDENCIA

    store = _obtener_retriever_jurisprudencia().vectorstore
    casos = CASOS[:limite] if limite else CASOS
    pmax = max(POOLS_FALLOS)
    detalle = []
    print(f"\n=== FALLOS: {len(casos)} casos | k de producción = {K_JURISPRUDENCIA} | pool máximo = {pmax}", flush=True)

    for c in casos:
        q, esperado = c["pregunta"], c["fallo"]
        res = store.similarity_search_with_score_by_vector(embed(q), k=pmax, query=q)
        ids = [d.metadata["id"] for d, _ in res]
        textos = [d.page_content for d, _ in res]
        fila = {"pregunta": q, "esperado": esperado, "vectorial": posicion(ids, esperado), "reranker": {}}
        for r in rerankers:
            sc = r.puntuar(q, textos)                       # una vez sobre el pool máximo
            fila["reranker"][r.clave] = {}
            for p in POOLS_FALLOS:                          # y se reordena cada subpool sin volver a puntuar
                orden = sorted(range(p), key=lambda i: -sc[i])
                fila["reranker"][r.clave][p] = posicion([ids[i] for i in orden], esperado)
        detalle.append(fila)
        print(f"  vec={fila['vectorial']!s:>4} " + " ".join(
            f"{r.clave}={fila['reranker'][r.clave][pmax]!s:>4}" for r in rerankers) + f" | {q[:70]}", flush=True)

    def resumen(pos_list, k=K_JURISPRUDENCIA):
        n = len(pos_list)
        return (sum(1 for p in pos_list if p == 1) / n, sum(1 for p in pos_list if p and p <= k) / n,
                statistics.mean(1 / p if p else 0.0 for p in pos_list))

    filas = [("vectorial (hoy)", *resumen([f["vectorial"] for f in detalle]),
              sum(1 for f in detalle if not f["vectorial"]))]
    for r in rerankers:
        for p in POOLS_FALLOS:
            filas.append((f"{r.clave} sobre top-{p}", *resumen([f["reranker"][r.clave][p] for f in detalle]),
                          sum(1 for f in detalle if not f["vectorial"] or f["vectorial"] > p)))
    imprimir_tabla("Fallos — ¿entra el esperado? (top3 = el k de producción)",
                   ["puesto 1", "top 3", "MRR", "fuera pool"], filas)
    return {"casos": detalle}


# ==================================================================================================
# EXPERIMENTO 2: ARTÍCULOS (especialista particular)
# ==================================================================================================

def candidatos_articulos(caso: dict, k: int) -> tuple[list, list, str]:
    """Reproduce la búsqueda vectorial de particular() con `k` por consulta. Devuelve (docs con duplicados, en
    el orden de las consultas; consultas usadas; sujeto)."""
    from api.especialistas.particular import _obtener_retriever
    store = _obtener_retriever().vectorstore
    sujeto, frases = analisis(caso["pregunta"])
    consultas = frases + [caso["pregunta"]]
    docs = []
    for q in consultas:
        for doc, score in store.similarity_search_with_score_by_vector(embed(q), k=k, query=q):
            docs.append((doc, score))
    return docs, consultas, sujeto


def sin_duplicados(pares: list) -> list:
    """Un doc por id, con el mejor score vectorial que tuvo en cualquier consulta."""
    mejor: dict[str, tuple] = {}
    for doc, score in pares:
        i = str(doc.metadata.get("id", ""))
        if i and (i not in mejor or score > mejor[i][1]):
            mejor[i] = (doc, score)
    return sorted(mejor.values(), key=lambda t: -t[1])


def exp_particular(rerankers: list[Reranker], limite: int | None, solo_validados: bool) -> dict:
    from api.especialistas.particular import filtrar_por_sujeto, K_VECTORIAL

    casos = [c for c in cargar_golden() if c["tipo"] == "particular" and (c.get("validado") or not solo_validados)]
    casos = casos[:limite] if limite else casos
    print(f"\n=== ARTÍCULOS (particular): {len(casos)} casos | k por consulta: hoy {K_VECTORIAL}, pool {K_CAND_ARTICULOS}", flush=True)

    sistemas: dict[str, list[dict]] = {}     # nombre -> lista de métricas por caso
    rank_metrics: dict[str, list[dict]] = {}  # nombre -> [{mrr, ndcg}] sobre el pool ordenado
    detalle = []

    def registrar(nombre, seleccion, esperados, utiles, chars):
        m = metricas_conjunto(seleccion, esperados, utiles)
        m["chars"] = float(chars)
        sistemas.setdefault(nombre, []).append(m)

    for c in casos:
        q, E, U = c["pregunta"], set(c["esperados"]), set(c.get("utiles", []))
        # Producción: k=5 por consulta y filtro por sujeto (lo que hace particular() hoy).
        docs5, _, sujeto = candidatos_articulos(c, K_VECTORIAL)
        prod = sin_duplicados([(d, 0.0) for d in filtrar_por_sujeto([d for d, _ in docs5], sujeto)])
        # Pool ampliado.
        docs_pool, _, _ = candidatos_articulos(c, K_CAND_ARTICULOS)
        pool = sin_duplicados(docs_pool)                            # ordenado por mejor score vectorial
        filtrados = sin_duplicados([(d, 0.0) for d in filtrar_por_sujeto([d for d, _ in docs_pool], sujeto)])
        ids_pool = [str(d.metadata["id"]) for d, _ in pool]
        largo = {str(d.metadata["id"]): len(d.page_content) for d, _ in pool}

        registrar("producción (k=5 + filtro)", [str(d.metadata["id"]) for d, _ in prod], E, U,
                  sum(len(d.page_content) for d, _ in prod))
        rank_metrics.setdefault("vectorial", []).append({"mrr": mrr(ids_pool, E), "ndcg": ndcg(ids_pool, E, U)})
        for n in TOPES_ARTICULOS:
            sel = ids_pool[:n]
            registrar(f"vectorial top-{n}", sel, E, U, sum(largo[i] for i in sel))

        fila = {"id": c["id"], "pregunta": q, "pool": len(pool), "esperados_en_pool": len(E & set(ids_pool)),
                "prod_ids": [str(d.metadata["id"]) for d, _ in prod]}
        for r in rerankers:
            for etiqueta, base in (("", pool), (" +filtro", filtrados)):
                if not base:
                    continue
                textos = [d.page_content for d, _ in base]
                sc = r.puntuar(q, textos)
                orden = [str(base[i][0].metadata["id"]) for i in sorted(range(len(base)), key=lambda i: -sc[i])]
                if not etiqueta:
                    rank_metrics.setdefault(r.clave, []).append({"mrr": mrr(orden, E), "ndcg": ndcg(orden, E, U)})
                    fila[r.clave] = orden[:max(TOPES_ARTICULOS)]
                for n in TOPES_ARTICULOS:
                    registrar(f"{r.clave}{etiqueta} top-{n}", orden[:n], E, U, sum(largo[i] for i in orden[:n]))
        detalle.append(fila)
        print(f"  {c['id']} pool={fila['pool']:>3} esperados_en_pool={fila['esperados_en_pool']}/{len(E)} | {q[:64]}", flush=True)

    filas = [(n, *(promediar(v)[k] for k in ("recall", "todos", "precision", "n", "chars"))) for n, v in sistemas.items()]
    imprimir_tabla("Artículos — lo que le llega al redactor (todos = casos con TODOS los esperados)",
                   ["recall", "todos", "precision", "n docs", "chars"], filas)
    filas_r = [(n, *(promediar(v)[k] for k in ("mrr", "ndcg"))) for n, v in rank_metrics.items()]
    imprimir_tabla("Artículos — calidad del orden sobre el pool completo", ["MRR", "nDCG@10"], filas_r)
    return {"casos": detalle}


# ==================================================================================================
# EXPERIMENTO 3: INSTITUTOS (especialista general)
# ==================================================================================================

def seleccionar_entidades(ids: list[str], p: list[float], politica: str) -> list[str]:
    """Aplica una política de corte sobre las probabilidades del reranker (`ids` ya ordenado por p desc)."""
    if politica.startswith("top"):
        return ids[:int(politica[3:])]
    if politica.startswith("margen"):
        m = float(politica[6:])
        return [i for i, x in zip(ids, p) if x >= p[0] - m][:5]
    if politica.startswith("umbral"):
        t = float(politica[6:])
        return ([i for i, x in zip(ids, p) if x >= t] or ids[:1])[:5]
    raise ValueError(politica)


def exp_general(rerankers: list[Reranker], limite: int | None, solo_validados: bool) -> dict:
    from utils.connectors import get_neo4j_driver
    from utils.rag.grafo import entidades_similares, K_ENTIDADES

    casos = [c for c in cargar_golden() if c["tipo"] == "general" and (c.get("validado") or not solo_validados)]
    casos = casos[:limite] if limite else casos
    print(f"\n=== INSTITUTOS (general): {len(casos)} casos | hoy k={K_ENTIDADES} con margen | pool {K_CAND_ENTIDADES}", flush=True)
    driver = get_neo4j_driver()
    sistemas: dict[str, list[dict]] = {}
    detalle = []

    def registrar(nombre, seleccion, esperados, utiles, resumenes):
        m = metricas_conjunto(seleccion, esperados, utiles)
        m["chars"] = float(sum(len(resumenes[i]) for i in seleccion))
        sistemas.setdefault(nombre, []).append(m)

    try:
        for c in casos:
            q, E, U = c["pregunta"], set(c["esperados"]), set(c.get("utiles", []))
            vec = embed(q)
            hoy = entidades_similares(driver, vec)                                  # k y margen de producción
            pool = entidades_similares(driver, vec, k=K_CAND_ENTIDADES, margen=10.0)  # sin corte
            resumenes = {e["id"]: e["resumen"] for e in pool}
            registrar("producción (k=5 + margen)", [e["id"] for e in hoy], E, U, resumenes)
            registrar("vectorial top-5 (sin margen)", [e["id"] for e in pool][:5], E, U, resumenes)
            fila = {"id": c["id"], "pregunta": q, "hoy": [e["id"] for e in hoy], "pool_ids": [e["id"] for e in pool],
                    "esperados_en_pool": len(E & {e["id"] for e in pool}), "reranker": {}}
            for r in rerankers:
                for largo in LARGOS_ENTIDAD:
                    textos = [f"{e['nombre'] or e['id']}\n{e['resumen'][:largo]}" for e in pool]
                    sc = r.puntuar(q, textos)
                    orden = sorted(range(len(pool)), key=lambda i: -sc[i])
                    ids = [pool[i]["id"] for i in orden]
                    p = [sc[i] for i in orden]
                    fila["reranker"][f"{r.clave}/{largo}"] = list(zip(ids, [round(x, 3) for x in p]))
                    for politica in ("top3", "top5", "margen0.1", "margen0.3", "umbral0.5"):
                        registrar(f"{r.clave} {largo}c {politica}", seleccionar_entidades(ids, p, politica), E, U, resumenes)
            detalle.append(fila)
            print(f"  {c['id']} hoy={len(hoy)} esperados_en_pool={fila['esperados_en_pool']}/{len(E)} | {q[:64]}", flush=True)
    finally:
        driver.close()

    filas = [(n, *(promediar(v)[k] for k in ("recall", "todos", "precision", "n", "chars"))) for n, v in sistemas.items()]
    imprimir_tabla("Institutos — lo que le llega al redactor (chars = resúmenes completos enviados)",
                   ["recall", "todos", "precision", "n docs", "chars"], filas)
    return {"casos": detalle}


# ==================================================================================================
# LATENCIA Y MAIN
# ==================================================================================================

def imprimir_latencia(rerankers: list) -> dict:
    out = {}
    print("\nLatencia por llamada a puntuar()")
    for r in rerankers:
        if not r.ms:
            continue
        ms = sorted(r.ms)
        p95 = ms[min(len(ms) - 1, int(len(ms) * 0.95))]
        por_par = sum(r.ms) / sum(r.pares)
        out[r.clave] = {"llamadas": len(ms), "p50_ms": statistics.median(ms), "p95_ms": p95, "ms_por_par": por_par,
                        "donde": r.donde}
        print(f"  {r.clave:12s} {len(ms):4d} llamadas | p50 {statistics.median(ms):7.0f} ms | p95 {p95:7.0f} ms | "
              f"{por_par:5.1f} ms por par | {r.donde}")
    return out


def main() -> int:
    args = sys.argv[1:]
    cpu = "--cpu" in args
    solo_validados = "--solo-validados" in args
    limite = int(args[args.index("--limite") + 1]) if "--limite" in args else None
    claves = args[args.index("--modelos") + 1].split(",") if "--modelos" in args else ["bge", "qwen3"]
    elegidos = [e for e in ("--fallos", "--particular", "--general") if e in args] or ["--fallos", "--particular", "--general"]

    golden = cargar_golden()
    sin_validar = sum(not c.get("validado") for c in golden)
    if sin_validar and ("--particular" in elegidos or "--general" in elegidos) and not solo_validados:
        print(f"AVISO: {sin_validar}/{len(golden)} casos del golden set siguen en borrador: los números de "
              f"particular y general son PROVISORIOS.")

    rerankers = []
    for clave in claves:
        t = time.time()
        rerankers.append(crear_reranker(clave, cpu))
        rerankers[-1].calentar()
        print(f"Modelo {clave} listo ({time.time() - t:.1f}s de carga)", flush=True)

    resultado = {"fecha": time.strftime("%Y-%m-%d %H:%M:%S"), "cpu": cpu, "modelos": claves, "limite": limite,
                 "casos_sin_validar": sin_validar}
    try:
        if "--fallos" in elegidos:
            resultado["fallos"] = exp_fallos(rerankers, limite)
        if "--particular" in elegidos:
            resultado["particular"] = exp_particular(rerankers, limite, solo_validados)
        if "--general" in elegidos:
            resultado["general"] = exp_general(rerankers, limite, solo_validados)
    finally:
        guardar_cache()
    resultado["latencia"] = imprimir_latencia(rerankers)

    os.makedirs(os.path.join(RAIZ, "logs"), exist_ok=True)
    ruta = os.path.join(RAIZ, "logs", f"bench_reranker_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=1)
    print(f"\nDetalle en {os.path.relpath(ruta, RAIZ)}")
    return 0


if __name__ == "__main__":
    if "--verificar" in sys.argv:
        sys.exit(verificar())
    if "-h" in sys.argv or "--help" in sys.argv:
        print(__doc__)
        sys.exit(0)
    sys.exit(main())
