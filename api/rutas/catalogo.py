"""EL CATÁLOGO — qué hay cargado en el grafo, y el contenido de una fuente citada.

Dos usos distintos que comparten origen:

1. **El inventario.** Para contestar «¿está cargada tal norma?» antes de confiar en una
   respuesta. Es una consulta puntual, no una biblioteca para pasear.
2. **El detalle de una cita.** Los chips que aparecen bajo cada respuesta traen solo un id; acá
   se resuelve el contenido que el usuario quiere leer.

TODAS LAS CONSULTAS SON FIJAS Y PARAMETRIZADAS, con `execute_read`. **Nada de esto pasa por el
motor Text-to-Cypher ni por su filtro de seguridad**: no hay texto de un LLM en juego, hay ids que
el propio backend emitió. Un id del usuario entra siempre como parámetro `$id`, nunca concatenado.

POR QUÉ LAS CONSULTAS VIVEN ACÁ Y NO EN `utils/rag/grafo.py`
------------------------------------------------------------
Ese archivo lo importan ~180 archivos y el proyecto trata su API como congelada. Estas son
consultas de PRESENTACIÓN —traen `texto`, `ubicacion`, carátulas— y no helpers de recuperación;
mezclarlas ahí ampliaría una superficie que conviene chica. Lo que sí se reusa es `NOMBRE_NORMA`,
porque el nombre con el que se cita una norma tiene que ser uno solo en todo el proyecto.
"""
import logging

from fastapi import APIRouter, HTTPException, Request

from api.auth import IdentidadInvalida, identidad
from utils.connectors import get_neo4j_driver
from utils.rag.citas import NOMBRE_NORMA

_log = logging.getLogger("catalogo")

router = APIRouter(prefix="/api")

# Etiquetas que NO son entidades de ontología. Se usan para descartar cuando se busca una entidad
# por id sin conocer su label — que es la situación normal, porque las 566 entidades tienen 566
# labels distintos, uno cada una, y al frontend solo le viaja el id.
ESTRUCTURALES = ["Articulo", "Norma", "VersionHistorica", "Jurisprudencia"]

_driver = None


def _obtener_driver():
    """El driver de Neo4j, perezoso.

    Perezoso por la misma razón que en `api/especialistas/particular.py`: importar la API no tiene
    que abrir una conexión con Aura. Es lo que permite arrancar el servidor —y correr los tests
    que no tocan el grafo— sin la base viva.
    """
    global _driver
    if _driver is None:
        _driver = get_neo4j_driver()
    return _driver


def _exigir_identidad(request: Request):
    """401 si la autenticación está encendida y el pedido no trae identidad válida.

    Es la misma traducción que hace `cuenta.py`, pero acá NO se resuelve el uuid del usuario ni se
    toca Postgres: el catálogo es el mismo para todos y tiene que poder consultarse sin base. Por
    eso son cuatro líneas repetidas en vez de un helper compartido — lo que comparten es la forma,
    no el comportamiento.
    """
    try:
        identidad(request.headers)
    except IdentidadInvalida as e:
        raise HTTPException(status_code=401, detail=str(e))


def _leer(cypher: str, **params) -> list[dict]:
    """Corre una consulta de solo lectura y devuelve las filas como diccionarios."""
    with _obtener_driver().session() as sesion:
        return sesion.execute_read(lambda tx: [r.data() for r in tx.run(cypher, **params)])


def _clave_fecha(fecha: str) -> tuple[int, int, int]:
    """Ordena una fecha guardada como «31/01/2007». Las que no se entienden van al final."""
    partes = (fecha or "").split("/")
    if len(partes) == 3 and all(p.isdigit() for p in partes):
        return (int(partes[2]), int(partes[1]), int(partes[0]))
    return (0, 0, 0)


# ==============================================================================================
# INVENTARIO
# ==============================================================================================

