# Home Assistant Monitor — Add-on

Мониторинг доступности Zigbee устройств, заряда батарей и уведомления через Telegram и MAX *(в разработке)*.

**Разработчик:** Garger Andrey

Источники данных: **Zigbee2MQTT через MQTT** + **Home Assistant REST API**.  
Стек: **FastAPI · MariaDB · APScheduler · Chart.js**.

---

## Возможности

- 📡 **Zigbee устройства** — список всех устройств, статус онлайн/офлайн, LQI, заряд батареи, картинки из Z2M или свои
- 🔋 **Заряд батарей** — сортировка по уровню, график разряда, TG-алерт при низком заряде
- ⚡ **Токопотребление** — добавление любых числовых метрик (ток, мощность, напряжение, энергия) с графиком
- 📈 **Конструктор графиков** — произвольный выбор метрик и устройств, период от 3 часов до 30 дней
- 🔔 **История уведомлений** — пагинация, ручное и автоматическое удаление (старше 24ч)
- 📨 **Telegram** — алерты офлайн, низкой батареи, превышения порогов; ежедневный отчёт
- 💬 **MAX** *(в разработке)* — отправка уведомлений в MAX мессенджер (max.ru)

---

## Быстрый старт

### 1. Необходимые аддоны в Home Assistant

| Аддон | Назначение |
|-------|-----------|
| Mosquitto broker | MQTT брокер для Zigbee2MQTT |
| Zigbee2MQTT | Мост Zigbee-координатора |
| MariaDB | Хранилище данных |

### 2. Установка

1. **Настройки → Аддоны → Магазин аддонов → ⋮ → Репозитории**
2. Добавить: `https://github.com/Onizyka/ha-monitor`
3. Установить **Home Assistant Monitor**

### 3. Конфигурация

Вкладка **Конфигурация** аддона:

```yaml
# MQTT
mqtt_host: core-mosquitto       # адрес брокера
mqtt_port: 1883
mqtt_user: "mqtt"               # логин MQTT брокера
mqtt_password: "mqtt"          # пароль MQTT брокера
mqtt_topic_prefix: zigbee2mqtt  # должен совпадать с настройкой Z2M

# База данных
db_host: core-mariadb
db_port: 3306
db_name: smarthome             # имя базы данных (создаётся автоматически)
db_user: smarthome             # имя пользователя БД (создаётся автоматически)
db_password: pass              # пароль пользователя БД
db_root_password: ""           # root-пароль MariaDB — нужен только при первом запуске
                               # для автоматического создания БД и пользователя

# Home Assistant API
ha_url: http://supervisor/core
ha_token: ""                    # оставить пустым — используется токен supervisor

# Telegram (необязательно)
telegram_enabled: true
telegram_token: "123456:ABC..."   # от @BotFather
telegram_chat_id: "-100123456"    # ID группы или личного чата

# MAX мессенджер (в разработке)
max_enabled: false
max_token: ""
max_chat_id: ""

log_level: info
```

### 4. Запуск

Нажать **Запустить**, затем **Открыть веб-интерфейс**.  
Дашборд обновляется автоматически каждые 30 секунд.

---

## База данных

### Автоматическое создание

При первом запуске аддон автоматически создаёт базу данных и пользователя — вручную ничего делать не нужно. Для этого укажи `db_root_password` в конфигурации:

```yaml
db_root_password: "root_пароль_от_MariaDB"
```

Аддон выполнит:
```sql
CREATE DATABASE IF NOT EXISTS smarthome CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'smarthome'@'%' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON smarthome.* TO 'smarthome'@'%';
FLUSH PRIVILEGES;
```

После успешного создания `db_root_password` можно оставить пустым — при повторных запусках аддон видит что БД уже существует и пропускает этот шаг.

> Если `db_root_password` не указан и БД не существует — аддон выведет в лог точные SQL-команды для ручного создания и попытается запуститься.

### Смена имени базы данных

Имя базы задаётся параметром `db_name` в конфигурации. Изменить его можно **только до первого запуска** или при переезде на чистую установку.

