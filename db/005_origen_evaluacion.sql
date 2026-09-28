-- ==========================================================================================
-- MIGRACIÓN 005 — de dónde salió cada evaluación: del sorteo o del botón «Evaluar»
-- ==========================================================================================
--
-- La encuesta aparece sorteada en 1 de cada 3 respuestas y, además, cada respuesta tiene un
-- botón «Evaluar» para calificarla cuando el escribano quiera. Las dos cosas no valen lo mismo
-- para el análisis: el sorteo es una muestra al azar, y lo voluntario viene sesgado hacia los
-- extremos (se evalúa lo que sorprendió, para bien o para mal). Sin esta columna no se podrían
-- separar.
--
-- Una respuesta que salió en el sorteo sigue siendo `muestreo` aunque el escribano la haya
-- descartado y la evalúe después con el botón: el endpoint no cambia el origen de una fila que
-- ya existe.
--
-- Idempotente. Las filas que ya existían son todas del sorteo, que es el valor por defecto.

ALTER TABLE notaria.evaluaciones
    ADD COLUMN IF NOT EXISTS origen text NOT NULL DEFAULT 'muestreo'
        CHECK (origen IN ('muestreo', 'voluntaria'));

-- La vista suma el origen AL FINAL: CREATE OR REPLACE VIEW solo permite agregar columnas después
-- de las que ya tenía.
CREATE OR REPLACE VIEW notaria.v_beta AS
SELECT t.id              AS turno_id,
       t.creado_en,
       t.version,
       u.email,
       t.conversacion_id,
       t.estado,
       t.rutas,
       t.pregunta,
       t.consulta,
       t.respuesta,
       t.segundos,
       t.ms_primer_token,
       jsonb_array_length(coalesce(t.fuentes, '[]'::jsonb)) AS n_fuentes,
       e.estado          AS encuesta,
       e.exactitud,
       e.pertinencia,
       e.completitud,
       e.fundamentacion,
       e.comentario,
       e.rubrica,
       c.llamadas,
       c.costo_usd,
       e.origen          AS origen_encuesta
FROM notaria.turnos t
JOIN notaria.usuarios u ON u.id = t.usuario_id
LEFT JOIN notaria.evaluaciones e ON e.turno_id = t.id
LEFT JOIN LATERAL (
    SELECT count(*) AS llamadas, sum(l.costo_usd) AS costo_usd
    FROM notaria.llamadas_llm l
    WHERE l.turno_id = t.id
) c ON true;
