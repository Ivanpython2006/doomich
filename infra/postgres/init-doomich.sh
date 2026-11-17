#!/bin/sh
# Первый запуск PostgreSQL: отдельная роль приложения без прав суперпользователя (иначе построчная
# защита данных RLS не действует), база этой роли и расширение pgvector (ставит только суперпользователь).
set -eu

psql -v ON_ERROR_STOP=1 -v app_password="$DOOMICH_DB_PASSWORD" --username "$POSTGRES_USER" --dbname postgres <<'SQL'
CREATE ROLE doomich LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'app_password';
CREATE DATABASE doomich OWNER doomich;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname doomich -c "CREATE EXTENSION IF NOT EXISTS vector;"
