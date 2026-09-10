"""¿Las rutas de la cuenta devuelven lo que corresponde, y SOLO lo del usuario que pregunta?

Dos cosas distintas se prueban acá, y la segunda es la que importa:

1. **Que funcionen** — el alias se guarda y vuelve, el historial se rehidrata con sus fuentes,
   el consumo cuadra con lo que hay en `llamadas_llm`.

2. **Que aíslen** — `conversaciones.id` lo genera el navegador y viaja en la URL, así que un id
   ajeno es trivial de pedir. Se crea un SEGUNDO usuario con su conversación y se verifica que
   el primero no la vea ni la pueda borrar.

POR QUÉ ESTO SE PUEDE PROBAR SIN UN TOKEN DE IAP. No se puede firmar un JWT de IAP en local, así
que el camino feliz con la autenticación encendida no es testeable acá. Pero el aislamiento no
depende de la identidad: depende de que cada consulta lleve `WHERE usuario_id = %s`. Usando el
cliente de prueba de FastAPI sin headers, la identidad es None y todo cae en el usuario de
desarrollo — que es exactamente el "usuario 1" que necesita la prueba. El "usuario 2" se inserta
a mano en Postgres.

Script suelto, sin pytest, como `tests/test_filtro_cypher.py`. Sale con código 1 si algo falla.

    .venv/bin/python tests/test_api_cuenta.py
"""
import json
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


# ==============================================================================================
# PREPARACIÓN — un segundo usuario con datos propios, que el primero no tiene que ver nunca
# ==============================================================================================

AJENO_EXTERNO = "test-api-cuenta-usuario-ajeno"
conv_ajena = str(uuid.uuid4())
conv_propia = str(uuid.uuid4())


def preparar(conn):
    """Crea el usuario ajeno con una conversación, y una conversación del usuario de desarrollo."""
    ajeno = conn.execute(
        "INSERT INTO notaria.usuarios (id_externo, email, alias) VALUES (%s, %s, %s) "
        "ON CONFLICT (id_externo) DO UPDATE SET email = EXCLUDED.email RETURNING id",
        (AJENO_EXTERNO, "ajeno@ejemplo.com", "Ajeno"),
    ).fetchone()[0]

    conn.execute(
        "INSERT INTO notaria.conversaciones (id, usuario_id, titulo) VALUES (%s, %s, %s)",
        (conv_ajena, ajeno, "Conversación del usuario ajeno"),
    )
    conn.execute(
        "INSERT INTO notaria.mensajes (conversacion_id, rol, contenido) VALUES (%s, 'usuario', %s)",
        (conv_ajena, "Esto no lo tiene que leer nadie más."),
    )

    # La conversación propia, con fuentes, para probar la rehidratación de los chips.
    conn.execute(
        "INSERT INTO notaria.usuarios (id, nombre) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
        (USUARIO_DESARROLLO, "Usuario de desarrollo"),
    )
    conn.execute(
        "INSERT INTO notaria.conversaciones (id, usuario_id, titulo) VALUES (%s, %s, %s)",
        (conv_propia, USUARIO_DESARROLLO, "Consulta de prueba del test"),
    )
    conn.execute(
        "INSERT INTO notaria.mensajes (conversacion_id, rol, contenido) VALUES (%s, 'usuario', %s)",
        (conv_propia, "¿Qué exige el art. 77 LSC?"),
    )
    conn.execute(
        "INSERT INTO notaria.mensajes (conversacion_id, rol, contenido, rutas, fuentes) "
        "VALUES (%s, 'asistente', %s, %s, %s)",
        (
            conv_propia,
            "El art. 77 exige...",
            ["particular"],
            json.dumps([{"id": "Art_77_Ley_19550", "tipo": "articulo",
                         "numero": "77", "norma": "Ley 19.550"}]),
        ),
    )
    return ajeno


def limpiar(conn, ajeno):
    """Borra lo que creó el test y nada más. Las conversaciones arrastran sus mensajes en cascada."""
    conn.execute("DELETE FROM notaria.conversaciones WHERE id = %s", (conv_propia,))
    conn.execute("DELETE FROM notaria.usuarios WHERE id = %s", (ajeno,))


