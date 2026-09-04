"""Motor Text-to-Cypher dinámico: traduce una pregunta en lenguaje natural a una query
Cypher de solo lectura contra el esquema del grafo. Se usa cuando el contexto vectorial
más remisiones no alcanza para responder (ver el gate de suficiencia en api/recuperacion.py).
"""
import re

from utils.extractor_base import RELACIONES_PERMITIDAS
from utils.llm_io import strip_markdown


class MotorCypherDinamico:
    # Cláusulas que no deben aparecer en una query de solo lectura.
    # execute_read() protege a nivel de routing pero no garantiza read-only en
    # servidores únicos; este filtro es la barrera real.
    _CLAUSULAS_ESCRITURA = {"DELETE", "DETACH", "REMOVE", "SET", "MERGE", "CREATE", "DROP", "CALL"}
    _PATRON_ESCRITURA = re.compile(r"\b(" + "|".join(_CLAUSULAS_ESCRITURA) + r")\b", re.IGNORECASE)

    def __init__(self, driver, llm_model, etiquetas_entidades: list[str]):
        self.driver = driver
        self.llm = llm_model

        relaciones_fmt = "\n  ".join(RELACIONES_PERMITIDAS)
        etiquetas_fmt = " | ".join(etiquetas_entidades) if etiquetas_entidades else "(ninguna cargada)"

        self._esquema = f"""
NODOS Y PROPIEDADES REALES:
  (:Norma {{id, numero, titulo, tipo, rama, jurisdiccion, vigente}})
    — tipo: "Ley" | "Codigo" | "Decreto" | "ResolucionGeneral" | "Resolución" |
            "DisposicionTecnicoRegistral" | "InstruccionDeTrabajo"
    — rama: LISTA de strings, filtrá con IN (ej: 'registral' IN norma.rama). Valores:
            registral | societario | civil | penal | financiero | notarial | tributario |
            inversiones | comercial | datos_personales | asociaciones_civiles
    — jurisdiccion: "Nacional" | "Ciudad Autónoma de Buenos Aires"
    — titulo puede ser NULL: usá coalesce(norma.titulo, norma.id).
    — Ejemplos de id: "Ley_19550" | "CCyCN" | "Decreto_2080_1980" | "RG_15_2024" | "DTR_5_2019"

  (:Articulo {{id, numero, texto, ubicacion, vigente, modificado}})
    — El id NO tiene un formato único: "Art_163_Ley_19550", "Art_1_CCyCN",
      "Art_105_Decreto_2080_1980", "Art_1_DTR_5_2019", "Art_3_RG_2139_2006".
      NUNCA lo parsees ni lo construyas: llegá al artículo por (:Norma)-[:CONTIENE]->(:Articulo).
    — vigente = false ⇒ artículo derogado: no debe usarse como derecho vigente.

  (:<Etiqueta>   {{id: "NOMBRE_EN_MAYUSCULAS_CON_GUIONES"}})
    — La propiedad de búsqueda es SIEMPRE "id", nunca "nombre".
    — Etiquetas de entidades ontológicas presentes en la DB:
      {etiquetas_fmt}

RELACIONES:
  (:Norma)-[:CONTIENE]->(:Articulo)
  (:Norma)-[:APLICA_SUPLETORIAMENTE]->(:Norma)   // supletoriedad entre leyes, NO entre entidades
  (:Articulo o :Entidad)-[:TIPO]->(: Articulo o :Entidad)
    Tipos disponibles:
  {relaciones_fmt}
"""

        self._ejemplo = """
EJEMPLO — supletoriedad (Ley 27349 aplica Ley 19550 supletoriamente):
Pregunta: "¿Puede una SAS emitir debentures?"
Cypher:
OPTIONAL MATCH (art_directo:Articulo)-[r]-(sas:SociedadPorAccionesSimplificada)
WHERE type(r) IN ['REGULA', 'AUTORIZA', 'PROHIBE', 'DEFINE']
  AND toLower(art_directo.texto) CONTAINS 'debenture'
  AND art_directo.vigente = true

MATCH (norma_origen:Norma)-[:CONTIENE]->(art_directo)
MATCH (norma_origen)-[:APLICA_SUPLETORIAMENTE]->(norma_sup:Norma)-[:CONTIENE]->(art_sup:Articulo)
WHERE toLower(art_sup.texto) CONTAINS 'debenture'
  AND art_sup.vigente = true

WITH collect(DISTINCT art_directo) + collect(DISTINCT art_sup) AS todos
UNWIND todos AS art
WITH art WHERE art IS NOT NULL
RETURN DISTINCT art.id AS id, art.numero AS numero, art.texto AS texto
LIMIT 5
"""

    def _generar_prompt(self, pregunta: str) -> str:
        return f"""Eres un experto en Neo4j y derecho argentino. Generá una query Cypher de SOLO LECTURA.

ESQUEMA DEL GRAFO:
{self._esquema}

{self._ejemplo}

REGLAS ESTRICTAS:
1. Devolvé ÚNICAMENTE el código Cypher. Sin texto adicional.
2. NO inventes etiquetas ni propiedades que no estén en el esquema.
3. Para buscar entidades usá su etiqueta específica y filtrá por "id" con toLower() + CONTAINS.
4. Para supletoriedad traversá a nivel de NORMA: (norma)-[:APLICA_SUPLETORIAMENTE]->(norma_sup)-[:CONTIENE]->(art).
5. Retorná exactamente estas columnas: id, numero, texto.
6. LIMIT 5.
7. Devolvé SOLO artículos vigentes: agregá `AND art.vigente = true` a cada match de artículo.
8. Si la pregunta acota una rama o una jurisdicción, filtrá por la Norma que lo contiene:
   MATCH (n:Norma)-[:CONTIENE]->(art)
   WHERE 'registral' IN n.rama AND n.jurisdiccion = 'Ciudad Autónoma de Buenos Aires'

PREGUNTA:
{pregunta}
Cypher:"""

    @staticmethod
    def _postprocesar(cypher: str) -> str:
        """Corrige patrones Cypher inválidos que el LLM genera por su training data."""
        # `UNWIND x AS y \n WHERE` es inválido; la forma correcta es `UNWIND x AS y \n WITH y WHERE`.
        cypher = re.sub(
            r'(UNWIND\s+\S+\s+AS\s+(\w+))(\s*\n\s*)WHERE',
            lambda m: f"{m.group(1)}{m.group(3)}WITH {m.group(2)} WHERE",
            cypher,
            flags=re.IGNORECASE,
        )
        return cypher

    def consultar(self, pregunta: str) -> list[dict]:
        print("  [Grafo] Generando Cypher dinámicamente...")
        try:
            respuesta_llm = self.llm.invoke(self._generar_prompt(pregunta))
            cypher = strip_markdown(str(respuesta_llm.content))
            cypher = self._postprocesar(cypher)

            bloqueadas = {m.upper() for m in self._PATRON_ESCRITURA.findall(cypher)}
            if bloqueadas:
                print(f"  [Grafo] Cypher rechazado: cláusulas no permitidas detectadas: {bloqueadas}")
                return []

            print(f"  [Grafo] Cypher:\n{'-'*30}\n{cypher}\n{'-'*30}")

            with self.driver.session() as session:
                records = session.execute_read(lambda tx: tx.run(cypher).data())
                return [r for r in records if r.get("id") and r.get("texto")]

        except Exception as e:
            print(f"  [Grafo] Error: {e}")
            return []
