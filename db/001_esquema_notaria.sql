-- ==========================================================================================
-- ESQUEMA notaria — usuarios, conversaciones y consumo del agente notarial
-- ==========================================================================================
--
-- QUÉ ES ESTO. Las tablas del producto: quién usó el sistema, qué conversó y cuánto costó.
-- No tiene nada que ver con el grafo de Neo4j (que sigue siendo la fuente de verdad legal)
-- ni con las tablas del checkpointer de LangGraph.
--
-- POR QUÉ UN ESQUEMA APARTE. Sobre la misma instancia de Postgres conviven dos cosas que no
-- hay que mezclar:
--
--   esquema `langgraph`  lo crea y lo migra LangGraph con su .setup(): checkpoints,
--                        checkpoint_writes, checkpoint_blobs. Formato interno y opaco.
--   esquema `notaria`    este archivo. Es lo que se consulta para facturar y para la UI.
--
-- El checkpointer versiona sus tablas a su ritmo. Si las nuestras vivieran en el mismo
-- esquema, una migración suya podría chocarnos. Separarlas cuesta una línea y evita el
-- problema entero.
--
-- ESTADO: **NO EJECUTADO CONTRA NINGUNA BASE.** Está escrito para PostgreSQL 15+ y
-- gen_random_uuid() es nativo desde la 13, así que no debería haber sorpresas, pero no es lo
-- mismo estar seguro que haberlo verificado. Antes de escribir una línea de Python que lo
-- use, correr:
--
--   docker run --rm -d --name pg-notaria -e POSTGRES_PASSWORD=dev -p 5432:5432 postgres:16
--   sleep 5 && docker exec -i pg-notaria psql -U postgres -v ON_ERROR_STOP=1 < db/001_esquema_notaria.sql
--   docker exec -i pg-notaria psql -U postgres -c "\dt notaria.*"    -- deben aparecer 5 tablas
-- ==========================================================================================

CREATE SCHEMA IF NOT EXISTS notaria;

