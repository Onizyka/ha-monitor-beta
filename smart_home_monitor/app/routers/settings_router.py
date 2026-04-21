"""Settings API — stores preferences in /data/dashboard_settings.json"""
import json
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException

router = APIRouter()
_logger = logging.getLogger(__name__)

# /data is the HA addon persistent storage volume - always available
SFILE = Path("/data/dashboard_settings.json")

DEFAULTS = {
    "offline_check_minutes": 180,
    "daily_status_enabled": False,
    "daily_status_time": "08:00",
    "daily_status_include_availability": True,
    "daily_status_include_battery": True,
    "tg_trigger_offline": True,
    "tg_trigger_battery": True,
    "tg_trigger_online_back": False,
    "thresholds": {},
}


def _load() -> dict:
    if SFILE.exists():
        try:
            return {**DEFAULTS, **json.loads(SFILE.read_text())}
        except Exception as e:
            _logger.error("Failed to read settings: %s", e)
    return dict(DEFAULTS)


def _save(data: dict) -> dict:
    try:
        SFILE.parent.mkdir(parents=True, exist_ok=True)
        merged = {**_load(), **data}
        SFILE.write_text(json.dumps(merged, indent=2, ensure_ascii=False))
        _logger.info("Settings saved to %s", SFILE)
        return merged
    except Exception as e:
        _logger.error("Failed to save settings: %s", e)
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения: {e}")


@router.get("/")
async def get_settings():
    s = _load()
    _logger.debug("Settings loaded: daily_enabled=%s, tg_offline=%s",
                  s.get("daily_status_enabled"), s.get("tg_trigger_offline"))
    return s


@router.post("/")
async def save_settings(body: dict):
    result = _save(body)
    # Reschedule threshold checker if interval changed
    try:
        from .. import jobs
        minutes = int(body.get("threshold_check_minutes") or 5)
        if minutes < 1: minutes = 1
        jobs.scheduler.reschedule_job("threshold_check", trigger="interval", minutes=minutes)
    except Exception:
        pass
    return result


@router.get("/thresholds")
async def get_thresholds():
    return _load().get("thresholds", {})


@router.post("/thresholds")
async def save_thresholds(body: dict):
    """body = {"ieee::metric": {"min": float|null, "max": float|null, "tg": bool}}"""
    s = _load()
    s["thresholds"] = {**s.get("thresholds", {}), **body}
    _logger.info("Saving thresholds: %s", list(s["thresholds"].keys()))
    SFILE.parent.mkdir(parents=True, exist_ok=True)
    SFILE.write_text(json.dumps(s, indent=2, ensure_ascii=False))
    return s["thresholds"]


@router.post("/daily-report-now")
async def trigger_daily_report_now():
    """Send daily report immediately regardless of schedule."""
    from ..jobs import send_daily_report
    from ..config import settings
    _logger.info("Manual daily report triggered. TG enabled: %s", settings.telegram_enabled)
    if not settings.telegram_enabled:
        raise HTTPException(status_code=400,
                            detail="Telegram не включён — проверь config аддона (telegram_enabled: true)")
    await send_daily_report()
    return {"ok": True, "message": "Отчёт отправлен"}


@router.post("/check-thresholds-now")
async def check_thresholds_now():
    """Trigger threshold check immediately."""
    from ..jobs import check_metric_thresholds
    from ..config import settings
    s = _load()
    thr = s.get("thresholds", {})
    _logger.info("Manual threshold check. TG enabled: %s, thresholds: %d", 
                 settings.telegram_enabled, len(thr))
    if not thr:
        raise HTTPException(status_code=400,
                            detail="Пороги не настроены — открой устройство и задай Мин/Макс")
    await check_metric_thresholds(force=True)
    return {"ok": True, "thresholds_checked": len(thr)}


@router.get("/debug")
async def debug_settings():
    """Debug endpoint — show file path and contents."""
    import os
    data_exists = Path("/data").exists()
    data_writable = os.access("/data", os.W_OK) if data_exists else False
    file_exists = SFILE.exists()
    contents = None
    if file_exists:
        try:
            contents = json.loads(SFILE.read_text())
        except Exception as e:
            contents = {"error": str(e)}
    from ..config import settings as cfg
    return {
        "sfile_path": str(SFILE),
        "data_dir_exists": data_exists,
        "data_dir_writable": data_writable,
        "file_exists": file_exists,
        "telegram_enabled": cfg.telegram_enabled,
        "telegram_token_set": bool(cfg.telegram_token),
        "telegram_chat_id_set": bool(cfg.telegram_chat_id),
        "contents": contents,
    }
