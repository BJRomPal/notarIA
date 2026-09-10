"""LA CUENTA DEL USUARIO — su alias, sus conversaciones y lo que consumió.

Es el espejo de lectura de `api/consumo.py`, y vive en un módulo aparte por una razón concreta
de diseño: **ese archivo se traga todas las excepciones a propósito** —escribir contabilidad no
puede tumbar una respuesta— y acá hace falta lo contrario. Si la lectura del historial falla, el
usuario tiene que ver un error; una lista vacía devuelta en silencio se lee como «no tenés
conversaciones», que es mentira y lo peor que puede pasar con el historial de alguien.

Lo único que se reusa de `consumo.py` es el pool y `id_usuario()`: el pool porque es uno por
proceso, y `id_usuario()` porque es la función que decide qué fila de `usuarios` le corresponde a
un token. Duplicar esa decisión sería tener dos criterios de identidad.

LA PROPIEDAD DE SEGURIDAD QUE ESTE ARCHIVO TIENE QUE SOSTENER
-------------------------------------------------------------
`conversaciones.id` lo genera el cliente (`crypto.randomUUID()` en el navegador) y es a la vez el
`thread_id` del checkpointer. O sea: **un id que viene en la URL no prueba nada**. Cualquiera
puede pedir `/api/conversaciones/<uuid ajeno>`. Por eso toda consulta lleva
`WHERE usuario_id = %s` con el usuario resuelto del token, nunca del pedido, y una conversación
que no es del usuario devuelve **404 y no 403**: un 403 confirmaría que ese id existe.
"""
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from api.auth import Identidad, IdentidadInvalida, identidad
from api.consumo import id_usuario, obtener_pool

_log = logging.getLogger("cuenta")

router = APIRouter(prefix="/api")

# Tope del alias. No es una regla de negocio, es para que el prompt de redacción no pueda recibir
# un texto arbitrariamente largo desde un campo del frontend.
MAX_ALIAS = 40


class AliasNuevo(BaseModel):
    """Body del PUT /api/usuario/alias."""
    alias: str

    @field_validator("alias")
    @classmethod
    def limpiar(cls, v: str) -> str:
        v = " ".join(v.split())        # colapsa espacios y saltos de línea
        if not v:
            raise ValueError("El alias no puede estar vacío.")
        return v[:MAX_ALIAS]


def _usuario(request: Request) -> tuple[uuid.UUID, Identidad | None]:
    """El uuid del usuario del pedido y su identidad, creando su fila si es la primera vez.

    Traduce las dos formas de fallar a códigos HTTP: sin identidad válida es 401 (y lo decide
    `api/auth.py`, no este archivo), y sin base es 503 — porque no es que el usuario no tenga
    datos, es que no hay dónde leerlos, y confundir las dos cosas sería mostrarle un historial
    vacío a alguien que lo tiene lleno.
    """
    try:
        quien = identidad(request.headers)
    except IdentidadInvalida as e:
        raise HTTPException(status_code=401, detail=str(e))

    pool = obtener_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="No hay base de datos configurada.")

    with pool.connection() as conn:
        return id_usuario(conn, quien), quien


def alias_sugerido(email: str | None) -> str:
    """Un nombre de pila tentativo a partir del email: mariano.miro@x → «Mariano».

    El JWT de IAP trae solo `sub` y `email` — **no trae `given_name`**, así que no hay nombre de
    pila que leer y hay que adivinarlo. Adivinarlo alcanza porque es una SUGERENCIA: el usuario
    la ve en un campo editable antes de guardarla. Con una casilla tipo `estudio@` o `info@` va a
    sugerir «Estudio», que es exactamente el caso en que el usuario la corrige.

    Devuelve "" si no hay de dónde sacarlo (el usuario de desarrollo no tiene email): el diálogo
    muestra el campo vacío con su placeholder.
    """
    if not email or "@" not in email:
        return ""
    local = email.split("@", 1)[0]
    primero = local.replace("_", ".").replace("-", ".").replace("+", ".").split(".")[0]
    primero = "".join(c for c in primero if not c.isdigit())
    return primero.capitalize()[:MAX_ALIAS]


