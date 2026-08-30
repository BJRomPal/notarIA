"""Re-resuelve las remisiones REMITE_A de todas las DTR ya cargadas.

`ingest_dtr.py` saltea las DTR que ya existen en el grafo, así que una mejora en
`resolver_remisiones()` no alcanza a las normas ingeridas antes. Este script recorre los
archivos fuente y vuelve a correr solo la resolución de remisiones sobre los artículos que
ya están en Neo4j: no crea ni modifica nodos, no recalcula embeddings, únicamente agrega
relaciones REMITE_A faltantes (MERGE, así que es idempotente).

    python exploration/reresolver_remisiones_dtr.py            # simulación
    python exploration/reresolver_remisiones_dtr.py --aplicar
"""
import os
import re
import sys
import glob
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

sys.path.insert(0, os.path.join(BASE_DIR, "extractors"))
import ingest_dtr as ing

APLICAR = "--aplicar" in sys.argv
DTR_DIR = ing.DTR_DIR


def main():
    cache, pendientes = {}, defaultdict(set)
    nuevas, ya_estaban = [], 0

    anios = sorted([d for d in os.listdir(DTR_DIR) if os.path.isdir(os.path.join(DTR_DIR, d))],
                   key=int)
    for anio in anios:
        for path in sorted(glob.glob(os.path.join(DTR_DIR, anio, "*.txt"))):
            m = re.match(r'dtr\s+(\d+)-(\d+)\.txt', os.path.basename(path), re.IGNORECASE)
            if not m:
                continue
            norma_id = f"DTR_{m.group(1)}_{anio}"
            texto_completo = open(path, encoding="utf-8").read()
            if not texto_completo.strip():
                continue
            _, _, articulos = ing.parsear_dtr(texto_completo)
            for numero, texto_art in articulos:
                art_id = f"Art_{numero}_{norma_id}"
                with ing.driver.session() as s:
                    if not s.run("MATCH (a:Articulo {id:$i}) RETURN a.id", i=art_id).single():
                        continue
                for origen, destino in ing.resolver_remisiones(
                        art_id, texto_art, int(anio), cache, pendientes):
                    with ing.driver.session() as s:
                        existe = s.run("MATCH (:Articulo {id:$o})-[:REMITE_A]->(b) "
                                       "WHERE b.id = $d RETURN 1 LIMIT 1", o=origen, d=destino).single()
                    if existe:
                        ya_estaban += 1
                    else:
                        nuevas.append((origen, destino))

    print(f"Remisiones ya presentes : {ya_estaban}")
    print(f"Remisiones NUEVAS       : {len(nuevas)}\n")
    por_norma = defaultdict(list)
    for o, d in nuevas:
        por_norma[d.split("_", 2)[-1]].append((o, d))
    for norma in sorted(por_norma):
        print(f"  -> {norma}  ({len(por_norma[norma])})")
        for o, d in sorted(por_norma[norma]):
            print(f"       {o}  ->  {d}")

    if APLICAR:
        with ing.driver.session() as s:
            for o, d in nuevas:
                s.run("""MATCH (a:Articulo {id:$o})
                         OPTIONAL MATCH (art:Articulo {id:$d})
                         OPTIONAL MATCH (nor:Norma {id:$d})
                         WITH a, coalesce(art, nor) AS b WHERE b IS NOT NULL
                         MERGE (a)-[:REMITE_A]->(b)""", o=o, d=d)
        print(f"\n{len(nuevas)} relaciones creadas.")
    else:
        print(f"\n(simulación — usar --aplicar para crear las {len(nuevas)} relaciones)")


if __name__ == "__main__":
    main()
