#!/usr/bin/env bash
# Удаляет «осиротевшие» deactivated позиции — те на которые нет ссылок
# из MatchCandidate (история матчей) и Verification (решения менеджера).
#
# Логика: REPLACE-импорт прайса по архитектуре делает soft-delete старых
# позиций (is_active=false), чтобы не сломать FK из истории. Но если на
# конкретную позицию никто не ссылается — её можно физически удалить
# без потери информации. Этот скрипт это делает.
#
# Использование (через cron):
#   15 4 * * * /home/master/fasttender/deploy/cleanup-deactivated.sh \
#     >> /home/master/fasttender/logs/cleanup.log 2>&1
#
# Зависимости: запущенный container ft_prod_postgres.

set -euo pipefail

LOG_PREFIX="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PG_CONTAINER="ft_prod_postgres"
PG_USER="fasttender"
PG_DB="fasttender"

echo "${LOG_PREFIX} cleanup-deactivated start"

# Снимок до
BEFORE=$(docker exec "${PG_CONTAINER}" psql -U "${PG_USER}" -d "${PG_DB}" -tA -c "
SELECT count(*) FROM item WHERE is_active = false;
")
echo "${LOG_PREFIX} inactive items before: ${BEFORE}"

# DELETE
DELETED=$(docker exec "${PG_CONTAINER}" psql -U "${PG_USER}" -d "${PG_DB}" -tA -c "
WITH deleted AS (
  DELETE FROM item
  WHERE is_active = false
    AND id NOT IN (SELECT DISTINCT item_id FROM match_candidate WHERE item_id IS NOT NULL)
    AND id NOT IN (SELECT DISTINCT chosen_item_id FROM verification WHERE chosen_item_id IS NOT NULL)
  RETURNING id
)
SELECT count(*) FROM deleted;
")
echo "${LOG_PREFIX} deleted orphaned inactive items: ${DELETED}"

# VACUUM (отдельной транзакцией — psql не разрешает VACUUM внутри tx)
docker exec "${PG_CONTAINER}" psql -U "${PG_USER}" -d "${PG_DB}" -c "VACUUM ANALYZE item;" >/dev/null
echo "${LOG_PREFIX} vacuum done"

# Снимок после
AFTER=$(docker exec "${PG_CONTAINER}" psql -U "${PG_USER}" -d "${PG_DB}" -tA -c "
SELECT count(*) FROM item WHERE is_active = false;
")
echo "${LOG_PREFIX} inactive items after: ${AFTER} (kept due to references in match/verification history)"
echo "---"
