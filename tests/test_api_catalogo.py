"""¿El catálogo devuelve lo que hay en el grafo, y el detalle de una cita trae contenido real?

Es un test de INTEGRACIÓN contra Neo4j: no hay mocks, corre contra la base viva. Por eso los
números están escritos: 197 normas y 292 fallos. Si alguno cambia, o entró una
norma nueva —y hay que actualizar el número y `inventario.md`— o algo se rompió. Las dos cosas
conviene enterarlas.

Lo que se prueba y por qué:

- **Que ninguna norma quede sin nombre.** 100 de las 197 no tienen `titulo`, así que un catálogo
  que mostrara el título tendría media lista en blanco. El nombre sale de `NOMBRE_NORMA`.
- **Que el listado sea liviano.** El inventario contesta «¿está cargada tal norma?» y nada más:
  no devuelve el articulado ni cuenta artículos. Esto lo verifica, porque es justo lo que se sacó.
- **Que el fallo NO traiga su texto** en el detalle. Promedia 19.571 caracteres y el más largo
  tiene 286.611: mandarlo con el resto sería descargar un cuarto de megabyte para abrir un modal.

    .venv/bin/python tests/test_api_catalogo.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from fastapi.testclient import TestClient

from api.server import app

cliente = TestClient(app)

fallos: list[str] = []


def verificar(condicion: bool, descripcion: str, detalle: str = ""):
    print(f"  [{'OK  ' if condicion else 'FALLA'}] {descripcion}")
    if not condicion:
        if detalle:
            print(f"          {detalle}")
        fallos.append(descripcion)


def main() -> int:
    print("\nINVENTARIO DE NORMAS")
    r = cliente.get("/api/catalogo/normas")
    verificar(r.status_code == 200, "GET /api/catalogo/normas responde 200", r.text[:200])
    normas = r.json()
    verificar(len(normas) == 197, "son 197 normas", f"vinieron {len(normas)}")
    verificar(all(n["nombre"] for n in normas),
              "ninguna norma queda sin nombre (NOMBRE_NORMA cubre las 100 sin titulo)",
              str([n["id"] for n in normas if not n["nombre"]][:5]))
    verificar(all("articulos" not in n for n in normas),
              "el listado NO trae la cantidad de artículos (es un índice, no un explorador)")
    verificar(all(set(n) == {"id", "nombre", "tipo", "numero", "titulo", "rama", "jurisdiccion"}
                  for n in normas),
              "y solo trae los campos del listado",
              str(sorted(set(normas[0]))))
    verificar(all(isinstance(n["rama"], list) for n in normas),
              "`rama` viene siempre como lista, incluso vacía")

    ccycn = next((n for n in normas if n["id"] == "CCyCN"), None)
    verificar(ccycn is not None and ccycn["nombre"] == "CCyCN",
              "el CCyCN se cita por su nombre corto y no por su título completo",
              str(ccycn))

    dtr = [n for n in normas if n["tipo"] == "DisposicionTecnicoRegistral"]
    verificar(len(dtr) == 106, "hay 106 DTR", f"hay {len(dtr)}")
    verificar(all(n["nombre"].startswith("DTR ") for n in dtr),
              "las DTR se nombran «DTR n/año», que es como se citan",
              str([n["nombre"] for n in dtr[:3]]))

    print("\nINVENTARIO DE FALLOS")
    r = cliente.get("/api/catalogo/fallos")
    verificar(r.status_code == 200, "GET /api/catalogo/fallos responde 200", r.text[:200])
    juris = r.json()
    verificar(len(juris) == 292, "son 292 fallos", f"vinieron {len(juris)}")
    verificar(all(isinstance(f["fecha"], str) for f in juris),
              "ninguna fecha viene nula (hay un fallo sin fecha en el grafo)")

    def anio(f):
        p = f["fecha"].split("/")
        return int(p[2]) if len(p) == 3 and p[2].isdigit() else 0

    anios = [anio(f) for f in juris if anio(f)]
    verificar(anios == sorted(anios, reverse=True),
              "vienen del más nuevo al más viejo, con la fecha como dd/mm/aaaa")

    print("\nDETALLE DE UNA FUENTE")
    r = cliente.get("/api/fuente/articulo/Art_77_Ley_19550")
    verificar(r.status_code == 200, "artículo: responde 200", r.text[:200])
    art = r.json()
    verificar(art["numero"] == "77" and art["norma"] == "Ley 19.550",
              "artículo: número y norma correctos", str(art)[:150])
    verificar(len(art["texto"]) > 100, "artículo: trae su texto completo",
              f"largo {len(art.get('texto', ''))}")
    verificar(art["ubicacion"] != "", "artículo: trae su ubicación en la norma")

    r = cliente.get("/api/fuente/entidad/SOCIEDAD_ANONIMA")
    verificar(r.status_code == 200, "entidad: responde 200", r.text[:200])
    ent = r.json()
    verificar(ent["nombre"] == "Sociedad Anónima",
              "entidad: el nombre viene con acentos, que es lo que ve el usuario",
              str(ent.get("nombre")))
    verificar(len(ent["resumen"]) > 500, "entidad: trae su resumen",
              f"largo {len(ent.get('resumen', ''))}")

    id_fallo = juris[0]["id"]
    r = cliente.get(f"/api/fuente/fallo/{id_fallo}")
    verificar(r.status_code == 200, "fallo: responde 200", r.text[:200])
    fa = r.json()
    verificar("texto" not in fa,
              "fallo: NO trae el texto literal (hasta 286.611 caracteres)")
    verificar(len(fa["resumen"]) > 100, "fallo: sí trae el resumen de doctrina",
              f"largo {len(fa.get('resumen', ''))}")
    verificar(fa["largo_texto"] > 0, "fallo: informa cuánto pesa el texto, para avisar antes")

    r = cliente.get(f"/api/fuente/fallo/{id_fallo}/texto")
    verificar(r.status_code == 200, "fallo: el texto completo se pide aparte", r.text[:200])
    verificar(len(r.json()["texto"]) == fa["largo_texto"],
              "y su largo coincide con el anunciado")

    print("\nERRORES")
    for ruta, desc in [
        ("/api/fuente/articulo/Art_9999_Ley_19550", "artículo inexistente"),
        ("/api/fuente/entidad/NO_EXISTE_ESTA_ENTIDAD", "entidad inexistente"),
        ("/api/fuente/fallo/Fallo_inventado", "fallo inexistente"),
        ("/api/fuente/vaca/loquesea", "tipo de fuente desconocido"),
        ("/api/fuente/entidad/Art_77_Ley_19550", "un artículo pedido como entidad"),
    ]:
        r = cliente.get(ruta)
        verificar(r.status_code == 404, f"{desc} da 404", f"dio {r.status_code}")

    print()
    if fallos:
        print(f"{len(fallos)} FALLAS:")
        for f in fallos:
            print(f"  - {f}")
        return 1
    print("Todo en orden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
