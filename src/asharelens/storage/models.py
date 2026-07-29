"""Typed SQLAlchemy schema shared by migrations and repositories."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import DATETIME, DECIMAL
from sqlalchemy.orm import Mapped, mapped_column

from asharelens.storage.database import Base

MYSQL_TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
}
UTC_DATETIME = DateTime(timezone=False).with_variant(DATETIME(fsp=6), "mysql")


def utc_now_naive() -> datetime:
    """Return UTC without tzinfo for MySQL DATETIME storage."""

    return datetime.now(UTC).replace(tzinfo=None)


class IngestionBatchRow(Base):
    """Immutable source batch lineage."""

    __tablename__ = "ingestion_batches"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "source_batch_id",
            "dataset",
            name="uq_ingestion_batch_source",
        ),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(32), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_batch_id: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=utc_now_naive,
        nullable=False,
    )


class DataPartitionRow(Base):
    """Immutable normalized partition and quality evidence."""

    __tablename__ = "data_partitions"
    __table_args__ = (
        UniqueConstraint(
            "dataset",
            "partition_date",
            "content_hash",
            name="uq_data_partition_content",
        ),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset: Mapped[str] = mapped_column(String(64), nullable=False)
    partition_date: Mapped[date] = mapped_column(Date, nullable=False)
    ingestion_batch_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ingestion_batches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(32), nullable=False)
    source_batch_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    quality_state: Mapped[str] = mapped_column(String(16), nullable=False)
    quality_report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=utc_now_naive,
        nullable=False,
    )


class DailyBarRow(Base):
    """One normalized daily observation owned by an immutable partition."""

    __tablename__ = "daily_bars"
    __table_args__ = (
        PrimaryKeyConstraint(
            "partition_id",
            "symbol",
            "trade_date",
            name="pk_daily_bar",
        ),
        Index("ix_daily_bar_symbol_date", "symbol", "trade_date"),
        MYSQL_TABLE_OPTIONS,
    )

    partition_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("data_partitions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal] = mapped_column(DECIMAL(18, 6), nullable=False)
    high: Mapped[Decimal] = mapped_column(DECIMAL(18, 6), nullable=False)
    low: Mapped[Decimal] = mapped_column(DECIMAL(18, 6), nullable=False)
    close: Mapped[Decimal] = mapped_column(DECIMAL(18, 6), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[Decimal] = mapped_column(DECIMAL(24, 4), nullable=False)
    is_trading: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_st: Mapped[bool] = mapped_column(Boolean, nullable=False)


class PublishedPartitionRow(Base):
    """Mutable pointer to the current accepted partition for a natural key."""

    __tablename__ = "published_partitions"
    __table_args__ = (
        PrimaryKeyConstraint(
            "dataset",
            "partition_date",
            name="pk_published_partition",
        ),
        MYSQL_TABLE_OPTIONS,
    )

    dataset: Mapped[str] = mapped_column(String(64), nullable=False)
    partition_date: Mapped[date] = mapped_column(Date, nullable=False)
    partition_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("data_partitions.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=utc_now_naive,
        onupdate=utc_now_naive,
        nullable=False,
    )


class RunnerJobRow(Base):
    """Durable at-least-once job protected by a renewable lease."""

    __tablename__ = "runner_jobs"
    __table_args__ = (
        UniqueConstraint(
            "job_type",
            "idempotency_key",
            name="uq_runner_job_idempotency",
        ),
        Index(
            "ix_runner_job_claim",
            "queue",
            "status",
            "available_at",
            "priority",
            "created_at",
        ),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    queue: Mapped[str] = mapped_column(String(32), nullable=False)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[datetime] = mapped_column(UTC_DATETIME, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    leased_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTC_DATETIME, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTC_DATETIME, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTC_DATETIME,
        default=utc_now_naive,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTC_DATETIME,
        default=utc_now_naive,
        onupdate=utc_now_naive,
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(UTC_DATETIME, nullable=True)
