"""Script de exploración: lista todos los nodos del grafo excepto Articulo y Norma,
agrupados por etiqueta y marcando IDs duplicados para auditar la calidad de la ingesta."""
import os
from collections import defaultdict
from dotenv import load_dotenv
from neo4j import GraphDatabase

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

NEO4J_URI = os.getenv("NEO4J_URI") or ""
NEO4J_USER = os.getenv("NEO4J_USERNAME") or ""
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD") or ""

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# Articulo y Norma son los nodos más numerosos y bien controlados; se excluyen para
# enfocarse en auditar la variedad y duplicados de los nodos de ontología (roles, conceptos, etc.).
query = """
MATCH (n)
WHERE NOT n:Articulo AND NOT n:Norma
RETURN labels(n)[0] AS etiqueta, n.id AS id, count(n) AS cantidad
ORDER BY etiqueta, cantidad DESC, id
"""

with driver.session() as session:
    resultados = list(session.run(query))

# Agrupar por etiqueta para imprimir ordenado
por_etiqueta = defaultdict(list)
for row in resultados:
    por_etiqueta[row["etiqueta"]].append((row["id"], row["cantidad"]))

total = 0
for etiqueta in sorted(por_etiqueta):
    nodos = por_etiqueta[etiqueta]
    print(f"\n── {etiqueta} ({len(nodos)} nodos) ──────────────────────────")
    for nodo_id, cantidad in nodos:
        marca = " ⚠ DUPLICADO" if cantidad > 1 else ""
        print(f"  [{cantidad}]  {nodo_id}{marca}")
    total += len(nodos)

print(f"\nTotal: {total} nodos (excluidos Articulo y Norma)")

driver.close()
