"""Consultas Cypher de solo lectura sobre el grafo de conocimiento, compartidas por el
pipeline RAG y los scripts de `exploration/`. El driver se recibe siempre por parámetro
(nunca un global de módulo) para que el mismo helper sirva a ambos sin duplicar drivers.
"""
from utils.rag.citas import NOMBRE_NORMA

# Labels que no son entidades de ontología: los estructurales del grafo y Jurisprudencia
# (fallos, con su propio índice vectorial, sin relaciones con artículos).
EXCLUSION_DEFAULT = {"Articulo", "Norma", "VersionHistorica", "Jurisprudencia"}


def etiquetas_ontologia(driver, excluir: set[str] | None = None) -> list[str]:
    """Labels reales de entidades de ontología presentes en el grafo, ordenados.

    No es la misma exclusión en todos lados —el pipeline excluye además :Jurisprudencia—,
    así que el conjunto de exclusiones es un parámetro, con el del pipeline por defecto.
    """
    if excluir is None:
        excluir = EXCLUSION_DEFAULT
    clausulas = " AND ".join(f"NOT n:{label}" for label in sorted(excluir))
    query = f"""
        MATCH (n) WHERE {clausulas}
        RETURN DISTINCT labels(n)[0] AS label
        ORDER BY label
    """
    with driver.session() as session:
        return [row["label"] for row in session.run(query) if row["label"]]


def seguir_remite_a(driver, article_ids: list[str]) -> list[dict]:
    """Dado un conjunto de artículos, devuelve los artículos referenciados vía REMITE_A."""
    if not article_ids:
        return []
    query = f"""
    UNWIND $ids AS art_id
    MATCH (origen:Articulo {{id: art_id}})-[:REMITE_A]->(referenciado:Articulo)
    WHERE referenciado.texto IS NOT NULL
    OPTIONAL MATCH (norma:Norma)-[:CONTIENE]->(referenciado)
    RETURN DISTINCT
        referenciado.id     AS id,
        referenciado.numero AS numero,
        referenciado.texto  AS texto,
        {NOMBRE_NORMA}      AS norma,
        origen.numero       AS origen_numero
    """
    with driver.session() as session:
        return [dict(row) for row in session.run(query, ids=article_ids)]


def datos_articulos(driver, article_ids: list[str]) -> dict[str, dict]:
    """Devuelve {article_id: {"numero", "norma"}} para los artículos dados.

    El número y la norma se leen del grafo y nunca se derivan del id: los ids no
    tienen un formato único (Art_163_Ley_19550, Art_1_CCyCN, Art_1_DTR_5_2019).
    """
    if not article_ids:
        return {}
    query = f"""
    UNWIND $ids AS art_id
    MATCH (norma:Norma)-[:CONTIENE]->(art:Articulo {{id: art_id}})
    RETURN art_id,
           art.numero AS numero,
           {NOMBRE_NORMA} AS norma
    """
    with driver.session() as session:
        return {
            row["art_id"]: {"numero": row["numero"], "norma": row["norma"]}
            for row in session.run(query, ids=article_ids)
        }


def entidades_relacionadas(driver, article_ids: list[str]) -> list[dict]:
    if not article_ids:
        return []
    query = """
    UNWIND $ids AS art_id
    MATCH (art:Articulo {id: art_id})-[r]-(entidad)
    WHERE NOT entidad:Norma AND NOT entidad:Articulo AND NOT entidad:VersionHistorica
    RETURN DISTINCT
        labels(entidad)[0] AS tipo,
        entidad.id         AS id,
        type(r)            AS relacion,
        art_id             AS articulo
    ORDER BY tipo, id
    """
    with driver.session() as session:
        return [dict(row) for row in session.run(query, ids=article_ids)]


def format_entidades(entidades: list[dict]) -> str:
    if not entidades:
        return ""
    lines = ["\n\nENTIDADES JURÍDICAS RELACIONADAS:"]
    for e in entidades:
        lines.append(f"  [{e['tipo']}] {e['id']}  —  {e['relacion']}  →  Art. {e['articulo']}")
    return "\n".join(lines)


# ==========================================================================================
# RECUPERACIÓN ENTIDAD-PRIMERO (especialista general)
# ==========================================================================================
# El pipeline particular busca artículos y deduce el instituto. Acá se invierte: se busca el
# instituto y se devuelve su resumen, que es un texto sintetizado que ya cita norma y
# artículo por dentro. Para eso se generaron los resúmenes (exploration/).
#
# POR QUÉ FUERZA BRUTA Y NO UN ÍNDICE VECTORIAL: un índice vectorial de Neo4j se declara
# sobre UN label, y las 566 entidades de ontología tienen 566 labels distintos, uno cada una
# (:SociedadAnonima, :Hipoteca, :Usufructo...). No hay un label común sobre el cual crearlo,
# y agregarlo rompería `labels(n)[0]`, que este mismo archivo usa para leer el tipo. La
# alternativa es calcular el coseno contra las 566: medido contra Aura, 288-1020 ms.