-- ------------------------------------------------------------------------------------------
-- USUARIOS
-- ------------------------------------------------------------------------------------------
-- Todavía no hay autenticación, y no hace falta para desarrollar el agente: se trabaja con un
-- usuario ficticio. `id_externo` queda esperando al proveedor de identidad que se elija
-- (Google Identity en GCP, vía Identity-Aware Proxy) — cuando llegue, el header que manda el
-- proxy trae exactamente esto y no hay que escribir código de login.
CREATE TABLE IF NOT EXISTS notaria.usuarios (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    id_externo   text UNIQUE,      -- el "sub" del IdP; NULL mientras no haya auth
    email        text UNIQUE,
    nombre       text,
    alias        text,
    creado_en    timestamptz NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------------------------------------
-- CONVERSACIONES
-- ------------------------------------------------------------------------------------------
-- El `id` ES el thread_id de LangGraph, y es el mismo que el frontend ya guarda en
-- localStorage. Una sola clave para las tres capas: sin traducciones ni tablas de mapeo.
CREATE TABLE IF NOT EXISTS notaria.conversaciones (
    id             uuid PRIMARY KEY,
    usuario_id     uuid NOT NULL REFERENCES notaria.usuarios(id) ON DELETE CASCADE,
    titulo         text,
    creada_en      timestamptz NOT NULL DEFAULT now(),
    actualizada_en timestamptz NOT NULL DEFAULT now(),
    archivada      boolean NOT NULL DEFAULT false
);
-- Para la lista lateral del chat: las conversaciones de un usuario, más recientes primero.
CREATE INDEX IF NOT EXISTS conversaciones_por_usuario
    ON notaria.conversaciones (usuario_id, actualizada_en DESC);

-- ------------------------------------------------------------------------------------------
-- MENSAJES
-- ------------------------------------------------------------------------------------------
-- LA CONVERSACIÓN COMPLETA VIVE ACÁ. Es importante entender por qué, porque a primera vista
-- duplica lo que guarda el checkpointer.
--
-- El estado del agente NO guarda la conversación entera: guarda los últimos turnos textuales
-- más un resumen corrido de lo anterior (ver la compactación en api/agente/nodos.py). Eso es
-- lo correcto para lo que el modelo necesita leer, y es lo que evita que el costo de una
-- conversación crezca de forma cuadrática.
--
-- Pero el usuario sí tiene que poder releer todo lo que habló. Esta tabla es ese registro: el
-- modelo de lectura del producto —listar conversaciones, buscar en el historial, sincronizar
-- entre dispositivos—, mientras el checkpointer es la memoria de trabajo del agente.
--
-- El riesgo es que diverjan. Se acota escribiendo acá en un solo lugar (al cerrar el turno) y
-- aceptando que si algo se cae en el medio, la autoridad para reanudar es el checkpointer.
CREATE TABLE IF NOT EXISTS notaria.mensajes (
    id              bigserial PRIMARY KEY,
    conversacion_id uuid NOT NULL REFERENCES notaria.conversaciones(id) ON DELETE CASCADE,
    rol             text NOT NULL CHECK (rol IN ('usuario','asistente')),
    contenido       text NOT NULL,
    rutas           text[],          -- qué especialistas atendieron el turno
    fuentes         jsonb,           -- las citas que se le mostraron al usuario
    creado_en       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mensajes_por_conversacion
    ON notaria.mensajes (conversacion_id, creado_en);

-- ------------------------------------------------------------------------------------------
-- LLAMADAS AL MODELO — el corazón del control de costos
-- ------------------------------------------------------------------------------------------
-- UNA FILA POR LLAMADA, no un total por conversación ni por usuario. La pregunta que va a
-- aparecer a la semana de estar en producción es "¿cuánto me cuesta cada ruta?" o "¿el
-- clasificador con flash-lite alcanza o hay que subirlo?", y con un total agregado eso ya no
-- se puede responder: se perdió qué nodo gastó qué. Al revés sí funciona — los totales por
-- conversación y por usuario son un SUM, y salen gratis (ver las vistas del final).
--
-- El volumen no es problema: una conversación de seis turnos genera unas 30 filas.
CREATE TABLE IF NOT EXISTS notaria.llamadas_llm (
    id                 bigserial PRIMARY KEY,
    conversacion_id    uuid NOT NULL REFERENCES notaria.conversaciones(id) ON DELETE CASCADE,
    mensaje_id         bigint REFERENCES notaria.mensajes(id) ON DELETE SET NULL,
    nodo               text NOT NULL,     -- clasificar | esp_particular | cypher | sintetizar | resumen
    modelo             text NOT NULL,     -- gemini-2.5-flash-lite
    tokens_entrada     integer NOT NULL,
    tokens_salida      integer NOT NULL,  -- incluye los de pensamiento, como factura Google
    tokens_pensamiento integer NOT NULL DEFAULT 0,
    costo_usd          numeric(12,8) NOT NULL,
    latencia_ms        integer,
    error              text,              -- si la llamada falló, por qué
    creado_en          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS llamadas_por_conversacion ON notaria.llamadas_llm (conversacion_id);
CREATE INDEX IF NOT EXISTS llamadas_por_fecha        ON notaria.llamadas_llm (creado_en);
CREATE INDEX IF NOT EXISTS llamadas_por_modelo_nodo  ON notaria.llamadas_llm (modelo, nodo);

-- POR QUÉ `mensaje_id` ES NULLABLE Y `conversacion_id` NO.
-- El gasto ocurre ANTES de que exista la respuesta: `clasificar` llama a Gemini cuando todavía
-- no hay una palabra que guardar en `mensajes`. Si `mensaje_id` fuera NOT NULL, esa primera
-- fila sería imposible de insertar y habría que juntar el consumo en memoria hasta el final
-- del turno. Y ahí aparece el problema de verdad, que no es de modelado sino de plata: si el
-- turno se corta a la mitad —el usuario aprieta Stop, Gemini falla, se cae la instancia— los
-- tokens ya se pagaron y la contabilidad se perdería entera.
-- Como `conversacion_id` existe desde el request (el thread_id viene en el body), toda fila de
-- consumo tiene dónde colgarse desde la primera llamada, y los totales cierran aunque ningún
-- mensaje se haya llegado a escribir. El `mensaje_id` se completa con un UPDATE al cerrar.

-- POR QUÉ `tokens_salida` INCLUYE EL PENSAMIENTO.
-- Porque es como factura Google: "response pricing is the sum of output tokens and thinking
-- tokens". `tokens_pensamiento` va aparte para poder responder cuánto se está pagando por
-- razonamiento invisible — medido sobre el prompt de redacción, hoy sería el 90% del renglón.

-- ------------------------------------------------------------------------------------------
-- PRECIOS
-- ------------------------------------------------------------------------------------------
-- Con ventana de vigencia, y no es sobreingeniería: la propia página de precios de Google dice
-- "$0.75 through December 31, 2026. $1.50 starting January 1, 2027".
--
-- El costo se congela en `llamadas_llm.costo_usd` al momento de escribir la fila. Si se
-- calculara al consultar, el histórico mutaría solo: una factura de octubre pasaría a decir
-- otra cosa en enero. Esta tabla sirve para calcularlo y para auditar con qué tarifa se hizo.
CREATE TABLE IF NOT EXISTS notaria.precios_modelo (
    modelo                 text NOT NULL,
    desde                  date NOT NULL,
    hasta                  date,                 -- NULL = vigente
    usd_entrada_por_millon numeric(10,4) NOT NULL,
    usd_salida_por_millon  numeric(10,4) NOT NULL,
    PRIMARY KEY (modelo, desde)
);

-- ------------------------------------------------------------------------------------------
-- VISTAS DE AGREGACIÓN — no guardan nada, son SUM sobre llamadas_llm
-- ------------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW notaria.consumo_por_conversacion AS
SELECT c.id, c.usuario_id, c.titulo,
       count(*)                  AS llamadas,
       sum(l.tokens_entrada)     AS tokens_entrada,
       sum(l.tokens_salida)      AS tokens_salida,
       sum(l.tokens_pensamiento) AS tokens_pensamiento,
       sum(l.costo_usd)          AS costo_usd
FROM notaria.conversaciones c
JOIN notaria.llamadas_llm l ON l.conversacion_id = c.id
GROUP BY c.id;

CREATE OR REPLACE VIEW notaria.consumo_por_usuario AS
SELECT usuario_id,
       sum(costo_usd)                        AS costo_usd,
       sum(tokens_entrada + tokens_salida)   AS tokens
FROM notaria.consumo_por_conversacion
GROUP BY usuario_id;

-- La consulta que justifica toda la granularidad por llamada, y que con un total por
-- conversación sería imposible de responder:
--
--   SELECT nodo, modelo, count(*) AS llamadas,
--          round(avg(latencia_ms))  AS ms_promedio,
--          sum(costo_usd)           AS costo_usd,
--          round(100.0 * sum(tokens_pensamiento) / nullif(sum(tokens_salida),0), 1) AS pct_pensamiento
--   FROM notaria.llamadas_llm
--   WHERE creado_en > now() - interval '7 days'
--   GROUP BY nodo, modelo ORDER BY costo_usd DESC;
