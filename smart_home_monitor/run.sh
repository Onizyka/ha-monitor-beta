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
bashio::config.exists 'db_root_user'     && export DB_ROOT_USER=$(bashio::config 'db_root_user')         || export DB_ROOT_USER="root"
bashio::config.exists 'db_root_password' && export DB_ROOT_PASSWORD=$(bashio::config 'db_root_password') || export DB_ROOT_PASSWORD=""

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
# TCP check — не требует учётных данных, не зависит от прав root
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

# ── Auto-provision database and user ─────────────────────────────────────────
bashio::log.info "Checking database provisioning..."
python3 - << PYEOF
import pymysql, sys

host      = "${DB_HOST}"
port      = int("${DB_PORT}")
db_name   = "${DB_NAME}"
db_user   = "${DB_USER}"
db_pass   = "${DB_PASSWORD}"
root_user = "${DB_ROOT_USER}"
root_pw   = "${DB_ROOT_PASSWORD}"

def log(msg):
    print(f"[db-init] {msg}", flush=True)

def try_connect(user, password, database=None):
    kwargs = dict(host=host, port=port, user=user, password=password, connect_timeout=3, charset="utf8mb4")
    if database:
        kwargs["database"] = database
    return pymysql.connect(**kwargs)

# Step 1: DB уже доступна под app-пользователем — ничего делать не нужно
try:
    try_connect(db_user, db_pass, database=db_name)
    log(f"Database '{db_name}' already accessible as '{db_user}' — skipping provisioning")
    sys.exit(0)
except Exception:
    pass

# Step 2: Подбираем рабочее root-подключение
# MariaDB HA addon: root доступен без пароля с localhost через сокет,
# но по сети (TCP) требует пароль. Пробуем оба варианта.
root_conn = None
tried = []

for u, p in [(root_user, root_pw), (root_user, ""), ("admin", root_pw), ("admin", "")]:
    label = f"{u}/{'***' if p else '(empty)'}"
    try:
        root_conn = try_connect(u, p)
        log(f"Connected as {label} — provisioning '{db_name}' for '{db_user}'")
        break
    except Exception as e:
        tried.append(f"{label}: {e}")

if root_conn is None:
    log("Could not connect with any admin credentials. Tried:")
    for t in tried:
        log(f"  {t}")
    log("Options:")
    log("  1. Set 'db_root_password' in addon config (root password of MariaDB addon)")
    log("  2. Set 'db_root_user' if your admin user is not 'root'")
    log("  3. Create DB manually in MariaDB addon terminal:")
    log(f"     CREATE DATABASE IF NOT EXISTS \`{db_name}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
    log(f"     CREATE USER IF NOT EXISTS '{db_user}'@'%' IDENTIFIED BY '<db_password из конфига>';")
    log(f"     GRANT ALL PRIVILEGES ON \`{db_name}\`.* TO '{db_user}'@'%';")
    log(f"     FLUSH PRIVILEGES;")
    sys.exit(1)

# Step 3: Создаём БД и пользователя
try:
    with root_conn.cursor() as cur:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS \`{db_name}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cur.execute(f"CREATE USER IF NOT EXISTS '{db_user}'@'%' IDENTIFIED BY '{db_pass}'")
        cur.execute(f"ALTER USER '{db_user}'@'%' IDENTIFIED BY '{db_pass}'")
        cur.execute(f"GRANT ALL PRIVILEGES ON \`{db_name}\`.* TO '{db_user}'@'%'")
        cur.execute("FLUSH PRIVILEGES")
    root_conn.commit()
    root_conn.close()
    log(f"Provisioning complete: database='{db_name}', user='{db_user}'")
    sys.exit(0)
except Exception as e:
    log(f"Provisioning query failed: {e}")
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
