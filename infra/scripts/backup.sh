#!/bin/sh
# Резервная копия «Думыча»: база данных, файлы пользователей и реестр моделей.
#   BACKUP_DIR=/var/backups/doomich KEEP_DAYS=14 infra/scripts/backup.sh
#
# Мастер-ключ (DOOMICH_MASTER_KEY из infra/compose/.env) в копию НЕ входит: без него зашифрованные
# данные не прочитать, поэтому храните его отдельно от копий (сейф, менеджер паролей вуза).
# Копию отправляйте в другой ЦОД (rsync, restic) — см. docs/dev/deploy.md.
set -eu

cd "$(dirname "$0")/../.."
BACKUP_DIR=${BACKUP_DIR:-/var/backups/doomich}
KEEP_DAYS=${KEEP_DAYS:-14}
PROJECT=${COMPOSE_PROJECT_NAME:-doomich}
STAMP=$(date +%Y-%m-%d_%H%M)

umask 077
mkdir -p "$BACKUP_DIR"

# база: согласованный снимок без остановки сервиса
docker compose -f infra/compose/compose.yaml exec -T postgres \
    pg_dump -U postgres -d doomich --format=custom > "$BACKUP_DIR/db-$STAMP.dump.partial"
mv "$BACKUP_DIR/db-$STAMP.dump.partial" "$BACKUP_DIR/db-$STAMP.dump"

# файлы пользователей (уже зашифрованы) и реестр моделей
for volume in storage registry; do
    docker run --rm -v "${PROJECT}_${volume}:/src:ro" -v "$BACKUP_DIR:/dst" alpine:3 \
        tar -czf "/dst/${volume}-$STAMP.tar.gz.partial" -C /src .
    mv "$BACKUP_DIR/${volume}-$STAMP.tar.gz.partial" "$BACKUP_DIR/${volume}-$STAMP.tar.gz"
done

find "$BACKUP_DIR" -type f \( -name '*.dump' -o -name '*.tar.gz' \) -mtime +"$KEEP_DAYS" -delete
echo "$(date -Is) резервная копия $STAMP готова: $BACKUP_DIR"
