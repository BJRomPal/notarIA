"""¿El sistema encuentra Y USA la jurisprudencia cuando el fallo es la respuesta?

POR QUÉ EXISTE
--------------
El especialista particular consulta 292 fallos por su índice vectorial propio, muestra una fase
«Buscando jurisprudencia» y publica los fallos en el panel de fuentes. Pero muchas veces la
respuesta final no los menciona, y eso deja al usuario con la impresión de que un fallo sostiene
algo que en realidad no se usó.

Antes de arreglar eso hay que poder MEDIRLO, y la medición tiene que separar dos fallas
distintas, porque se arreglan en lugares distintos:

    NIVEL 1 — RECUPERACIÓN: ¿el fallo correcto entra entre los K que trae el retriever?
              Si falla acá, el problema es el índice o el `k`, y el prompt no lo va a salvar.

    NIVEL 2 — USO: teniendo el fallo en el contexto, ¿la respuesta lo aprovecha?
              Si falla acá, el problema es la redacción, y ahí sí es cuestión de prompt.

Un test que solo mirara la respuesta final confundiría las dos y llevaría a arreglar lo que no
es.

CÓMO SE ELIGIERON LOS CASOS
---------------------------
14 fallos reales del grafo, de las cuatro ramas con más volumen (registral, notarial, comercial,
civil), elegidos porque su doctrina es DISTINTIVA: la pregunta no se contesta bien sin ese fallo
—o sin uno que diga lo mismo—. Las preguntas están escritas como las haría un escribano, no
como una consulta armada para que el buscador acierte.

**Las preguntas NO se ajustaron hasta que pasaran.** Un test cuyas preguntas se editan hasta dar
verde no mide nada. Los casos que fallan son hallazgos.

LA LIMITACIÓN QUE HAY QUE TENER PRESENTE
----------------------------------------
El nivel 2 es un PROXY, no una prueba. El redactor escribe prosa y no declara qué fuentes usó,
así que "lo usó" se aproxima buscando en la respuesta los `marcadores` de cada caso: términos de
esa doctrina que difícilmente aparezcan por casualidad. Puede dar falso negativo si el modelo
dice lo mismo con otras palabras, y falso positivo si llega a la misma conclusión por la vía de
la ley sin haber mirado el fallo. Sirve para comparar antes y después de un cambio; no para
afirmar en un caso puntual que el modelo leyó el fallo.

USO
---
    .venv/bin/python tests/test_jurisprudencia.py --recuperacion   # solo nivel 1: gratis y rápido
    .venv/bin/python tests/test_jurisprudencia.py                  # los dos niveles (gasta en Gemini)

El modo `--recuperacion` no llama a ningún LLM de redacción: es el que conviene correr al tocar
el retriever, el `k` o los embeddings.
"""
import re
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Cuántos fallos se piden al mirar la posición real del esperado. Es mayor que el K de
# producción a propósito: si el fallo correcto sale 5º, el diagnóstico «no lo encuentra» y
# «lo encuentra pero queda afuera del k» son cosas distintas, y la segunda se arregla subiendo k.
K_DIAGNOSTICO = 10