@router.get("/usuario")
def ver_usuario(request: Request):
    """Quién es el usuario y cómo quiere que lo llamen."""
    usuario_id, quien = _usuario(request)
    with obtener_pool().connection() as conn:
        fila = conn.execute(
            "SELECT email, alias, nombre FROM notaria.usuarios WHERE id = %s",
            (usuario_id,),
        ).fetchone()

    email, alias, nombre = (fila or (None, None, None))
    return {
        "email": email or (quien.email if quien else ""),
        "alias": alias,
        "alias_sugerido": alias or alias_sugerido(email) or (nombre or "").split(" ")[0],
        # El frontend abre el diálogo de bienvenida con esto. Es `alias IS NULL` y no "alias
        # vacío": un usuario que borró su alias a propósito no tiene que ser interrogado otra vez.
        "necesita_alias": alias is None,
    }


@router.put("/usuario/alias")
def guardar_alias(cuerpo: AliasNuevo, request: Request):
    """Cambia el nombre con el que el agente se dirige al usuario."""
    usuario_id, _ = _usuario(request)
    with obtener_pool().connection() as conn:
        # `nombre` se rellena solo si está vacío: es el dato "de origen" y el alias es la
        # preferencia. Pisarlo en cada edición borraría la diferencia entre los dos.
        conn.execute(
            "UPDATE notaria.usuarios SET alias = %s, nombre = coalesce(nombre, %s) WHERE id = %s",
            (cuerpo.alias, cuerpo.alias, usuario_id),
        )
    return {"alias": cuerpo.alias}


@router.get("/conversaciones")
def listar_conversaciones(request: Request):
    """Las conversaciones del usuario, la más reciente primero.

    Usa el índice `conversaciones_por_usuario (usuario_id, actualizada_en DESC)` que ya existe en
    el esquema, así que es una lectura del índice y no un orden en memoria.
    """
    usuario_id, _ = _usuario(request)
    with obtener_pool().connection() as conn:
        filas = conn.execute(
            "SELECT id, titulo, actualizada_en FROM notaria.conversaciones "
            "WHERE usuario_id = %s AND NOT archivada "
            "ORDER BY actualizada_en DESC",
            (usuario_id,),
        ).fetchall()

    return [
        {"id": str(f[0]), "titulo": f[1] or "Consulta sin título", "actualizada_en": f[2].isoformat()}
        for f in filas
    ]


@router.get("/conversaciones/{conversacion_id}")
def ver_conversacion(conversacion_id: str, request: Request):
    """Los mensajes de una conversación, para rehidratar el chat.

    `mensajes.fuentes` guarda las citas que se le mostraron al usuario, así que los chips de una
    respuesta de la semana pasada se reconstruyen **sin tocar Neo4j**: son los mismos ids que el
    retrieval resolvió entonces.
    """
    usuario_id, _ = _usuario(request)
    try:
        uuid.UUID(conversacion_id)
    except ValueError:
        # `conversaciones.id` es uuid: un id con otra forma no es "no encontrado por permisos",
        # simplemente no puede existir. Se contesta 404 igual, para no dar dos respuestas
        # distinguibles según la forma del id.
        raise HTTPException(status_code=404, detail="No existe esa conversación.")

    with obtener_pool().connection() as conn:
        cabecera = conn.execute(
            "SELECT titulo FROM notaria.conversaciones WHERE id = %s AND usuario_id = %s",
            (conversacion_id, usuario_id),
        ).fetchone()
        if cabecera is None:
            raise HTTPException(status_code=404, detail="No existe esa conversación.")

        filas = conn.execute(
            "SELECT rol, contenido, fuentes, creado_en FROM notaria.mensajes "
            "WHERE conversacion_id = %s ORDER BY creado_en, id",
            (conversacion_id,),
        ).fetchall()

    return {
        "id": conversacion_id,
        "titulo": cabecera[0] or "Consulta sin título",
        "mensajes": [
            {"rol": f[0], "contenido": f[1], "fuentes": f[2] or [], "creado_en": f[3].isoformat()}
            for f in filas
        ],
    }


