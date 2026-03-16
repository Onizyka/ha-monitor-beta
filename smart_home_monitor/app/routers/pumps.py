from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import PumpStat, Alert

# ─── Pumps ────────────────────────────────────────────────────
router = APIRouter()


@router.get("/")
async def list_pumps(db: AsyncSession = Depends(get_db)):
    """Latest stat row per pump entity."""
    rows = (await db.execute(text("""
        SELECT p.*
        FROM pump_stats p
        INNER JOIN (
            SELECT entity_id, MAX(ts) AS max_ts
            FROM pump_stats
            GROUP BY entity_id
        ) latest
        ON p.entity_id = latest.entity_id AND p.ts = latest.max_ts
        ORDER BY p.friendly_name
    """))).mappings().all()

    return [dict(r) for r in rows]


@router.get("/{entity_id}/history")
async def pump_history(
    entity_id: str,
    hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(text("""
        SELECT ts, state, rpm, temperature, pressure, power_w
        FROM pump_stats
        WHERE entity_id = :eid
          AND ts >= UTC_TIMESTAMP() - INTERVAL :h HOUR
        ORDER BY ts DESC
        LIMIT 500
    """), {"eid": entity_id, "h": hours})).mappings().all()
    return [dict(r) for r in rows]
