"""Create immutable market-data persistence tables.

Revision ID: 20260729_0001
Revises:
Create Date: 2026-07-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260729_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
}


def upgrade() -> None:
    """Create the initial lineage and daily-bar schema."""

    op.create_table(
        "ingestion_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset", sa.String(length=64), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("provider_version", sa.String(length=32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("source_batch_id", sa.String(length=128), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_id",
            "source_batch_id",
            "dataset",
            name="uq_ingestion_batch_source",
        ),
        **MYSQL_OPTIONS,
    )
    op.create_table(
        "data_partitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset", sa.String(length=64), nullable=False),
        sa.Column("partition_date", sa.Date(), nullable=False),
        sa.Column("ingestion_batch_id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("provider_version", sa.String(length=32), nullable=False),
        sa.Column("source_batch_id", sa.String(length=128), nullable=False),
        sa.Column("source_content_hash", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("quality_state", sa.String(length=16), nullable=False),
        sa.Column("quality_report", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingestion_batch_id"],
            ["ingestion_batches.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dataset",
            "partition_date",
            "content_hash",
            name="uq_data_partition_content",
        ),
        **MYSQL_OPTIONS,
    )
    op.create_index(
        "ix_data_partitions_ingestion_batch_id",
        "data_partitions",
        ["ingestion_batch_id"],
        unique=False,
    )
    op.create_table(
        "daily_bars",
        sa.Column("partition_id", sa.String(length=36), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", mysql.DECIMAL(precision=18, scale=6), nullable=False),
        sa.Column("high", mysql.DECIMAL(precision=18, scale=6), nullable=False),
        sa.Column("low", mysql.DECIMAL(precision=18, scale=6), nullable=False),
        sa.Column("close", mysql.DECIMAL(precision=18, scale=6), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("amount", mysql.DECIMAL(precision=24, scale=4), nullable=False),
        sa.Column("is_trading", sa.Boolean(), nullable=False),
        sa.Column("is_st", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["partition_id"],
            ["data_partitions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "partition_id",
            "symbol",
            "trade_date",
            name="pk_daily_bar",
        ),
        **MYSQL_OPTIONS,
    )
    op.create_index(
        "ix_daily_bar_symbol_date",
        "daily_bars",
        ["symbol", "trade_date"],
        unique=False,
    )
    op.create_table(
        "published_partitions",
        sa.Column("dataset", sa.String(length=64), nullable=False),
        sa.Column("partition_date", sa.Date(), nullable=False),
        sa.Column("partition_id", sa.String(length=36), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["partition_id"],
            ["data_partitions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "dataset",
            "partition_date",
            name="pk_published_partition",
        ),
        sa.UniqueConstraint("partition_id"),
        **MYSQL_OPTIONS,
    )


def downgrade() -> None:
    """Remove the initial schema from a disposable database."""

    op.drop_table("published_partitions")
    op.drop_index("ix_daily_bar_symbol_date", table_name="daily_bars")
    op.drop_table("daily_bars")
    op.drop_index(
        "ix_data_partitions_ingestion_batch_id",
        table_name="data_partitions",
    )
    op.drop_table("data_partitions")
    op.drop_table("ingestion_batches")
