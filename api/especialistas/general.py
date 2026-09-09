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

COSTO: **cero llamadas a un LLM.** Un embedding de la pregunta y dos consultas a Neo4j.
Medido de punta a punta: ~1 a 3 segundos.
"""
from utils.connectors import get_neo4j_driver, get_gemini_embeddings
from utils.rag.grafo import entidades_similares
from api.especialistas.particular import ContextoAcumulado

embeddings = get_gemini_embeddings()
neo4j_driver = get_neo4j_driver()


# Palabras que van en minúscula cuando no abren el nombre. Sin esto, "IMPUESTO_A_LAS_GANANCIAS"
# se mostraría como "Impuesto A Las Ganancias".
_CONECTORES = {"a", "de", "del", "la", "las", "el", "los", "y", "en", "por", "con", "sin"}


def nombre_legible(entidad_id: str) -> str:
    """Convierte el id de una entidad en algo que se pueda mostrar en pantalla.

        SOCIEDAD_ANONIMA         -> "Sociedad Anonima"
        IMPUESTO_A_LAS_GANANCIAS -> "Impuesto a las Ganancias"

    Es el inverso exacto de la convención de ids del proyecto (NOMBRE_EN_MAYUSCULAS_SIN_TILDES,
    siempre singular), así que no hace falta consultar el grafo.

    Y no conviene consultarlo: la propiedad `e.nombre` existe pero **solo 18 de las 566
    entidades la tienen cargada**. Una consulta costaría 180 ms para resolver el 3% de los
    casos y dejaría el otro 97% igual que ahora.

    LIMITACIÓN CONOCIDA: se pierden los acentos, porque el id no los lleva ("Sociedad
    Anonima"). Se arregla poblando `e.nombre` en las 566 entidades con un script de
    `exploration/`; hasta entonces esto es lo correcto sin tocar el grafo.
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
        nombre = nombre_legible(entidad["id"])
        # Mismo formato de bloque que usa el especialista particular para los artículos: una
        # etiqueta en mayúsculas por línea. El prompt de redacción ya sabe leer esa forma.
        texto = (
            f"INSTITUTO JURÍDICO: {nombre}\n"
            f"DESCRIPCIÓN:\n{entidad['resumen']}"
        )
        if ctx.agregar(entidad["id"], texto, fase="entidades"):
            yield {"type": "item", "texto": nombre}

    return ctx


def fuentes_general(ctx: ContextoAcumulado) -> list[dict]:
    """Traduce el contexto acumulado a las citas que ve el usuario.

    Una fuente de este especialista es un instituto, no un artículo, así que va con
    `tipo: "entidad"` y sin norma: el frontend usa el tipo para no escribir "Art." delante
    de "Sociedad Anonima".

    El nombre se rearma desde el id con `nombre_legible()`: ContextoAcumulado solo guarda ids
    —es su trabajo, deduplicar— y volver al grafo por un dato que ya tuvimos sería tirar plata.
    """
    return [
        {
            "id": entidad_id,
            "tipo": "entidad",
            "numero": nombre_legible(entidad_id),
            "norma": "",
        }
        for entidad_id in ctx.ids
    ]