# Cada caso: la pregunta, el fallo que debería sostener la respuesta, y los marcadores que
# delatan que esa doctrina llegó al texto final. Los marcadores se buscan en minúsculas y sin
# exigir que estén todos: alcanza con uno.
CASOS = [
    # ---------------------------------------------------------------- registral
    {
        "pregunta": "¿La anotación de litis caduca sola o hay que pedir su levantamiento?",
        "fallo": "Fallo_registral_Caducidad_Anotacion_Litis",
        "marcadores": ["caducidad", "cinco años", "5 años"],
    },
    {
        "pregunta": "Si una hipoteca fue cancelada con un documento falsificado, ¿el adquirente "
                    "que confió en el registro queda protegido?",
        "fallo": "Fallo_registral_Cancelacion_Hipoteca_Apocrifa",
        "marcadores": ["declarativa", "fe pública", "falsificado", "apariencia registral"],
    },
    {
        "pregunta": "¿Puede desafectar el bien de familia uno solo de los cónyuges?",
        "fallo": "Fallo_registral_Desafectacion_BF_conformidad_ambos_conyuges",
        "marcadores": ["ambos cónyuges", "consentimiento", "conformidad"],
    },
    {
        "pregunta": "Inscripta la declaratoria de herederos, ¿los herederos pasan a ser "
                    "condóminos del inmueble?",
        "fallo": "Fallo_registral_Comunidad_Hereditaria",
        "marcadores": ["indivisión hereditaria", "no constituye", "condominio", "exterioriza"],
    },
    # ---------------------------------------------------------------- notarial
    {
        "pregunta": "¿La responsabilidad del escribano por la escritura que autoriza es de "
                    "medios o de resultado?",
        "fallo": "Fallo_notarial_Responsabilidad_Escribano_Deudas",
        "marcadores": ["de resultado", "acto válido"],
    },
    {
        "pregunta": "Un escribano renunció a su registro mientras tenía un sumario abierto. "
                    "¿Se extingue la responsabilidad disciplinaria?",
        "fallo": "Fallo_notarial_Renuncia_no_implica_no_sancion",
        "marcadores": ["no extingue", "responsabilidad disciplinaria", "renuncia"],
    },
    {
        "pregunta": "¿Qué consecuencias disciplinarias tiene antedatar una escritura?",
        "fallo": "Fallo_notarial_Sancion_Escrituras_Antesdatadas",
        "marcadores": ["antedatada", "antesdatada", "falta grave", "disciplinaria"],
    },
    # ---------------------------------------------------------------- comercial
    {
        "pregunta": "¿Desde cuándo es oponible a la sociedad la transmisión hereditaria de "
                    "acciones de una sociedad anónima?",
        "fallo": "Fallo_comercial_Acreditacion_caracter_accionista_trasmision_hereditaria",
        "marcadores": ["libro de registro de acciones", "oponible", "inscripción"],
    },
    {
        "pregunta": "¿Desde cuándo ejercen su cargo los directores designados por asamblea: "
                    "desde la designación o desde la inscripción?",
        "fallo": "Fallo_comercial_Designacion_Autoridades_Inscripcion",
        "marcadores": ["declarativa", "desde la decisión", "desde la asamblea", "no constitutiva"],
    },
    {
        "pregunta": "¿Puede rechazarse la inscripción de una sociedad por tener una "
                    "denominación parecida a la de otra ya inscripta?",
        "fallo": "Fallo_comercial_Denominacion_Homonimia",
        "marcadores": ["homonimia", "novedad", "confusión", "distinguir"],
    },
    {
        "pregunta": "¿Cuál es la diferencia entre fusión y escisión de sociedades?",
        "fallo": "Fallo_comercial_Distincion_Fusion_Escision",
        "marcadores": ["escisión", "unificación", "amalgama", "patrimonio"],
    },
    {
        "pregunta": "¿Qué porcentaje del capital hace falta para pedir judicialmente la "
                    "convocatoria a asamblea?",
        "fallo": "Fallo_comercial_Asamblea_Convocatoria_Judicial",
        "marcadores": ["cinco por ciento", "5%", "convocatoria judicial"],
    },
    # ---------------------------------------------------------------- civil
    {
        "pregunta": "El comprador por boleto que todavía no escrituró, ¿puede reivindicar el "
                    "inmueble contra un tercero?",
        "fallo": "Fallo_civil_Acciones_Titular_Boleto",
        "marcadores": ["reivindicatoria", "legitimación", "boleto", "titularidad"],
    },
    {
        "pregunta": "¿Prescribe la acción para pedir la partición de los bienes gananciales "
                    "después del divorcio?",
        "fallo": "Fallo_civil_Accion_particion_gananciales_imprescriptible",
        "marcadores": ["imprescriptible", "en todo tiempo", "no prescribe"],
    },
]


