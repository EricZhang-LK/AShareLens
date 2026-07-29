"""Create the durable Runner job queue.

Revision ID: 20260729_0002
Revises: 20260729_0001
Create Date: 2026-07-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260729_0002"
down_revision: str | None = "20260729_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
}


def upgrade() -> None:
    """Create the lease-based durable job table."""

    op.create_table(
        "runner_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("queue", sa.String(length=32), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("available_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("leased_by", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("heartbeat_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("finished_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_type",
            "idempotency_key",
            name="uq_runner_job_idempotency",
        ),
        **MYSQL_OPTIONS,
    )
    op.create_index(
        "ix_runner_job_claim",
        "runner_jobs",
        ["queue", "status", "available_at", "priority", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the Runner job queue from a disposable database."""

    op.drop_index("ix_runner_job_claim", table_name="runner_jobs")
    op.drop_table("runner_jobs")
