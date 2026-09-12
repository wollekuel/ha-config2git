#!/usr/bin/with-contenv bashio
set -e

bashio::log.info "ha-config2git: starting"

exec python3 /app/main.py
