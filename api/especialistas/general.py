"""ESPECIALISTA GENERAL — consultas sobre institutos jurídicos.

Uno de los tres especialistas del agente notarial. Atiende las preguntas que no apuntan a un
artículo sino a una figura del derecho: «dime las diferencias entre la SA y la SRL», «¿qué es
el usufructo?», «¿cómo funciona el fideicomiso?».

RECUPERACIÓN ENTIDAD-PRIMERO: invierte el orden del especialista particular. Ese busca
artículos y deduce el instituto; este busca el instituto y devuelve su resumen.

POR QUÉ EL RESUMEN Y NO LOS ARTÍCULOS. Cada una de las 566 entidades de ontología tiene un
resumen ya generado y guardado en el grafo (`exploration/generar_resumenes_entidades.py`):
2.600 a 20.700 caracteres, estructurados por secciones, que citan norma y artículo por dentro.
Para eso se generaron. Bajar además al articulado sería redundante y caro: la SOCIEDAD_ANONIMA
tiene 259 artículos vigentes colgando y la SRL 125 — volcarlos es imposible, y elegir ocho es
elegir mal. El resumen ya hizo ese trabajo, una vez, offline.

La comparación no la hace este módulo: trae los resúmenes completos de los institutos
involucrados y es el nodo `sintetizar` el que lee los dos y extrae las diferencias. Por eso
importa que la búsqueda cubra a TODOS los institutos de la pregunta y no solo al primero
(ver K_ENTIDADES en `utils/rag/grafo.py`).

CONTRATO CON EL AGENTE (el mismo para los tres especialistas):
    general(pregunta) -> Generator[dict, None, ContextoAcumulado]

No importa LangGraph. El puente vive en `api/agente/nodos.py`.

JURISPRUDENCIA, IGUAL QUE EL PARTICULAR. El resumen de una entidad dice qué es un instituto;
un fallo dice cómo lo aplicaron los tribunales, y eso refuerza —o matiza— la conclusión del
resumen. Antes esta ruta no los consultaba, y el efecto era invisible pero grande: la fase
`jurisprudencia` la emitía SOLO el especialista particular, así que **cada consulta doctrinal
que el clasificador mandaba acá dejaba los 292 fallos fuera de alcance**. Medido con
`tests/test_jurisprudencia.py`: «¿la responsabilidad del escribano es de medios o de
resultado?» se rutea a esta ruta, y el fallo que contesta exactamente eso salía SEGUNDO en el
índice y nunca llegaba al redactor.

COSTO: **sigue en cero llamadas a un LLM.** La búsqueda de fallos usa
`similarity_search_by_vector()` con el vector que ya se calculó para buscar las entidades, así
que no hay un segundo embedding: es un embedding y tres consultas a Neo4j.
"""
from utils.connectors import get_neo4j_driver, get_gemini_embeddings
from utils.rag.grafo import entidades_similares
# Del especialista particular se reusan tres cosas, y no se duplican a propósito: el acumulador
# de contexto, el retriever de fallos —que es el mismo índice `index_jurisprudencia`, no tiene
# sentido tener dos— y el helper que trae tribunal y fecha para citarlos.
from api.especialistas.particular import (
    ContextoAcumulado, K_JURISPRUDENCIA, _obtener_retriever_jurisprudencia, _datos_fallos,
)

embeddings = get_gemini_embeddings()
neo4j_driver = get_neo4j_driver()


# Palabras que van en minúscula cuando no abren el nombre. Sin esto, "IMPUESTO_A_LAS_GANANCIAS"
# se mostraría como "Impuesto A Las Ganancias".
_CONECTORES = {"a", "de", "del", "la", "las", "el", "los", "y", "en", "por", "con", "sin"}


# Los nombres que ya vinieron del grafo, para que `fuentes_general()` no tenga que reconstruirlos
# desde el id ni volver a consultar. Lo llena `general()` con lo que trajo la búsqueda; vive a
# nivel de módulo porque las dos funciones se llaman en turnos distintos del mismo pedido. Las
# escrituras concurrentes son inocuas: la misma clave siempre recibe el mismo valor.
_NOMBRES: dict[str, str] = {}


def nombre_legible(entidad_id: str) -> str:
    """Convierte el id de una entidad en algo que se pueda mostrar en pantalla.

        SOCIEDAD_ANONIMA         -> "Sociedad Anonima"
        IMPUESTO_A_LAS_GANANCIAS -> "Impuesto a las Ganancias"

    Es el inverso exacto de la convención de ids del proyecto (NOMBRE_EN_MAYUSCULAS_SIN_TILDES,
    siempre singular), así que no hace falta consultar el grafo.

    ES EL PLAN B, NO EL PRINCIPAL. Las 566 entidades tienen cargado `e.nombre` con el nombre
    bien escrito —acentos incluidos— y `entidades_similares()` ya lo trae en su RETURN, así que
    el camino normal es usar ése y no reconstruir nada. Esta función queda para los casos en que
    solo hay un id a mano: `fuentes_general()`, que lee de un ContextoAcumulado donde lo único
    guardado son ids.

    Pierde los acentos, porque el id no los lleva: devuelve "Sociedad Anonima", no "Sociedad
    Anónima". Por eso es el plan B.
    """
    palabras = [p for p in entidad_id.split("_") if p]
    if not palabras:
        return entidad_id
    return " ".join(
        palabra.lower() if i > 0 and palabra.lower() in _CONECTORES else palabra.lower().capitalize()
        for i, palabra in enumerate(palabras)
    )


