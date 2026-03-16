"""
Telegram bot for Smart Home Monitor alerts.

Uses HTML parse_mode — no special character escaping needed.

Commands:
  /start    — welcome + command list
  /status   — online/offline counts, low batteries
  /pumps    — current pump states
  /alerts   — last 5 alerts
  /mute 60  — silence notifications for N minutes
  /unmute   — re-enable notifications
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import TelegramError

from .config import settings

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))
def now_msk() -> datetime:
    return datetime.now(MSK)

_app: Optional[Application] = None
_muted_until: Optional[datetime] = None
_get_db = None


# ── Lifecycle ─────────────────────────────────────────────────────────────

async def start_bot(get_db_func):
    global _app, _get_db
    if not settings.telegram_enabled or not settings.telegram_token:
        logger.info("Telegram bot disabled — skipping.")
        return
    _get_db = get_db_func
    try:
        _app = Application.builder().token(settings.telegram_token).build()
        _app.add_handler(CommandHandler("start",  cmd_start))
        _app.add_handler(CommandHandler("status", cmd_status))
        _app.add_handler(CommandHandler("pumps",  cmd_pumps))
        _app.add_handler(CommandHandler("alerts", cmd_alerts))
        _app.add_handler(CommandHandler("mute",   cmd_mute))
        _app.add_handler(CommandHandler("unmute", cmd_unmute))
        await _app.initialize()
        await _app.start()
        await _app.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=[],
            error_callback=lambda err: logger.warning("Telegram polling error (ignored): %s", err)
        )
        logger.info("Telegram bot started.")
    except Exception as e:
        logger.error("Telegram bot failed to start: %s", e)
        _app = None


async def stop_bot():
    if _app:
        try:
            await _app.updater.stop()
            await _app.stop()
            await _app.shutdown()
        except Exception as e:
            logger.warning("Telegram bot stop error: %s", e)


# ── Outbound alerts ───────────────────────────────────────────────────────

def _is_muted() -> bool:
    return _muted_until is not None and datetime.utcnow() < _muted_until


def _html(s: str) -> str:
    """Escape string for Telegram HTML parse mode."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def send_alert(message: str, level: str = "warn", html: bool = False) -> bool:
    """
    Send message to configured chat using HTML parse mode.
    message: plain text (will be escaped) unless html=True (pre-formatted HTML).
    Returns True on success. Respects mute state.
    """
    if not settings.telegram_enabled or not settings.telegram_token:
        return False
    if not _app:
        logger.warning("Telegram bot not initialized — skipping alert")
        return False
    if _is_muted():
        logger.debug("Telegram muted — skipping: %s", message)
        return False

    icons = {"ok": "✅", "warn": "⚠️", "err": "🔴", "info": "ℹ️"}
    icon = icons.get(level, "📢")
    now = now_msk().strftime("%H:%M MSK")
    body = message if html else _html(message)
    text = f"{icon} <b>Smart Home</b> <code>{now}</code>\n{body}"

    tg_ok = False
    try:
        bot = Bot(token=settings.telegram_token)
        await bot.send_message(
            chat_id=settings.telegram_chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
        )
        tg_ok = True
    except TelegramError as e:
        from telegram.error import Conflict
        if isinstance(e, Conflict):
            logger.warning("Telegram Conflict (another instance running): %s", e)
        else:
            logger.error("Telegram send failed: %s", e)

    # Send to MAX independently — regardless of Telegram result
    try:
        from .max_bot import send_max_message
        await send_max_message(text, html=True)
    except Exception:
        pass

    return tg_ok


async def send_battery_alert(device_name: str, pct: int):
    await send_alert(
        f"🪫 Батарея <b>{_html(device_name)}</b> — {pct}%. Требуется замена.",
        level="warn", html=True,
    )


async def send_offline_alert(device_name: str, minutes: int):
    await send_alert(
        f"📵 Устройство <b>{_html(device_name)}</b> офлайн более {minutes} минут.",
        level="err", html=True,
    )


