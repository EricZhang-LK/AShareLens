from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from asharelens.core.models import DailyBar
from asharelens.data.models import DataBatch, Dataset
from asharelens.data.partition import partition_daily_bars
from asharelens.data.quality import (
    QualityIssue,
    QualityReport,
    QualitySeverity,
)
from asharelens.storage.data_repository import (
    DataRepository,
    UnpublishablePartition,
)
from asharelens.storage.database import (
    Base,
    create_database_engine,
    create_session_factory,
)
from asharelens.storage.models import DailyBarRow, DataPartitionRow

TRADE_DATE = date(2026, 7, 1)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory() as database_session:
        yield database_session


def make_batch(
    *,
    source_batch_id: str = "batch-1",
    content_hash: str = "a" * 64,
    close: float = 10,
) -> DataBatch[DailyBar]:
    bar = DailyBar(
        symbol="sh.600000",
        trade_date=TRADE_DATE,
        open=close,
        high=close + 0.1,
        low=close - 0.1,
        close=close,
        volume=1000,
        amount=close * 1000,
    )
    return DataBatch[DailyBar](
        dataset=Dataset.DAILY_BARS,
        provider_id="fixture",
        provider_version="1",
        fetched_at=datetime(2026, 7, 1, 10, tzinfo=UTC),
        request={"date": TRADE_DATE.isoformat()},
        source_batch_id=source_batch_id,
        content_hash=content_hash,
        records=(bar,),
    )


def passing_report() -> QualityReport:
    return QualityReport(coverage=1, issues=())


def test_recording_same_source_batch_twice_is_idempotent(session: Session) -> None:
    repository = DataRepository(session)
    batch = make_batch()

    first = repository.record_batch(batch)
    second = repository.record_batch(batch)

    assert first == second


def test_publishing_same_partition_twice_does_not_duplicate_bars(
    session: Session,
) -> None:
    repository = DataRepository(session)
    batch = make_batch()
    repository.record_batch(batch)
    partition = partition_daily_bars(batch)[0]

    first = repository.publish_daily_partition(partition, passing_report())
    second = repository.publish_daily_partition(partition, passing_report())
    bar_count = session.scalar(select(func.count()).select_from(DailyBarRow))

    assert first == second
    assert bar_count == 1


def test_new_content_moves_pointer_without_mutating_old_partition(
    session: Session,
) -> None:
    repository = DataRepository(session)
    first_batch = make_batch()
    second_batch = make_batch(
        source_batch_id="batch-2",
        content_hash="b" * 64,
        close=11,
    )
    repository.record_batch(first_batch)
    repository.record_batch(second_batch)
    first_id = repository.publish_daily_partition(
        partition_daily_bars(first_batch)[0],
        passing_report(),
    )
    second_id = repository.publish_daily_partition(
        partition_daily_bars(second_batch)[0],
        passing_report(),
    )

    published = repository.get_published_daily_bars(
        Dataset.DAILY_BARS,
        TRADE_DATE,
    )
    partition_count = session.scalar(
        select(func.count()).select_from(DataPartitionRow)
    )

    assert first_id != second_id
    assert published is not None
    assert published.partition_id == second_id
    assert published.bars[0].close == 11
    assert partition_count == 2


def test_failure_report_keeps_previous_published_pointer(
    session: Session,
) -> None:
    repository = DataRepository(session)
    first_batch = make_batch()
    rejected_batch = make_batch(
        source_batch_id="batch-rejected",
        content_hash="c" * 64,
        close=12,
    )
    repository.record_batch(first_batch)
    repository.record_batch(rejected_batch)
    accepted_id = repository.publish_daily_partition(
        partition_daily_bars(first_batch)[0],
        passing_report(),
    )
    failed_report = QualityReport(
        coverage=0.5,
        issues=(
            QualityIssue(
                severity=QualitySeverity.FAILURE,
                code="coverage_below_threshold",
                message="coverage failed",
            ),
        ),
    )

    with pytest.raises(UnpublishablePartition):
        repository.publish_daily_partition(
            partition_daily_bars(rejected_batch)[0],
            failed_report,
        )

    published = repository.get_published_daily_bars(
        Dataset.DAILY_BARS,
        TRADE_DATE,
    )
    assert published is not None
    assert published.partition_id == accepted_id


def test_retrieved_partition_preserves_full_lineage(session: Session) -> None:
    repository = DataRepository(session)
    batch = make_batch()
    repository.record_batch(batch)
    partition = partition_daily_bars(batch)[0]
    repository.publish_daily_partition(partition, passing_report())

    published = repository.get_published_daily_bars(
        Dataset.DAILY_BARS,
        TRADE_DATE,
    )

    assert published is not None
    assert published.provider_id == "fixture"
    assert published.source_batch_id == "batch-1"
    assert published.content_hash == partition.content_hash
