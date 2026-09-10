-- MIGRACIÓN: la columna `alias` en bases que se crearon antes de que existiera.
--
-- POR QUÉ HACE FALTA SI YA ESTÁ EN 001. `001_esquema_notaria.sql` define `usuarios.alias`, pero
-- todas sus tablas se crean con CREATE TABLE IF NOT EXISTS: en una base que YA tenía `usuarios`,
-- volver a correr 001 no hace nada y la columna nueva nunca aparece. Verificado contra el
-- contenedor de desarrollo, que tenía las otras cinco columnas y no esta.
--
-- Es idempotente y sirve para los dos casos: en una base nueva —donde 001 ya la creó— no hace
-- nada, y en una vieja la agrega.
--
-- Para qué es la columna: el nombre con el que el usuario quiere que el agente se dirija a él.
-- NULL significa "todavía no se le preguntó", que es distinto de "no quiere alias" (cadena
-- vacía). De esa diferencia depende que el diálogo de bienvenida se abra una sola vez.

ALTER TABLE notaria.usuarios ADD COLUMN IF NOT EXISTS alias text;
