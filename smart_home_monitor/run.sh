#!/usr/bin/with-contenv bashio

# ── Read config ───────────────────────────────────────────────────────────────
export MQTT_HOST=$(bashio::config 'mqtt_host')
export MQTT_PORT=$(bashio::config 'mqtt_port')
export MQTT_TOPIC_PREFIX=$(bashio::config 'mqtt_topic_prefix')

# Optional fields — default to empty string if null/missing
bashio::config.exists 'mqtt_user'     && export MQTT_USER=$(bashio::config 'mqtt_user')         || export MQTT_USER=""
bashio::config.exists 'mqtt_password' && export MQTT_PASSWORD=$(bashio::config 'mqtt_password') || export MQTT_PASSWORD=""
bashio::config.exists 'ha_token'      && export HA_TOKEN=$(bashio::config 'ha_token')           || export HA_TOKEN=""

export DB_HOST=$(bashio::config 'db_host')
export DB_PORT=$(bashio::config 'db_port')
export DB_NAME=$(bashio::config 'db_name')
export DB_USER=$(bashio::config 'db_user')
export DB_PASSWORD=$(bashio::config 'db_password')
bashio::config.exists 'db_root_password' && export DB_ROOT_PASSWORD=$(bashio::config 'db_root_password') || export DB_ROOT_PASSWORD=""

export HA_URL=$(bashio::config 'ha_url')

export TELEGRAM_ENABLED=$(bashio::config 'telegram_enabled')
bashio::config.exists 'telegram_token'    && export TELEGRAM_TOKEN=$(bashio::config 'telegram_token')       || export TELEGRAM_TOKEN=""
bashio::config.exists 'telegram_chat_id'  && export TELEGRAM_CHAT_ID=$(bashio::config 'telegram_chat_id')   || export TELEGRAM_CHAT_ID=""
export BATTERY_THRESHOLD=$(bashio::config 'battery_threshold')
export OFFLINE_MINUTES=$(bashio::config 'offline_minutes')
export MAX_ENABLED=$(bashio::config 'max_enabled')
bashio::config.exists 'max_token'   && export MAX_TOKEN=$(bashio::config 'max_token')     || export MAX_TOKEN=""
bashio::config.exists 'max_chat_id' && export MAX_CHAT_ID=$(bashio::config 'max_chat_id') || export MAX_CHAT_ID=""


# pump_entity_ids is a JSON array — pass it as a string
export PUMP_ENTITY_IDS=$(bashio::config 'pump_entity_ids' || echo "[]")

export LOG_LEVEL=$(bashio::config 'log_level')
export INGRESS_PATH=$(bashio::addon.ingress_entry)

bashio::log.info "Starting Smart Home Monitor..."
bashio::log.info "DB: ${DB_HOST}:${DB_PORT}/${DB_NAME}"
bashio::log.info "MQTT: ${MQTT_HOST}:${MQTT_PORT} / ${MQTT_TOPIC_PREFIX}"
bashio::log.info "Ingress path: ${INGRESS_PATH}"

# ── Wait for MariaDB root (max 60s) ──────────────────────────────────────────
bashio::log.info "Waiting for MariaDB..."
for i in $(seq 1 60); do
  if python3 - << PYEOF 2>/dev/null
import pymysql, sys
try:
    pymysql.connect(
        host="${DB_HOST}", port=int("${DB_PORT}"),
        user="root", password="${DB_ROOT_PASSWORD}",
        connect_timeout=2,
    )
    sys.exit(0)
except Exception:
    # Fallback: try connecting as app user (DB may already be provisioned)
    try:
        pymysql.connect(
            host="${DB_HOST}", port=int("${DB_PORT}"),
            user="${DB_USER}", password="${DB_PASSWORD}",
            database="${DB_NAME}", connect_timeout=2,
        )
        sys.exit(0)
    except Exception:
        sys.exit(1)
PYEOF
  then
    bashio::log.info "MariaDB ready after ${i}s"
    break
  fi
  if [ "$i" -eq 60 ]; then
    bashio::log.error "MariaDB not available after 60s — starting anyway"
  fi
  sleep 1
done

# ── Auto-provision database and user ─────────────────────────────────────────
bashio::log.info "Checking database provisioning..."
python3 - << PYEOF
import pymysql, sys

host     = "${DB_HOST}"
port     = int("${DB_PORT}")
db_name  = "${DB_NAME}"
db_user  = "${DB_USER}"
db_pass  = "${DB_PASSWORD}"
root_pw  = "${DB_ROOT_PASSWORD}"

def log(msg):
    print(f"[db-init] {msg}", flush=True)

# Step 1: Check if DB already accessible as app user — nothing to do
try:
    pymysql.connect(host=host, port=port, user=db_user, password=db_pass,
                    database=db_name, connect_timeout=3)
    log(f"Database '{db_name}' already accessible as '{db_user}' — skipping provisioning")
    sys.exit(0)
except Exception:
    pass

# Step 2: Try root connection to provision
try:
    conn = pymysql.connect(host=host, port=port, user="root", password=root_pw,
                           connect_timeout=3, charset="utf8mb4")
    log(f"Connected as root — provisioning database '{db_name}' and user '{db_user}'")
    with conn.cursor() as cur:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS \`{db_name}\` "
            f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        # Create user for all hosts, update password if already exists
        cur.execute(
            f"CREATE USER IF NOT EXISTS '{db_user}'@'%' IDENTIFIED BY '{db_pass}'"
        )
        cur.execute(
            f"ALTER USER '{db_user}'@'%' IDENTIFIED BY '{db_pass}'"
        )
        cur.execute(
            f"GRANT ALL PRIVILEGES ON \`{db_name}\`.* TO '{db_user}'@'%'"
        )
        cur.execute("FLUSH PRIVILEGES")
    conn.commit()
    conn.close()
    log(f"Provisioning complete: database='{db_name}', user='{db_user}'")
    sys.exit(0)
except Exception as e:
    log(f"Root provisioning failed: {e}")
    log("Hint: set 'db_root_password' in addon config, or create DB manually:")
    log(f"  CREATE DATABASE {db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
    log(f"  CREATE USER '{db_user}'@'%' IDENTIFIED BY '<password>';")
    log(f"  GRANT ALL PRIVILEGES ON {db_name}.* TO '{db_user}'@'%';")
    log(f"  FLUSH PRIVILEGES;")
    sys.exit(1)
PYEOF

DB_INIT_EXIT=$?
if [ "$DB_INIT_EXIT" -ne 0 ]; then
  bashio::log.warning "DB provisioning failed — will try to continue anyway"
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