def main() -> int:
    pool = obtener_pool()
    if pool is None:
        print("Sin POSTGRES_URL: este test necesita la base. Levantala con "
              "db/levantar_postgres_local.sh")
        return 1

    with pool.connection() as conn:
        ajeno = preparar(conn)

    try:
        print("\nALIAS")
        r = cliente.get("/api/usuario")
        verificar(r.status_code == 200, "GET /api/usuario responde 200", r.text)
        antes = r.json()
        verificar("necesita_alias" in antes and "alias_sugerido" in antes,
                  "trae necesita_alias y alias_sugerido", r.text)

        r = cliente.put("/api/usuario/alias", json={"alias": "  Mariano  el  escribano "})
        verificar(r.status_code == 200, "PUT /api/usuario/alias responde 200", r.text)
        verificar(r.json().get("alias") == "Mariano el escribano",
                  "colapsa los espacios del alias", r.text)

        r = cliente.get("/api/usuario")
        verificar(r.json().get("alias") == "Mariano el escribano", "el alias se persistió", r.text)
        verificar(r.json().get("necesita_alias") is False,
                  "con alias puesto, necesita_alias pasa a False", r.text)

        r = cliente.put("/api/usuario/alias", json={"alias": "   "})
        verificar(r.status_code == 422, "un alias vacío se rechaza con 422", r.text)

        r = cliente.put("/api/usuario/alias", json={"alias": "A" * 80})
        verificar(len(r.json().get("alias", "")) == 40, "el alias se recorta a 40", r.text)

        # Se restaura el alias original para no dejar el entorno cambiado.
        if antes.get("alias") is None:
            with pool.connection() as conn:
                conn.execute("UPDATE notaria.usuarios SET alias = NULL WHERE id = %s",
                             (USUARIO_DESARROLLO,))
        else:
            cliente.put("/api/usuario/alias", json={"alias": antes["alias"]})

        print("\nSUGERENCIA DE NOMBRE DE PILA")
        from api.rutas.cuenta import alias_sugerido
        casos = [
            ("mariano.miro@gmail.com", "Mariano"),
            ("mariano_miro@estudio.com.ar", "Mariano"),
            ("jperez77@notaria.com", "Jperez"),
            ("estudio@juridico.com.ar", "Estudio"),
            ("", ""),
            (None, ""),
        ]
        for email, esperado in casos:
            obtenido = alias_sugerido(email)
            verificar(obtenido == esperado, f"{email!r} → {esperado!r}", f"dio {obtenido!r}")

        print("\nLISTA DE CONVERSACIONES")
        r = cliente.get("/api/conversaciones")
        verificar(r.status_code == 200, "GET /api/conversaciones responde 200", r.text)
        ids = [c["id"] for c in r.json()]
        verificar(conv_propia in ids, "aparece la conversación propia")
        verificar(conv_ajena not in ids, "NO aparece la conversación del otro usuario")

        print("\nREHIDRATACIÓN DE UNA CONVERSACIÓN")
        r = cliente.get(f"/api/conversaciones/{conv_propia}")
        verificar(r.status_code == 200, "GET de la conversación propia responde 200", r.text)
        datos = r.json()
        verificar(len(datos.get("mensajes", [])) == 2, "vuelven los dos mensajes", r.text)
        fuentes = datos["mensajes"][1]["fuentes"]
        verificar(fuentes and fuentes[0]["id"] == "Art_77_Ley_19550",
                  "las fuentes vuelven del jsonb, sin tocar Neo4j", str(fuentes))

        print("\nAISLAMIENTO ENTRE USUARIOS")
        r = cliente.get(f"/api/conversaciones/{conv_ajena}")
        verificar(r.status_code == 404,
                  "leer la conversación ajena da 404 (no 403: un 403 confirmaría que existe)",
                  f"dio {r.status_code}")

        r = cliente.delete(f"/api/conversaciones/{conv_ajena}")
        verificar(r.status_code == 404, "borrar la conversación ajena da 404", f"dio {r.status_code}")
        with pool.connection() as conn:
            sigue = conn.execute("SELECT count(*) FROM notaria.conversaciones WHERE id = %s",
                                 (conv_ajena,)).fetchone()[0]
        verificar(sigue == 1, "y la conversación ajena sigue existiendo")

        r = cliente.get("/api/conversaciones/no-es-un-uuid")
        verificar(r.status_code == 404, "un id que no es uuid da 404, no 500", f"dio {r.status_code}")

        print("\nCONSUMO")
        r = cliente.get("/api/consumo")
        verificar(r.status_code == 200, "GET /api/consumo responde 200", r.text)
        consumo = r.json()
        for clave in ("llamadas", "tokens_entrada", "tokens_salida", "tokens_pensamiento",
                      "costo_usd", "conversaciones", "por_conversacion"):
            verificar(clave in consumo, f"trae {clave}")

        with pool.connection() as conn:
            real = conn.execute(
                "SELECT coalesce(sum(l.tokens_entrada), 0), coalesce(count(*), 0) "
                "FROM notaria.llamadas_llm l "
                "JOIN notaria.conversaciones c ON c.id = l.conversacion_id "
                "WHERE c.usuario_id = %s",
                (USUARIO_DESARROLLO,),
            ).fetchone()
        verificar(consumo["tokens_entrada"] == int(real[0]),
                  "los tokens de entrada cuadran con llamadas_llm",
                  f"API {consumo['tokens_entrada']} vs base {real[0]}")
        verificar(consumo["llamadas"] == int(real[1]),
                  "la cantidad de llamadas cuadra con llamadas_llm",
                  f"API {consumo['llamadas']} vs base {real[1]}")
        verificar(all(c["id"] != conv_ajena for c in consumo["por_conversacion"]),
                  "el detalle no incluye la conversación ajena")

        print("\nBORRADO PROPIO")
        r = cliente.delete(f"/api/conversaciones/{conv_propia}")
        verificar(r.status_code == 204, "borrar la propia responde 204", f"dio {r.status_code}")
        with pool.connection() as conn:
            quedan = conn.execute("SELECT count(*) FROM notaria.conversaciones WHERE id = %s",
                                  (conv_propia,)).fetchone()[0]
            mensajes = conn.execute("SELECT count(*) FROM notaria.mensajes "
                                    "WHERE conversacion_id = %s", (conv_propia,)).fetchone()[0]
        verificar(quedan == 0, "la conversación ya no está")
        verificar(mensajes == 0, "y sus mensajes se fueron en cascada")

    finally:
        with pool.connection() as conn:
            limpiar(conn, ajeno)

    print()
    if fallos:
        print(f"{len(fallos)} FALLAS:")
        for f in fallos:
            print(f"  - {f}")
        return 1
    print("Todo en orden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