def verificar_casos(driver) -> list[str]:
    """Que los ids esperados existan en el grafo. Un id mal escrito daría 'no recuperado'
    para siempre, y sería un test roto disfrazado de hallazgo."""
    ids = [c["fallo"] for c in CASOS]
    query = "UNWIND $ids AS i MATCH (j:Jurisprudencia {id: i}) RETURN collect(j.id) AS hay"
    with driver.session() as session:
        hay = set(session.run(query, ids=ids).single()["hay"])
    return [i for i in ids if i not in hay]


def posicion(pregunta: str, fallo_id: str) -> int | None:
    """En qué puesto sale el fallo esperado, pidiendo K_DIAGNOSTICO. None si no está.

    Levanta la excepción si la API falla en los tres intentos: que un 503 se confunda con
    "el fallo no se recuperó" sería el peor resultado posible de este test.
    """
    from api.especialistas.particular import _obtener_retriever_jurisprudencia

    retriever = _obtener_retriever_jurisprudencia()
    # Reintento corto: la API de embeddings de Google devuelve 503 transitorios seguido, y sin
    # esto el test se cae a mitad de corrida por un problema ajeno. No es el
    # `embed_con_reintento()` de la ingesta, que espera 60 s: acá interesa terminar la medición.
    for intento in range(3):
        try:
            # Se pide más de lo que usa producción para poder distinguir "no lo encuentra" de
            # "lo encuentra pero queda afuera del k".
            docs = retriever.vectorstore.similarity_search(pregunta, k=K_DIAGNOSTICO)
            break
        except Exception:
            if intento == 2:
                raise
            time.sleep(3)
    for i, doc in enumerate(docs, start=1):
        if doc.metadata.get("id") == fallo_id:
            return i
    return None


def _plano(texto: str) -> str:
    """Minúsculas y sin markdown ni espacios de más.

    NO es cosmético: el redactor escribe en markdown y pone en negrita justo la palabra que
    importa. Medido, la respuesta decía «es de **resultado**» y el marcador "de resultado" no
    matcheaba por los asteriscos del medio — un falso negativo del test, no del sistema.
    """
    return re.sub(r"\s+", " ", re.sub(r"[*_`#]", "", texto.lower()))


def usa_la_doctrina(respuesta: str, marcadores: list[str]) -> bool:
    """Proxy: alcanza con que aparezca UN marcador. Ver la limitación en el docstring."""
    bajo = _plano(respuesta)
    return any(_plano(m) in bajo for m in marcadores)


def menciona_jurisprudencia(respuesta: str) -> bool:
    """Señal más débil que los marcadores: que la respuesta hable de fallos siquiera."""
    bajo = _plano(respuesta)
    return any(p in bajo for p in ("fallo", "jurisprudencia", "tribunal", "cámara", "sentencia"))


