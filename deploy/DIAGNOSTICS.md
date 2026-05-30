# Диагностика инцидентов с исчезновением контейнеров

На пилотном сервере (2026-05-29 / 30) несколько раз самопроизвольно
удалялись контейнеры `ft_prod_postgres / redis / app / worker` вместе
с volume `fasttender_postgres_data`. Caddy и контейнеры соседнего
приложения `maksmart-*` оставались живы. Возможные подозреваемые:

- кто-то на сервере (без root-доступа диагностировать сложно)
- `docker compose down` в нашей директории по ошибке
- системный cron c `docker system prune --volumes`
- watchtower-подобный auto-updater
- Portainer/UI-операции

## Что развёрнуто для расследования

### 1. `deploy/events-monitor.sh`

Persistent docker events logger. Логирует **все** create/start/stop/die/destroy/kill для
контейнеров и volumes в `/home/master/fasttender/logs/docker-events.log`.

Запускается из текущей SSH-сессии через `setsid` (нужно — `master`
должен быть в группе `docker`, что у systemd user-сессии не наследуется
по умолчанию):

```bash
setsid sh -c '~/fasttender/deploy/events-monitor.sh' > /dev/null 2>&1 < /dev/null &
```

После `@reboot` cron автоматически перезапускает.

### 2. `deploy/state-snapshot.sh` (cron каждые 5 минут)

Пишет в `/home/master/fasttender/logs/state-snapshot.log` строку вида:

```
2026-05-30T06:15:32Z containers=[ft_prod_postgres=Up 52 minutes ...] volume_size=1.1G item_rows_active/total=96614/96614
```

Каждые 5 минут. Позволяет понять с точностью до 5-минутного окна когда
именно произошёл инцидент, и сопоставить с `docker-events.log` для
точного timestamp + бэкап текущего состояния в bash history пользователя.

### 3. Logrotate (cron 04:15 ежедневно)

`~/.config/logrotate/fasttender.conf` — ротация обоих логов, max 50MB,
до 14 поколений, gzip, copytruncate (чтобы не разрывать pipe nohup-процесса).

### 4. Ежедневный бэкап postgres (cron 03:30)

Уже было — `./deploy/bootstrap.sh backup-db`. Это plaster, не fix —
от инцидента не защищает, но позволяет восстановить.

## Чек-лист после следующего инцидента

1. Зафиксировать `current time` и какие контейнеры исчезли.
2. `tail -200 ~/fasttender/logs/state-snapshot.log` — последний снапшот ДО
   инцидента покажет состояние «всё в норме», следующий — «контейнеров нет».
   Между ними окно ≤ 5 минут.
3. `grep -E "destroy|stop|die" ~/fasttender/logs/docker-events.log | grep ft_prod` —
   точные события удаления с unix-timestamp.
4. `tail -50 ~/.bash_history` — что было выполнено в это окно.
5. Если нужен root: попросить пользователя выполнить:
   - `sudo grep -rE "docker.*prune|docker.*rm|docker compose" /etc/cron* /etc/systemd /var/spool/cron`
   - `sudo journalctl -u docker.service --since "1h ago" --grep "destroy|remove"`
   - `sudo cat /var/log/auth.log | tail -100` — кто что делал через sudo

## Что НЕ закрыто этой диагностикой

- **Защиты данных нет**. Если volume снова исчезнет — восстанавливаем из
  бэкапа (ручной, на самом сервере; внешнего бэкапа в S3 пока нет).
- **Контейнеры не поднимаются автоматически после удаления** —
  при `restart: unless-stopped` они переживают `stop`/`die`, но
  `destroy` удаляет контейнер полностью; restart policy на удалённый
  контейнер уже не действует.

Когда найдём виновника, делаем хардфикс:
- Bind-mount volume вместо named (защита от `docker volume prune`)
- Systemd watchdog с автоподъёмом (защита от `docker rm`)
- Внешний бэкап (защита от потери диска)
