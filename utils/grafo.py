"""Consultas Cypher de solo lectura sobre el grafo de conocimiento, compartidas por el
pipeline RAG y los scripts de `exploration/`. El driver se recibe siempre por parámetro
(nunca un global de módulo) para que el mismo helper sirva a ambos sin duplicar drivers.
"""
from utils.citas import NOMBRE_NORMA

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
