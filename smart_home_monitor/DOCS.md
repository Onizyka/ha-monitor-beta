# Home Assistant Monitor

Мониторинг доступности Zigbee устройств, заряда батарей и уведомлений через Telegram и MAX.

**Разработчик:** Garger Andrey

## Возможности

- 📡 **Zigbee устройства** — статус онлайн/офлайн, LQI, батарея, картинки из Z2M
- 🔋 **Заряд батарей** — сортировка по уровню, график разряда, TG-алерт
- ⚡ **Токопотребление** — мощность, ток, напряжение, энергия с графиком
- 📈 **Конструктор графиков** — любые метрики, период от 3 часов до 30 дней
- ⏱️ **Таймаут офлайн** — по умолчанию 180 минут (настраивается для каждого устройства)
- 🔔 **История уведомлений** — пагинация, автоудаление через 24ч
- 📨 **Telegram** — алерты офлайн, батареи, превышения порогов, ежедневный отчёт
- 💬 **MAX** *(в разработке)* — уведомления в MAX мессенджер (max.ru)

## Необходимые аддоны

| Аддон | Назначение |
|-------|-----------|
| Mosquitto broker | MQTT брокер |
| Zigbee2MQTT | Мост Zigbee-координатора |
| MariaDB | База данных |
| phpMyAdmin | Управление базой данных |

## Быстрый старт

### 1. Установка

1. **Настройки → Аддоны → Магазин аддонов → ⋮ → Репозитории**
2. Добавить: `https://github.com/Onizyka/ha-monitor`
3. Установить **Home Assistant Monitor**

### 2. Установка phpMyAdmin

Установить аддон **phpMyAdmin** из магазина аддонов → Запустить → Открыть веб-интерфейс

### 3. Создание базы данных

1. Нажать **SQL** (цифра 1) в верхней центральной части экрана
2. В появившемся окне вставить код:

![phpMyAdmin SQL](https://raw.githubusercontent.com/Onizyka/ha-monitor/main/smart_home_monitor/docs/phpmyadmin-sql.png)

```sql
CREATE DATABASE IF NOT EXISTS `smarthome` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'smarthome'@'%' IDENTIFIED BY 'pass';
GRANT ALL PRIVILEGES ON `smarthome`.* TO 'smarthome'@'%';
FLUSH PRIVILEGES;
```

Код создаёт базу данных `smarthome`, пользователя `smarthome` и пароль `pass`.

3. Нажать кнопку **Вперёд** (цифра 2)

### 4. Конфигурация

Вкладка **Конфигурация** аддона:

```yaml
mqtt_host: core-mosquitto
mqtt_port: 1883
mqtt_user: "mqtt"
mqtt_password: "mqtt"
mqtt_topic_prefix: zigbee2mqtt

db_host: core-mariadb
db_port: 3306
db_name: smarthome
db_user: smarthome
db_password: pass

ha_url: http://supervisor/core
ha_token: ""

telegram_enabled: true
telegram_token: "123456:ABC..."
telegram_chat_id: "-100123456"

log_level: info
```

### 5. Запуск

Нажать **Запустить**, затем **Открыть веб-интерфейс**.
Дашборд обновляется автоматически каждые 30 секунд.

## Настройка Telegram

1. Написать [@BotFather](https://t.me/BotFather) → `/newbot` → получить токен
2. Получить chat_id через [@userinfobot](https://t.me/userinfobot)
3. Заполнить `telegram_token` и `telegram_chat_id` в конфигурации
4. Включить `telegram_enabled: true`

## Настройка MAX *(в разработке)*

Требуется верифицированное юрлицо РФ. Подробнее: [dev.max.ru](https://dev.max.ru)

1. Создать бота через **@MasterBot** в MAX
2. Получить токен: **Чат-боты → Интеграция → Получить токен**
3. Заполнить `max_token` и `max_chat_id` в конфигурации
4. Включить `max_enabled: true`
