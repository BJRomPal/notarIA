"""Vuelca los datos de la beta con escribanos para analizarlos fuera de la base.

Lee el esquema `notaria` de Postgres (ver `db/004_beta.sql`) y escribe dos archivos:

  logs/beta_<fecha>/turnos.csv    — la vista `notaria.v_beta`: un turno por fila, con su
                                    encuesta y su costo. Es lo que se abre en una planilla.
  logs/beta_<fecha>/turnos.jsonl  — cada turno COMPLETO: traza con tiempos, contexto que leyó el
                                    redactor, fuentes, evaluación y todas sus llamadas al modelo
                                    con lo que se les mandó y lo que devolvieron. Es la materia
                                    prima del golden dataset.

Va a `logs/` porque no se versiona: son consultas reales de colegas.

No escribe nada en la base. Contra Cloud SQL, correrlo con el Cloud SQL Auth Proxy levantado y
POSTGRES_URL apuntando a él.

Uso:
    .venv/bin/python exploration/exportar_beta.py
    .venv/bin/python exploration/exportar_beta.py --desde 2026-10-01
"""
import argparse
import csv
import json
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv(os.path.join(BASE_DIR, ".env"))

DIMENSIONES = ("exactitud", "pertinencia", "completitud", "fundamentacion")

TURNOS_COMPLETOS = """
SELECT t.*, u.email,
       to_jsonb(e) - 'turno_id' - 'usuario_id' AS evaluacion,
       coalesce((
           SELECT jsonb_agg(jsonb_build_object(
                      'nodo', l.nodo, 'modelo', l.modelo, 'tokens_entrada', l.tokens_entrada,
                      'tokens_salida', l.tokens_salida, 'tokens_pensamiento', l.tokens_pensamiento,
                      'costo_usd', l.costo_usd, 'latencia_ms', l.latencia_ms, 'error', l.error,
                      'entrada', l.entrada, 'salida', l.salida) ORDER BY l.id)
           FROM notaria.llamadas_llm l WHERE l.turno_id = t.id
       ), '[]'::jsonb) AS llamadas
FROM notaria.turnos t
JOIN notaria.usuarios u ON u.id = t.usuario_id
LEFT JOIN notaria.evaluaciones e ON e.turno_id = t.id
WHERE t.creado_en >= %s
ORDER BY t.creado_en
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--desde", default="1970-01-01", help="solo turnos desde esta fecha (AAAA-MM-DD)")
    args = parser.parse_args()

    url = os.getenv("POSTGRES_URL")
    if not url:
        print("Falta POSTGRES_URL.")
        return 1

    carpeta = os.path.join(BASE_DIR, "logs", f"beta_{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(carpeta, exist_ok=True)

    with psycopg.connect(url, row_factory=dict_row) as conn:
        resumen = conn.execute(
            "SELECT * FROM notaria.v_beta WHERE creado_en >= %s ORDER BY creado_en", (args.desde,)
        ).fetchall()
        turnos = conn.execute(TURNOS_COMPLETOS, (args.desde,)).fetchall()

    ruta_csv = os.path.join(carpeta, "turnos.csv")
    with open(ruta_csv, "w", newline="", encoding="utf-8") as f:
        if resumen:
            w = csv.DictWriter(f, fieldnames=list(resumen[0].keys()))
            w.writeheader()
            w.writerows(resumen)

    ruta_jsonl = os.path.join(carpeta, "turnos.jsonl")
    with open(ruta_jsonl, "w", encoding="utf-8") as f:
        for t in turnos:
            f.write(json.dumps(t, ensure_ascii=False, default=str) + "\n")

    # Un resumen en pantalla para saber qué se exportó sin abrir los archivos.
    por_estado: dict[str, int] = {}
    for t in resumen:
        por_estado[t["estado"]] = por_estado.get(t["estado"], 0) + 1
    print(f"{len(resumen)} turnos {por_estado}")
    # El sorteo y el botón «Evaluar» por separado: lo voluntario viene sesgado hacia los extremos,
    # y mezclarlo cambiaría tanto la tasa de respuesta como las medias.
    for origen in ("muestreo", "voluntaria"):
        encuestas = [t for t in resumen if t["encuesta"] and t["origen_encuesta"] == origen]
        respondidas = [t for t in encuestas if t["encuesta"] == "respondida"]
        print(f"{origen}: {len(encuestas)} encuestas abiertas, {len(respondidas)} respondidas"
              + (f" ({100 * len(respondidas) / len(encuestas):.0f} %)" if encuestas else ""))
        for d in DIMENSIONES:
            notas = [t[d] for t in respondidas]
            if notas:
                print(f"  {d:15} media {sum(notas) / len(notas):.2f}  (n={len(notas)})")
    print(f"\n{ruta_csv}\n{ruta_jsonl}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
