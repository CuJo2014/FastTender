#!/bin/sh
# Persistent docker events logger.
exec docker events \
  --filter event=destroy \
  --filter event=die \
  --filter event=kill \
  --filter event=stop \
  --filter event=start \
  --filter event=create \
  --format '{{.Time}} {{.Action}} {{.Type}} name={{.Actor.Attributes.name}} id={{.Actor.ID}}' >> /home/master/fasttender/logs/docker-events.log 2>&1
