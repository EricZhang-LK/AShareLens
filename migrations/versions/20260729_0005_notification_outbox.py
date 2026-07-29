"""Create the notification delivery ledger.

Revision ID: 20260729_0005
Revises: 20260729_0004
Create Date: 2026-07-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260729_0005"
down_revision: str | None = "20260729_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
}


def upgrade() -> None:
    """Create the audit ledger driven by durable Runner jobs."""

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("notifier_id", sa.String(length=128), nullable=False),
        sa.Column("dedupe_key", sa.String(length=160), nullable=False),
        sa.Column("message", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=256), nullable=True),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("delivered_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "notifier_id",
            "dedupe_key",
            name="uq_notification_delivery_dedupe",
        ),
        **MYSQL_OPTIONS,
    )
    op.create_index(
        "ix_notification_delivery_status",
        "notification_deliveries",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove notification audits from a disposable database."""

    op.drop_index(
        "ix_notification_delivery_status",
        table_name="notification_deliveries",
    )
    op.drop_table("notification_deliveries")
