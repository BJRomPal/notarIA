"""Regenera y carga el resumen de una o más entidades de ontología puntuales.

Reemplaza a los scripts de lote ad-hoc que se iban creando para cada tanda de correcciones
(regenerar_resumenes_sesion, _ccycn_rg15, _inconsistencias, resumir_entidades_firma): en vez
de una lista fija en el código, las entidades se pasan por línea de comandos.

A diferencia de generar_resumenes_entidades.py, que vuelca a archivos para revisión manual,
este escribe directamente en Neo4j: resumen nuevo con Qwen y embedding nuevo con Gemini. Es
el camino para cuando se corrigen vinculaciones de una entidad y hay que ponerla al día.

El texto generado se imprime por salida estándar para poder revisarlo. Para reconstruir los
archivos master después de varias corridas: exportar_resumenes_y_contexto.py.

Uso:
    python exploration/regenerar_resumen_entidad.py TractoSucesivo
    python exploration/regenerar_resumen_entidad.py ActaNotarial Certificado Superficie
"""
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from exploration import generar_resumenes_entidades as g
from langchain_ollama import ChatOllama
from utils.connectors import get_neo4j_driver, get_gemini_embeddings
from utils.extractor_base import embed_con_reintento
from utils.rag.grafo import etiquetas_ontologia

driver = get_neo4j_driver()


def regenerar(etiqueta: str, embedder) -> bool:
    entidad_id, directos, adicionales = g.reunir_contexto_con_reintento(etiqueta)
    if entidad_id is None:
        print(f"  {etiqueta}: la entidad no existe en el grafo")
        return False
    if not directos:
        print(f"  {etiqueta}: sin artículos conectados, no hay con qué generar el resumen")
        return False

    t0 = time.time()
    prompt = g.armar_prompt(etiqueta, entidad_id, directos, adicionales)
    num_ctx = g.calcular_num_ctx(prompt)
    print(f"  {etiqueta} (id={entidad_id}): {len(directos)} directos + {len(adicionales)} "
          f"por remisión | num_ctx={num_ctx} | generando con {g.MODELO}...")

    texto = ChatOllama(model=g.MODELO, temperature=0.2, num_ctx=num_ctx,
                       reasoning=False).invoke(prompt).content
    if not texto:
        print(f"  {etiqueta}: el modelo devolvió una respuesta vacía")
        return False
    texto = texto.strip()

    embedding = embed_con_reintento(embedder, texto)
    if embedding is None:
        print(f"  {etiqueta}: no se pudo calcular el embedding, no se escribe nada")
        return False

    with driver.session() as s:
        antes = s.run("MATCH (n {id:$i}) RETURN size(n.resumen) AS l", i=entidad_id).single()
        s.execute_write(lambda tx: tx.run(
            "MATCH (n {id:$i}) SET n.resumen=$t, n.embedding=$e",
            i=entidad_id, t=texto, e=embedding))

    previo = antes["l"] if antes and antes["l"] is not None else 0
    print(f"  {etiqueta}: cargado | {previo} -> {len(texto)} caracteres | "
          f"embedding {len(embedding)} dims | {time.time()-t0:.0f}s")
    print(f"\n{'=' * 70}\nENTIDAD: {etiqueta} (id: {entidad_id}) — "
          f"{len(directos)} directos + {len(adicionales)} por remisión\n{'=' * 70}\n")
    print(texto + "\n")
    return True


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    pedidas = sys.argv[1:]
    validas = set(etiquetas_ontologia(driver))
    if desconocidas := [e for e in pedidas if e not in validas]:
        for e in desconocidas:
            parecidas = sorted(v for v in validas if e.lower()[:6] in v.lower())
            print(f"Etiqueta desconocida: {e}"
                  + (f" — ¿quisiste decir {', '.join(parecidas[:5])}?" if parecidas else ""))
        sys.exit(1)

    embedder = get_gemini_embeddings()
    print(f"Entidades a regenerar: {len(pedidas)}")
    ok = sum(regenerar(e, embedder) for e in pedidas)
    print(f"\nCompletado: {ok}/{len(pedidas)} entidades regeneradas y cargadas.")
    if ok:
        print("Para actualizar los archivos master: "
              "python exploration/exportar_resumenes_y_contexto.py")


if __name__ == "__main__":
    main()
