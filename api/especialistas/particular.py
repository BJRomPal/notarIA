"""ESPECIALISTA PARTICULAR — consultas sobre articulado concreto.

Uno de los tres especialistas del agente notarial. Atiende las preguntas que apuntan a una
norma o a un supuesto puntual («¿qué requisitos exige el art. 77 LSC para la fusión?»):
busca artículos, sigue las remisiones entre ellos, consulta jurisprudencia y, si hace falta,
baja al grafo con Text-to-Cypher.

Es `api/recuperacion.py` movido acá y renombrado. El nombre viejo describía un paso del
pipeline; el nuevo describe qué clase de consulta resuelve, que es lo que importa ahora que
hay tres caminos posibles.

CONTRATO CON EL AGENTE (el mismo para los tres especialistas):
    particular(pregunta) -> Generator[dict, None, ContextoAcumulado]

Es un generador que emite dicts del contrato SSE y cuyo `return` es el contexto acumulado.
**No importa LangGraph y no sabe que existe.** Esa ignorancia es deliberada: es lo que hace
reversible la decisión de usar LangGraph, y lo que permite consumir este módulo desde un
script suelto igual que desde un nodo del grafo. El puente vive en `api/agente/nodos.py`.

FASES QUE EMITE, en orden:
    analisis        extrae sujeto y frases de búsqueda (1 llamada a flash-lite)
    vectorial       busca en index_articulos y filtra por sujeto
    remisiones      sigue REMITE_A desde lo encontrado
    jurisprudencia  busca en index_jurisprudencia (fallos)
    evaluacion      decide si el contexto alcanza (1 llamada a flash-lite)
    grafo           SOLO si la evaluación dio insuficiente: Text-to-Cypher (la más cara)
"""
import os
from typing import Iterator

from utils.connectors import get_neo4j_driver, get_gemini_embeddings, get_gemini_llm
from utils.rag.citas import NOMBRE_NORMA
from utils.rag.texto import normalizar, formato_articulo
from utils.rag.llm_io import json_del_llm
from utils.rag.grafo import seguir_remite_a, datos_articulos
from api.cypher import MotorCypherDinamico
from langchain_neo4j import Neo4jVector

llm_lite   = get_gemini_llm()                          # flash-lite: tareas simples (extracción, evaluación)
llm        = get_gemini_llm("gemini-2.5-flash")        # flash: respuesta final y Cypher
embeddings = get_gemini_embeddings()
neo4j_driver = get_neo4j_driver()

# --- Parámetros de recuperación (heurísticas explicadas donde se usan) ---
K_VECTORIAL          = 5   # vecinos a recuperar por cada frase de búsqueda
LONGITUD_MIN_KEYWORD = 4   # palabras del sujeto más cortas se ignoran (poco discriminantes)
MIN_DOCS_TRAS_FILTRO = 2   # si el filtro por sujeto deja menos, se descarta el filtro (prioriza recall)
K_JURISPRUDENCIA     = 3   # fallos a recuperar: son doctrina de apoyo, no la fuente principal

# ==========================================
# 1. MOTOR VECTORIAL
# ==========================================

retrieval_query = f"""
OPTIONAL MATCH (norma:Norma)-[:CONTIENE]->(node)
RETURN
    "FUENTE: " + {NOMBRE_NORMA} + "\\n" +
    "ARTICULO: " + coalesce(node.numero, '') + "\\n" +
    "TEXTO: " + coalesce(node.texto, '') AS text,
    score,
    {{
        ley: {NOMBRE_NORMA},
        norma_id: coalesce(norma.id, ''),
        art: coalesce(node.numero, ''),
        id: node.id,
        ubicacion: coalesce(node.ubicacion, '')
    }} AS metadata
"""

# INIT PEREZOSO, mismo patrón que `_obtener_motor_cypher()` más abajo. `from_existing_index()`
# NO es un constructor barato: consulta a Neo4j los metadatos del índice, así que llamarlo a
# nivel de módulo hacía que `import api.agente.grafo` contactara la base dos veces —una por
# índice— antes de ejecutar una sola línea. Eso obligaba a tener Aura viva para importar el
# agente, que es lo que vuelve lento y frágil cualquier test.
_retriever = None

