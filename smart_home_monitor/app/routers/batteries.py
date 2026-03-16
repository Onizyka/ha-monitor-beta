from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Device, PumpStat, Alert

# ─── Batteries ───────────────────────────────────────────────
router = APIRouter()


@router.get("/")
async def list_batteries(
    low_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    from ..config import settings
    q = (
        select(Device)
        .where(Device.battery != None)
        .order_by(Device.battery)
    )
    if low_only:
        q = q.where(Device.battery <= settings._battery_threshold)

    result = await db.execute(q)
    devices = result.scalars().all()
    return [
        {
            "ieee": d.ieee,
            "friendly_name": d.friendly_name,
            "model": d.model,
            "vendor": d.vendor,
            "battery": d.battery,
            "online": d.online,
            "last_seen": d.last_seen.isoformat() if d.last_seen else None,
        }
        for d in devices
    ]