_NORMAS = f"""
MATCH (norma:Norma)
RETURN norma.id            AS id,
       {NOMBRE_NORMA}      AS nombre,
       norma.tipo          AS tipo,
       norma.numero        AS numero,
       norma.titulo        AS titulo,
       coalesce(norma.rama, [])     AS rama,
       norma.jurisdiccion  AS jurisdiccion
"""


@router.get("/catalogo/normas")
def listar_normas(request: Request):
    """Las 197 normas: qué son, de qué tratan y de dónde salen.

    Es un LISTADO, no un explorador: contesta «¿está cargada tal norma?» y nada más. No trae el
    articulado ni cuenta artículos —eso era peso sin uso: nadie va a leer el CCyCN de a un
    artículo por acá, y para eso están las citas de cada respuesta—.

    Se traen las 197 de una: es una sola consulta y tenerlas en el navegador es lo que hace que el
    buscador filtre sin ida y vuelta por tecla.

    El nombre sale de `NOMBRE_NORMA` y no de `titulo`: medido, **100 de las 197 normas no tienen
    título**, y ese helper ya sabe armar «DTR 6/2019» desde el id.
    """
    _exigir_identidad(request)
    filas = _leer(_NORMAS)
    filas.sort(key=lambda f: (f["nombre"] or "").lower())
    return filas


@router.get("/catalogo/fallos")
def listar_fallos(request: Request):
    """Los 292 fallos y dictámenes, del más nuevo al más viejo.

    NO se filtra por `temas` ni por `tipo`, aunque las propiedades existan: medido en el grafo,
    `temas` está vacío en 278 de 292, y el 97% de los `tipo` es "sentencia". Un filtro que no
    separa nada es un menú de más.
    """
    _exigir_identidad(request)
    filas = _leer(
        """
        MATCH (fallo:Jurisprudencia)
        RETURN fallo.id                       AS id,
               coalesce(fallo.tribunal, '')   AS tribunal,
               coalesce(fallo.caratula, '')   AS caratula,
               coalesce(fallo.fecha, '')      AS fecha,
               coalesce(fallo.rama, '')       AS rama
        """
    )
    filas.sort(key=lambda f: _clave_fecha(f["fecha"]), reverse=True)
    return filas


# ==============================================================================================
# EL CONTENIDO DE UNA FUENTE
# ==============================================================================================

# NOMBRE_NORMA está escrito sobre el alias `norma`. Acá hace falta una segunda vez, para la norma
# que MODIFICÓ al artículo, y por eso se reescribe el alias. Es preferible a duplicar el fragmento:
# la convención de cómo se nombra una norma tiene que existir en un solo lugar.
_NOMBRE_MODIFICADORA = NOMBRE_NORMA.replace("norma.", "modificadora.")

_ARTICULO = f"""
MATCH (norma:Norma)-[:CONTIENE]->(art:Articulo {{id: $id}})
OPTIONAL MATCH (previo:Articulo)-[:MODIFICA_A]->(art)
OPTIONAL MATCH (modificadora:Norma)-[:CONTIENE]->(previo)
RETURN art.numero          AS numero,
       {NOMBRE_NORMA}      AS norma,
       norma.id            AS norma_id,
       art.ubicacion       AS ubicacion,
       coalesce(art.vigente, true)    AS vigente,
       coalesce(art.modificado, false) AS modificado,
       art.vigencia_desde  AS vigencia_desde,
       art.texto           AS texto,
       collect(DISTINCT {_NOMBRE_MODIFICADORA}) AS modificadoras
"""


def _nota_vigencia(fila: dict) -> str:
    """La leyenda «Texto según Ley 27.444, vigente desde 08/2018», o "" si no corresponde.

    Se arma en el servidor y el frontend la TRANSCRIBE, igual que hace el retrieval con el prompt:
    la vigencia de una norma no es algo que deba inferir quien la muestra.
    """
    if not fila.get("modificado"):
        return ""
    normas = [n for n in (fila.get("modificadoras") or []) if n and n != "Norma no identificada"]
    desde = fila.get("vigencia_desde")
    partes = []
    if normas:
        partes.append(f"Texto según {', '.join(normas)}")
    if desde:
        partes.append(f"vigente desde {desde}")
    return ", ".join(partes)


