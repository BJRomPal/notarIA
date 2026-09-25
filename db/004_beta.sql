-- ==========================================================================================
-- MIGRACIÓN 004 — la beta con escribanos: el turno completo y su evaluación
-- ==========================================================================================
--
-- PARA QUÉ. Durante la beta se guarda TODO lo que pasa en un turno, por dos motivos: analizar
-- cómo le fue al sistema con usuarios reales y armar después un golden dataset para evaluarlo
-- en forma automática. Hasta acá el turno no existía como entidad: eran dos filas de `mensajes`
-- sin nada que las uniera, y casi toda la traza (consulta reescrita, contexto que leyó el
-- redactor, Cypher generado, prompts) vivía solo en memoria o en el checkpoint.
--
-- Idempotente como las anteriores: se puede correr sobre una base nueva o sobre una que ya
-- tenga 001-003.

-- ------------------------------------------------------------------------------------------
-- TURNOS — la unidad de análisis de la beta
-- ------------------------------------------------------------------------------------------
-- EL `id` LO GENERA EL NAVEGADOR y viaja en el body del POST /api/chat, igual que el
-- thread_id. Es lo que le permite a la encuesta referirse a la respuesta que evalúa sin tocar
-- el contrato SSE. Como `conversaciones.id`, un id que viene del cliente no prueba propiedad:
-- toda lectura o escritura sobre un turno lleva el `usuario_id` resuelto del token.
--
-- LA FILA NACE AL EMPEZAR EL TURNO (`en_curso`) y se completa al cerrarlo. Tiene que existir
-- desde el principio porque `llamadas_llm.turno_id` apunta acá y la primera llamada al modelo
-- ocurre antes de que haya respuesta. Un turno que queda `en_curso` para siempre es un proceso
-- que murió a mitad de camino: también es un dato.
--
-- `respuesta` y `pregunta` duplican lo que hay en `mensajes`, a propósito: `mensajes` es lo que
-- el usuario relee y solo tiene turnos completos; acá están también los cortados y los que
-- fallaron, con la respuesta parcial que llegó a ver.
--
-- `conversacion_id` ES `ON DELETE SET NULL` Y NO CASCADE: si un escribano borra una
-- conversación deja de verla, pero el dato de la beta queda. Las filas de `llamadas_llm` sí se
-- van con la conversación, como antes.
CREATE TABLE IF NOT EXISTS notaria.turnos (
    id               uuid PRIMARY KEY,
    conversacion_id  uuid REFERENCES notaria.conversaciones(id) ON DELETE SET NULL,
    usuario_id       uuid NOT NULL REFERENCES notaria.usuarios(id),
    mensaje_id       bigint REFERENCES notaria.mensajes(id) ON DELETE SET NULL,  -- la respuesta, si terminó
    estado           text NOT NULL DEFAULT 'en_curso'
                     CHECK (estado IN ('en_curso','completo','cortado','error')),
    pregunta         text NOT NULL,
    consulta         text,          -- reescrita por el clasificador
    rutas            text[],
    respuesta        text,          -- parcial si el turno se cortó
    fuentes          jsonb,         -- las deduplicadas que vio el usuario
    contexto         jsonb,         -- los bloques que leyó el redactor
    traza            jsonb,         -- eventos fase/item/fuentes/fin/error con `t_ms` desde el inicio
    error            text,
    segundos         numeric(7,1),
    ms_primer_token  integer,
    version          text,          -- SHA de la imagen que atendió el turno
    creado_en        timestamptz NOT NULL DEFAULT now(),
    cerrado_en       timestamptz
);
CREATE INDEX IF NOT EXISTS turnos_por_conversacion ON notaria.turnos (conversacion_id, creado_en);
CREATE INDEX IF NOT EXISTS turnos_por_usuario      ON notaria.turnos (usuario_id, creado_en);

-- ------------------------------------------------------------------------------------------
-- LLAMADAS AL MODELO — ahora también con lo que se le mandó y lo que devolvió
-- ------------------------------------------------------------------------------------------
-- `entrada` son los mensajes enviados al modelo y `salida` su contenido más las tool_calls. De
-- acá sale el Cypher generado, la salida cruda del clasificador, el veredicto de suficiencia y
-- los parámetros del determinista, sin que ningún especialista tenga que reportar nada.
ALTER TABLE notaria.llamadas_llm
    ADD COLUMN IF NOT EXISTS turno_id uuid REFERENCES notaria.turnos(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS entrada  jsonb,
    ADD COLUMN IF NOT EXISTS salida   jsonb;
CREATE INDEX IF NOT EXISTS llamadas_por_turno ON notaria.llamadas_llm (turno_id);

-- ------------------------------------------------------------------------------------------
-- EVALUACIONES — la encuesta que aparece en 1 de cada 4 respuestas
-- ------------------------------------------------------------------------------------------
-- Una por turno. Se escribe cuando la encuesta APARECE (`mostrada`) y se actualiza cuando el
-- escribano responde o la descarta: sin las mostradas no se puede medir cuántos no respondieron
-- ni en qué turnos, y quien no responde no es una muestra al azar.
--
-- `rubrica` es la versión del texto de la encuesta. Si se cambia la redacción de una pregunta
-- a mitad de la beta, las notas de antes y de después dejan de ser comparables.
CREATE TABLE IF NOT EXISTS notaria.evaluaciones (
    turno_id        uuid PRIMARY KEY REFERENCES notaria.turnos(id) ON DELETE CASCADE,
    usuario_id      uuid NOT NULL REFERENCES notaria.usuarios(id),
    estado          text NOT NULL CHECK (estado IN ('mostrada','respondida','descartada')),
    exactitud       smallint CHECK (exactitud      BETWEEN 1 AND 5),
    pertinencia     smallint CHECK (pertinencia    BETWEEN 1 AND 5),
    completitud     smallint CHECK (completitud    BETWEEN 1 AND 5),
    fundamentacion  smallint CHECK (fundamentacion BETWEEN 1 AND 5),
    comentario      text,
    rubrica         text NOT NULL,
    mostrada_en     timestamptz NOT NULL DEFAULT now(),
    respondida_en   timestamptz,
    CONSTRAINT respondida_con_las_cuatro_notas CHECK (
        estado <> 'respondida'
        OR (exactitud IS NOT NULL AND pertinencia IS NOT NULL
            AND completitud IS NOT NULL AND fundamentacion IS NOT NULL)
    )
);

-- ------------------------------------------------------------------------------------------
-- VISTA PARA EL ANÁLISIS — un turno por fila, con su encuesta y su costo
-- ------------------------------------------------------------------------------------------
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
       c.costo_usd
FROM notaria.turnos t
JOIN notaria.usuarios u ON u.id = t.usuario_id
LEFT JOIN notaria.evaluaciones e ON e.turno_id = t.id
LEFT JOIN LATERAL (
    SELECT count(*) AS llamadas, sum(l.costo_usd) AS costo_usd
    FROM notaria.llamadas_llm l
    WHERE l.turno_id = t.id
) c ON true;
