"""Transactional repositories for immutable market-data publication."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from asharelens.core.models import DailyBar, FrozenModel
from asharelens.data.models import DataBatch, Dataset
from asharelens.data.partition import DataPartition
from asharelens.data.quality import QualityReport
from asharelens.storage.models import (
    DailyBarRow,
    DataPartitionRow,
    IngestionBatchRow,
    PublishedPartitionRow,
    utc_now_naive,
)


class UnpublishablePartition(ValueError):
    """A quality-failed partition cannot become the current version."""


class MissingIngestionBatch(LookupError):
    """A partition must reference a previously recorded source batch."""


class PublishedDailyData(FrozenModel):
    """Published bars and the exact lineage used to produce them."""

    partition_id: str
    partition_date: date
    provider_id: str
    source_batch_id: str
    content_hash: str
    bars: tuple[DailyBar, ...]


class DataRepository:
    """Persist data without owning the caller's commit or rollback."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record_batch[RecordT](self, batch: DataBatch[RecordT]) -> str:
        """Record one immutable Provider batch idempotently."""

        existing = self.session.scalar(
            select(IngestionBatchRow).where(
                IngestionBatchRow.provider_id == batch.provider_id,
                IngestionBatchRow.source_batch_id == batch.source_batch_id,
                IngestionBatchRow.dataset == batch.dataset.value,
            )
        )
        if existing is not None:
            return existing.id

        row = IngestionBatchRow(
            id=str(uuid4()),
            dataset=batch.dataset.value,
            provider_id=batch.provider_id,
            provider_version=batch.provider_version,
            fetched_at=_to_naive_utc(batch.fetched_at),
            request=batch.request,
            source_batch_id=batch.source_batch_id,
            content_hash=batch.content_hash,
            schema_version=batch.schema_version,
        )
        self.session.add(row)
        self.session.flush()
        return row.id

    def publish_daily_partition(
        self,
        partition: DataPartition,
        report: QualityReport,
    ) -> str:
        """Persist a version and atomically move its natural-key pointer."""

        if not report.publishable:
            raise UnpublishablePartition("quality failures prevent publication")
        if partition.key.dataset is not Dataset.DAILY_BARS:
            raise ValueError("publish_daily_partition requires daily_bars")

        batch = self.session.scalar(
            select(IngestionBatchRow).where(
                IngestionBatchRow.provider_id == partition.provider_id,
                IngestionBatchRow.source_batch_id == partition.source_batch_id,
                IngestionBatchRow.dataset == partition.key.dataset.value,
            )
        )
        if batch is None:
            raise MissingIngestionBatch(partition.source_batch_id)

        stored = self.session.scalar(
            select(DataPartitionRow).where(
                DataPartitionRow.dataset == partition.key.dataset.value,
                DataPartitionRow.partition_date == partition.key.partition_date,
                DataPartitionRow.content_hash == partition.content_hash,
            )
        )
        if stored is None:
            stored = DataPartitionRow(
                id=str(uuid4()),
                dataset=partition.key.dataset.value,
                partition_date=partition.key.partition_date,
                ingestion_batch_id=batch.id,
                provider_id=partition.provider_id,
                provider_version=partition.provider_version,
                source_batch_id=partition.source_batch_id,
                source_content_hash=partition.source_content_hash,
                content_hash=partition.content_hash,
                schema_version=partition.schema_version,
                quality_state="degraded" if report.degraded else "passed",
                quality_report=report.model_dump(mode="json"),
            )
            self.session.add(stored)
            self.session.flush()
            self.session.add_all(
                [
                    DailyBarRow(
                        partition_id=stored.id,
                        symbol=bar.symbol,
                        trade_date=bar.trade_date,
                        open=Decimal(str(bar.open)),
                        high=Decimal(str(bar.high)),
                        low=Decimal(str(bar.low)),
                        close=Decimal(str(bar.close)),
                        volume=bar.volume,
                        amount=Decimal(str(bar.amount)),
                        is_trading=bar.is_trading,
                        is_st=bar.is_st,
                    )
                    for bar in partition.records
                ]
            )
            self.session.flush()

        pointer = self.session.get(
            PublishedPartitionRow,
            (partition.key.dataset.value, partition.key.partition_date),
        )
        if pointer is None:
            pointer = PublishedPartitionRow(
                dataset=partition.key.dataset.value,
                partition_date=partition.key.partition_date,
                partition_id=stored.id,
            )
            self.session.add(pointer)
        else:
            pointer.partition_id = stored.id
            pointer.updated_at = utc_now_naive()
        self.session.flush()
        return stored.id

    def get_published_daily_bars(
        self,
        dataset: Dataset,
        partition_date: date,
    ) -> PublishedDailyData | None:
        """Load the current partition and reconstruct normalized domain bars."""

        pointer = self.session.get(
            PublishedPartitionRow,
            (dataset.value, partition_date),
        )
        if pointer is None:
            return None
        partition = self.session.get(DataPartitionRow, pointer.partition_id)
        if partition is None:
            return None

        rows = self.session.scalars(
            select(DailyBarRow)
            .where(DailyBarRow.partition_id == partition.id)
            .order_by(DailyBarRow.symbol, DailyBarRow.trade_date)
        ).all()
        bars = tuple(
            DailyBar(
                symbol=row.symbol,
                trade_date=row.trade_date,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=row.volume,
                amount=float(row.amount),
                is_trading=row.is_trading,
                is_st=row.is_st,
            )
            for row in rows
        )
        return PublishedDailyData(
            partition_id=partition.id,
            partition_date=partition.partition_date,
            provider_id=partition.provider_id,
            source_batch_id=partition.source_batch_id,
            content_hash=partition.content_hash,
            bars=bars,
        )

    def get_published_daily_range(
        self,
        dataset: Dataset,
        start: date,
        end: date,
    ) -> tuple[PublishedDailyData, ...]:
        """Load current daily partitions in chronological order."""

        if start > end:
            raise ValueError("start must not be later than end")
        dates = tuple(
            self.session.scalars(
                select(PublishedPartitionRow.partition_date)
                .where(
                    PublishedPartitionRow.dataset == dataset.value,
                    PublishedPartitionRow.partition_date >= start,
                    PublishedPartitionRow.partition_date <= end,
                )
                .order_by(PublishedPartitionRow.partition_date)
            )
        )
        published = (
            self.get_published_daily_bars(dataset, partition_date)
            for partition_date in dates
        )
        return tuple(item for item in published if item is not None)


def _to_naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)
