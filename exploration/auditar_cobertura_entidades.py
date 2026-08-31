"""Audita huecos de vinculación artículo → entidad de ontología.

Busca artículos que el LLM de extracción dejó sin conectar a una entidad que sus vecinos
de la misma `ubicacion` sí tienen. El caso que originó el script: los Arts. 34 y 35 del
Decreto 2080/80 quedaron vinculados a `TractoSucesivo` y los Arts. 36 y 37 no, estando los
cuatro en el mismo "CAPITULO IX - DEL TRACTO".

Es una heurística, no una verdad: un artículo puede legítimamente no tratar la entidad
dominante de su capítulo. La salida es una lista de candidatos para revisión manual.

Los candidatos se separan en dos grupos, porque su tasa de acierto es muy distinta:
  - HUERFANOS: el artículo no tiene NINGUNA entidad. Casi siempre es un hueco real.
  - CLASIFICADOS DISTINTO: el artículo tiene otra entidad, más específica y correcta
    (ej. Art. 287 CCyCN → InstrumentoPrivado, no InstrumentoPublico). Mayormente ruido.

No escribe nada en Neo4j. Los hallazgos se registran en `inconsistencias.md`.

Uso:
    python exploration/auditar_cobertura_entidades.py [cobertura_minima]   # default 0.8
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from utils.connectors import get_neo4j_driver

# Un grupo de una sola entidad y un solo artículo no tiene con qué comparar.
MIN_ARTICULOS_GRUPO = 2

SIN_ENTIDAD = """
MATCH (n:Norma)-[:CONTIENE]->(a:Articulo)
WHERE a.vigente = true
  AND NOT EXISTS { (a)-[]-(e) WHERE NOT e:Norma AND NOT e:Articulo AND NOT e:VersionHistorica }
RETURN n.id AS norma, count(a) AS articulos, collect(a.id)[..8] AS muestra
ORDER BY articulos DESC
"""

COBERTURA_PARCIAL = """
MATCH (n:Norma)-[:CONTIENE]->(a:Articulo)
WHERE a.vigente = true AND a.ubicacion IS NOT NULL
WITH n, a.ubicacion AS ubi, collect(a) AS arts
WHERE size(arts) >= $min_arts
UNWIND arts AS art
OPTIONAL MATCH (art)-[]-(e)
WHERE NOT e:Norma AND NOT e:Articulo AND NOT e:VersionHistorica
WITH n, ubi, arts, e, collect(DISTINCT art.id) AS con_entidad
WHERE e IS NOT NULL AND size(con_entidad) < size(arts)
WITH n.id AS norma, ubi, labels(e)[0] AS entidad,
     size(con_entidad) AS con, size(arts) AS total,
     toFloat(size(con_entidad)) / size(arts) AS cobertura,
     [x IN [a IN arts | a.id] WHERE NOT x IN con_entidad] AS faltantes
WHERE cobertura >= $cobertura_min
RETURN norma, ubi, entidad, con, total, cobertura, faltantes
ORDER BY cobertura DESC, total DESC
"""

# Los artículos sin ninguna entidad son los candidatos de alta confianza.
HUERFANOS = """
UNWIND $ids AS aid
MATCH (a:Articulo {id: aid})
WHERE NOT EXISTS { (a)-[]-(e) WHERE NOT e:Norma AND NOT e:Articulo AND NOT e:VersionHistorica }
RETURN collect(a.id) AS huerfanos
"""


def main():
    cobertura_min = float(sys.argv[1]) if len(sys.argv) > 1 else 0.8
    driver = get_neo4j_driver()

    with driver.session() as session:
        sin_entidad = [dict(r) for r in session.run(SIN_ENTIDAD)]
        parciales = [
            dict(r) for r in session.run(
                COBERTURA_PARCIAL, min_arts=MIN_ARTICULOS_GRUPO, cobertura_min=cobertura_min
            )
        ]

    total_sin = sum(r["articulos"] for r in sin_entidad)
    print(f"\n=== Artículos vigentes sin ninguna entidad de ontología: {total_sin} ===")
    for r in sin_entidad:
        print(f"  {r['articulos']:>4}  {r['norma']}")
        print(f"        {', '.join(r['muestra'])}")

    faltantes = sorted({f for r in parciales for f in r["faltantes"]})
    with driver.session() as session:
        huerfanos = set(session.run(HUERFANOS, ids=faltantes).single()["huerfanos"])

    for titulo, solo_huerfanos in [("HUÉRFANOS (alta confianza)", True),
                                   ("CLASIFICADOS DISTINTO (revisar, mayormente ruido)", False)]:
        grupos = [
            (r, [f for f in r["faltantes"] if (f in huerfanos) == solo_huerfanos])
            for r in parciales
        ]
        grupos = [(r, fs) for r, fs in grupos if fs]
        entidades = sorted({r["entidad"] for r, _ in grupos})
        print(f"\n=== {titulo} — cobertura >= {cobertura_min:.0%}: "
              f"{len(grupos)} grupos | {len(entidades)} entidades ===")
        for r, fs in grupos:
            print(f"  [{r['entidad']}] {r['con']}/{r['total']} ({r['cobertura']:.0%})  "
                  f"{r['norma']} | {r['ubi']}")
            print(f"      faltan: {', '.join(fs)}")
        print(f"  Entidades: {', '.join(chr(34) + e + chr(34) for e in entidades)}")


if __name__ == "__main__":
    main()
