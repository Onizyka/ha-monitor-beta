from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
import logging

from ..database import get_db
from ..models import Device, DeviceHistory

router = APIRouter()
logger = logging.getLogger(__name__)

EXCLUDE_NAMES = {"Coordinator"}


# ══ ALL static/prefixed routes BEFORE /{ieee} ══════════════════════════════

@router.get("/history/{ieee}")
async def device_history(
    ieee: str,
    hours: int = Query(24, ge=1, le=8760),
    metric: str = Query("battery"),
    from_: str | None = Query(None, alias="from"),
    to_: str | None = Query(None, alias="to"),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import text
    from datetime import timedelta

    field_map = {
        "battery": "battery", "linkquality": "linkquality",
        "temperature": "temperature", "humidity": "humidity",
        "voltage": "voltage", "power": "power",
        "current": "current", "energy": "energy",
    }
    col = field_map.get(metric)
    if not col:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Unknown metric: {metric}")

    # Adaptive decimation: ~1500 points regardless of period
    bk = max(8, int(hours * 3600 / 1500))

    # Build SQL as plain string (no f-string for params to avoid escaping issues)
    if from_ and to_:
        sql = (
            f"SELECT FROM_UNIXTIME(FLOOR(UNIX_TIMESTAMP(ts)/{bk})*{bk}) AS ts,"
            f" CAST(AVG({col}) AS DECIMAL(12,4)) AS value"
            f" FROM device_history"
            f" WHERE ieee = :ieee AND ts >= :t1 AND ts <= :t2 AND {col} IS NOT NULL"
            f" GROUP BY FLOOR(UNIX_TIMESTAMP(ts)/{bk}) ORDER BY ts ASC"
        )
        params = {"ieee": ieee, "t1": from_, "t2": to_}
    else:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        sql = (
            f"SELECT FROM_UNIXTIME(FLOOR(UNIX_TIMESTAMP(ts)/{bk})*{bk}) AS ts,"
            f" CAST(AVG({col}) AS DECIMAL(12,4)) AS value"
            f" FROM device_history"
            f" WHERE ieee = :ieee AND ts >= :cutoff AND {col} IS NOT NULL"
            f" GROUP BY FLOOR(UNIX_TIMESTAMP(ts)/{bk}) ORDER BY ts ASC"
        )
        params = {"ieee": ieee, "cutoff": cutoff}

    try:
        rows = (await db.execute(text(sql), params)).mappings().all()
    except Exception as e:
        logger.error("History query failed (bk=%s): %s", bk, e)
        # Fallback: simple raw query with LIMIT
        if from_ and to_:
            sql2 = f"SELECT ts, CAST({col} AS DECIMAL(12,4)) AS value FROM device_history WHERE ieee = :ieee AND ts >= :t1 AND ts <= :t2 AND {col} IS NOT NULL ORDER BY ts ASC LIMIT 2000"
            params2 = {"ieee": ieee, "t1": from_, "t2": to_}
        else:
            sql2 = f"SELECT ts, CAST({col} AS DECIMAL(12,4)) AS value FROM device_history WHERE ieee = :ieee AND ts >= :cutoff AND {col} IS NOT NULL ORDER BY ts ASC LIMIT 2000"
            params2 = {"ieee": ieee, "cutoff": cutoff}
        try:
            rows = (await db.execute(text(sql2), params2)).mappings().all()
        except Exception as e2:
            logger.error("Fallback query also failed: %s", e2)
            return []

    result = []
    for r in rows:
        try:
            ts_val = r["ts"]
            ts_str = ts_val.isoformat() if hasattr(ts_val, "isoformat") else str(ts_val)
            result.append({"ts": ts_str, "value": float(r["value"])})
        except Exception as e:
            logger.warning("Row parse error: %s", e)
    logger.info("history %s %s h=%s bk=%s -> %d rows", ieee[:8], col, hours, bk, len(result))
    return result

@router.get("/last-values/{ieee}")
async def last_values(ieee: str, db: AsyncSession = Depends(get_db)):
    """Most recent value for every metric — no time filter, just latest row."""
    from sqlalchemy import text
    row = (await db.execute(text("""
        SELECT battery, linkquality, temperature, humidity,
               voltage, power, current, energy, ts
        FROM device_history
        WHERE ieee = :ieee
        ORDER BY ts DESC LIMIT 1
    """), {"ieee": ieee})).mappings().first()

    if not row:
        logger.warning("last-values: no rows for ieee=%s", ieee)
        return {}

    result = {}
    for k in ("battery","linkquality","temperature","humidity",
              "voltage","power","current","energy"):
        if row[k] is not None:
            result[k] = float(row[k])

    logger.debug("last-values %s: ts=%s -> %s", ieee, row.get("ts"), result)
    return result


@router.get("/metrics-available")
async def metrics_available(db: AsyncSession = Depends(get_db)):
    """Devices with the metrics they have data for.
    Uses last 1000 rows per device to avoid full table scan on large histories.
    """
    from sqlalchemy import text
    rows = (await db.execute(text("""
        SELECT
            d.ieee, d.friendly_name, d.device_type, d.battery,
            MAX(CASE WHEN dh.battery     IS NOT NULL THEN 1 ELSE 0 END) AS has_battery,
            MAX(CASE WHEN dh.linkquality IS NOT NULL THEN 1 ELSE 0 END) AS has_linkquality,
            MAX(CASE WHEN dh.temperature IS NOT NULL THEN 1 ELSE 0 END) AS has_temperature,
            MAX(CASE WHEN dh.humidity    IS NOT NULL THEN 1 ELSE 0 END) AS has_humidity,
            MAX(CASE WHEN dh.voltage     IS NOT NULL THEN 1 ELSE 0 END) AS has_voltage,
            MAX(CASE WHEN dh.power       IS NOT NULL THEN 1 ELSE 0 END) AS has_power,
            MAX(CASE WHEN dh.current     IS NOT NULL THEN 1 ELSE 0 END) AS has_current,
            MAX(CASE WHEN dh.energy      IS NOT NULL THEN 1 ELSE 0 END) AS has_energy
        FROM devices d
        LEFT JOIN (
            SELECT ieee, battery, linkquality, temperature, humidity,
                   voltage, power, current, energy
            FROM device_history
            WHERE ts >= UTC_TIMESTAMP() - INTERVAL 7 DAY
        ) dh ON d.ieee = dh.ieee
        WHERE d.friendly_name NOT IN ('Coordinator')
          AND (d.device_type IS NULL OR LOWER(d.device_type) != 'coordinator')
        GROUP BY d.ieee, d.friendly_name, d.device_type, d.battery
        ORDER BY d.friendly_name
    """))).mappings().all()

    result = []
    for r in rows:
        metrics = []
        if r["has_battery"]:     metrics.append("battery")
        if r["has_linkquality"]: metrics.append("linkquality")
        if r["has_temperature"]: metrics.append("temperature")
        if r["has_humidity"]:    metrics.append("humidity")
        if r["has_voltage"]:     metrics.append("voltage")
        if r["has_power"]:       metrics.append("power")
        if r["has_current"]:     metrics.append("current")
        if r["has_energy"]:      metrics.append("energy")
        result.append({
            "ieee": r["ieee"],
            "friendly_name": r["friendly_name"],
            "device_type": r["device_type"],
            "has_battery": bool(r["battery"] is not None or r["has_battery"]),
            "available_metrics": metrics,
        })
    return result


@router.get("/debug/db-stats")
async def db_stats(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import text
    total = (await db.execute(text("SELECT COUNT(*) as c FROM device_history"))).scalar()
    per_device = (await db.execute(text("""
        SELECT d.friendly_name, COUNT(dh.id) as rows,
               SUM(CASE WHEN dh.voltage  IS NOT NULL THEN 1 ELSE 0 END) as has_voltage,
               SUM(CASE WHEN dh.power    IS NOT NULL THEN 1 ELSE 0 END) as has_power,
               SUM(CASE WHEN dh.battery  IS NOT NULL THEN 1 ELSE 0 END) as has_battery,
               MAX(dh.ts) as last_ts
        FROM devices d
        LEFT JOIN device_history dh ON d.ieee = dh.ieee
        GROUP BY d.ieee, d.friendly_name ORDER BY rows DESC
    """))).mappings().all()
    return {"total_history_rows": total,
            "per_device": [dict(r) for r in per_device]}


@router.get("/debug/last-payload/{friendly_name}")
async def last_payload(friendly_name: str, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import text
    row = (await db.execute(text("""
        SELECT dh.*, d.friendly_name
        FROM device_history dh
        JOIN devices d ON d.ieee = dh.ieee
        WHERE d.friendly_name = :name
        ORDER BY dh.ts DESC LIMIT 1
    """), {"name": friendly_name})).mappings().first()
    if not row:
        return {"error": "no data", "friendly_name": friendly_name}
    return dict(row)


@router.get("/")
async def list_devices(
    online: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Device).order_by(Device.friendly_name)
    if online is not None:
        q = q.where(Device.online == online)
    result = await db.execute(q)
    devices = result.scalars().all()
    devices = [d for d in devices
               if d.friendly_name not in EXCLUDE_NAMES
               and (d.device_type or "").lower() != "coordinator"]
    return [_serialize(d) for d in devices]


# ══ /{ieee} LAST — catches everything not matched above ════════════════════

@router.get("/all-including-offline")
async def all_devices_including_offline(db: AsyncSession = Depends(get_db)):
    """Return ALL devices from DB including long-offline ones (for device manager)."""
    result = await db.execute(select(Device).order_by(Device.online.desc(), Device.friendly_name))
    devices = result.scalars().all()
    return [_serialize(d) for d in devices]


@router.post("/delete-batch")
async def delete_batch(body: dict, db: AsyncSession = Depends(get_db)):
    """Delete multiple devices and their history by IEEE list."""
    from sqlalchemy import text, delete as sql_delete
    ieee_list = body.get("ieee_list", [])
    if not ieee_list:
        return {"deleted": 0}
    deleted = 0
    for ieee in ieee_list:
        # Delete history first
        await db.execute(text("DELETE FROM device_history WHERE ieee = :ieee"), {"ieee": ieee})
        # Delete device
        dev = await db.get(Device, ieee)
        if dev:
            await db.delete(dev)
            deleted += 1
    await db.commit()
    logger.info("Deleted %d devices: %s", deleted, ieee_list)
    return {"deleted": deleted, "ieee_list": ieee_list}


@router.delete("/duplicates")
async def remove_duplicates(db: AsyncSession = Depends(get_db)):
    """Remove devices with _1, _2 suffix that are duplicates of existing devices."""
    from sqlalchemy import text, delete
    import re

    # Find devices with numeric suffix like _1, _2
    result = await db.execute(select(Device).order_by(Device.friendly_name))
    all_devs = result.scalars().all()

    names = {d.friendly_name for d in all_devs}
    to_delete = []
    for d in all_devs:
        # Check if name matches pattern name_N where name exists without suffix
        m = re.match(r'^(.+)_(\d+)$', d.friendly_name)
        if m and m.group(1) in names:
            to_delete.append(d)

    deleted = []
    for d in to_delete:
        await db.delete(d)
        deleted.append(d.friendly_name)

    await db.commit()
    return {"deleted": deleted, "count": len(deleted)}


@router.get("/{ieee}")
async def get_device(ieee: str, db: AsyncSession = Depends(get_db)):
    device = await db.get(Device, ieee)
    if not device:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Device not found")
    return _serialize(device)


@router.post("/{ieee}/notifications")
async def set_device_notifications(
    ieee: str, body: dict, db: AsyncSession = Depends(get_db),
):
    device = await db.get(Device, ieee)
    if not device:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Device not found")
    return {"ok": True, "ieee": ieee, "telegram_notify": body.get("telegram_notify", False)}


def _serialize(d: Device) -> dict:
    offline_minutes = None
    if d.last_seen and not d.online:
        offline_minutes = int((datetime.utcnow() - d.last_seen).total_seconds() / 60)
    return {
        "ieee": d.ieee,
        "friendly_name": d.friendly_name,
        "model": d.model,
        "vendor": d.vendor,
        "device_type": d.device_type,
        "online": d.online,
        "battery": d.battery,
        "has_battery": d.battery is not None,
        "linkquality": d.linkquality,
        "last_seen": d.last_seen.isoformat() if d.last_seen else None,
        "offline_minutes": offline_minutes,
    }
