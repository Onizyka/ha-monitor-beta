# Home Assistant Monitor

Мониторинг доступности Zigbee устройств, заряда батарей и уведомлений через Telegram и MAX.

**Разработчик:** Garger Andrey

## Возможности

- 📡 **Zigbee устройства** — статус онлайн/офлайн, LQI, батарея, картинки из Z2M
- 🔋 **Заряд батарей** — сортировка по уровню, график разряда, TG-алерт
- ⚡ **Токопотребление** — мощность, ток, напряжение, энергия с графиком
- 📈 **Конструктор графиков** — любые метрики, период от 3 часов до 30 дней
- ⏱️ **Таймаут офлайн** — по умолчанию 180 минут (настраивается индивидуально для каждого устройства)
- 🔔 **История уведомлений** — пагинация, автоудаление через 24ч
- 📨 **Telegram** — алерты офлайн, батареи, превышения порогов, ежедневный отчёт
- 💬 **MAX** *(в разработке)* — уведомления в MAX мессенджер (max.ru)

## Необходимые аддоны

| Аддон | Назначение |
|-------|-----------|
| Mosquitto broker | MQTT брокер |
| Zigbee2MQTT | Мост Zigbee-координатора |
| MariaDB | База данных |

## Создание базы данных

```sql
CREATE DATABASE smarthome CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'smarthome'@'%' IDENTIFIED BY 'pass';
GRANT ALL PRIVILEGES ON smarthome.* TO 'smarthome'@'%';
FLUSH PRIVILEGES;
```

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
