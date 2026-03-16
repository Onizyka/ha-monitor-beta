import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse

from .config import settings
from .database import engine, Base, AsyncSessionLocal
from .mqtt import run_mqtt_listener
from .jobs import start_scheduler
from . import telegram_bot
from .routers import devices, batteries, pumps, alerts, settings_router

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

STATIC_DIR = Path("/app/app/static")

def _read_addon_version() -> str:
    """Read version from config.json at runtime — single source of truth."""
    try:
        cfg_path = Path("/app/config.json")
        if cfg_path.exists():
            return json.loads(cfg_path.read_text()).get("version", "unknown")
    except Exception:
        pass
    return "unknown"

ADDON_VERSION = _read_addon_version()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("DB init…")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        logger.error("DB init error: %s", e)

    mqtt_task = asyncio.create_task(run_mqtt_listener())
    start_scheduler()
    # Run offline check immediately on startup
    from .jobs import check_offline_devices
    asyncio.create_task(check_offline_devices())
    await telegram_bot.start_bot(AsyncSessionLocal)
    logger.info("Startup complete — :8080, ingress_path=%s", settings.ingress_path)
    yield
    mqtt_task.cancel()
    await telegram_bot.stop_bot()
    await engine.dispose()


app = FastAPI(
    title="Home Assistant Monitor",
    version=ADDON_VERSION,
    # Do NOT set root_path here — it breaks static file URL generation
    # HA ingress proxy handles path rewriting
    lifespan=lifespan,
)

app.include_router(devices.router,         prefix="/api/devices",   tags=["devices"])
app.include_router(batteries.router,       prefix="/api/batteries", tags=["batteries"])
app.include_router(pumps.router,           prefix="/api/pumps",     tags=["pumps"])
app.include_router(alerts.router,          prefix="/api/alerts",    tags=["alerts"])
app.include_router(settings_router.router, prefix="/api/settings",  tags=["settings"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": ADDON_VERSION,
            "ingress_path": settings.ingress_path}


@app.get("/api/summary")
async def summary():
    from sqlalchemy import select, func
    from .models import Device, Alert
    from datetime import datetime, timedelta
    try:
        async with AsyncSessionLocal() as db:
            total    = (await db.execute(select(func.count()).select_from(Device))).scalar_one()
            online   = (await db.execute(select(func.count()).where(Device.online == True))).scalar_one()
            low_bat  = (await db.execute(
                select(func.count())
                .where(Device.battery <= settings._battery_threshold)
                .where(Device.battery.is_not(None))
            )).scalar_one()
            since = datetime.utcnow() - timedelta(hours=24)
            alerts_t = (await db.execute(select(func.count()).where(Alert.ts >= since))).scalar_one()
    except Exception as e:
        logger.error("Summary error: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})
    return {"total_devices": total, "online_devices": online,
            "low_battery_count": low_bat, "alerts_today": alerts_t,
            "battery_threshold": settings._battery_threshold}


# ── Serve index.html for all non-API routes ──────────────────────────────

INDEX = STATIC_DIR / "index.html"

@app.get("/")
async def root():
    return FileResponse(INDEX)

@app.get("/index.html")
async def index_html():
    return FileResponse(INDEX)

@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api"):
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return FileResponse(INDEX)
