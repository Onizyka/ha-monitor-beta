"""Add electrical metrics to device_history

Revision ID: 0002
Revises: 0001
Create Date: 2024-01-02 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("device_history", sa.Column("voltage", sa.Float, nullable=True))
    op.add_column("device_history", sa.Column("power",   sa.Float, nullable=True))
    op.add_column("device_history", sa.Column("current", sa.Float, nullable=True))
    op.add_column("device_history", sa.Column("energy",  sa.Float, nullable=True))


def downgrade():
    op.drop_column("device_history", "energy")
    op.drop_column("device_history", "current")
    op.drop_column("device_history", "power")
    op.drop_column("device_history", "voltage")