def _obtener_retriever():
    """El retriever de artículos, construido en el primer uso y cacheado en módulo."""
    global _retriever
    if _retriever is None:
        vector_db = Neo4jVector.from_existing_index(
            embeddings,
            url=os.getenv("NEO4J_URI"),
            username=os.getenv("NEO4J_USERNAME"),
            password=os.getenv("NEO4J_PASSWORD"),
            index_name="index_articulos",
            retrieval_query=retrieval_query,
        )
        _retriever = vector_db.as_retriever(search_kwargs={"k": K_VECTORIAL})
    return _retriever

# ------------------------------------------------------------------------------------------
# Motor vectorial de JURISPRUDENCIA (segundo índice, separado del de artículos)
# ------------------------------------------------------------------------------------------
# Son 292 fallos que hasta ahora no consultaba nadie. Van por un índice propio y no por el de
# artículos porque son otra cosa: doctrina de apoyo, no norma vigente.
#
# Se devuelve el RESUMEN, no el texto del fallo, por dos razones que se refuerzan:
#   1. El embedding se calculó sobre el resumen (extract_jurisprudencia.py), así que lo que
#      matchea es lo que se devuelve. Buscar por resumen y devolver el texto completo sería
#      devolver algo que nunca participó de la búsqueda.
#   2. El texto promedia 19.500 caracteres y llega a 286.000. Tres fallos completos harían
#      estallar el prompt; tres resúmenes son ~1.800 caracteres.
retrieval_query_jurisprudencia = """
RETURN
    "FALLO: " + coalesce(node.tribunal, '') + "\\n" +
    "FECHA: " + coalesce(node.fecha, '') + "\\n" +
    "DOCTRINA: " + coalesce(node.resumen, '') AS text,
    score,
    {
        id: node.id,
        tribunal: coalesce(node.tribunal, ''),
        fecha: coalesce(node.fecha, ''),
        tipo: coalesce(node.tipo, ''),
        rama: coalesce(node.rama, '')
    } AS metadata
"""

_retriever_jurisprudencia = None

def _obtener_retriever_jurisprudencia():
    """El retriever de fallos, construido en el primer uso y cacheado en módulo."""
    global _retriever_jurisprudencia
    if _retriever_jurisprudencia is None:
        vector_db = Neo4jVector.from_existing_index(
            embeddings,
            url=os.getenv("NEO4J_URI"),
            username=os.getenv("NEO4J_USERNAME"),
            password=os.getenv("NEO4J_PASSWORD"),
            index_name="index_jurisprudencia",
            retrieval_query=retrieval_query_jurisprudencia,
        )
        _retriever_jurisprudencia = vector_db.as_retriever(
            search_kwargs={"k": K_JURISPRUDENCIA}
        )
    return _retriever_jurisprudencia

# ==========================================
# 2. CONTEXTO ACUMULADO
# ==========================================

class ContextoAcumulado:
    """Acumula artículos únicos (dedup por id) con su texto ya formateado y la fase
    que lo trajo al contexto (vectorial, remision o grafo) — atribución que permite
    medir por separado el aporte de cada fase de recuperación."""
    def __init__(self):
        self._vistos: set[str] = set()
        self.ids: list[str] = []
        self.textos: list[str] = []
        self.fases: dict[str, str] = {}

    def agregar(self, art_id, texto: str, fase: str) -> bool:
        """Registra el artículo si no fue visto antes. Devuelve True si era nuevo."""
        art_id = str(art_id)
        if not art_id or art_id in self._vistos:
            return False
        self._vistos.add(art_id)
        self.ids.append(art_id)
        self.textos.append(texto)
        self.fases[art_id] = fase
        return True

    def __contains__(self, art_id) -> bool:
        return str(art_id) in self._vistos

    def __len__(self) -> int:
        return len(self._vistos)

# ==========================================
# 3. EXTRACCIÓN PARA FASE VECTORIAL
# ==========================================

def extraer_parametros_vectoriales(pregunta: str) -> tuple[str, list[str]]:
    prompt = f"""Analizá la pregunta jurídica y extraé parámetros para búsqueda semántica.
Devolvé un JSON con:
- "sujeto": El sujeto o instituto jurídico central de la pregunta, en lenguaje natural
  (ej: "sociedad anonima", "SAS", "hipoteca", "escritura publica", "usufructo",
  "reporte de operacion sospechosa", "tracto abreviado"). Si la pregunta no gira sobre
  un instituto identificable, devolvé "".
- "frases_vectoriales": Lista de 2 o 3 frases en lenguaje natural. Incluí el número de artículo si se menciona.
Devuelve SOLO el JSON.
Pregunta: {pregunta}"""
    try:
        respuesta = llm_lite.invoke(prompt)
        data = json_del_llm(str(respuesta.content))
        return str(data.get("sujeto", "")), data.get("frases_vectoriales", [pregunta])
    except Exception:
        return "", [pregunta]

