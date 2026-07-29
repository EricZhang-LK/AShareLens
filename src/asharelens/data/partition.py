"""Immutable daily partitions and reproducible snapshot manifests."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import date

from asharelens.core.models import DailyBar, FrozenModel
from asharelens.data.models import DataBatch, Dataset


class PartitionKey(FrozenModel):
    """Natural key used for atomic data publication."""

    dataset: Dataset
    partition_date: date


class DataPartition(FrozenModel):
    """One normalized, single-provider daily partition."""

    key: PartitionKey
    provider_id: str
    provider_version: str
    source_batch_id: str
    source_content_hash: str
    schema_version: str
    content_hash: str
    records: tuple[DailyBar, ...]

    @classmethod
    def create(
        cls,
        *,
        key: PartitionKey,
        provider_id: str,
        provider_version: str,
        source_batch_id: str,
        source_content_hash: str,
        schema_version: str,
        records: Iterable[DailyBar],
    ) -> DataPartition:
        ordered_records = tuple(
            sorted(records, key=lambda record: (record.trade_date, record.symbol))
        )
        return cls(
            key=key,
            provider_id=provider_id,
            provider_version=provider_version,
            source_batch_id=source_batch_id,
            source_content_hash=source_content_hash,
            schema_version=schema_version,
            content_hash=_record_hash(ordered_records),
            records=ordered_records,
        )


class PartitionReference(FrozenModel):
    """Compact lineage stored in a snapshot manifest."""

    key: PartitionKey
    provider_id: str
    source_batch_id: str
    schema_version: str
    content_hash: str


class SnapshotManifest(FrozenModel):
    """Canonical list of immutable partitions consumed by one run."""

    snapshot_id: str
    partitions: tuple[PartitionReference, ...]

    @classmethod
    def from_partitions(
        cls,
        partitions: Iterable[DataPartition],
    ) -> SnapshotManifest:
        references = tuple(
            sorted(
                (
                    PartitionReference(
                        key=partition.key,
                        provider_id=partition.provider_id,
                        source_batch_id=partition.source_batch_id,
                        schema_version=partition.schema_version,
                        content_hash=partition.content_hash,
                    )
                    for partition in partitions
                ),
                key=lambda reference: (
                    reference.key.dataset,
                    reference.key.partition_date,
                    reference.provider_id,
                ),
            )
        )
        payload = [reference.model_dump(mode="json") for reference in references]
        return cls(snapshot_id=_canonical_hash(payload), partitions=references)


def partition_daily_bars(
    batch: DataBatch[DailyBar],
) -> tuple[DataPartition, ...]:
    """Split one Provider batch into deterministic, single-source days."""

    if batch.dataset is not Dataset.DAILY_BARS:
        raise ValueError("partition_daily_bars requires the daily_bars dataset")

    grouped: dict[date, list[DailyBar]] = defaultdict(list)
    for record in batch.records:
        grouped[record.trade_date].append(record)

    return tuple(
        DataPartition.create(
            key=PartitionKey(dataset=Dataset.DAILY_BARS, partition_date=partition_date),
            provider_id=batch.provider_id,
            provider_version=batch.provider_version,
            source_batch_id=batch.source_batch_id,
            source_content_hash=batch.content_hash,
            schema_version=batch.schema_version,
            records=grouped[partition_date],
        )
        for partition_date in sorted(grouped)
    )


def _record_hash(records: tuple[DailyBar, ...]) -> str:
    return _canonical_hash([record.model_dump(mode="json") for record in records])


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
