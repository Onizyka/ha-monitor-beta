#!/usr/bin/with-contenv bashio

# ── Read config ───────────────────────────────────────────────────────────────
export MQTT_HOST=$(bashio::config 'mqtt_host')
export MQTT_PORT=$(bashio::config 'mqtt_port')
export MQTT_TOPIC_PREFIX=$(bashio::config 'mqtt_topic_prefix')

bashio::config.exists 'mqtt_user'     && export MQTT_USER=$(bashio::config 'mqtt_user')         || export MQTT_USER=""
bashio::config.exists 'mqtt_password' && export MQTT_PASSWORD=$(bashio::config 'mqtt_password') || export MQTT_PASSWORD=""
bashio::config.exists 'ha_token'      && export HA_TOKEN=$(bashio::config 'ha_token')           || export HA_TOKEN=""

export DB_HOST=$(bashio::config 'db_host')
export DB_PORT=$(bashio::config 'db_port')
export DB_NAME=$(bashio::config 'db_name')
export DB_USER=$(bashio::config 'db_user')
export DB_PASSWORD=$(bashio::config 'db_password')

export HA_URL=$(bashio::config 'ha_url')

export TELEGRAM_ENABLED=$(bashio::config 'telegram_enabled')
bashio::config.exists 'telegram_token'   && export TELEGRAM_TOKEN=$(bashio::config 'telegram_token')     || export TELEGRAM_TOKEN=""
bashio::config.exists 'telegram_chat_id' && export TELEGRAM_CHAT_ID=$(bashio::config 'telegram_chat_id') || export TELEGRAM_CHAT_ID=""
export BATTERY_THRESHOLD=$(bashio::config 'battery_threshold')
export OFFLINE_MINUTES=$(bashio::config 'offline_minutes')
export MAX_ENABLED=$(bashio::config 'max_enabled')
bashio::config.exists 'max_token'   && export MAX_TOKEN=$(bashio::config 'max_token')     || export MAX_TOKEN=""
bashio::config.exists 'max_chat_id' && export MAX_CHAT_ID=$(bashio::config 'max_chat_id') || export MAX_CHAT_ID=""

export PUMP_ENTITY_IDS=$(bashio::config 'pump_entity_ids' || echo "[]")
export LOG_LEVEL=$(bashio::config 'log_level')
export INGRESS_PATH=$(bashio::addon.ingress_entry)

bashio::log.info "Starting Smart Home Monitor..."
bashio::log.info "DB: ${DB_HOST}:${DB_PORT}/${DB_NAME}"
bashio::log.info "MQTT: ${MQTT_HOST}:${MQTT_PORT} / ${MQTT_TOPIC_PREFIX}"
bashio::log.info "Ingress path: ${INGRESS_PATH}"

# ── Wait for MariaDB TCP port (max 60s) ───────────────────────────────────────
bashio::log.info "Waiting for MariaDB on ${DB_HOST}:${DB_PORT}..."
for i in $(seq 1 60); do
  if python3 -c "
import socket, sys
s = socket.socket()
s.settimeout(2)
try:
    s.connect(('${DB_HOST}', int('${DB_PORT}')))
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
    bashio::log.info "MariaDB TCP ready after ${i}s"
    break
  fi
  if [ "$i" -eq 60 ]; then
    bashio::log.error "MariaDB not available after 60s — starting anyway"
  fi
  sleep 1
done

# ── Check DB accessibility, print hint if not ready ──────────────────────────
bashio::log.info "Checking database access..."
python3 - << PYEOF
import pymysql, sys

host    = "${DB_HOST}"
port    = int("${DB_PORT}")
db_name = "${DB_NAME}"
db_user = "${DB_USER}"
db_pass = "${DB_PASSWORD}"

def log(msg):
    print(f"[db-init] {msg}", flush=True)

try:
    pymysql.connect(host=host, port=port, user=db_user, password=db_pass,
                    database=db_name, connect_timeout=3)
    log(f"Database '{db_name}' accessible — OK")
    sys.exit(0)
except Exception as e:
    log(f"Cannot connect to database '{db_name}' as '{db_user}': {e}")
    log("")
    log("Run these commands in the MariaDB addon terminal (Terminal & SSH → MariaDB):")
    log(f"  mysql -u root -p")
    log(f"  > CREATE DATABASE IF NOT EXISTS \`{db_name}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
    log(f"  > CREATE USER IF NOT EXISTS '{db_user}'@'%' IDENTIFIED BY '<db_password из конфига>';")
    log(f"  > GRANT ALL PRIVILEGES ON \`{db_name}\`.* TO '{db_user}'@'%';")
    log(f"  > FLUSH PRIVILEGES;")
    log("")
    log("Then restart this addon.")
    sys.exit(1)
PYEOF

DB_CHECK_EXIT=$?
if [ "$DB_CHECK_EXIT" -ne 0 ]; then
  bashio::log.error "Database not accessible — addon will fail to start. See instructions above."
  exit 1
fi

# ── Alembic migrations ────────────────────────────────────────────────────────
cd /app
bashio::log.info "Running database migrations..."
python3 -m alembic upgrade head || bashio::log.warning "Alembic migration failed — DB may already be up to date"

# ── Start server ──────────────────────────────────────────────────────────────
bashio::log.info "Starting uvicorn on 0.0.0.0:8080 ..."
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8080 \
  --log-level "${LOG_LEVEL}" \
  --root-path "${INGRESS_PATH}"