async def send_pump_alert(pump_name: str, reason: str):
    await send_alert(
        f"💧 Насос <b>{_html(pump_name)}</b>: {_html(reason)}",
        level="err", html=True,
    )


# ── Command handlers ──────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 <b>Smart Home Monitor</b>\n\n"
        "/status — состояние сети\n"
        "/pumps  — насосы\n"
        "/alerts — последние тревоги\n"
        "/mute 60 — тишина на N минут\n"
        "/unmute  — включить уведомления",
        parse_mode=ParseMode.HTML,
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if _get_db is None:
        await update.message.reply_text("⚙️ База данных не подключена.")
        return
    try:
        from sqlalchemy import select, func
        from .models import Device

        async with _get_db() as db:
            total  = (await db.execute(select(func.count()).select_from(Device))).scalar()
            online = (await db.execute(select(func.count()).where(Device.online == True))).scalar()
            low    = (await db.execute(
                select(Device.friendly_name, Device.battery)
                .where(Device.battery <= settings.telegram_battery_threshold)
                .where(Device.battery != None)
                .order_by(Device.battery)
                .limit(5)
            )).all()

        lines = [
            f"📡 Устройств: <b>{online}/{total}</b> онлайн",
            f"🔋 Батарея ≤{settings.telegram_battery_threshold}%: <b>{len(low)}</b> шт.",
        ]
        if low:
            lines.append("")
            for name, pct in low:
                lines.append(f"  • {_html(name)} — {pct}%")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def cmd_pumps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if _get_db is None:
        await update.message.reply_text("⚙️ База данных не подключена.")
        return
    try:
        from sqlalchemy import text

        async with _get_db() as db:
            rows = (await db.execute(text("""
                SELECT p.*
                FROM pump_stats p
                INNER JOIN (
                    SELECT entity_id, MAX(ts) AS max_ts
                    FROM pump_stats GROUP BY entity_id
                ) l ON p.entity_id = l.entity_id AND p.ts = l.max_ts
                ORDER BY p.friendly_name
            """))).mappings().all()

        if not rows:
            await update.message.reply_text("Данных о насосах нет.")
            return

        lines = ["💧 <b>Насосы:</b>"]
        for r in rows:
            icon = "🟢" if r["state"] == "on" else "🔴"
            name = _html(r["friendly_name"] or r["entity_id"])
            lines.append(f"\n{icon} <b>{name}</b>")
            if r["rpm"]:        lines.append(f"   {r['rpm']} об/мин")
            if r["temperature"]:lines.append(f"   {r['temperature']}°C")
            if r["pressure"]:   lines.append(f"   {r['pressure']} bar")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if _get_db is None:
        await update.message.reply_text("⚙️ База данных не подключена.")
        return
    try:
        from sqlalchemy import select
        from .models import Alert

        async with _get_db() as db:
            rows = (await db.execute(
                select(Alert).order_by(Alert.ts.desc()).limit(5)
            )).scalars().all()

        if not rows:
            await update.message.reply_text("Нет уведомлений.")
            return

        icons = {"ok": "✅", "warn": "⚠️", "err": "🔴", "info": "ℹ️"}
        lines = ["📋 <b>Последние уведомления:</b>"]
        for a in rows:
            ts   = a.ts.strftime("%d.%m %H:%M")
            icon = icons.get(a.level, "•")
            lines.append(f"{icon} {ts} — {_html(a.message)}")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _muted_until
    minutes = 60
    if context.args:
        try:
            minutes = max(1, int(context.args[0]))
        except ValueError:
            pass
    _muted_until = datetime.utcnow() + timedelta(minutes=minutes)
    until_str = _muted_until.strftime("%H:%M UTC")
    await update.message.reply_text(
        f"🔕 Уведомления отключены на <b>{minutes} мин</b> (до {until_str}).",
        parse_mode=ParseMode.HTML,
    )


async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _muted_until
    _muted_until = None
    await update.message.reply_text("🔔 Уведомления включены.")