def main() -> int:
    from utils.connectors import get_neo4j_driver

    solo_recuperacion = "--recuperacion" in sys.argv
    k_produccion = None

    driver = get_neo4j_driver()
    faltantes = verificar_casos(driver)
    if faltantes:
        print("Estos ids no existen en el grafo — el test estaría roto, no el sistema:")
        for i in faltantes:
            print(f"  {i}")
        return 1

    from api.especialistas.particular import K_JURISPRUDENCIA
    k_produccion = K_JURISPRUDENCIA

    print(f"{len(CASOS)} casos | k de producción = {k_produccion} | k de diagnóstico = {K_DIAGNOSTICO}\n")

    en_k = fuera_de_k = no_esta = con_error = 0
    usados = mencionan = 0
    evaluados_uso = sin_consultar = 0

    for caso in CASOS:
        try:
            pos = posicion(caso["pregunta"], caso["fallo"])
        except Exception as e:
            con_error += 1
            print(f"  [ERROR    ] {caso['pregunta'][:62]}")
            print(f"      no se pudo ni recuperar: {type(e).__name__}: {str(e)[:80]}")
            continue
        if pos is None:
            estado, no_esta = "NO ESTÁ  ", no_esta + 1
        elif pos <= k_produccion:
            estado, en_k = f"pos {pos} OK ", en_k + 1
        else:
            estado, fuera_de_k = f"pos {pos} >k", fuera_de_k + 1

        linea = f"  [{estado}] {caso['pregunta'][:62]}"

        if not solo_recuperacion:
            import uuid
            from api.agente.streaming import responder_stream

            # UN CASO QUE REVIENTA NO PUEDE LLEVARSE LA CORRIDA ENTERA. Son 14 turnos completos
            # contra servicios de red: medido, un 503 transitorio de la API de embeddings de
            # Google cortó dos corridas a mitad de camino y se perdió todo lo ya gastado. El
            # caso se marca como ERROR y la medición sigue.
            partes, fases = [], []
            try:
                for evento in responder_stream(caso["pregunta"], thread_id=str(uuid.uuid4())):
                    if evento["type"] == "token":
                        partes.append(evento["texto"])
                    elif evento["type"] == "fase":
                        fases.append(evento["fase"])
            except Exception as e:
                con_error += 1
                print(linea + f"\n      ERROR, no se pudo evaluar: {type(e).__name__}: {str(e)[:90]}")
                continue
            respuesta = "".join(partes)

            # QUE EL FALLO ESTÉ EN EL ÍNDICE NO SIGNIFICA QUE HAYA LLEGADO AL REDACTOR. La fase
            # `jurisprudencia` la emite SOLO el especialista particular: si el clasificador mandó
            # la consulta a la ruta general, no se consultó un solo fallo por más que el correcto
            # saliera primero. Sin esta distinción, ese caso se contaría como "el modelo ignoró la
            # doctrina", que es un diagnóstico equivocado y lleva a tocar el prompt del redactor
            # cuando el problema está en el ruteo.
            if "jurisprudencia" not in fases:
                sin_consultar += 1
                linea += f"\n      la ruta NO consultó jurisprudencia (fases: {', '.join(fases)})"
            elif pos is not None and pos <= k_produccion:
                evaluados_uso += 1
                uso = usa_la_doctrina(respuesta, caso["marcadores"])
                men = menciona_jurisprudencia(respuesta)
                usados += uso
                mencionan += men
                linea += f"\n      doctrina en la respuesta: {'SÍ' if uso else 'NO'}"
                linea += f" | menciona jurisprudencia: {'sí' if men else 'no'}"

        print(linea)

    print(f"\nNIVEL 1 — recuperación:")
    print(f"  dentro del k de producción : {en_k}/{len(CASOS)}")
    print(f"  encontrado pero fuera del k: {fuera_de_k}/{len(CASOS)}   (se arregla subiendo k)")
    print(f"  no aparece en {K_DIAGNOSTICO}          : {no_esta}/{len(CASOS)}   (problema de índice, no de prompt)")

    if not solo_recuperacion:
        if con_error:
            print(f"\nCASOS PERDIDOS por error de red o de servicio: {con_error}/{len(CASOS)}")
            print("  No cuentan ni a favor ni en contra: no se pudo evaluar la respuesta.")
        if sin_consultar:
            print(f"\nRUTEO — casos donde NO se consultó jurisprudencia: {sin_consultar}/{len(CASOS)}")
            print("  El fallo estaba en el índice y no llegó al redactor: la ruta general no")
            print("  consulta jurisprudencia. Es un problema de ruteo, no de redacción.")
        if evaluados_uso:
            print(f"\nNIVEL 2 — uso (sobre los {evaluados_uso} que sí llegaron al contexto):")
            print(f"  doctrina presente en la respuesta: {usados}/{evaluados_uso}")
            print(f"  menciona jurisprudencia          : {mencionan}/{evaluados_uso}")

    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
