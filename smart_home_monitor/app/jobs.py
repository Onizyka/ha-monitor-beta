"""
Background periodic jobs.
  check_offline_devices   — every 5 min
  check_metric_thresholds — every 5 min
  poll_pump_states        — every 1 min
  _schedule_daily_report  — every 1 min
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, func, text

from .config import settings
from .database import AsyncSessionLocal
from .models import Device, DeviceHistory, PumpStat, Alert
from . import telegram_bot
from .telegram_bot import MSK, now_msk, _html

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()
SFILE = Path("/data/dashboard_settings.json")

METRIC_LABELS = {
    "battery": ("Батарея", "%"),
    "linkquality": ("Связь", "LQI"),
    "temperature": ("Температура", "°C"),
    "humidity": ("Влажность", "%"),
    "voltage": ("Напряжение", "В"),
    "power": ("Мощность", "Вт"),
    "current": ("Ток", "А"),
    "energy": ("Энергия", "кВт·ч"),
}

EXCLUDE_NAMES = {"Coordinator"}


def _load_sett() -> dict:
    if SFILE.exists():
        try:
            return json.loads(SFILE.read_text())
        except Exception as e:
            logger.error("Failed to load settings: %s", e)
    return {}


# ── Offline checker ───────────────────────────────────────────────────────

async def check_offline_devices():
    s = _load_sett()
    default_minutes = s.get("offline_check_minutes", settings._offline_minutes)
    alert_cutoff = datetime.utcnow() - timedelta(hours=4)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Device))
        devices = result.scalars().all()

        for device in devices:
            if device.friendly_name in EXCLUDE_NAMES:
                continue
            if not device.last_seen:
                continue

            cutoff = datetime.utcnow() - timedelta(minutes=default_minutes)

            if device.last_seen < cutoff and device.online:
                device.online = False
                if (device.last_offline_alert is None
                        or device.last_offline_alert < alert_cutoff):
                    device.last_offline_alert = datetime.utcnow()
                    minutes = int((datetime.utcnow() - device.last_seen).total_seconds() / 60)
                    db.add(Alert(level="err", category="offline",
                                 message=f"Устройство {device.friendly_name} офлайн {minutes} мин",
                                 entity_id=device.ieee))
                    await db.flush()
                    if s.get("tg_trigger_offline", True):
                        await telegram_bot.send_offline_alert(device.friendly_name, minutes)

            elif (device.last_seen >= datetime.utcnow() - timedelta(minutes=6)
                  and not device.online):
                device.online = True
                if s.get("tg_trigger_online_back", False):
                    await telegram_bot.send_alert(
                        f"✅ Устройство <b>{_html(device.friendly_name)}</b> снова онлайн.",
                        level="ok", html=True)

        await db.commit()


# ── Metric threshold checker ──────────────────────────────────────────────

async def check_metric_thresholds():
    s = _load_sett()
    thresholds = s.get("thresholds", {})
    if not thresholds:
        logger.debug("No thresholds configured, skipping.")
        return

    logger.info("Checking %d metric thresholds...", len(thresholds))
    alert_gap = timedelta(minutes=30)
    updated = False

    async with AsyncSessionLocal() as db:
        for key, cfg in list(thresholds.items()):
            if "::" not in key:
                logger.warning("Skipping malformed threshold key (no '::'): %s", key)
                continue
            # Detect reversed format metric::ieee and auto-correct
            parts = key.split("::", 1)
            if parts[0] in ("battery","linkquality","temperature","humidity",
                            "voltage","power","current","energy"):
                # Key is metric::ieee — swap to ieee::metric
                correct_key = f"{parts[1]}::{parts[0]}"
                logger.warning("Auto-correcting threshold key %s -> %s", key, correct_key)
                thresholds[correct_key] = thresholds.pop(key)
                s["thresholds"] = thresholds
                SFILE.write_text(json.dumps(s, indent=2, ensure_ascii=False))
                key = correct_key

            ieee, metric = key.split("::", 1)
            mn = cfg.get("min")
            mx = cfg.get("max")
            raw_tg = cfg.get("tg", True)
            tg_enabled = raw_tg if isinstance(raw_tg, bool) else str(raw_tg).lower() != "false"
            can_send_tg = tg_enabled and settings.telegram_enabled and bool(settings.telegram_token)

            # Skip if no thresholds set
            if mn is None and mx is None:
                continue

            col = metric if metric in ("battery","linkquality","temperature",
                                       "humidity","voltage","power","current","energy") else None
            if not col:
                logger.warning("Unknown metric in threshold: %s", metric)
                continue

            # Get latest value — no time filter to ensure we always get something
            row = (await db.execute(text(f"""
                SELECT dh.{col} AS val, d.friendly_name
                FROM device_history dh
                JOIN devices d ON d.ieee = dh.ieee
                WHERE dh.ieee = :ieee
                  AND dh.{col} IS NOT NULL
                ORDER BY dh.ts DESC LIMIT 1
            """), {"ieee": ieee})).mappings().first()

            if not row or row["val"] is None:
                logger.info("Threshold %s: no recent data in DB", key)
                continue

            val = float(row["val"])
            name = row["friendly_name"]
            logger.info("Threshold check %s %s: val=%.2f min=%s max=%s", 
                       name, metric, val, mn, mx)
            label, unit = METRIC_LABELS.get(metric, (metric, ""))

            logger.info("Threshold check %s (%s): val=%.3f  min=%s  max=%s  tg=%s",
                        name, metric, val, mn, mx, tg_enabled)

            # Check last alert throttle
            last_alert_str = cfg.get("last_alert")
            if last_alert_str:
                try:
                    last_alert = datetime.fromisoformat(last_alert_str)
                    elapsed = datetime.utcnow() - last_alert
                    if elapsed < alert_gap:
                        logger.info("  → throttled (last alert %s ago)", elapsed)
                        continue
                except Exception:
                    pass

            triggered = False

            if mn is not None and val <= float(mn):
                tpl = cfg.get("msg_min") or "⬇️ <b>{name}</b> — {label} ниже минимума!\nТекущее: <b>{value} {unit}</b>  (порог мин: {min} {unit})"
                msg = tpl.format(name=_html(name), label=label, value=val, unit=unit,
                                 min=mn, max=mx if mx is not None else "—",
                                 direction="ниже", ieee=ieee)
                logger.info("  → BELOW MIN: %.3f <= %.3f", val, float(mn))
                db.add(Alert(level="warn", category="threshold",
                             message=f"{name}: {label} {val}{unit} < мин {mn}{unit}",
                             entity_id=ieee))
                await db.flush()
                if can_send_tg:
                    await telegram_bot.send_alert(msg, level="warn", html=True)
                triggered = True

            elif mx is not None and val >= float(mx):
                tpl = cfg.get("msg_max") or "⬆️ <b>{name}</b> — {label} выше максимума!\nТекущее: <b>{value} {unit}</b>  (порог макс: {max} {unit})"
                msg = tpl.format(name=_html(name), label=label, value=val, unit=unit,
                                 min=mn if mn is not None else "—", max=mx,
                                 direction="выше", ieee=ieee)
                logger.info("  → ABOVE MAX: %.3f >= %.3f", val, float(mx))
                db.add(Alert(level="err", category="threshold",
                             message=f"{name}: {label} {val}{unit} > макс {mx}{unit}",
                             entity_id=ieee))
                await db.flush()
                if can_send_tg:
                    await telegram_bot.send_alert(msg, level="err", html=True)
                triggered = True

            else:
                logger.info("  → OK (val=%.3f in range [%s, %s])", val, mn, mx)

            if triggered:
                thresholds[key]["last_alert"] = datetime.utcnow().isoformat()
                updated = True

        await db.commit()

    if updated:
        s["thresholds"] = thresholds
        SFILE.write_text(json.dumps(s, indent=2))
        logger.info("Thresholds updated in settings file.")


# ── Pump poller ───────────────────────────────────────────────────────────

async def poll_pump_states():
    if not settings.pump_entity_ids_list:
        return
    headers = {}
    if settings.ha_token:
        headers["Authorization"] = f"Bearer {settings.ha_token}"
    async with httpx.AsyncClient(base_url=settings.ha_url, headers=headers, timeout=10) as client:
        for entity_id in settings.pump_entity_ids_list:
            try:
                resp = await client.get(f"/api/states/{entity_id}")
                resp.raise_for_status()
                await _store_pump_stat(entity_id, resp.json())
            except Exception as e:
                logger.warning("Failed to poll pump %s: %s", entity_id, e)


async def _store_pump_stat(entity_id: str, state_data: dict):
    attrs = state_data.get("attributes", {})
    state = state_data.get("state", "unknown")
    stat = PumpStat(
        entity_id=entity_id, friendly_name=attrs.get("friendly_name"),
        ts=datetime.utcnow(), state=state,
        rpm=attrs.get("rpm") or attrs.get("current_rpm"),
        temperature=attrs.get("temperature") or attrs.get("current_temperature"),
        pressure=attrs.get("pressure"),
        power_w=attrs.get("current_power_w") or attrs.get("power"),
        total_hours=attrs.get("total_operation_hours"),
    )
    async with AsyncSessionLocal() as db:
        db.add(stat)
        if state == "unavailable":
            db.add(Alert(level="err", category="pump",
                         message=f"Насос {attrs.get('friendly_name', entity_id)} недоступен",
                         entity_id=entity_id))
            await db.flush()
            await telegram_bot.send_pump_alert(attrs.get("friendly_name", entity_id), "недоступен")
        await db.commit()


# ── Daily report ──────────────────────────────────────────────────────────

async def send_daily_report():
    if not settings.telegram_enabled:
        return
    s = _load_sett()
    # Note: when called manually from endpoint, always send regardless of enabled flag
    # The daily scheduler checks enabled flag before calling us

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Device).order_by(Device.friendly_name))
        all_devs = result.scalars().all()
        devices = [d for d in all_devs
                   if d.friendly_name not in EXCLUDE_NAMES
                   and (d.device_type or '').lower() != 'coordinator']
        since = datetime.utcnow() - timedelta(hours=24)
        alerts_today = (await db.execute(
            select(func.count()).where(Alert.ts >= since)
        )).scalar_one()

    now_str = now_msk().strftime("%d.%m.%Y %H:%M MSK")
    total  = len(devices)
    online = sum(1 for d in devices if d.online)
    low_bat = [d for d in devices
               if d.battery is not None and d.battery <= settings._battery_threshold]

    lines = [f"📊 <b>Ежедневный отчёт</b> {now_str}", "",
             f"📡 Сеть: <b>{online}/{total}</b> онлайн", ""]

    if s.get("daily_status_include_availability", True):
        lines.append("<b>Статус устройств:</b>")
        for d in devices:
            status = "✅ OK" if d.online else "🔴 Офлайн"
            bat = f" 🔋{d.battery}%" if d.battery is not None else ""
            lqi = f" 📶{d.linkquality}" if d.linkquality is not None else ""
            lines.append(f"  {status} {_html(d.friendly_name)}{bat}{lqi}")
        lines.append("")

    if s.get("daily_status_include_battery", True) and low_bat:
        lines.append(f"⚠️ Низкий заряд ({len(low_bat)} шт.):")
        for d in low_bat:
            lines.append(f"  🔴 {_html(d.friendly_name)} — {d.battery}%")
        lines.append("")

    lines.append(f"🔔 Тревог за 24ч: <b>{alerts_today}</b>")

    await telegram_bot.send_alert("\n".join(lines), level="info", html=True)
    logger.info("Daily report sent.")


async def _schedule_daily_report_check():
    s = _load_sett()
    if not s.get("daily_status_enabled"):
        return
    target = s.get("daily_status_time", "08:00")
    if now_msk().strftime("%H:%M") == target:
        await send_daily_report()


# ── Scheduler start ───────────────────────────────────────────────────────

async def cleanup_old_alerts():
    """Delete alerts older than 24 hours automatically."""
    from .models import Alert
    from sqlalchemy import delete as sql_delete
    cutoff = datetime.utcnow() - timedelta(hours=24)
    async with AsyncSessionLocal() as db:
        result = await db.execute(sql_delete(Alert).where(Alert.ts < cutoff))
        deleted = result.rowcount
        await db.commit()
    if deleted:
        logger.info("Auto-cleaned %d old alerts", deleted)


def start_scheduler():
    scheduler.add_job(check_offline_devices,        "interval", minutes=5,  id="offline_check",   replace_existing=True)
    scheduler.add_job(check_metric_thresholds,      "interval", minutes=5,  id="threshold_check", replace_existing=True)
    scheduler.add_job(poll_pump_states,             "interval", minutes=1,  id="pump_poll",       replace_existing=True)
    scheduler.add_job(_schedule_daily_report_check, "interval", minutes=1,  id="daily_check",     replace_existing=True)
    scheduler.add_job(cleanup_old_alerts,           "interval", hours=1,    id="alert_cleanup",   replace_existing=True)
    scheduler.start()
    logger.info("Scheduler started.")
