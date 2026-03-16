"""
MAX мессенджер (max.ru от VK Group) — отправка уведомлений через Bot API.

API: https://platform-api.max.ru
Документация: https://dev.max.ru/docs-api

Авторизация: заголовок Authorization: <token>  (НЕ query-параметр)
Отправка сообщения: POST /messages
  Body: {"chat_id": <int>, "text": "<string>"}

Как получить токен:
  1. Зарегистрируй бота через @MasterBot в MAX мессенджере
     (требуется верифицированное юрлицо РФ с авг 2025)
  2. Получи токен и chat_id из настроек бота
  3. Пропиши в config.yaml аддона: max_enabled, max_token, max_chat_id
"""
import logging
import httpx
from .config import settings

logger = logging.getLogger(__name__)

MAX_API = "https://platform-api.max.ru"


async def send_max_message(text: str, html: bool = False) -> bool:
    """Отправить сообщение в MAX мессенджер."""
    if not getattr(settings, 'max_enabled', False):
        return False

    token   = getattr(settings, 'max_token', None)
    chat_id = getattr(settings, 'max_chat_id', None)

    if not token or not chat_id:
        logger.warning("MAX: max_token или max_chat_id не настроены в config.yaml")
        return False

    # MAX API не поддерживает HTML-разметку Telegram-стиля — очищаем теги
    clean_text = text
    if html:
        import re
        clean_text = re.sub(r'<[^>]+>', '', text)
        clean_text = clean_text.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')

    payload = {
        "chat_id": int(chat_id),
        "text": clean_text,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{MAX_API}/messages",
                headers={
                    "Authorization": token,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code in (200, 201):
                logger.info("MAX message sent successfully")
                return True
            logger.error("MAX send failed: %s — %s", resp.status_code, resp.text[:300])
            return False
    except Exception as e:
        logger.error("MAX send error: %s", e)
        return False
