"""Prueba comparativa: genera un texto descriptivo para una entidad de ontología (no
Articulo/Norma) usando 3 modelos locales de Ollama con el mismo prompt, para elegir cuál
usar en el pipeline definitivo de "completar entidades". Reúne todos los artículos
conectados a la entidad (relación directa) más los artículos alcanzados por REMITE_A
desde esos artículos (remisiones), arma un único prompt pidiendo síntesis genuina (no
repetición de un artículo puntual) y guarda las 3 respuestas crudas en un solo .txt
plano para revisión manual. No escribe nada en Neo4j — es solo de exploración.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from langchain_ollama import ChatOllama
from utils.connectors import get_neo4j_driver

ENTIDAD_ETIQUETA = "EscrituraPublica"
MODELOS = ["qwen3.6:27b"]

driver = get_neo4j_driver()


def reunir_contexto(etiqueta: str):
    with driver.session() as s:
        nodo = s.run(f"MATCH (n:{etiqueta}) RETURN n.id AS id").single()
        if not nodo:
            raise SystemExit(f"No existe ningún nodo con etiqueta :{etiqueta}")
        entidad_id = nodo["id"]

        directos = s.run(f"""
            MATCH (a:Articulo)-[rel]->(n:{etiqueta} {{id: $eid}})
            RETURN DISTINCT a.id AS art, a.texto AS texto
        """, eid=entidad_id).data()

        ids_directos = {d["art"] for d in directos}

        remisiones = s.run(f"""
            MATCH (a:Articulo)-[rel]->(n:{etiqueta} {{id: $eid}})
            MATCH (a)-[:REMITE_A]->(destino:Articulo)
            RETURN DISTINCT destino.id AS art, destino.texto AS texto
        """, eid=entidad_id).data()

        adicionales = [r for r in remisiones if r["art"] not in ids_directos]

    return entidad_id, directos, adicionales


def armar_prompt(etiqueta: str, entidad_id: str, directos, adicionales) -> str:
    bloques = []
    for d in directos:
        bloques.append(f"[{d['art']}]\n{d['texto']}")
    for a in adicionales:
        bloques.append(f"[{a['art']} — remisión]\n{a['texto']}")
    contexto = "\n\n".join(bloques)

    return f"""Sos un jurista argentino experto en derecho notarial, civil y registral.

Te paso a continuación el texto completo de todos los artículos legales conectados a la entidad "{etiqueta}" (id: {entidad_id}) en una base de conocimiento jurídico, incluyendo artículos a los que estos remiten.

ARTÍCULOS:
{contexto}

TAREA: Escribí un texto descriptivo y completo sobre "{etiqueta}" que sirva como referencia general para responder preguntas del tipo "¿Cuáles son las características de {etiqueta}?" o "¿Qué es {etiqueta}?".

Reglas estrictas:
1. NO te limites a repetir o parafrasear un solo artículo. Sintetizá la información de TODOS los artículos provistos en un texto coherente, propio y que sea bien explicativo.
2. Organizá el contenido en secciones temáticas bien diferenciadas, con un título claro para cada una (por ejemplo: Concepto, Naturaleza jurídica, Forma y requisitos, Quiénes intervienen, Efectos, Sanciones o consecuencias del incumplimiento, Remisiones a otras normas — adaptá o agregá secciones según lo que realmente esté respaldado por los artículos). No organices artículo por artículo.
3. Si distintos artículos aportan matices o requisitos complementarios sobre el mismo aspecto, integralos en una sola explicación dentro de la sección correspondiente.
4. Cuando corresponda, mencioná de qué norma y artículo sale cada afirmación relevante (cita breve entre paréntesis y sin usar guiones), pero el texto debe leerse como una explicación jurídica propia, no como una lista de citas.
5. No inventes contenido que no esté respaldado por los artículos provistos.
6. Evita mencionar temas que no estén directamente relacionados con la "{etiqueta}", aunque aparezcan en los artículos.
7. Podés usar Markdown para estructurar el texto: títulos de sección con "##", y listas con viñetas o numeradas cuando ayuden a la claridad (por ejemplo, para enumerar requisitos o medios de justificación). No abuses del formato: usalo solo donde aporte claridad, el cuerpo de cada sección debe seguir siendo prosa explicativa.
8. Extensión aproximada: 800 a 1000 palabras.
"""


def guardar_contexto(etiqueta: str, entidad_id: str, directos, adicionales) -> str:
    destino = os.path.join(BASE_DIR, "input", "entidades", f"contexto_{etiqueta}.txt")
    with open(destino, "w", encoding="utf-8") as f:
        f.write(f"ENTIDAD: {etiqueta} (id: {entidad_id})\n")
        f.write(f"Artículos directos: {len(directos)} | Adicionales por remisión: {len(adicionales)}\n")
        f.write("=" * 70 + "\n\n")
        f.write("ARTICULOS DIRECTOS\n")
        f.write("-" * 70 + "\n\n")
        for d in directos:
            f.write(f"[{d['art']}]\n{d['texto']}\n\n")
        f.write("ARTICULOS ADICIONALES (por remisión)\n")
        f.write("-" * 70 + "\n\n")
        for a in adicionales:
            f.write(f"[{a['art']}]\n{a['texto']}\n\n")
    return destino


def consultar_modelo(modelo: str, prompt: str) -> str:
    llm = ChatOllama(model=modelo, temperature=0.2)
    respuesta = llm.invoke(prompt)
    return respuesta.content


def main():
    entidad_id, directos, adicionales = reunir_contexto(ENTIDAD_ETIQUETA)
    print(f"Entidad: {ENTIDAD_ETIQUETA} (id={entidad_id})")
    print(f"Artículos directos: {len(directos)} | Adicionales por remisión: {len(adicionales)}")

    ruta_contexto = guardar_contexto(ENTIDAD_ETIQUETA, entidad_id, directos, adicionales)
    print(f"Contexto guardado en: {ruta_contexto}")

    prompt = armar_prompt(ENTIDAD_ETIQUETA, entidad_id, directos, adicionales)

    salidas = []
    for modelo in MODELOS:
        print(f"\nConsultando {modelo}...")
        texto = consultar_modelo(modelo, prompt)
        salidas.append((modelo, texto))
        print(f"  OK ({len(texto)} caracteres)")

    destino = os.path.join(BASE_DIR, "input", "entidades", f"prueba_{ENTIDAD_ETIQUETA}_qwen_markdown.txt")
    with open(destino, "w", encoding="utf-8") as f:
        for modelo, texto in salidas:
            f.write(f"MODELO: {modelo}\n")
            f.write("-" * 70 + "\n")
            f.write(texto.strip())
            f.write("\n\n")
            f.write("=" * 70 + "\n\n")

    print(f"\nGuardado en: {destino}")


if __name__ == "__main__":
    main()
