"""Create persistent Runner schedules.

Revision ID: 20260729_0003
Revises: 20260729_0002
Create Date: 2026-07-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260729_0003"
down_revision: str | None = "20260729_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
}


def upgrade() -> None:
    """Create daily local-time schedules persisted with UTC fire times."""

    op.create_table(
        "runner_schedules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("queue", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("local_time", sa.Time(), nullable=False),
        sa.Column("weekdays", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("catch_up_limit", sa.Integer(), nullable=False),
        sa.Column("next_fire_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("last_enqueued_for", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_runner_schedule_name"),
        **MYSQL_OPTIONS,
    )
    op.create_index(
        "ix_runner_schedule_due",
        "runner_schedules",
        ["enabled", "next_fire_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove persistent schedules from a disposable database."""

    op.drop_index("ix_runner_schedule_due", table_name="runner_schedules")
    op.drop_table("runner_schedules")
