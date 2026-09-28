"""¿Un artículo citado expresamente se trae exacto, sin depender de un modelo?

Nació de un error real (2026-09-28): «¿Qué dicen los artículos 36 y 37 de la ley 27349?» volvió
sin los dos artículos, que están cargados. La búsqueda vectorial trajo los arts. 36 y 37 de OTRAS
normas —los embeddings captan «artículo 36» pero no el número de ley— y el Text-to-Cypher armó
`art.numero IN [36, 37]` comparando con números, cuando en el grafo `numero` es texto.

Dos niveles, como test_jurisprudencia.py:

1. **El analizador** (`buscar_referencias`), contra un catálogo armado a mano: no toca la base.
   Cubre cómo escribe un escribano una cita: con y sin puntos en el número de ley, «N°», «arts. 36
   y 37», rangos, «bis», «1º», la norma antes o después, alias (LSC, CCyCN) y lo que NO es una cita.
2. **La resolución contra el grafo** (`catalogo_normas` + `resolver_referencias`), con Neo4j vivo:
   que traiga los ids exactos, que informe lo que no está cargado y que marque lo derogado.

Script suelto, sin pytest. Sale con código 1 si algo falla.

    .venv/bin/python tests/test_citas_exactas.py            # los dos niveles
    .venv/bin/python tests/test_citas_exactas.py --sin-base # solo el analizador
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from utils.rag.referencias import Catalogo, buscar_referencias, catalogo_normas, resolver_referencias

fallos: list[str] = []


def verificar(condicion: bool, descripcion: str, detalle: str = ""):
    estado = "OK  " if condicion else "FALLA"
    print(f"  [{estado}] {descripcion}")
    if not condicion:
        if detalle:
            print(f"          {detalle}")
        fallos.append(descripcion)


# Un catálogo chico con las formas reales del grafo: números con y sin puntos, decretos con año de
# dos dígitos cuyo id lleva cuatro, y una norma que se cita por su nombre.
CATALOGO = Catalogo.desde_filas([
    {"id": "Ley_27349", "tipo": "Ley", "numero": "27349", "nombre": "Ley 27349"},
    {"id": "Ley_19550", "tipo": "Ley", "numero": "19.550", "nombre": "Ley 19.550"},
    {"id": "Ley_404", "tipo": "Ley", "numero": "404", "nombre": "Ley 404"},
    {"id": "CCyCN", "tipo": "Codigo", "numero": "26994", "nombre": "CCyCN"},
    {"id": "Ley_11179", "tipo": "Ley", "numero": "11.179", "nombre": "Código Penal"},
    {"id": "Decreto_2080_1980", "tipo": "Decreto", "numero": "2080/80", "nombre": "Decreto 2080/80"},
    {"id": "RG_15_2024", "tipo": "ResolucionGeneral", "numero": "15/2024", "nombre": "RG 15/2024"},
    {"id": "RG_242_2023", "tipo": "Resolución", "numero": "242/2023", "nombre": "RG 242/2023"},
    {"id": "DTR_5_2019", "tipo": "DisposicionTecnicoRegistral", "numero": "5/19", "nombre": "DTR 5/2019"},
    {"id": "IT_3_2016", "tipo": "InstruccionDeTrabajo", "numero": "3/2016", "nombre": "IT 3/2016"},
])

CASOS = [
    # (consulta, [(norma_id, [artículos])])
    ("Que dicen los articulos 36 y 37 de la ley 27349?", [("Ley_27349", ["36", "37"])]),
    ("¿Qué dicen los artículos 36 y 37 de la Ley N° 27.349?", [("Ley_27349", ["36", "37"])]),
    ("¿Qué exige el art. 77 LSC?", [("Ley_19550", ["77"])]),
    ("art 94 bis de la ley 19.550", [("Ley_19550", ["94 bis"])]),
    ("¿Qué establece el artículo 1017 del Código Civil y Comercial?", [("CCyCN", ["1017"])]),
    ("artículo 1017 del CCyCN", [("CCyCN", ["1017"])]),
    ("arts. 3 a 5 de la Ley 404", [("Ley_404", ["3", "4", "5"])]),
    ("artículos 3, 4 y 6 de la ley 404", [("Ley_404", ["3", "4", "6"])]),
    ("En la Ley 404, ¿qué dice el art. 1º?", [("Ley_404", ["1"])]),
    ("Decreto 2080/80, art. 105", [("Decreto_2080_1980", ["105"])]),
    ("art. 105 del decreto 2080/1980", [("Decreto_2080_1980", ["105"])]),
    ("art. 70 de la RG IGJ 15/2024", [("RG_15_2024", ["70"])]),
    ("artículo 28 de la Resolución UIF 242/2023", [("RG_242_2023", ["28"])]),
    ("DTR 5/2019 art. 2", [("DTR_5_2019", ["2"])]),
    ("art. 1 de la IT 3/2016", [("IT_3_2016", ["1"])]),
    ("art. 36 de la ley 27349 y art. 77 de la LSC", [("Ley_27349", ["36"]), ("Ley_19550", ["77"])]),
    ("art. 149 bis del Código Penal", [("Ley_11179", ["149 bis"])]),
    # Varios grupos: cada uno con su norma, o heredándola del grupo encadenado.
    ("art. 36 y art. 37 de la ley 27349", [("Ley_27349", ["36", "37"])]),
    ("ley 27349, art. 36 y art. 37", [("Ley_27349", ["36", "37"])]),
    ("según la ley 27349, el art. 36 y el art. 5 de la LSC", [("Ley_27349", ["36"]), ("Ley_19550", ["5"])]),
    # Lo que NO es una cita resoluble: no se inventa nada.
    ("¿Qué dice el art. 36?", []),
    ("¿Qué es la hipoteca?", []),
    ("La ley 27349 creó la SAS", []),
    ("art. 5 de la ley 99999", []),
]


def nivel_analizador():
    print("\nNIVEL 1 — EL ANALIZADOR (sin base)")
    for consulta, esperado in CASOS:
        obtenido = [(r.norma_id, r.articulos) for r in buscar_referencias(consulta, CATALOGO)]
        verificar(obtenido == esperado, consulta, f"esperado {esperado}, vino {obtenido}")
    # Un rango absurdo no puede vaciar un código entero en el prompt.
    refs = buscar_referencias("arts. 1 a 2000 del CCyCN", CATALOGO)
    verificar(bool(refs) and len(refs[0].articulos) <= 20, "un rango enorme se recorta",
              f"vinieron {len(refs[0].articulos) if refs else 0} artículos")


def nivel_grafo():
    print("\nNIVEL 2 — LA RESOLUCIÓN CONTRA EL GRAFO")
    from utils.connectors import get_neo4j_driver
    driver = get_neo4j_driver()
    catalogo = catalogo_normas(driver)
    verificar(len(catalogo.nombres) >= 198, "el catálogo tiene todas las normas", f"{len(catalogo.nombres)}")

    def resolver(consulta):
        return resolver_referencias(driver, buscar_referencias(consulta, catalogo))

    encontrados, faltantes = resolver("¿Qué dicen los artículos 36 y 37 de la ley 27349?")
    verificar([a["id"] for a in encontrados] == ["Art_36_Ley_27349", "Art_37_Ley_27349"],
              "el caso que falló trae los dos artículos exactos", str([a["id"] for a in encontrados]))
    verificar(all(a["texto"].startswith("Artículo 3") for a in encontrados), "con su texto")
    verificar(faltantes == [], "y no informa faltantes", str(faltantes))

    encontrados, faltantes = resolver("art. 5 de la ley 27349")
    verificar(encontrados == [] and faltantes == [("Ley 27349", "5")],
              "un artículo no cargado se informa como faltante", f"{encontrados} / {faltantes}")

    encontrados, _ = resolver("En la Ley 17.801, ¿qué dice el art. 9?")
    verificar([a["id"] for a in encontrados] == ["Art_9_Ley_17801"] and encontrados[0]["numero"] == "9º",
              "«art. 9» encuentra el que está guardado como «9º»", str(encontrados[:1]))

    encontrados, _ = resolver("art. 94 bis de la LSC")
    verificar([a["id"] for a in encontrados] == ["Art_94_bis_Ley_19550"], "encuentra un «bis»",
              str([a["id"] for a in encontrados]))

    encontrados, _ = resolver("art. 105 de la RG 15/2024")
    verificar(len(encontrados) == 1 and encontrados[0]["vigente"] is False,
              "un artículo derogado vuelve marcado como no vigente", str(encontrados[:1]))


def main() -> int:
    nivel_analizador()
    if "--sin-base" not in sys.argv:
        nivel_grafo()
    if fallos:
        print(f"\n{len(fallos)} FALLAS:")
        for f in fallos:
            print(f"  - {f}")
        return 1
    print("\nTodo en orden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
