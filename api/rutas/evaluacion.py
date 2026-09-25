"""LA ENCUESTA DE LA BETA — la nota que un escribano le pone a una respuesta.

La encuesta aparece en 1 de cada 4 respuestas (el sorteo lo hace el frontend, ver
`frontend/src/lib/encuesta.ts`) y pasa por tres estados, todos sobre la misma fila de
`notaria.evaluaciones`:

    mostrada    apareció en pantalla. Se registra aunque nadie la conteste: sin esto no se
                puede medir cuántos no respondieron, y quien no responde no es una muestra al azar.
    respondida  con las cuatro notas (y el comentario, opcional). Es definitiva.
    descartada  el escribano apretó «Ahora no».

LA MISMA PROPIEDAD DE SEGURIDAD QUE `cuenta.py`. El `turno_id` lo genera el navegador y viaja en
la URL, así que no prueba nada: la escritura exige que el turno sea del usuario resuelto del
TOKEN, y un turno ajeno da 404 —no 403, que confirmaría que ese id existe—. Se reusa
`_usuario()` de `cuenta.py` para no tener dos criterios de identidad.
"""
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from api.consumo import obtener_pool
from api.rutas.cuenta import _usuario

router = APIRouter(prefix="/api")

Nota = Field(default=None, ge=1, le=5)


class Evaluacion(BaseModel):
    """Body del PUT /api/turnos/{turno_id}/evaluacion."""
    estado: Literal["mostrada", "respondida", "descartada"]
    exactitud: int | None = Nota
    pertinencia: int | None = Nota
    completitud: int | None = Nota
    fundamentacion: int | None = Nota
    comentario: str | None = Field(default=None, max_length=4000)
    rubrica: str = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def notas_segun_estado(self):
        """Respondida lleva las cuatro notas; mostrada y descartada, ninguna. Una nota suelta en
        una encuesta descartada no se sabe si es una opinión o un clic a medias."""
        notas = [self.exactitud, self.pertinencia, self.completitud, self.fundamentacion]
        if self.estado == "respondida" and any(n is None for n in notas):
            raise ValueError("Una evaluación respondida lleva las cuatro notas.")
        if self.estado != "respondida" and (any(n is not None for n in notas) or self.comentario):
            raise ValueError("Solo una evaluación respondida lleva notas o comentario.")
        return self


@router.put("/turnos/{turno_id}/evaluacion")
def guardar_evaluacion(turno_id: str, cuerpo: Evaluacion, request: Request):
    """Registra que la encuesta apareció, o su respuesta, o que se descartó.

    Las transiciones válidas son mostrada → respondida | descartada, y descartada → respondida.
    Una `mostrada` repetida (el componente se volvió a montar) no pisa nada y responde 200.
    Pisar una evaluación ya respondida da 409: la nota que se dio es la que vale.
    """
    usuario_id, _ = _usuario(request)
    try:
        uuid.UUID(turno_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No existe ese turno.")

    comentario = (cuerpo.comentario or "").strip() or None
    with obtener_pool().connection() as conn:
        propio = conn.execute(
            "SELECT 1 FROM notaria.turnos WHERE id = %s AND usuario_id = %s",
            (turno_id, usuario_id),
        ).fetchone()
        if propio is None:
            raise HTTPException(status_code=404, detail="No existe ese turno.")

        fila = conn.execute(
            "INSERT INTO notaria.evaluaciones "
            "  (turno_id, usuario_id, estado, exactitud, pertinencia, completitud, "
            "   fundamentacion, comentario, rubrica, respondida_en) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "        CASE WHEN %s = 'respondida' THEN now() END) "
            "ON CONFLICT (turno_id) DO UPDATE SET "
            "  estado = EXCLUDED.estado, exactitud = EXCLUDED.exactitud, "
            "  pertinencia = EXCLUDED.pertinencia, completitud = EXCLUDED.completitud, "
            "  fundamentacion = EXCLUDED.fundamentacion, comentario = EXCLUDED.comentario, "
            "  rubrica = EXCLUDED.rubrica, respondida_en = EXCLUDED.respondida_en "
            "WHERE EXCLUDED.estado <> 'mostrada' AND notaria.evaluaciones.estado <> 'respondida' "
            "RETURNING estado",
            (turno_id, usuario_id, cuerpo.estado, cuerpo.exactitud, cuerpo.pertinencia,
             cuerpo.completitud, cuerpo.fundamentacion, comentario, cuerpo.rubrica,
             cuerpo.estado),
        ).fetchone()

    if fila is None and cuerpo.estado != "mostrada":
        raise HTTPException(status_code=409, detail="Esa respuesta ya fue evaluada.")
    return {"estado": cuerpo.estado}
