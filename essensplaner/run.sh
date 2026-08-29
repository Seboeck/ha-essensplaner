#!/usr/bin/with-contenv bashio
set -e

export HA_URL=$(bashio::config 'ha_url')
export CALENDAR_ENTITY=$(bashio::config 'calendar_entity')
export TODO_ENTITY=$(bashio::config 'todo_entity')
export FAMILY_ADULTS=$(bashio::config 'family_adults')
export FAMILY_KIDS=$(bashio::config 'family_kids')
export SUPERVISOR_TOKEN=${SUPERVISOR_TOKEN}
export DB_PATH="/data/essensplaner.db"

bashio::log.info "Starte Essensplaner Add-on..."
cd /app
uvicorn main:app --host 0.0.0.0 --port 8099
