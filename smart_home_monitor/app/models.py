from datetime import datetime
from sqlalchemy import String, Integer, Float, DateTime, Boolean, Text, Index
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class Device(Base):
    """Zigbee device registry — updated on every MQTT message."""
    __tablename__ = "devices"

    ieee: Mapped[str] = mapped_column(String(64), primary_key=True)
    friendly_name: Mapped[str] = mapped_column(String(128), index=True)
    model: Mapped[str | None] = mapped_column(String(128))
    vendor: Mapped[str | None] = mapped_column(String(128))
    device_type: Mapped[str | None] = mapped_column(String(64))   # sensor/switch/router/…
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    battery: Mapped[int | None] = mapped_column(Integer)           # %
    linkquality: Mapped[int | None] = mapped_column(Integer)       # LQI 0-255
    last_seen: Mapped[datetime | None] = mapped_column(DateTime)
    last_battery_alert: Mapped[datetime | None] = mapped_column(DateTime)
    last_offline_alert: Mapped[datetime | None] = mapped_column(DateTime)


class DeviceHistory(Base):
    """Time-series battery and linkquality snapshots."""
    __tablename__ = "device_history"
    __table_args__ = (Index("ix_dh_ieee_ts", "ieee", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ieee: Mapped[str] = mapped_column(String(64), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    battery: Mapped[int | None] = mapped_column(Integer)
    linkquality: Mapped[int | None] = mapped_column(Integer)
    temperature: Mapped[float | None] = mapped_column(Float)
    humidity: Mapped[float | None] = mapped_column(Float)
    voltage: Mapped[float | None] = mapped_column(Float)
    power: Mapped[float | None] = mapped_column(Float)
    current: Mapped[float | None] = mapped_column(Float)
    energy: Mapped[float | None] = mapped_column(Float)


class PumpStat(Base):
    """Pump telemetry — written every poll cycle from HA API."""
    __tablename__ = "pump_stats"
    __table_args__ = (Index("ix_ps_entity_ts", "entity_id", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[str] = mapped_column(String(128), index=True)
    friendly_name: Mapped[str | None] = mapped_column(String(128))
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    state: Mapped[str | None] = mapped_column(String(32))          # on/off/unavailable
    rpm: Mapped[int | None] = mapped_column(Integer)
    temperature: Mapped[float | None] = mapped_column(Float)
    pressure: Mapped[float | None] = mapped_column(Float)
    power_w: Mapped[float | None] = mapped_column(Float)
    total_hours: Mapped[float | None] = mapped_column(Float)


class Alert(Base):
    """Notification history — written by alert rules, shown on dashboard."""
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    level: Mapped[str] = mapped_column(String(16))       # ok / warn / err / info
    category: Mapped[str] = mapped_column(String(32))    # battery / offline / pump / system
    message: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[str | None] = mapped_column(String(128))
    sent_telegram: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
