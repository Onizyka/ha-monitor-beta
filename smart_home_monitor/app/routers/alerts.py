from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Alert

router = APIRouter()


@router.get("/")
async def list_alerts(
    limit: int = Query(50, ge=1, le=500),
    level: str | None = Query(None, regex="^(ok|warn|err|info)$"),
    category: str | None = Query(None),
    unacked: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    q = select(Alert).order_by(Alert.ts.desc()).limit(limit)
    if level:
        q = q.where(Alert.level == level)
    if category:
        q = q.where(Alert.category == category)
    if unacked:
        q = q.where(Alert.acknowledged == False)
    result = await db.execute(q)
    alerts = result.scalars().all()
    return [_ser(a) for a in alerts]


@router.post("/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int, db: AsyncSession = Depends(get_db)):
    alert = await db.get(Alert, alert_id)
    if not alert:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.acknowledged = True
    await db.commit()
    return {"ok": True}


@router.delete("/{alert_id}")
async def delete_alert(alert_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a single alert from history."""
    alert = await db.get(Alert, alert_id)
    if not alert:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Alert not found")
    await db.delete(alert)
    await db.commit()
    return {"ok": True}


@router.delete("/")
async def delete_all_alerts(
    acknowledged_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """Delete all (or only acknowledged) alerts from history."""
    q = delete(Alert)
    if acknowledged_only:
        q = q.where(Alert.acknowledged == True)
    await db.execute(q)
    await db.commit()
    return {"ok": True}


@router.post("/telegram/test")
async def telegram_test():
    from ..telegram_bot import send_alert
    from ..config import settings
    if not settings.telegram_enabled:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Telegram не включён в настройках")
    ok = await send_alert("🧪 Тестовое сообщение от Home Assistant Monitor. Всё работает!", level="info")
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Не удалось отправить — проверь токен и chat_id")
    return {"ok": True}


@router.post("/telegram/device-test")
async def telegram_device_test(body: dict):
    from ..telegram_bot import send_alert
    from ..config import settings
    if not settings.telegram_enabled:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Telegram не включён в настройках")

    name        = body.get("friendly_name", "Устройство")
    battery     = body.get("battery")
    online      = body.get("online", True)
    offline_min = body.get("offline_minutes")
    lqi         = body.get("linkquality")
    notify      = body.get("notify", {})

    from ..telegram_bot import _html
    model   = body.get("model") or body.get("vendor") or ""
    metrics = body.get("metrics") or {}  # {"voltage": 242.3, "power": 512.7, ...}

    METRIC_ICONS = {
        "battery": "🔋", "linkquality": "📶", "temperature": "🌡️",
        "humidity": "💧", "voltage": "⚡", "power": "💡",
        "current": "🔌", "energy": "📊",
    }
    METRIC_LABELS = {
        "battery": ("Батарея", "%"), "linkquality": ("Связь", "LQI"),
        "temperature": ("Температура", "°C"), "humidity": ("Влажность", "%"),
        "voltage": ("Напряжение", "В"), "power": ("Мощность", "Вт"),
        "current": ("Ток", "А"), "energy": ("Энергия", "кВт·ч"),
    }

    lines = [f"🧪 <b>Тест: {_html(name)}</b>"]
    if model:
        lines.append(f"<i>{_html(model)}</i>")
    lines.append("")

    # Status
    if online:
        lines.append("📡 Статус: <b>Онлайн ✅</b>")
    else:
        lines.append(f"📵 Статус: <b>Офлайн 🔴</b>{f' ({offline_min} мин)' if offline_min else ''}")

    # All metric values
    if metrics:
        lines.append("")
        lines.append("<b>Текущие значения:</b>")
        for mkey, val in metrics.items():
            icon = METRIC_ICONS.get(mkey, "•")
            label, unit = METRIC_LABELS.get(mkey, (mkey, ""))
            # Format number nicely
            if isinstance(val, float):
                fmt = f"{val:.1f}" if val < 100 else f"{val:.0f}"
            else:
                fmt = str(val)
            lines.append(f"  {icon} {label}: <b>{fmt} {unit}</b>")

    # Active notifications
    active = []
    if notify.get("telegram"): active.append("Telegram")
    if notify.get("battery") and battery is not None: active.append("Батарея")
    if notify.get("offline"):  active.append("Офлайн")
    lines.append("")
    if active:
        lines.append("🔔 Уведомления: " + ", ".join(active))
    else:
        lines.append("🔕 Уведомления не настроены")

    ok = await send_alert("\n".join(lines), level="info", html=True)
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Не удалось отправить — проверь токен и chat_id")
    return {"ok": True}


def _ser(a: Alert) -> dict:
    return {
        "id": a.id,
        "ts": a.ts.isoformat(),
        "level": a.level,
        "category": a.category,
        "message": a.message,
        "entity_id": a.entity_id,
        "sent_telegram": a.sent_telegram,
        "acknowledged": a.acknowledged,
    }
