-- ==========================================================================================
-- PRECIOS INICIALES de los modelos de Gemini que usa el agente
-- ==========================================================================================
-- Fuente: https://ai.google.dev/gemini-api/docs/pricing, consultada el 06/09/2026.
-- Valores en dólares por millón de tokens.
--
-- Se carga aparte del esquema (001) a propósito: el esquema se corre una vez, los precios
-- cambian. Cuando Google actualice una tarifa, la forma correcta NO es un UPDATE sino cerrar
-- la fila vigente con `hasta` e insertar una nueva con `desde` — así el histórico de
-- `llamadas_llm` sigue siendo auditable contra la tarifa que efectivamente se aplicó.
--
-- ESTADO: no ejecutado contra ninguna base. Ver la cabecera de 001_esquema_notaria.sql.

INSERT INTO notaria.precios_modelo (modelo, desde, hasta, usd_entrada_por_millon, usd_salida_por_millon)
VALUES
    -- El modelo de todo lo mecánico: clasificar, extraer, evaluar suficiencia, resumir la
    -- conversación y elegir herramienta. Es el más barato del catálogo de Gemini.
    ('gemini-2.5-flash-lite', DATE '2026-01-01', NULL, 0.1000, 0.4000),

    -- El modelo de la redacción final y del Text-to-Cypher: lo único que se parece a razonar.
    ('gemini-2.5-flash',      DATE '2026-01-01', NULL, 0.3000, 2.5000)
ON CONFLICT (modelo, desde) DO NOTHING;
