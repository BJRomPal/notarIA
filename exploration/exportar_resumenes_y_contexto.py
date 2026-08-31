"""Vuelca a dos archivos el estado actual de los resúmenes de entidades de ontología.

El master `resumenes_entidades_completo.txt` se fue quedando atrás del grafo: cada vez que
se corrigen vinculaciones y se regenera un resumen, la versión buena queda en Neo4j y el
archivo conserva la vieja. Este script invierte la dirección — **el grafo es la fuente de
verdad** — y produce un snapshot completo y consistente:

  resumenes_entidades_<fecha>.txt  — el n.resumen de cada entidad
  contexto_entidades_<fecha>.txt   — los artículos que sustentan cada resumen

Ambos respetan el formato de bloques que ya usa el proyecto (cabecera ENTIDAD + separador),
de modo que cargar_resumenes_entidades.py puede leer el primero sin cambios.

No escribe nada en Neo4j.

Uso:
    python exploration/exportar_resumenes_y_contexto.py
"""
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "exploration"))

import generar_resumenes_entidades as g
from utils.connectors import get_neo4j_driver

SEPARADOR = "=" * 70
CIERRE = "-" * 70

# Jurisprudencia no es una entidad de ontología: son fallos, con su propio índice vectorial
# y sin relaciones con artículos. Los estructurales tampoco llevan resumen de este tipo.
EXCLUIDOS = "NOT n:Articulo AND NOT n:Norma AND NOT n:VersionHistorica AND NOT n:Jurisprudencia"


def listar_entidades(driver) -> list[dict]:
    with driver.session() as s:
        return [dict(r) for r in s.run(f"""
            MATCH (n) WHERE {EXCLUIDOS} AND n.resumen IS NOT NULL
            RETURN labels(n)[0] AS etiqueta, n.id AS id, n.resumen AS resumen
            ORDER BY etiqueta
        """)]


def main():
    fecha = time.strftime("%Y%m%d")
    ruta_resumenes = os.path.join(g.DIR_SALIDA, f"resumenes_entidades_{fecha}.txt")
    ruta_contexto = os.path.join(g.DIR_SALIDA, f"contexto_entidades_{fecha}.txt")

    driver = get_neo4j_driver()
    entidades = listar_entidades(driver)
    print(f"entidades con resumen: {len(entidades)}")
    print(f"resúmenes -> {ruta_resumenes}")
    print(f"contexto  -> {ruta_contexto}")

    sin_articulos = []
    with open(ruta_resumenes, "w", encoding="utf-8") as f_res, \
         open(ruta_contexto, "w", encoding="utf-8") as f_ctx:

        for i, e in enumerate(entidades, 1):
            etiqueta, entidad_id = e["etiqueta"], e["id"]
            _, directos, adicionales = g.reunir_contexto_con_reintento(etiqueta)
            if not directos:
                sin_articulos.append(etiqueta)

            cabecera = (f"ENTIDAD: {etiqueta} (id: {entidad_id}) — "
                        f"{len(directos)} directos + {len(adicionales)} por remisión\n")

            f_res.write(cabecera + SEPARADOR + "\n\n" + e["resumen"].strip() + "\n\n")

            f_ctx.write(cabecera + SEPARADOR + "\n\n")
            for d in directos:
                f_ctx.write(f"[{g.citar(d)}]  ({d['art']})\n{d['texto']}\n\n")
            for a in adicionales:
                f_ctx.write(f"[{g.citar(a)} — remisión]  ({a['art']})\n{a['texto']}\n\n")
            f_ctx.write(CIERRE + "\n\n")

            if i % 100 == 0:
                print(f"  {i}/{len(entidades)}...")

    print(f"\nlisto: {len(entidades)} bloques en cada archivo")
    print(f"resúmenes: {os.path.getsize(ruta_resumenes):,} bytes")
    print(f"contexto:  {os.path.getsize(ruta_contexto):,} bytes")
    if sin_articulos:
        print(f"entidades con resumen pero sin artículos conectados ({len(sin_articulos)}): "
              f"{', '.join(sin_articulos)}")


if __name__ == "__main__":
    main()