@router.delete("/conversaciones/{conversacion_id}", status_code=204)
def borrar_conversacion(conversacion_id: str, request: Request):
    """Borra una conversación de verdad: sus filas y su checkpoint.

    BORRAR SOLO LAS FILAS DE `notaria` SERÍA UN BORRADO A MEDIAS. El historial que usa el agente
    no vive ahí: vive en las tablas del checkpointer de LangGraph, indexadas por `thread_id`, que
    es este mismo id. Sin borrar el checkpoint, la conversación desaparece de la lista pero el
    agente la sigue teniendo.

    EL ORDEN IMPORTA. Primero las filas de `notaria` —que es lo que el usuario ve— y después el
    checkpoint. Si falla el checkpoint, queda un huérfano que ocupa lugar y se loguea; si fuera
    al revés y fallaran las filas, quedaría una conversación visible con su historial ya borrado,
    que es peor: el próximo turno arrancaría sin memoria sin que nada lo explique.
    """
    usuario_id, _ = _usuario(request)
    try:
        uuid.UUID(conversacion_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No existe esa conversación.")

    with obtener_pool().connection() as conn:
        # El DELETE lleva el usuario_id: sin eso, cualquiera borraría la conversación de otro
        # con solo acertar un uuid. `rowcount` en 0 significa que no existe o no es suya, y las
        # dos cosas se contestan igual.
        cur = conn.execute(
            "DELETE FROM notaria.conversaciones WHERE id = %s AND usuario_id = %s",
            (conversacion_id, usuario_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="No existe esa conversación.")

    try:
        from utils.connectors import get_checkpointer
        get_checkpointer().delete_thread(conversacion_id)
    except Exception as e:
        _log.warning(f"Quedó el checkpoint huérfano de {conversacion_id}: {e}")


@router.get("/consumo")
def ver_consumo(request: Request):
    """Lo que el usuario gastó, en total y por conversación.

    Sale de las dos vistas que `db/001_esquema_notaria.sql` ya define:
    `consumo_por_conversacion` para el detalle y la misma agregada para los totales. El costo
    está congelado en cada fila al momento de escribirla, así que esto no recalcula nada — y por
    eso un cambio de precios no reescribe el pasado.
    """
    usuario_id, _ = _usuario(request)
    with obtener_pool().connection() as conn:
        filas = conn.execute(
            "SELECT id, titulo, llamadas, tokens_entrada, tokens_salida, tokens_pensamiento, "
            "       costo_usd "
            "FROM notaria.consumo_por_conversacion WHERE usuario_id = %s "
            "ORDER BY costo_usd DESC",
            (usuario_id,),
        ).fetchall()

    detalle = [
        {
            "id": str(f[0]),
            "titulo": f[1] or "Consulta sin título",
            "llamadas": int(f[2] or 0),
            "tokens_entrada": int(f[3] or 0),
            "tokens_salida": int(f[4] or 0),
            "tokens_pensamiento": int(f[5] or 0),
            "costo_usd": float(f[6] or 0),
        }
        for f in filas
    ]

    # Los totales se suman acá en vez de con una segunda consulta a `consumo_por_usuario`: son
    # las mismas filas que ya vinieron, y dos consultas podrían devolver números distintos si
    # entra un turno en el medio.
    return {
        "conversaciones": len(detalle),
        "llamadas": sum(d["llamadas"] for d in detalle),
        "tokens_entrada": sum(d["tokens_entrada"] for d in detalle),
        "tokens_salida": sum(d["tokens_salida"] for d in detalle),
        "tokens_pensamiento": sum(d["tokens_pensamiento"] for d in detalle),
        "costo_usd": round(sum(d["costo_usd"] for d in detalle), 6),
        "por_conversacion": detalle,
    }
