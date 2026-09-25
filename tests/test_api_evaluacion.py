"""¿La encuesta de la beta guarda lo que corresponde, y SOLO sobre turnos del usuario que evalúa?

Tres cosas se prueban:

1. **Que funcione**: mostrada, respondida con las cuatro notas y descartada quedan en
   `notaria.evaluaciones` y se ven en la vista `v_beta`.
2. **Que valide**: una nota fuera de 1..5, una respondida incompleta o una descartada con notas
   son 422, y una evaluación ya respondida no se pisa (409).
3. **Que aísle**: el `turno_id` lo genera el navegador y viaja en la URL. Un turno de OTRO usuario
   da 404 y no se escribe nada.

Igual que `tests/test_api_cuenta.py`: sin token de IAP la identidad es None y todo cae en el
usuario de desarrollo, que es el «usuario 1»; el «usuario 2» se inserta a mano en Postgres. Los
turnos también se insertan a mano: no hace falta correr el agente para probar la encuesta.

Script suelto, sin pytest. Sale con código 1 si algo falla.

    .venv/bin/python tests/test_api_evaluacion.py
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from fastapi.testclient import TestClient

from api.consumo import USUARIO_DESARROLLO, obtener_pool
from api.server import app

cliente = TestClient(app)

fallos: list[str] = []


def verificar(condicion: bool, descripcion: str, detalle: str = ""):
    estado = "OK  " if condicion else "FALLA"
    print(f"  [{estado}] {descripcion}")
    if not condicion:
        if detalle:
            print(f"          {detalle}")
        fallos.append(descripcion)


AJENO_EXTERNO = "test-api-evaluacion-usuario-ajeno"
conv_propia, conv_ajena = str(uuid.uuid4()), str(uuid.uuid4())
turno_propio, turno_propio_2, turno_ajeno = (str(uuid.uuid4()) for _ in range(3))

CUATRO_NOTAS = {"exactitud": 4, "pertinencia": 5, "completitud": 3, "fundamentacion": 4}


def preparar(conn):
    """Un turno ajeno y dos propios, cada uno en su conversación."""
    ajeno = conn.execute(
        "INSERT INTO notaria.usuarios (id_externo, email) VALUES (%s, %s) "
        "ON CONFLICT (id_externo) DO UPDATE SET email = EXCLUDED.email RETURNING id",
        (AJENO_EXTERNO, "ajeno-evaluacion@ejemplo.com"),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO notaria.usuarios (id, nombre) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
        (USUARIO_DESARROLLO, "Usuario de desarrollo"),
    )
    for conv, usuario in ((conv_propia, USUARIO_DESARROLLO), (conv_ajena, ajeno)):
        conn.execute(
            "INSERT INTO notaria.conversaciones (id, usuario_id, titulo) VALUES (%s, %s, %s)",
            (conv, usuario, "Conversación del test de evaluación"),
        )
    for turno, conv, usuario in ((turno_propio, conv_propia, USUARIO_DESARROLLO),
                                 (turno_propio_2, conv_propia, USUARIO_DESARROLLO),
                                 (turno_ajeno, conv_ajena, ajeno)):
        conn.execute(
            "INSERT INTO notaria.turnos (id, conversacion_id, usuario_id, pregunta, estado) "
            "VALUES (%s, %s, %s, %s, 'completo')",
            (turno, conv, usuario, "¿Qué exige el art. 77 LSC?"),
        )
    return ajeno


def limpiar(conn, ajeno):
    """Borra lo que creó el test. Las evaluaciones se van en cascada con sus turnos."""
    conn.execute("DELETE FROM notaria.turnos WHERE id = ANY(%s)",
                 ([turno_propio, turno_propio_2, turno_ajeno],))
    conn.execute("DELETE FROM notaria.conversaciones WHERE id = ANY(%s)", ([conv_propia, conv_ajena],))
    conn.execute("DELETE FROM notaria.usuarios WHERE id = %s", (ajeno,))


def evaluar(turno: str, **cuerpo):
    return cliente.put(f"/api/turnos/{turno}/evaluacion", json={"rubrica": "v1", **cuerpo})


def fila(conn, turno: str):
    return conn.execute(
        "SELECT estado, exactitud, pertinencia, completitud, fundamentacion, comentario, "
        "       respondida_en IS NOT NULL FROM notaria.evaluaciones WHERE turno_id = %s",
        (turno,),
    ).fetchone()


def main() -> int:
    pool = obtener_pool()
    if pool is None:
        print("Sin POSTGRES_URL: este test necesita la base. Levantala con "
              "db/levantar_postgres_local.sh")
        return 1

    with pool.connection() as conn:
        ajeno = preparar(conn)
    try:
        print("\nCAMINO FELIZ")
        r = evaluar(turno_propio, estado="mostrada")
        verificar(r.status_code == 200, "mostrada responde 200", r.text)
        r = evaluar(turno_propio, estado="mostrada")
        verificar(r.status_code == 200, "una mostrada repetida también es 200", r.text)
        r = evaluar(turno_propio, estado="respondida", comentario="  Faltó el art. 78.  ", **CUATRO_NOTAS)
        verificar(r.status_code == 200, "respondida con las cuatro notas responde 200", r.text)
        with pool.connection() as conn:
            f = fila(conn, turno_propio)
        verificar(f == ("respondida", 4, 5, 3, 4, "Faltó el art. 78.", True),
                  "quedaron las notas, el comentario sin espacios y la hora de respuesta", str(f))

        r = evaluar(turno_propio_2, estado="mostrada")
        r = evaluar(turno_propio_2, estado="descartada")
        verificar(r.status_code == 200, "descartada responde 200", r.text)
        r = evaluar(turno_propio_2, estado="mostrada")
        with pool.connection() as conn:
            f = fila(conn, turno_propio_2)
        verificar(f is not None and f[0] == "descartada",
                  "una mostrada posterior no revive una descartada", str(f))
        r = evaluar(turno_propio_2, estado="respondida", **CUATRO_NOTAS)
        verificar(r.status_code == 200, "descartada → respondida se permite", r.text)

        with pool.connection() as conn:
            v = conn.execute("SELECT encuesta, exactitud, fundamentacion FROM notaria.v_beta "
                             "WHERE turno_id = %s", (turno_propio,)).fetchone()
        verificar(v == ("respondida", 4, 4), "la vista v_beta muestra la evaluación", str(v))

        print("\nVALIDACIÓN")
        r = evaluar(turno_propio, estado="respondida", **CUATRO_NOTAS)
        verificar(r.status_code == 409, "pisar una respondida da 409", f"vino {r.status_code}")
        r = evaluar(turno_propio, estado="descartada")
        verificar(r.status_code == 409, "descartar una respondida da 409", f"vino {r.status_code}")
        tres = {k: v for k, v in CUATRO_NOTAS.items() if k != "fundamentacion"}
        r = evaluar(turno_propio_2, estado="respondida", **tres)
        verificar(r.status_code == 422, "respondida con tres notas da 422", f"vino {r.status_code}")
        r = evaluar(turno_propio_2, estado="respondida", **{**CUATRO_NOTAS, "exactitud": 6})
        verificar(r.status_code == 422, "una nota de 6 da 422", f"vino {r.status_code}")
        r = evaluar(turno_propio_2, estado="descartada", exactitud=3)
        verificar(r.status_code == 422, "descartada con una nota da 422", f"vino {r.status_code}")
        r = cliente.post("/api/chat", json={"pregunta": "hola", "turno_id": "no-es-un-uuid"})
        verificar(r.status_code == 422, "un turno_id malformado en /api/chat da 422", f"vino {r.status_code}")

        print("\nAISLAMIENTO")
        r = evaluar(turno_ajeno, estado="respondida", **CUATRO_NOTAS)
        verificar(r.status_code == 404, "evaluar un turno ajeno da 404", f"vino {r.status_code}")
        with pool.connection() as conn:
            verificar(fila(conn, turno_ajeno) is None, "y no se escribió nada sobre el turno ajeno")
        r = evaluar(str(uuid.uuid4()), estado="mostrada")
        verificar(r.status_code == 404, "un turno inexistente da 404", f"vino {r.status_code}")
        r = evaluar("no-es-un-uuid", estado="mostrada")
        verificar(r.status_code == 404, "un id malformado da 404 (no se distingue de ajeno)",
                  f"vino {r.status_code}")
    finally:
        with pool.connection() as conn:
            limpiar(conn, ajeno)

    if fallos:
        print(f"\n{len(fallos)} FALLAS:")
        for f in fallos:
            print(f"  - {f}")
        return 1
    print("\nTodo en orden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