@router.get("/fuente/{tipo}/{fuente_id}")
def ver_fuente(tipo: str, fuente_id: str, request: Request):
    """El contenido de una fuente citada: un artículo, un instituto o un fallo.

    UNA SOLA RUTA PARA LOS TRES y no tres rutas, porque hay un solo llamador: el modal, que ya
    recibe `tipo` en cada `Fuente`. Con tres rutas, el frontend tendría que elegir cuál llamar con
    un if de tres ramas, que es exactamente el despacho que se hace acá.

    El fallo viene SIN su texto: promedia 19.571 caracteres y el más largo tiene 286.611. Lo que
    se devuelve es el `resumen` de doctrina —que es lo mismo que leyó el modelo para responder— y
    el texto literal queda a un clic, en /api/fuente/fallo/{id}/texto. El artículo sí trae su
    texto: promedia 568 caracteres.
    """
    _exigir_identidad(request)

    if tipo == "articulo":
        filas = _leer(_ARTICULO, id=fuente_id)
        if not filas:
            raise HTTPException(status_code=404, detail="No se encontró ese artículo.")
        f = filas[0]
        return {
            "tipo": "articulo",
            "numero": f["numero"],
            "norma": f["norma"],
            "norma_id": f["norma_id"],
            "ubicacion": f["ubicacion"] or "",
            "vigente": f["vigente"],
            "modificado": f["modificado"],
            "nota_vigencia": _nota_vigencia(f),
            "texto": f["texto"] or "",
        }

    if tipo == "entidad":
        filas = _leer(
            f"""
            MATCH (e {{id: $id}})
            WHERE NOT any(l IN labels(e) WHERE l IN {ESTRUCTURALES})
            RETURN coalesce(e.nombre, e.id) AS nombre, coalesce(e.resumen, '') AS resumen
            """,
            id=fuente_id,
        )
        if not filas:
            raise HTTPException(status_code=404, detail="No se encontró ese instituto.")
        return {"tipo": "entidad", **filas[0]}

    if tipo == "fallo":
        filas = _leer(
            """
            MATCH (fallo:Jurisprudencia {id: $id})
            RETURN coalesce(fallo.tribunal, '')   AS tribunal,
                   coalesce(fallo.caratula, '')   AS caratula,
                   coalesce(fallo.fecha, '')      AS fecha,
                   coalesce(fallo.expediente, '') AS expediente,
                   coalesce(fallo.rama, '')       AS rama,
                   coalesce(fallo.resumen, '')    AS resumen,
                   size(coalesce(fallo.texto, '')) AS largo_texto
            """,
            id=fuente_id,
        )
        if not filas:
            raise HTTPException(status_code=404, detail="No se encontró ese fallo.")
        return {"tipo": "fallo", **filas[0]}

    raise HTTPException(status_code=404, detail=f"Tipo de fuente desconocido: {tipo}")


@router.get("/fuente/fallo/{fallo_id}/texto")
def ver_texto_fallo(fallo_id: str, request: Request):
    """El texto literal completo de un fallo, bajo demanda.

    Ruta aparte justamente porque es lo caro: hasta 286.611 caracteres. Solo se pide si el usuario
    aprieta «ver texto completo», que es la diferencia entre un modal que abre al instante y uno
    que descarga un cuarto de megabyte para que lo ojeen.
    """
    _exigir_identidad(request)
    filas = _leer(
        "MATCH (fallo:Jurisprudencia {id: $id}) RETURN coalesce(fallo.texto, '') AS texto",
        id=fallo_id,
    )
    if not filas:
        raise HTTPException(status_code=404, detail="No se encontró ese fallo.")
    return {"texto": filas[0]["texto"]}
