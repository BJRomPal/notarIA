#!/usr/bin/env bash
# ==========================================================================================
# Levanta el Postgres de desarrollo y carga el esquema `notaria`.
# ==========================================================================================
# Idempotente: si el contenedor ya existe lo reusa, y el SQL usa IF NOT EXISTS / ON CONFLICT.
# Correr desde la raíz del proyecto:  bash db/levantar_postgres_local.sh
#
# REQUISITO: pertenecer al grupo docker. Una sola vez:  sudo usermod -aG docker $USER
#
# Es postgres:16 a propósito: es la misma versión mayor que Cloud SQL, así que el esquema que
# valide acá es el que va a andar allá. Los datos viven en un volumen con nombre y sobreviven
# a `docker rm`; para empezar de cero, borrar el volumen (ver el final del archivo).
set -euo pipefail

NOMBRE=pg-notaria
CLAVE=dev
PUERTO=5432
VOLUMEN=notaria-pgdata

if docker ps -a --format '{{.Names}}' | grep -qx "$NOMBRE"; then
    echo "==> El contenedor $NOMBRE ya existe; me aseguro de que esté corriendo."
    docker start "$NOMBRE" >/dev/null
else
    echo "==> Creando $NOMBRE (postgres:16) en el puerto $PUERTO."
    docker run -d --name "$NOMBRE" \
        -e POSTGRES_PASSWORD="$CLAVE" \
        -p "$PUERTO":5432 \
        -v "$VOLUMEN":/var/lib/postgresql/data \
        --restart unless-stopped \
        postgres:16 >/dev/null
fi

echo "==> Esperando a que acepte conexiones..."
for i in $(seq 1 60); do
    if docker exec "$NOMBRE" pg_isready -U postgres >/dev/null 2>&1; then break; fi
    sleep 1
done
docker exec "$NOMBRE" pg_isready -U postgres

echo "==> Cargando db/001_esquema_notaria.sql"
docker exec -i "$NOMBRE" psql -U postgres -v ON_ERROR_STOP=1 -q < db/001_esquema_notaria.sql

echo "==> Cargando db/002_precios_modelo.sql"
docker exec -i "$NOMBRE" psql -U postgres -v ON_ERROR_STOP=1 -q < db/002_precios_modelo.sql

echo "==> Cargando db/003_alias_usuario.sql"
docker exec -i "$NOMBRE" psql -U postgres -v ON_ERROR_STOP=1 -q < db/003_alias_usuario.sql

echo
echo "==> Tablas del esquema notaria:"
docker exec "$NOMBRE" psql -U postgres -c "\dt notaria.*"
echo "==> Vistas:"
docker exec "$NOMBRE" psql -U postgres -c "\dv notaria.*"
echo "==> Precios cargados:"
docker exec "$NOMBRE" psql -U postgres -c "SELECT * FROM notaria.precios_modelo"

echo
echo "Listo. Agregar al .env de la raíz:"
echo "  POSTGRES_URL=postgresql://postgres:$CLAVE@localhost:$PUERTO/postgres"
echo
echo "Para empezar de cero (BORRA los datos):"
echo "  docker rm -f $NOMBRE && docker volume rm $VOLUMEN"
