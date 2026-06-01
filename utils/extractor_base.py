"""Modelos Pydantic, lista canónica de relaciones y funciones de utilidad
compartidas por todos los pipelines de ingesta del proyecto."""
import logging, time
from typing import List, Optional
from pydantic import BaseModel, Field


# --- Modelos Pydantic ---

class PropiedadesNodo(BaseModel):
    numero: Optional[str] = Field(None)
    titulo: Optional[str] = Field(None)
    jurisdiccion: Optional[str] = Field(None)
    texto: Optional[str] = Field(None)
    ubicacion: Optional[str] = Field(None)
    ley_nombre: Optional[str] = Field(None)
    ley_numero: Optional[str] = Field(None)

class NodoLegal(BaseModel):
    id: str
    etiqueta: str
    propiedades: PropiedadesNodo

class RelacionLegal(BaseModel):
    inicio: Optional[str]
    fin: Optional[str]
    tipo: Optional[str]

class GrafoLegalExtraido(BaseModel):
    nodos: List[NodoLegal]
    relaciones: List[RelacionLegal]


# --- Lista canónica de relaciones ---
# Común a todos los extractores. Ampliar solo si el nuevo tipo sirve a TODAS las normas
# y se evalúa el impacto en el grafo existente.

RELACIONES_PERMITIDAS = [
    # Artículos → entidades
    "DEFINE",
    "REGULA",
    "MENCIONA",
    "AUTORIZA",
    "PROHIBE",
    "ESTABLECE_REQUISITOS_DE",
    "APLICA_SUPLETORIAMENTE",
    # Jerárquicas y de composición
    "ES_TIPO_DE",
    "ES_PARTE_DE",
    "ESTA_COMPUESTO_POR",
    "SE_DIVIDE_EN",
    # Roles y funciones
    "ADMINISTRA",
    "FISCALIZA",
    "REPRESENTA",
    "INTEGRA",
    # Acciones y procesos
    "EMITE",
    "SUSCRIBE",
    "APRUEBA",
    "CONVOCA",
    "SE_INSTRUMENTA_EN",
    "SE_INSCRIBE_EN",
    # Temporales y de modificación
    "MODIFICA_A",
    "DEROGA_A",
    "REEMPLAZA_A",
    "SE_TRANSFORMA_EN",
    "ABSORBE_A",
    "SE_ESCINDE_EN",
    # Remisiones normativas (artículo → artículo o artículo → norma)
    "REMITE_A",
]


# --- Funciones compartidas ---

def embed_con_reintento(embedder, texto: str, max_reintentos: int = 3) -> list:
    """Llama embed_query con reintentos y backoff exponencial ante ResourceExhausted."""
    logger = logging.getLogger(__name__)
    espera = 60
    for intento in range(1, max_reintentos + 1):
        try:
            return embedder.embed_query(texto)
        except Exception as e:
            if intento < max_reintentos:
                logger.warning(
                    f"  Error embedding (intento {intento}/{max_reintentos}): {e}. "
                    f"Reintentando en {espera}s..."
                )
                time.sleep(espera)
                espera *= 2
            else:
                logger.error(f"  Error embedding tras {max_reintentos} intentos: {e}")
                raise


def articulo_existe_en_neo4j(db_driver, articulo_id: str) -> bool:
    """Verifica si un artículo ya fue ingresado al grafo (garantiza idempotencia)."""
    with db_driver.session() as session:
        result = session.run(
            "MATCH (n:Articulo {id: $id}) RETURN n LIMIT 1",
            id=articulo_id
        )
        return result.single() is not None


def validar_grafo(
    grafo: GrafoLegalExtraido,
    articulo_id: str,
    etiquetas_validas: set,
    relaciones_validas: set,
    canonicos: dict,
    logger: logging.Logger,
) -> GrafoLegalExtraido:
    """Normaliza IDs y descarta nodos/relaciones que no respetan la ontología cerrada.

    El ID del artículo se sobreescribe siempre con el derivado del nombre del archivo;
    lo que devuelva el LLM para ese campo se ignora.
    """

    def canonicalizar(nodo_id: str) -> str:
        limpio = nodo_id.replace("º", "").replace("°", "")
        return canonicos.get(limpio, limpio)

    # A. Filtrar nodos
    nodos_validos = []
    for nodo in grafo.nodos:
        if nodo.etiqueta == "Articulo":
            nodo.id = articulo_id
            nodos_validos.append(nodo)
        elif nodo.etiqueta in etiquetas_validas:
            nodo.id = canonicalizar(nodo.id)
            nodos_validos.append(nodo)
        else:
            logger.warning(f"  Nodo descartado (etiqueta no permitida): [{nodo.etiqueta}] {nodo.id}")
    grafo.nodos = nodos_validos

    # B. Normalizar IDs del artículo en relaciones y canonicalizar entidades
    for rel in grafo.relaciones:
        if rel.inicio:
            rel.inicio = articulo_id if rel.inicio.upper() == articulo_id.upper() else canonicalizar(rel.inicio)
        if rel.fin:
            rel.fin = articulo_id if rel.fin.upper() == articulo_id.upper() else canonicalizar(rel.fin)

    # C. Filtrar relaciones inválidas
    rels_validas = []
    for r in grafo.relaciones:
        if not (r.inicio and r.fin and r.tipo):
            logger.warning(f"  Relación descartada (campos nulos): {r}")
        elif r.tipo not in relaciones_validas:
            logger.warning(f"  Relación descartada (tipo no permitido): {r.inicio} -[{r.tipo}]-> {r.fin}")
        else:
            rels_validas.append(r)
    grafo.relaciones = rels_validas

    return grafo
