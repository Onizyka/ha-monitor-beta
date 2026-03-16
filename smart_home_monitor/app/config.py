from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional, List
import json, os


class Settings(BaseSettings):
    # MQTT
    mqtt_host: str = "core-mosquitto"
    mqtt_port: int = 1883
    mqtt_user: Optional[str] = None
    mqtt_password: Optional[str] = None
    mqtt_topic_prefix: str = "zigbee2mqtt"

    # Database
    db_host: str = "core-mariadb"
    db_port: int = 3306
    db_name: str = "smarthome"
    db_user: str = "smarthome"
    db_password: str = ""

    # Home Assistant
    ha_url: str = "http://supervisor/core"
    ha_token: Optional[str] = None

    # Telegram
    telegram_enabled: bool = False
    telegram_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    # MAX мессенджер
    max_enabled: bool = False
    max_token: Optional[str] = None
    max_chat_id: Optional[str] = None

    # Пороги — Optional чтобы выжить если HA передаёт "null"
    battery_threshold: Optional[int] = 20
    offline_minutes: Optional[int] = 180

    # Старые имена (обратная совместимость) — тоже Optional
    telegram_battery_threshold: Optional[int] = None
    telegram_alert_battery_threshold: Optional[int] = None
    telegram_alert_device_offline_minutes: Optional[int] = None

    # Pumps
    pump_entity_ids: str = ""

    # App
    log_level: str = "info"
    ingress_path: str = ""

    @field_validator('battery_threshold', 'offline_minutes',
                     'telegram_battery_threshold',
                     'telegram_alert_battery_threshold',
                     'telegram_alert_device_offline_minutes',
                     mode='before')
    @classmethod
    def coerce_int_or_none(cls, v):
        """Accept 'null', '', None → return None; else parse as int."""
        if v is None or str(v).strip().lower() in ('null', 'none', ''):
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    @property
    def _battery_threshold(self) -> int:
        """Resolved battery threshold with fallback chain."""
        return (self.battery_threshold
                or self.telegram_battery_threshold
                or self.telegram_alert_battery_threshold
                or 20)

    @property
    def _offline_minutes(self) -> int:
        """Resolved offline minutes with fallback chain."""
        return (self.offline_minutes
                or self.telegram_alert_device_offline_minutes
                or 180)

    @property
    def pump_entity_ids_list(self) -> List[str]:
        raw = (self.pump_entity_ids or "").strip()
        if not raw:
            return []
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
                return [str(x) for x in parsed if x]
            except Exception:
                pass
        return [x.strip() for x in raw.split(",") if x.strip()]

    @property
    def db_url(self) -> str:
        return (
            f"mysql+aiomysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def db_url_sync(self) -> str:
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
