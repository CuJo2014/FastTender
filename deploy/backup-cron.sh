#!/usr/bin/env bash
# Ежедневный бэкап БД + загрузка в Google Drive + ротация.
#
# Использование (через cron):
#   0 3 * * * /home/master/fasttender/deploy/backup-cron.sh >> /home/master/fasttender/logs/backup.log 2>&1
#
# Зависимости: rclone в ~/.local/bin/, remote `gdrive:` настроен.
# Папка на Drive: FastTender-Backups/

set -euo pipefail

DEPLOY_DIR="/home/master/fasttender"
LOG_PREFIX="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RCLONE="${HOME}/.local/bin/rclone"
REMOTE="gdrive:FastTender-Backups"

# Ретеншн (дней)
LOCAL_RETENTION_DAYS=14
REMOTE_RETENTION_DAYS=90

echo "${LOG_PREFIX} backup-cron start"

# 1. Дамп БД (создаёт ./backups/fasttender_YYYYMMDD-HHMMSS.sql.gz)
cd "${DEPLOY_DIR}"
./deploy/bootstrap.sh backup-db

# Найти только что созданный файл (самый свежий .sql.gz)
LATEST=$(ls -t backups/fasttender_*.sql.gz 2>/dev/null | head -1)
if [[ -z "${LATEST}" ]]; then
    echo "${LOG_PREFIX} ERROR: no backup file found after backup-db"
    exit 1
fi
echo "${LOG_PREFIX} created: ${LATEST} ($(du -h "${LATEST}" | cut -f1))"

# 2. Загрузка в Google Drive
"${RCLONE}" copy "${LATEST}" "${REMOTE}/" --progress=false --stats=0 2>&1
echo "${LOG_PREFIX} uploaded to ${REMOTE}/$(basename "${LATEST}")"

# 3. Ротация локальная: удалить старше LOCAL_RETENTION_DAYS
DELETED_LOCAL=$(find backups/ -name 'fasttender_*.sql.gz' -mtime "+${LOCAL_RETENTION_DAYS}" -print -delete | wc -l)
echo "${LOG_PREFIX} local cleanup: deleted ${DELETED_LOCAL} files older than ${LOCAL_RETENTION_DAYS}d"

# 4. Ротация на Drive: удалить старше REMOTE_RETENTION_DAYS
"${RCLONE}" delete "${REMOTE}/" --min-age "${REMOTE_RETENTION_DAYS}d" 2>&1 | grep -v "^$" || true
echo "${LOG_PREFIX} remote cleanup: applied min-age=${REMOTE_RETENTION_DAYS}d"

echo "${LOG_PREFIX} backup-cron done"
echo "---"
