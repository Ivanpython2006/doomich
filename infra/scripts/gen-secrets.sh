#!/bin/sh
# Случайные секреты для infra/compose/.env. Печатает строки — допишите их в .env и сохраните копию
# в надёжном месте: без DOOMICH_MASTER_KEY зашифрованные данные пользователей не прочитать.
set -eu
hex() { od -An -tx1 -N"$1" /dev/urandom | tr -d ' \n'; }
echo "POSTGRES_PASSWORD=$(hex 24)"
echo "DOOMICH_DB_PASSWORD=$(hex 24)"
echo "DOOMICH_JWT_SECRET=$(hex 32)"
echo "DOOMICH_MASTER_KEY=$(head -c 32 /dev/urandom | base64 | tr -d '\n')"
echo "DOOMICH_INVITE_PEPPER=$(hex 16)"
echo "GRAFANA_ADMIN_PASSWORD=$(hex 12)"