**Важно:** смена `db_name` на работающей системе не переносит данные — вся история устройств, алерты и настройки останутся в старой базе.

Чтобы переименовать базу на новой установке:

1. Остановить аддон
2. В конфигурации указать нужные значения:
```yaml
db_name: my_smarthome          # новое имя базы
db_user: my_smarthome_user     # новое имя пользователя (опционально)
db_password: new_password
db_root_password: "root_пароль"
```
3. Запустить аддон — база и пользователь будут созданы с новыми именами автоматически

---

## Настройка Telegram

1. Написать [@BotFather](https://t.me/BotFather) → `/newbot` → получить токен
2. Добавить бота в группу или написать напрямую → получить chat_id через [@userinfobot](https://t.me/userinfobot)
3. Заполнить `telegram_token` и `telegram_chat_id` в конфигурации
4. Установить `telegram_enabled: true` и перезапустить аддон

---

## Настройка MAX мессенджера *(в разработке)*

> ⚠️ **Важно:** с августа 2025 года создание ботов в MAX доступно только для верифицированных **юридических лиц РФ**. ИП, самозанятые и физлица пока не допускаются.

Если у вас есть юрлицо:

1. Зарегистрировать бизнес-аккаунт на [dev.max.ru](https://dev.max.ru/docs/maxbusiness/connection)
2. Пройти верификацию организации
3. Открыть диалог с **@MasterBot** в MAX → `/create` → создать бота и пройти модерацию
4. После одобрения: **Чат-боты → Интеграция → Получить токен**
5. Узнать `chat_id` — написать своему боту, он вернёт ID чата в первом сообщении
6. Заполнить конфигурацию аддона:

```yaml
max_enabled: true
max_token: "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"   # токен от MasterBot
max_chat_id: "123456789"                             # ID вашего чата
```

7. Перезапустить аддон → нажать **💬 Тест MAX сообщения** в настройках

**API:** `POST https://platform-api.max.ru/messages`  
**Авторизация:** заголовок `Authorization: <token>` (не query-параметр)

---

## API

Все эндпоинты доступны через ingress путь:

| Эндпоинт | Описание |
|----------|----------|
| `GET /api/summary` | Статистика заголовка |
| `GET /api/devices/` | Все Zigbee устройства |
| `GET /api/devices/history/{ieee}` | История метрики устройства |
| `GET /api/batteries/` | Устройства с батареей, сортировка по уровню |
| `GET /api/alerts/` | История уведомлений |
| `POST /api/alerts/{id}/acknowledge` | Прочитать уведомление |
| `GET /api/settings/` | Настройки мониторинга |
| `POST /api/settings/thresholds` | Сохранить пороги метрик |
| `GET /api/health` | Состояние сервиса |

---

## Структура проекта

```
ha-monitor/
├── config.json / config.yaml   ← Манифест аддона HA
├── Dockerfile
├── run.sh                      ← Точка входа (bashio config → env)
├── requirements.txt
├── alembic/                    ← Миграции базы данных
└── app/
    ├── main.py                 ← FastAPI приложение
    ├── config.py               ← Настройки из переменных окружения
    ├── database.py             ← SQLAlchemy async engine
    ├── models.py               ← Device, DeviceHistory, Alert
    ├── mqtt.py                 ← Подписка на Zigbee2MQTT
    ├── jobs.py                 ← Планировщик: проверка офлайн, алерты, очистка
    ├── telegram_bot.py         ← Telegram бот и отправка алертов
    ├── max_bot.py              ← MAX мессенджер (в разработке)
    ├── routers/
    │   ├── devices.py          ← Устройства и история метрик
    │   ├── batteries.py        ← Батареи
    │   ├── alerts.py           ← Уведомления
    │   └── settings_router.py  ← Настройки и пороги
    └── static/
        └── index.html          ← Одностраничный дашборд (SPA)
```

---

## Локальная разработка

```bash
cp .env.example .env        # скопировать и заполнить переменные
pip install -r requirements.txt
alembic upgrade head        # применить миграции
uvicorn app.main:app --reload --port 8080
```
