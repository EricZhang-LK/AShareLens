from datetime import UTC, date, datetime

import pytest

from asharelens.core.models import DailyBar
from asharelens.data.models import DataBatch, Dataset
from asharelens.data.partition import SnapshotManifest, partition_daily_bars


def make_bar(symbol: str, trade_date: date, close: float) -> DailyBar:
    return DailyBar(
        symbol=symbol,
        trade_date=trade_date,
        open=close,
        high=close + 0.1,
        low=close - 0.1,
        close=close,
        volume=1000,
        amount=close * 1000,
    )


def make_batch(records: tuple[DailyBar, ...]) -> DataBatch[DailyBar]:
    return DataBatch[DailyBar](
        dataset=Dataset.DAILY_BARS,
        provider_id="fixture",
        provider_version="1.2.3",
        fetched_at=datetime(2026, 7, 29, 10, tzinfo=UTC),
        request={"start": "2026-07-01", "end": "2026-07-02"},
        source_batch_id="source-batch-1",
        content_hash="a" * 64,
        records=records,
    )


def test_daily_batch_becomes_one_partition_per_trade_date() -> None:
    first_date = date(2026, 7, 1)
    second_date = date(2026, 7, 2)
    batch = make_batch(
        (
            make_bar("sz.000001", second_date, 12),
            make_bar("sh.600000", first_date, 10),
            make_bar("sz.000001", first_date, 11),
        )
    )

    partitions = partition_daily_bars(batch)

    assert tuple(partition.key.partition_date for partition in partitions) == (
        first_date,
        second_date,
    )
    assert all(partition.provider_id == "fixture" for partition in partitions)
    assert all(partition.source_batch_id == "source-batch-1" for partition in partitions)
    assert tuple(bar.symbol for bar in partitions[0].records) == (
        "sh.600000",
        "sz.000001",
    )


def test_partition_content_hash_is_independent_of_record_order() -> None:
    trade_date = date(2026, 7, 1)
    records = (
        make_bar("sh.600000", trade_date, 10),
        make_bar("sz.000001", trade_date, 11),
    )

    first = partition_daily_bars(make_batch(records))[0]
    second = partition_daily_bars(make_batch(tuple(reversed(records))))[0]

    assert first.content_hash == second.content_hash
    assert first.records == second.records


def test_snapshot_id_is_independent_of_partition_order() -> None:
    batch = make_batch(
        (
            make_bar("sh.600000", date(2026, 7, 1), 10),
            make_bar("sh.600000", date(2026, 7, 2), 11),
        )
    )
    partitions = partition_daily_bars(batch)

    first = SnapshotManifest.from_partitions(partitions)
    second = SnapshotManifest.from_partitions(tuple(reversed(partitions)))

    assert first.snapshot_id == second.snapshot_id
    assert len(first.snapshot_id) == 64


def test_daily_partitioning_rejects_another_dataset() -> None:
    batch = DataBatch[DailyBar](
        dataset=Dataset.INSTRUMENTS,
        provider_id="fixture",
        provider_version="1.2.3",
        fetched_at=datetime(2026, 7, 29, 10, tzinfo=UTC),
        request={},
        source_batch_id="source-batch-1",
        content_hash="a" * 64,
        records=(),
    )

    with pytest.raises(ValueError, match="daily_bars"):
        partition_daily_bars(batch)