# Palabras demasiado genéricas para discriminar: aparecen en casi cualquier norma del
# corpus (societario, civil, registral, notarial, penal, tributario). Las de <= 4 letras
# ya las descarta LONGITUD_MIN_KEYWORD.
_STOPWORDS = {
    "sociedad", "capital", "social", "socios",
    "derecho", "derechos", "juridico", "juridica",
    "articulo", "articulos", "norma", "normas",
    "publico", "publica", "general", "nacional", "legal", "legales",
}

def filtrar_por_sujeto(docs: list, sujeto: str) -> list:
    """Filtra los docs vectoriales para quedarse con los del sujeto preguntado.
    Privilegia recall sobre precisión: si el filtro deja menos de MIN_DOCS_TRAS_FILTRO
    documentos, se descarta y se devuelven todos."""
    if not sujeto:
        return docs
    words = [w for w in normalizar(sujeto).split() if len(w) > LONGITUD_MIN_KEYWORD and w not in _STOPWORDS]
    if not words:
        return docs

    # Frecuencia: cuántas frases de búsqueda distintas devolvieron cada doc.
    frecuencia: dict[str, int] = {}
    for doc in docs:
        doc_id = str(doc.metadata.get("id", ""))
        if doc_id:
            frecuencia[doc_id] = frecuencia.get(doc_id, 0) + 1

    filtrados = [
        doc for doc in docs
        if any(w in normalizar(doc.page_content) or w in normalizar(str(doc.metadata.get("ubicacion", ""))) for w in words)
        or frecuencia.get(str(doc.metadata.get("id", "")), 0) >= 2
    ]
    return filtrados if len(filtrados) >= MIN_DOCS_TRAS_FILTRO else docs

# ==========================================
# 4. MOTOR CYPHER DINÁMICO (init perezoso)
# ==========================================

# Arma el motor recién en el primer uso, con caché en módulo. Desde que los dos retrievers de
# arriba también son perezosos, **importar este módulo ya no toca la base**: el costo se paga
# en la primera consulta que lo necesite y no en el arranque de uvicorn ni al importar.
_motor_cypher: MotorCypherDinamico | None = None

def _obtener_motor_cypher() -> MotorCypherDinamico:
    global _motor_cypher
    if _motor_cypher is None:
        # Recibe `embeddings` y no la lista de etiquetas: el motor recorta el esquema por
        # pregunta, trayendo solo las 20 etiquetas más cercanas en vez de las 566. Con eso
        # desapareció también la carga de `etiquetas_ontologia()` en el arranque —y su print
        # de 566 nombres, que ensuciaba la salida de cada corrida.
        _motor_cypher = MotorCypherDinamico(neo4j_driver, llm, embeddings)
    return _motor_cypher

# ==========================================
# 5. VECINDARIO ONTOLÓGICO
# ==========================================

def _agregar_remisiones(ids_origen: list[str], ctx: ContextoAcumulado) -> Iterator[dict]:
    """Sigue REMITE_A desde `ids_origen`, agrega al contexto los artículos nuevos
    y emite un evento por cada uno."""
    for art in seguir_remite_a(neo4j_driver, ids_origen):
        origen_num = art.get("origen_numero", "")
        norma_ref  = art.get("norma", "")
        texto = formato_articulo(
            f"{norma_ref} (referenciada por Art. {origen_num})",
            art.get("numero", ""),
            art.get("texto", ""),
        )
        if ctx.agregar(art.get("id", ""), texto, fase="remision"):
            yield {"type": "item", "texto": f"Art. {art.get('numero', '')} ({norma_ref}) — citado por el Art. {origen_num}"}

# ==========================================
# 6. EVALUACIÓN DE SUFICIENCIA
# ==========================================

