"""¿El router manda cada consulta al especialista que corresponde?

EL ERROR QUE MOTIVÓ ESTE TEST. Dos consultas reales de un escribano —«¿qué sociedades deben
publicar edictos en oportunidad de su constitución?» y «¿cuándo un cónyuge debe dar el asentimiento
conyugal?»— cayeron en la ruta `general`, que responde con el RESUMEN del instituto en vez de ir al
articulado. Las respuestas salieron citando «según el instituto Sociedad Comercial» en lugar del
texto del artículo, y las fuentes que vio el usuario fueron entidades, no artículos: no tenía a qué
hacerle clic para verificar.

No era inestabilidad del modelo: medido 5 de 5 veces, siempre mal. El criterio del prompt era **qué
nombra la consulta** (si aparece un instituto → general) cuando el criterio correcto es **qué se
pregunta sobre él**:

    general     → qué ES algo, cómo se define, en qué se diferencia de otro
    particular  → qué EXIGE la norma, cuándo corresponde, quién puede, qué plazo hay

POR QUÉ CADA CASO CORRE VARIAS VECES. El clasificador es una llamada a un LLM: un caso que pasa una
vez puede fallar la siguiente. Lo que interesa no es si acierta, sino cuántas de N acierta. Un caso
que sale 2 de 3 está roto aunque el test "pase" esa corrida.

    .venv/bin/python tests/test_clasificador.py          # 3 corridas por caso
    .venv/bin/python tests/test_clasificador.py 5        # 5 corridas por caso
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from api.agente.nodos import _clasificar_y_resolver

# (consulta, rutas esperadas, por qué)
#
# Las dos primeras son las que fallaron en producción. El resto está para que el arreglo no se
# coma los casos que YA funcionaban: un prompt que mande todo a `particular` arreglaría las dos
# primeras y rompería las cinco de `general`.
CASOS: list[tuple[str, set[str], str]] = [
    # --- Las que fallaron ---
    ("¿Qué sociedades deben publicar edictos en oportunidad de su constitución?",
     {"particular"}, "pide una obligación concreta, no qué es una sociedad"),
    ("Cuando un cónyuge debe dar el asentimiento conyugal?",
     {"particular"}, "pide en qué supuestos rige, no qué es el asentimiento"),

    # --- Particular: la norma operativa. Nombran institutos, pero preguntan por el articulado ---
    ("¿Quienes no pueden ser testigo en un testamento por escritura pública?",
     {"particular"}, "pide una enumeración del articulado"),
    ("¿Qué requisitos exige el art. 77 de la Ley 19.550 para la fusión?",
     {"particular"}, "cita un artículo concreto"),
    ("¿Qué datos debe contener la escritura de constitución de una SRL?",
     {"particular"}, "pide contenido exigido, no qué es una SRL"),
    ("¿Qué plazo hay para inscribir una escritura en el Registro de la Propiedad Inmueble?",
     {"particular"}, "pide un plazo, que lo fija una norma"),
    ("¿Puede un emancipado donar un inmueble recibido a título gratuito?",
     {"particular"}, "pide si un supuesto está permitido"),
    ("¿Qué documentación exige la IGJ para inscribir un cambio de sede social?",
     {"particular"}, "pide requisitos de un trámite"),
    ("¿Cuándo caduca la anotación de litis?",
     {"particular"}, "pide un plazo de caducidad"),
    ("¿Es obligatorio el asentimiento conyugal para vender un inmueble propio?",
     {"particular"}, "pide si rige en un supuesto puntual"),

    # --- General: el instituto en abstracto ---
    ("¿Qué es el usufructo?",
     {"general"}, "pide una definición"),
    ("¿Cuáles son las diferencias entre la SA y la SRL?",
     {"general"}, "compara dos institutos"),
    ("¿Qué es el derecho real de superficie?",
     {"general"}, "pide una definición"),
    ("Explicame en qué consiste el fideicomiso",
     {"general"}, "pide una explicación conceptual"),
    ("¿En qué se diferencia el uso del usufructo?",
     {"general"}, "compara dos institutos"),

    # --- Determinista: cálculos exactos ---
    ("¿Cuál es el dígito verificador de la partida 164360?",
     {"determinista"}, "cálculo exacto"),
    ("Un certificado de dominio en CABA solicitado el 24/07/2026, ¿cuándo vence?",
     {"determinista"}, "cálculo de plazo registral"),
    ("El causante falleció con 3 hijos y sin cónyuge, ¿qué fracción del inmueble le "
     "corresponde a cada heredero?",
     {"determinista"}, "cálculo de porciones hereditarias"),
    ("La valuación fiscal de una donación de un campo a un sobrino es de $80.000.000, "
     "¿cuánto hay que pagar de ITGB?",
     {"determinista"}, "cálculo de impuesto por escala progresiva"),

    # --- Mixta: dos partes de distinto tipo en una sola consulta ---
    ("¿Qué exige la IGJ para inscribir una transformación y cuál es el DV de la partida 1180431?",
     {"particular", "determinista"}, "una parte normativa y una de cálculo"),
]


def main(corridas: int = 3) -> int:
    print(f"\n{len(CASOS)} casos × {corridas} corridas\n")
    fallados: list[str] = []
    aciertos_totales = 0

    for consulta, esperadas, motivo in CASOS:
        obtenidas = Counter()
        aciertos = 0
        for _ in range(corridas):
            try:
                rutas, _ = _clasificar_y_resolver(consulta, "")
            except Exception as e:
                rutas = [f"ERROR: {e}"]
            obtenidas[tuple(sorted(rutas))] += 1
            if set(rutas) == esperadas:
                aciertos += 1

        aciertos_totales += aciertos
        ok = aciertos == corridas
        marca = "OK  " if ok else ("PARCIAL" if aciertos else "FALLA")
        print(f"  [{marca:7}] {aciertos}/{corridas}  {consulta[:64]}")
        if not ok:
            print(f"            esperado {sorted(esperadas)} | obtenido {dict(obtenidas)}")
            print(f"            {motivo}")
            fallados.append(consulta)

    total = len(CASOS) * corridas
    print(f"\n{aciertos_totales}/{total} clasificaciones correctas "
          f"({100 * aciertos_totales // total}%), {len(CASOS) - len(fallados)}/{len(CASOS)} casos "
          f"perfectos")

    return 1 if fallados else 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 3))
