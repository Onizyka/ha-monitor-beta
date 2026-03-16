"""
MQTT subscriber for Zigbee2MQTT.

Zigbee2MQTT payload field names vary by device. Common mappings:
  Smart plugs / energy meters:
    energy       -> energy, energy_1, energy_2
    voltage      -> voltage, voltage_1
    power        -> power, power_1
    current      -> current, current_1
    power_factor -> power_factor
  Sensors:
    temperature  -> temperature
    humidity     -> humidity
    pressure     -> pressure
"""

import asyncio
import json
import logging
from datetime import datetime

import aiomqtt
from sqlalchemy import select

from .config import settings
from .database import AsyncSessionLocal
from .models import Device, DeviceHistory, Alert
from . import telegram_bot

logger = logging.getLogger(__name__)


def _get_float(payload: dict, *keys) -> float | None:
    """Try multiple key names, return first non-None float found."""
    for k in keys:
        v = payload.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


async def run_mqtt_listener():
    """Run forever, reconnecting on error."""
    while True:
        try:
            await _connect_and_listen()
        except Exception as e:
            logger.error("MQTT error: %s — reconnecting in 10s", e)
            await asyncio.sleep(10)


async def _connect_and_listen():
    kwargs = dict(hostname=settings.mqtt_host, port=settings.mqtt_port)
    if settings.mqtt_user:
        kwargs["username"] = settings.mqtt_user
        kwargs["password"] = settings.mqtt_password

    logger.info("Connecting to MQTT %s:%s", settings.mqtt_host, settings.mqtt_port)

    async with aiomqtt.Client(**kwargs) as client:
        prefix = settings.mqtt_topic_prefix
        await client.subscribe(f"{prefix}/bridge/devices")
        await client.subscribe(f"{prefix}/bridge/logging")
        await client.subscribe(f"{prefix}/+")
        logger.info("MQTT subscribed to %s/#", prefix)

        async for message in client.messages:
            topic = str(message.topic)
            try:
                payload = json.loads(message.payload)
            except (json.JSONDecodeError, ValueError):
                continue

            if topic.endswith("/bridge/devices"):
                await _handle_bridge_devices(payload)
            elif topic.endswith("/bridge/logging"):
                pass  # ignore bridge logs
            else:
                device_name = topic.split("/")[-1]
                if isinstance(payload, dict):
                    await _handle_device_state(device_name, payload)


async def _handle_bridge_devices(devices: list):
    """Sync full device registry from bridge/devices."""
    if not isinstance(devices, list):
        return
    async with AsyncSessionLocal() as db:
        for d in devices:
            ieee = d.get("ieee_address")
            if not ieee:
                continue
            existing = await db.get(Device, ieee)
            obj = existing or Device(ieee=ieee)
            obj.friendly_name = d.get("friendly_name", ieee)
            obj.model  = d.get("definition", {}).get("model")
            obj.vendor = d.get("definition", {}).get("vendor")
            obj.device_type = d.get("type")
            db.add(obj)
        await db.commit()
    logger.debug("Bridge devices synced: %d entries", len(devices))


async def _handle_device_state(device_name: str, payload: dict):
    """Process a per-device state message."""

    if device_name.lower() in ("coordinator", "bridge"):
        return

    # Extract all possible metric fields with fallback key names
    battery     = payload.get("battery")
    linkquality = payload.get("linkquality")

    temperature = _get_float(payload, "temperature")
    humidity    = _get_float(payload, "humidity")

    # Energy meter fields — Zigbee2MQTT uses different names per device type
    voltage = _get_float(payload, "voltage", "voltage_1", "voltage_phase_a")
    power   = _get_float(payload, "power",   "power_1",   "active_power")
    current = _get_float(payload, "current", "current_1", "current_phase_a")
    energy  = _get_float(payload, "energy",  "energy_1",  "sum_delivered",
                          "energy_delivered", "consumed_energy")

    # Log first occurrence of energy device for debugging
    if any(v is not None for v in [voltage, power, current, energy]):
        logger.debug("Energy device %s: V=%.1f W=%.1f A=%.3f kWh=%.3f",
                     device_name,
                     voltage or 0, power or 0, current or 0, energy or 0)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Device).where(Device.friendly_name == device_name)
        )
        device = result.scalar_one_or_none()

        if device is None:
            device = Device(ieee=device_name, friendly_name=device_name)
            db.add(device)

        device.online    = True
        device.last_seen = datetime.utcnow()
        if battery is not None:
            device.battery = int(battery)
        if linkquality is not None:
            device.linkquality = int(linkquality)

        # Write time-series snapshot for every message
        db.add(DeviceHistory(
            ieee        = device.ieee,
            ts          = datetime.utcnow(),
            battery     = device.battery,
            linkquality = device.linkquality,
            temperature = temperature,
            humidity    = humidity,
            voltage     = voltage,
            power       = power,
            current     = current,
            energy      = energy,
        ))

        # ── Battery alert ─────────────────────────────────────────────
        if battery is not None and int(battery) <= settings._battery_threshold:
            from datetime import timedelta
            threshold = datetime.utcnow() - timedelta(hours=24)
            if (device.last_battery_alert is None
                    or device.last_battery_alert < threshold):
                device.last_battery_alert = datetime.utcnow()
                db.add(Alert(
                    level="warn", category="battery",
                    message=f"Батарея {device_name} — {int(battery)}%",
                    entity_id=device.ieee,
                ))
                await db.commit()
                await telegram_bot.send_battery_alert(device_name, int(battery))
                return

        await db.commit()