def _evaluar_suficiencia(pregunta: str, contexto: list[str]) -> tuple[bool, str]:
    """Evalúa si el contexto vectorial es suficiente para responder sin recurrir al grafo."""
    contexto_txt = "\n\n---\n\n".join(contexto) if contexto else "(ningún artículo recuperado)"
    prompt = f"""Eres un experto en derecho argentino (societario, civil, registral, notarial, penal \
y tributario). Evaluá si el contexto legal recuperado \
es SUFICIENTE para responder la pregunta del usuario de forma útil y precisa.

CRITERIO: Respondé "suficiente: true" si los artículos recuperados permiten dar una respuesta \
sustancialmente completa. Respondé "suficiente: false" SOLO si hay aspectos CENTRALES de la pregunta \
que los artículos no abordan en absoluto y cuya ausencia cambiaría materialmente la respuesta.

PREGUNTA:
{pregunta}

CONTEXTO RECUPERADO:
{contexto_txt}

Devolvé SOLO un JSON con este formato exacto:
{{"suficiente": true, "razon": "explicación breve de una línea"}}"""
    try:
        respuesta = llm_lite.invoke(prompt)
        data = json_del_llm(str(respuesta.content))
        return bool(data.get("suficiente", False)), str(data.get("razon", ""))
    except Exception as e:
        return False, f"Error al evaluar: {e}"


def particular(pregunta: str):
    """Resuelve una consulta particular: analiza, busca artículos, sigue remisiones, mira
    jurisprudencia, evalúa si alcanza y —solo si no alcanza— consulta el grafo.

    NO redacta ni gasta un token de redacción: eso lo hace el nodo `sintetizar`, que es
    común a los tres especialistas.

    Generador: emite eventos de progreso ("fase"/"item") y su `return` es el
    ContextoAcumulado final (ids, textos, y la fase que trajo cada cosa). Se consume con
    `yield from` desde un script, o con `_drenar()` desde un nodo del grafo; las dos formas
    preservan el orden exacto de los eventos.
    """
    yield {"type": "fase", "fase": "analisis", "label": "Analizando la consulta"}
    sujeto, frases_vectoriales = extraer_parametros_vectoriales(pregunta)
    if sujeto:
        yield {"type": "item", "texto": f"Sujeto identificado: {sujeto}"}

    ctx = ContextoAcumulado()

    # Fase 2: búsqueda vectorial. Se consulta cada frase (y la pregunta cruda) y
    # luego se filtra por sujeto; los duplicados alimentan la señal de frecuencia.
    yield {"type": "fase", "fase": "vectorial", "label": "Buscando artículos relevantes"}
    docs_raw = []
    for frase in frases_vectoriales + [pregunta]:
        for doc in _obtener_retriever().invoke(frase):
            docs_raw.append(doc)

    docs_filtrados = filtrar_por_sujeto(docs_raw, sujeto)

    for doc in docs_filtrados:
        if ctx.agregar(doc.metadata.get("id", ""), doc.page_content, fase="vectorial"):
            norma_display = doc.metadata.get('ley') or doc.metadata.get('norma_id', '?')
            yield {"type": "item", "texto": f"Art. {doc.metadata.get('art', '')} ({norma_display})"}

    # Fase 3.5 (primera pasada): remisiones explícitas desde lo recuperado en Fase 2.
    yield {"type": "fase", "fase": "remisiones", "label": "Siguiendo remisiones normativas"}
    yield from _agregar_remisiones(ctx.ids, ctx)

    # Fase 3.6: jurisprudencia. Va ANTES del gate de suficiencia a propósito: si un fallo
    # resuelve el punto, el gate lo ve y puede ahorrarse el Cypher dinámico.
    yield {"type": "fase", "fase": "jurisprudencia", "label": "Buscando jurisprudencia"}
    for doc in _obtener_retriever_jurisprudencia().invoke(pregunta):
        tribunal = doc.metadata.get("tribunal", "") or "Tribunal no identificado"
        fecha = doc.metadata.get("fecha", "")
        if ctx.agregar(doc.metadata.get("id", ""), doc.page_content, fase="jurisprudencia"):
            yield {"type": "item", "texto": f"{tribunal}{' — ' + fecha if fecha else ''}"}

    # Gate: ¿el contexto vectorial + remisiones ya alcanza? Si sí, se omite el
    # Cypher dinámico (la operación más cara del pipeline).
    yield {"type": "fase", "fase": "evaluacion", "label": "Evaluando suficiencia del contexto"}
    suficiente, razon = _evaluar_suficiencia(pregunta, ctx.textos)
    yield {"type": "item", "texto": ("Contexto suficiente — " if suficiente else "Contexto insuficiente — ") + razon}

    # Fase 3: Cypher dinámico (solo si el gate dio insuficiente).
    if not suficiente:
        yield {"type": "fase", "fase": "grafo", "label": "Consultando el grafo de conocimiento"}
        ids_antes_fase3 = list(ctx.ids)
        arts_grafo = _obtener_motor_cypher().consultar(pregunta)
        arts_grafo_nuevos = [a for a in arts_grafo if str(a.get("id", "")) and a.get("id") not in ctx]
        datos_grafo = datos_articulos(neo4j_driver, [str(a["id"]) for a in arts_grafo_nuevos])
        for art in arts_grafo_nuevos:
            art_id = str(art["id"])
            # La FUENTE es la norma real, no "Grafo Ontológico": el prompt de respuesta
            # exige citar la norma de cada afirmación y solo puede leerla de acá.
            norma = datos_grafo.get(art_id, {}).get("norma", "Norma no identificada")
            texto = formato_articulo(norma, art.get("numero", ""), art.get("texto", ""))
            if ctx.agregar(art_id, texto, fase="grafo"):
                yield {"type": "item", "texto": f"Art. {art.get('numero', '')} ({norma})"}

        # Fase 3.5 (segunda pasada): remisiones desde los artículos nuevos del grafo.
        ids_nuevos_fase3 = [i for i in ctx.ids if i not in ids_antes_fase3]
        if ids_nuevos_fase3:
            yield from _agregar_remisiones(ids_nuevos_fase3, ctx)

    return ctx


