"""Genera el nombre legible, CON ACENTOS, de las entidades de ontología.

POR QUÉ EXISTE
--------------
`api/especialistas/general.py::nombre_legible()` deriva el nombre visible del id de la entidad
—SOCIEDAD_ANONIMA → «Sociedad Anonima»— porque la convención de ids es MAYÚSCULAS SIN TILDES.
Funciona, pero pierde los acentos, y eso llega hasta la pantalla: el usuario ve «Sociedad
Anonima» y «Sindico» en el panel de fuentes.

La propiedad `e.nombre` existe en el grafo y es el lugar correcto para el nombre bien escrito,
pero solo 18 de las 566 entidades la tenían cargada. Este script llena las que faltan.

CÓMO
----
Una pasada de `gemini-2.5-flash-lite` en lotes: se le pasan los ids y devuelve el nombre en
castellano correcto. Es una tarea de ortografía, no de contenido — por eso NO usa Qwen, que en
este proyecto está reservado a los resúmenes de entidades.

DOS PASOS, A PROPÓSITO. Un nombre mal puesto se ve en pantalla y se propaga a las citas, así
que el flujo separa generar de cargar:

    .venv/bin/python exploration/nombrar_entidades.py            # genera el archivo
    # (se revisa nombres_entidades.json)
    .venv/bin/python exploration/nombrar_entidades.py --cargar   # carga ESE archivo

`--cargar` **lee el archivo que ya existe** en vez de regenerar. No es un detalle: si volviera
a llamar al modelo, cargaría nombres que nadie revisó y la revisión no garantizaría nada. Si el
archivo no está, avisa y no escribe.

NO PISA las 18 entidades que ya tienen nombre: son datos curados a mano y el modelo no tiene
por qué mejorarlos.
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.connectors import get_neo4j_driver, get_gemini_llm
from utils.rag.llm_io import json_del_llm

SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nombres_entidades.json")
TAMANO_LOTE = 40   # 40 ids por llamada: ~14 llamadas para las 566, y el JSON entra holgado.

_PROMPT = """Sos un experto en derecho argentino. Te paso ids de entidades jurídicas escritos \
en MAYÚSCULAS, SIN TILDES y con guiones bajos. Devolvé el nombre en castellano correcto de cada uno.

REGLAS:
- Poné los acentos que correspondan: SINDICO -> "Síndico", SOCIEDAD_ANONIMA -> "Sociedad Anónima".
- Respetá las mayúsculas de un nombre propio jurídico y usá minúscula en los conectores:
  IMPUESTO_A_LAS_GANANCIAS -> "Impuesto a las Ganancias".
- NO traduzcas, NO expandas siglas que no estén en el id, NO agregues palabras que no estén.
  El nombre tiene que ser el mismo concepto, solo bien escrito.
- Mantené el número gramatical del id: si está en singular, va en singular.

Devolvé SOLO un objeto JSON {{"ID": "Nombre", ...}} con una clave por cada id que te paso.

IDS:
{ids}"""


def entidades_sin_nombre(driver) -> list[str]:
    """Los ids de las entidades de ontología que todavía no tienen `e.nombre`."""
    query = """
    MATCH (e) WHERE e.resumen IS NOT NULL
      AND (e.nombre IS NULL OR e.nombre = '')
      AND NOT e:Articulo AND NOT e:Norma AND NOT e:VersionHistorica AND NOT e:Jurisprudencia
    RETURN e.id AS id ORDER BY id
    """
    with driver.session() as session:
        return [r["id"] for r in session.run(query)]


def generar(llm, ids: list[str]) -> dict[str, str]:
    """{id: nombre} para todos los ids, en lotes. Un lote que falla no frena a los demás."""
    nombres: dict[str, str] = {}
    for i in range(0, len(ids), TAMANO_LOTE):
        lote = ids[i:i + TAMANO_LOTE]
        print(f"  lote {i // TAMANO_LOTE + 1}: {len(lote)} ids...", flush=True)
        try:
            respuesta = llm.invoke(_PROMPT.format(ids="\n".join(lote)))
            datos = json_del_llm(str(respuesta.content))
        except Exception as e:
            print(f"    FALLÓ: {e}")
            continue
        for entidad_id in lote:
            propuesto = str(datos.get(entidad_id, "")).strip()
            if propuesto:
                nombres[entidad_id] = propuesto
            else:
                print(f"    sin respuesta para {entidad_id}")
    return nombres


def cargar(driver, nombres: dict[str, str]) -> int:
    """Escribe `e.nombre`. Solo sobre entidades que NO lo tengan ya."""
    query = """
    UNWIND $filas AS fila
    MATCH (e {id: fila.id})
    WHERE e.resumen IS NOT NULL AND (e.nombre IS NULL OR e.nombre = '')
    SET e.nombre = fila.nombre
    RETURN count(e) AS n
    """
    filas = [{"id": k, "nombre": v} for k, v in nombres.items()]
    with driver.session() as session:
        return session.run(query, filas=filas).single()["n"]


def main() -> int:
    driver = get_neo4j_driver()

    if "--cargar" in sys.argv:
        if not os.path.exists(SALIDA):
            print(f"No existe {SALIDA}. Corré el script sin --cargar primero.")
            return 1
        with open(SALIDA, encoding="utf-8") as f:
            nombres = json.load(f)
        print(f"{len(nombres)} nombres leídos de {SALIDA}")
        print(f"cargados en Neo4j: {cargar(driver, nombres)}")
        driver.close()
        return 0

    ids = entidades_sin_nombre(driver)
    print(f"entidades sin nombre: {len(ids)}")
    if not ids:
        print("nada que hacer.")
        driver.close()
        return 0

    nombres = generar(get_gemini_llm(), ids)
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(nombres, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"\n{len(nombres)}/{len(ids)} nombres generados -> {SALIDA}")

    con_tilde = sum(1 for v in nombres.values() if any(c in v for c in "áéíóúÁÉÍÓÚñÑü"))
    print(f"con al menos un acento o ñ: {con_tilde}")
    print("(revisá el archivo y volvé a correr con --cargar para escribir en el grafo)")
    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
