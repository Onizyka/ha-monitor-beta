"""Initial schema — devices, device_history, pump_stats, alerts

Revision ID: 0001
Revises: 
Create Date: 2024-01-01 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "devices",
        sa.Column("ieee", sa.String(64), primary_key=True),
        sa.Column("friendly_name", sa.String(128), nullable=False, index=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("vendor", sa.String(128), nullable=True),
        sa.Column("device_type", sa.String(64), nullable=True),
        sa.Column("online", sa.Boolean, default=False, nullable=False),
        sa.Column("battery", sa.Integer, nullable=True),
        sa.Column("linkquality", sa.Integer, nullable=True),
        sa.Column("last_seen", sa.DateTime, nullable=True),
        sa.Column("last_battery_alert", sa.DateTime, nullable=True),
        sa.Column("last_offline_alert", sa.DateTime, nullable=True),
    )

    op.create_table(
        "device_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ieee", sa.String(64), nullable=False, index=True),
        sa.Column("ts", sa.DateTime, nullable=False),
        sa.Column("battery", sa.Integer, nullable=True),
        sa.Column("linkquality", sa.Integer, nullable=True),
        sa.Column("temperature", sa.Float, nullable=True),
        sa.Column("humidity", sa.Float, nullable=True),
    )
    op.create_index("ix_dh_ieee_ts", "device_history", ["ieee", "ts"])

    op.create_table(
        "pump_stats",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("entity_id", sa.String(128), nullable=False, index=True),
        sa.Column("friendly_name", sa.String(128), nullable=True),
        sa.Column("ts", sa.DateTime, nullable=False),
        sa.Column("state", sa.String(32), nullable=True),
        sa.Column("rpm", sa.Integer, nullable=True),
        sa.Column("temperature", sa.Float, nullable=True),
        sa.Column("pressure", sa.Float, nullable=True),
        sa.Column("power_w", sa.Float, nullable=True),
        sa.Column("total_hours", sa.Float, nullable=True),
    )
    op.create_index("ix_ps_entity_ts", "pump_stats", ["entity_id", "ts"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime, nullable=False, index=True),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=True),
        sa.Column("sent_telegram", sa.Boolean, default=False, nullable=False),
        sa.Column("acknowledged", sa.Boolean, default=False, nullable=False),
    )


def downgrade():
    op.drop_table("alerts")
    op.drop_table("pump_stats")
    op.drop_table("device_history")
    op.drop_table("devices")