# ==========================================
# 7. FUENTES QUE VE EL USUARIO
# ==========================================

def fuentes_particular(ctx: ContextoAcumulado) -> list[dict]:
    """Traduce el contexto acumulado a la lista de citas que se le muestra al usuario.

    Vive acá y no en el nodo del grafo porque **es el especialista el que sabe qué recuperó**:
    sus ids son de dos clases distintas y solo él conoce la diferencia. El nodo se limita a
    llamar a esta función y poner el resultado en el estado.

    Cada fuente lleva un `tipo`, que es lo que le permite al frontend no escribir "Art." delante
    de un fallo:
        articulo -> {"numero": "77",                     "norma": "Ley 19.550"}
        fallo    -> {"numero": "CNCiv. Sala A",          "norma": "12/03/2015"}

    El `or art_id` del final es la red: si un id no aparece en el grafo (no debería pasar, pero
    pasaría con datos inconsistentes) se muestra el id crudo en vez de romper la respuesta.
    """
    ids_fallos = [i for i in ctx.ids if ctx.fases.get(i) == "jurisprudencia"]
    ids_articulos = [i for i in ctx.ids if i not in ids_fallos]

    datos_art = datos_articulos(neo4j_driver, ids_articulos)
    datos_fallo = _datos_fallos(ids_fallos)

    fuentes = []
    for nodo_id in ctx.ids:
        if nodo_id in datos_fallo:
            d = datos_fallo[nodo_id]
            fuentes.append({"id": nodo_id, "tipo": "fallo",
                            "numero": d["tribunal"] or nodo_id, "norma": d["fecha"] or "Jurisprudencia"})
        else:
            d = datos_art.get(nodo_id, {})
            fuentes.append({"id": nodo_id, "tipo": "articulo",
                            "numero": d.get("numero") or nodo_id, "norma": d.get("norma") or "?"})
    return fuentes


def _datos_fallos(ids: list[str]) -> dict[str, dict]:
    """{id: {"tribunal", "fecha"}} para los fallos dados. Usa el índice `jurisprudencia_id`,
    que es el único índice sobre `.id` que existe en el grafo."""
    if not ids:
        return {}
    query = """
    UNWIND $ids AS fallo_id
    MATCH (j:Jurisprudencia {id: fallo_id})
    RETURN fallo_id, coalesce(j.tribunal, '') AS tribunal, coalesce(j.fecha, '') AS fecha
    """
    with neo4j_driver.session() as session:
        return {r["fallo_id"]: {"tribunal": r["tribunal"], "fecha": r["fecha"]}
                for r in session.run(query, ids=ids)}