def general(pregunta: str):
    """Resuelve una consulta general: encuentra los institutos jurídicos de los que habla la
    pregunta y devuelve sus resúmenes completos.

    Generador: emite eventos de progreso ("fase"/"item") y su `return` es el
    ContextoAcumulado, igual que el especialista particular.

    Usa ContextoAcumulado —y no una lista pelada— por lo mismo que el particular: deduplica
    por id. Una pregunta puede traer dos veces la misma entidad si se reformula, y el resumen
    de la SOCIEDAD_ANONIMA son 18.629 caracteres que no conviene pagar dos veces.
    """
    yield {"type": "fase", "fase": "entidades", "label": "Buscando institutos jurídicos"}

    vector = embeddings.embed_query(pregunta)
    entidades = entidades_similares(neo4j_driver, vector)

    ctx = ContextoAcumulado()
    for entidad in entidades:
        # `e.nombre` viaja en el RETURN de entidades_similares(), así que usarlo no cuesta una
        # consulta extra — y trae los acentos, que el id no tiene.
        nombre = entidad.get("nombre") or nombre_legible(entidad["id"])
        _NOMBRES[entidad["id"]] = nombre
        # Mismo formato de bloque que usa el especialista particular para los artículos: una
        # etiqueta en mayúsculas por línea. El prompt de redacción ya sabe leer esa forma.
        texto = (
            f"INSTITUTO JURÍDICO: {nombre}\n"
            f"DESCRIPCIÓN:\n{entidad['resumen']}"
        )
        if ctx.agregar(entidad["id"], texto, fase="entidades"):
            yield {"type": "item", "texto": nombre}

    # Fase 2: jurisprudencia. Va DESPUÉS de las entidades por la misma razón que en el
    # especialista particular: primero lo que define el instituto, después la doctrina que lo
    # aplica. El orden es el que lee el redactor.
    #
    # `similarity_search_by_vector` y no `.invoke(pregunta)`: el vector de la pregunta ya está
    # calculado unas líneas más arriba para buscar las entidades. Pasar por el retriever lo
    # embebería de nuevo — otra llamada a la API y medio segundo, por el mismo vector.
    yield {"type": "fase", "fase": "jurisprudencia", "label": "Buscando jurisprudencia"}
    #
    # El `query=pregunta` es obligatorio aunque parezca redundante: langchain_neo4j arma la
    # consulta con un parámetro `query_text` para el índice fulltext y lo lee sin condición
    # (`kwargs["query"]`), así que sin él tira KeyError. En búsqueda vectorial pura ese
    # parámetro viaja hasta Neo4j y no lo usa nadie — solo interviene en modo híbrido.
    almacen = _obtener_retriever_jurisprudencia().vectorstore
    for doc in almacen.similarity_search_by_vector(vector, k=K_JURISPRUDENCIA, query=pregunta):
        if ctx.agregar(doc.metadata.get("id", ""), doc.page_content, fase="jurisprudencia"):
            tribunal = doc.metadata.get("tribunal", "") or "Fallo"
            fecha = doc.metadata.get("fecha", "")
            yield {"type": "item", "texto": f"{tribunal}{' — ' + fecha if fecha else ''}"}

    return ctx


def fuentes_general(ctx: ContextoAcumulado) -> list[dict]:
    """Traduce el contexto acumulado a las citas que ve el usuario.

    Una fuente de este especialista es un instituto, no un artículo, así que va con
    `tipo: "entidad"` y sin norma: el frontend usa el tipo para no escribir "Art." delante
    de "Sociedad Anonima".

    Desde que esta ruta también consulta jurisprudencia, el contexto trae **dos clases de id**
    y hay que separarlas: un fallo no es un instituto y el frontend los pinta distinto. La
    separación sale de `ctx.fases`, que el acumulador ya registra — es el mismo mecanismo que
    usa `fuentes_particular()` para distinguir artículos de fallos.

        entidad -> {"numero": "Síndico",              "norma": ""}
        fallo   -> {"numero": "CNCiv. Sala A",        "norma": "12/03/2015"}

    El nombre del instituto sale de `_NOMBRES`, que `general()` llenó con el `e.nombre` que ya
    trajo la búsqueda: ContextoAcumulado solo guarda ids —es su trabajo, deduplicar— y volver al
    grafo por un dato que ya tuvimos sería tirar plata. Si por algún camino el id no está en el
    caché, se cae a reconstruirlo desde el id, que es correcto aunque sin acentos.
    """
    ids_fallos = [i for i in ctx.ids if ctx.fases.get(i) == "jurisprudencia"]
    datos_fallo = _datos_fallos(ids_fallos)

    fuentes = []
    for nodo_id in ctx.ids:
        if nodo_id in datos_fallo:
            d = datos_fallo[nodo_id]
            fuentes.append({
                "id": nodo_id,
                "tipo": "fallo",
                "numero": d["tribunal"] or nodo_id,
                "norma": d["fecha"] or "Jurisprudencia",
            })
        else:
            fuentes.append({
                "id": nodo_id,
                "tipo": "entidad",
                "numero": _NOMBRES.get(nodo_id) or nombre_legible(nodo_id),
                "norma": "",
            })
    return fuentes
