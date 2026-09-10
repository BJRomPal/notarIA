"""IDENTIDAD DEL USUARIO — quién está haciendo la consulta.

El proyecto NO implementa login propio, y es deliberado: un chat legal que gasta en Gemini por
request necesita saber quién pregunta, pero escribir autenticación a mano es la peor forma de
conseguirlo. La identidad la resuelve Google —Identity-Aware Proxy adelante de Cloud Run— y acá
solo se la lee.

CÓMO LLEGA, Y POR QUÉ SE VERIFICA LA FIRMA
-------------------------------------------
IAP agrega dos cosas a cada request que deja pasar:

    X-Goog-Authenticated-User-Email : "accounts.google.com:alguien@dominio.com"
    X-Goog-IAP-JWT-Assertion        : un JWT firmado por Google con la misma identidad

**Este módulo usa el JWT, no los headers de texto plano, y la diferencia es la seguridad
entera.** Los headers `X-Goog-Authenticated-User-*` son texto que cualquiera puede escribir: si
alguien consigue llegar al contenedor sin pasar por IAP —una regla de ingress mal puesta, un
puerto expuesto, otro servicio del mismo proyecto— manda ese header a mano y es quien quiera.
El JWT no se puede falsificar sin la clave privada de Google.

REQUISITO DE DESPLIEGUE QUE ESTE CÓDIGO NO PUEDE GARANTIZAR
------------------------------------------------------------
Verificar la firma prueba que el token lo emitió Google para ESTE servicio; no prueba que el
request haya pasado por IAP. Falta cerrar la puerta de atrás: el servicio de Cloud Run tiene que
quedar inalcanzable salvo a través del balanceador con IAP
(`--ingress=internal-and-cloud-load-balancing`). Sin eso, un atacante que llegue directo
simplemente no manda el JWT — y ahí lo que salva es que `IAP_AUDIENCE` esté configurado, porque
entonces un request sin token se rechaza. De ahí que la ausencia de token sea 401 y no un
"seguí como anónimo".

MODO DESARROLLO
---------------
Si `IAP_AUDIENCE` no está en el entorno, la autenticación está APAGADA y `identidad()` devuelve
None: el sistema sigue funcionando como hasta ahora, con el usuario de desarrollo. Es lo que
permite trabajar en local sin levantar un proxy, y es también el interruptor que hay que
acordarse de encender: **sin esa variable no hay autenticación de ningún tipo.**

    IAP_AUDIENCE=/projects/<NUMERO_DE_PROYECTO>/global/backendServices/<ID_DEL_BACKEND>
"""
import os
from dataclasses import dataclass

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

# Las claves públicas con las que Google firma los tokens de IAP. Es un endpoint distinto del
# de los id_token normales de Google (`https://www.googleapis.com/oauth2/v1/certs`): IAP usa su
# propio juego de claves, y verificar contra el otro falla siempre.
CERTS_IAP = "https://www.gstatic.com/iap/verify/public_key"

HEADER_JWT = "X-Goog-IAP-JWT-Assertion"


class IdentidadInvalida(Exception):
    """El pedido no trae una identidad verificable y la autenticación está encendida."""


@dataclass(frozen=True)
class Identidad:
    """Quién es el usuario, en los términos que espera `notaria.usuarios`.

    `id_externo` es el `sub` del token —un identificador estable que no cambia si la persona
    cambia de mail— y por eso es la clave, no el email.
    """
    id_externo: str
    email: str


def autenticacion_activa() -> bool:
    """Hay autenticación solo si se configuró la audiencia esperada."""
    return bool(os.getenv("IAP_AUDIENCE"))


def identidad(headers) -> Identidad | None:
    """La identidad verificada del pedido, o None si la autenticación está apagada.

    `headers` es cualquier mapeo tipo `request.headers` (búsqueda sin distinguir mayúsculas).

    Levanta `IdentidadInvalida` si la autenticación está encendida y el token falta, está
    vencido, viene firmado por otro o fue emitido para otra audiencia. Nunca degrada a anónimo:
    con la autenticación puesta, un pedido sin identidad válida no se atiende.
    """
    audiencia = os.getenv("IAP_AUDIENCE")
    if not audiencia:
        return None

    token = headers.get(HEADER_JWT)
    if not token:
        raise IdentidadInvalida(f"Falta el header {HEADER_JWT}.")

    try:
        # verify_token valida firma, expiración y audiencia. Si algo no cierra, levanta.
        datos = id_token.verify_token(
            token, google_requests.Request(), audience=audiencia, certs_url=CERTS_IAP
        )
    except Exception as e:
        raise IdentidadInvalida(f"Token de IAP inválido: {e}") from e

    sub = datos.get("sub")
    if not sub:
        raise IdentidadInvalida("El token no trae `sub`.")
    return Identidad(id_externo=str(sub), email=str(datos.get("email") or ""))