# Cuántas entidades se traen como máximo, y a qué distancia del mejor score se corta.
# Ambos valores salen de medir, no de la intuición (ver el documento de arquitectura):
#   - Con K_ENTIDADES=3, «diferencias entre la SA y la SRL» devolvía SRL, SociedadPorAcciones
#     y SAS: la SOCIEDAD_ANONIMA quedaba cuarta y afuera, o sea que el modelo habría
#     comparado la SRL contra el tipo equivocado. Por eso 5.
#   - El margen evita el problema opuesto: en «¿qué requisitos debe cumplir el usufructo?»
#     el USUFRUCTO saca 0,888 y el siguiente 0,858, así que traer 5 sería sumar 34.000
#     caracteres de ruido. Con el margen se trae una sola entidad.
K_ENTIDADES = 5
MARGEN_SCORE = 0.03


def entidades_similares(driver, vector: list[float], k: int = K_ENTIDADES,
                        margen: float = MARGEN_SCORE) -> list[dict]:
    """Entidades de ontología semánticamente cercanas a un vector, con su resumen.

    Devuelve como máximo `k`, y descarta las que estén a más de `margen` por debajo del
    mejor score: así una pregunta amplia (dos institutos) trae varias y una precisa trae
    una sola, sin tener que adivinar el número de antemano.

    El resumen viene completo a propósito. Son textos de 2.600 a 20.700 caracteres,
    estructurados por secciones, y las diferencias entre dos institutos están repartidas a
    lo largo de todo el texto: truncar corta justo lo que se está preguntando.

    Devuelve [{"id", "label", "nombre", "resumen", "score"}], de mayor a menor score.
    """
    query = """
    MATCH (e)
    WHERE e.embedding IS NOT NULL AND e.resumen IS NOT NULL
      AND NOT e:Articulo AND NOT e:Norma AND NOT e:VersionHistorica AND NOT e:Jurisprudencia
    WITH e, vector.similarity.cosine(e.embedding, $vector) AS score
    ORDER BY score DESC LIMIT $k
    RETURN e.id AS id, labels(e)[0] AS label, e.nombre AS nombre, e.resumen AS resumen, score
    """
    with driver.session() as session:
        filas = [dict(row) for row in session.run(query, vector=vector, k=k)]
    if not filas:
        return []
    piso = filas[0]["score"] - margen
    return [f for f in filas if f["score"] >= piso]


# Cuántas etiquetas se le muestran al motor Text-to-Cypher. Sale de medir en qué posición
# aparece la etiqueta correcta al ordenar las 566 por similitud con la pregunta: en 9 de 10
# casos está primera o segunda. El único caso que se va lejos es «¿qué exige la IGJ para
# inscribir una transformación?», donde `Transformacion` cae en la posición 16 porque "IGJ"
# domina la señal y arrastra entidades institucionales. Con 20 entran los 10 casos medidos, y
# 20 etiquetas son ~400 caracteres contra los 11.390 de pasarlas todas.
K_ETIQUETAS_CYPHER = 20


def etiquetas_similares(driver, vector: list[float], k: int = K_ETIQUETAS_CYPHER) -> list[str]:
    """Las `k` etiquetas de entidad más cercanas a un vector, sin traer los resúmenes.

    Es el subconjunto del esquema que se le muestra al modelo que escribe Cypher, en vez de
    las 566 etiquetas completas. La documentación de Neo4j sobre Text2Cypher llama a eso
    "oversized schemas" y lo marca como anti-patrón: recomienda recuperar por similitud solo
    la porción relevante, que es exactamente esto.

    NO reusa `entidades_similares()` a propósito, aunque la consulta se parezca: aquella
    devuelve el `resumen` de cada entidad —de 2.600 a 20.700 caracteres— porque su consumidor
    es el especialista general, que necesita el texto. Acá solo hace falta el nombre de la
    etiqueta, y traer cinco resúmenes para descartarlos serían 90.000 caracteres por la red en
    cada consulta al grafo.
    """
    query = """
    MATCH (e)
    WHERE e.embedding IS NOT NULL
      AND NOT e:Articulo AND NOT e:Norma AND NOT e:VersionHistorica AND NOT e:Jurisprudencia
    WITH e, vector.similarity.cosine(e.embedding, $vector) AS score
    ORDER BY score DESC LIMIT $k
    RETURN labels(e)[0] AS label
    """
    with driver.session() as session:
        return [row["label"] for row in session.run(query, vector=vector, k=k) if row["label"]]
