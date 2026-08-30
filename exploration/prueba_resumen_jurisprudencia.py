"""Prueba de concepto: resumen de doctrina jurídica de fallos con Qwen.

Toma una muestra chica de fallos con distinto volumen de texto y genera para cada uno un
resumen de <=100 palabras centrado exclusivamente en el derecho de fondo (la regla jurídica
que rige la relación), descartando todo lo procesal: admisibilidad de recursos, honorarios,
costas, plazos, trámite.

Vuelca los fallos usados a un .txt y los resúmenes a otro, para verificación manual cruzada.
"""
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from langchain_ollama import ChatOllama

MODELO = "qwen3.8:latest"
DIR_FALLOS = os.path.join(BASE_DIR, "input", "Jurisprudencia")
RUTA_FALLOS = os.path.join(DIR_FALLOS, "_muestra_fallos.txt")
RUTA_RESUMENES = os.path.join(DIR_FALLOS, "_muestra_resumenes.txt")

# Muestra con espectro de volumen deliberado: los sumarios ya vienen condensados (control),
# mientras que en los fallos largos la doctrina está enterrada bajo el trámite procesal, que
# es donde el prompt realmente se pone a prueba.
MUESTRA = [
    "comercial/Sindicacion acciones.txt",                    # sumario
    "registral/Calificacíon de los Bienes.txt",              # breve
    "civil/Asentimiento Nulidad Relativa.txt",               # medio
    "notarial/Sancion escribano faltas varias.txt",          # largo
    "civil/División Condominio Acción.txt",                  # muy largo
]

NUM_CTX_TIERS = [8192, 16384, 32768, 65536, 131072, 200000]


def calcular_num_ctx(prompt: str) -> int:
    tokens = len(prompt) // 4 + 2048
    for tier in NUM_CTX_TIERS:
        if tokens <= tier:
            return tier
    return NUM_CTX_TIERS[-1]


def armar_prompt(texto_fallo: str) -> str:
    return f"""Sos un jurista argentino experto en derecho civil, comercial, notarial y registral.

Te paso el texto completo de un fallo judicial argentino.

FALLO:
{texto_fallo}

TAREA: Escribí un resumen de la DOCTRINA JURÍDICA del fallo.

Reglas estrictas:
1. MÁXIMO 100 PALABRAS. Es un límite duro, no una sugerencia. Sé conciso.
2. Escribí ÚNICAMENTE derecho de fondo.

   EL TEST QUE DEBÉS APLICAR A CADA ORACIÓN QUE ESCRIBAS:
   ¿Esta regla gobierna la CONDUCTA de las personas en sus relaciones jurídicas
   (qué deben hacer, qué les está permitido, qué responsabilidad asumen, cómo se
   adquiere o se pierde un derecho, qué facultades tiene un órgano o funcionario)?
   -> Va en el resumen.
   ¿Esta regla gobierna CÓMO SE LITIGA (cuándo o cómo hay que pedir, alegar, plantear,
   probar, recurrir u oponer algo ante un tribunal; quién carga con qué dentro del
   juicio; qué consecuencia tiene hacerlo tarde o mal)?
   -> NO va, aunque esté redactada como principio general y suene doctrinal.

3. Aplicá ese test también a las reglas sobre planteos de inconstitucionalidad,
   oportunidad procesal, preclusión y carga de la prueba: todas son procesales y
   quedan afuera, por más que el fallo les dedique espacio.
4. NO narres los hechos del caso ni quién ganó el pleito. Enunciá la REGLA, no la historia.
5. Escribí en prosa jurídica directa, en presente, como una regla general aplicable a otros
   casos. Nada de "el tribunal dijo que...": enunciá la doctrina.
6. Si el fallo fija más de una regla de fondo, mencioná las principales, siempre dentro del
   límite de 100 palabras.
7. No inventes contenido que no esté en el fallo.
8. ANTES DE RESPONDER hacé esta revisión en dos pasos:
   (a) Releé tu texto y borrá toda oración que no pase el test del punto 2.
   (b) CONTÁ LAS PALABRAS. Si el resultado supera las 100, recortá lo menos esencial
       hasta cumplir el límite. Un resumen de 80 palabras es mejor que uno de 110.

9. NO CIERRES con una oración sobre la vía procesal disponible, el remedio para reclamar,
   ni sobre cómo o ante quién deben plantearse las cuestiones. Es el error más frecuente:
   se enuncia bien la doctrina de fondo y se remata con una coda procesal. El resumen
   termina con la última regla sustantiva, sin epílogo.

RECORDATORIO FINAL: máximo 100 palabras, exclusivamente derecho de fondo, sin coda procesal.
"""


def main():
    resultados = []
    for i, rel in enumerate(MUESTRA, 1):
        ruta = os.path.join(DIR_FALLOS, rel)
        with open(ruta, encoding="utf-8", errors="replace") as f:
            texto = f.read().strip()

        prompt = armar_prompt(texto)
        num_ctx = calcular_num_ctx(prompt)
        print(f"[{i}/{len(MUESTRA)}] {rel}  ({len(texto)} chars, num_ctx={num_ctx})")

        t0 = time.time()
        llm = ChatOllama(model=MODELO, temperature=0.2, num_ctx=num_ctx, reasoning=False)
        resumen = llm.invoke(prompt).content.strip()
        dt = time.time() - t0

        palabras = len(resumen.split())
        print(f"        -> {palabras} palabras en {dt:.0f}s"
              f"{'  ** EXCEDE 100 **' if palabras > 100 else ''}")
        resultados.append({"rel": rel, "texto": texto, "resumen": resumen,
                           "palabras": palabras, "chars": len(texto)})

    with open(RUTA_FALLOS, "w", encoding="utf-8") as f:
        f.write("MUESTRA DE FALLOS USADOS PARA LA PRUEBA DE RESUMEN\n")
        f.write(f"Modelo: {MODELO} | {len(resultados)} fallos\n\n")
        for i, r in enumerate(resultados, 1):
            f.write("=" * 78 + "\n")
            f.write(f"FALLO {i}: {r['rel']}  ({r['chars']} caracteres)\n")
            f.write("=" * 78 + "\n\n")
            f.write(r["texto"] + "\n\n\n")

    with open(RUTA_RESUMENES, "w", encoding="utf-8") as f:
        f.write("RESUMENES DE DOCTRINA JURIDICA (maximo 100 palabras, solo derecho de fondo)\n")
        f.write(f"Modelo: {MODELO} | {len(resultados)} fallos\n\n")
        for i, r in enumerate(resultados, 1):
            f.write("=" * 78 + "\n")
            f.write(f"FALLO {i}: {r['rel']}\n")
            f.write(f"({r['chars']} caracteres de origen -> resumen de {r['palabras']} palabras)\n")
            f.write("=" * 78 + "\n\n")
            f.write(r["resumen"] + "\n\n\n")

    print(f"\nFallos    -> {os.path.relpath(RUTA_FALLOS, BASE_DIR)}")
    print(f"Resumenes -> {os.path.relpath(RUTA_RESUMENES, BASE_DIR)}")


if __name__ == "__main__":
    main()
