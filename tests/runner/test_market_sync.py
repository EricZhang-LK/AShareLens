from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from asharelens.core.models import DailyBar
from asharelens.data.models import Adjustment, DataBatch, Dataset
from asharelens.data.provider import ProviderError, ProviderMetadata
from asharelens.data.quality import DailyBarQualityGate
from asharelens.runner.workflows.market_sync import (
    MarketDataSynchronizer,
    MarketSyncFailure,
    MarketSyncStatus,
)
from asharelens.storage.data_repository import DataRepository
from asharelens.storage.database import Base, create_database_engine

SYMBOLS = ("sh.600000", "sz.000001")


def _bar(symbol: str, trade_date: date, close: float = 10) -> DailyBar:
    return DailyBar(
        symbol=symbol,
        trade_date=trade_date,
        open=close,
        high=close + 0.1,
        low=close - 0.1,
        close=close,
        volume=1_000,
        amount=close * 1_000,
    )


def _batch(
    provider_id: str,
    records: tuple[DailyBar, ...],
) -> DataBatch[DailyBar]:
    return DataBatch[DailyBar](
        dataset=Dataset.DAILY_BARS,
        provider_id=provider_id,
        provider_version="1.0",
        fetched_at=datetime(2026, 7, 30, tzinfo=UTC),
        request={"start": "2026-07-29", "end": "2026-07-30"},
        source_batch_id=f"{provider_id}-batch",
        content_hash=("a" if provider_id == "primary" else "b") * 64,
        records=records,
    )


class FakeProvider:
    def __init__(
        self,
        provider_id: str,
        outcome: DataBatch[DailyBar] | ProviderError,
    ) -> None:
        self.metadata = ProviderMetadata(
            provider_id=provider_id,
            name=provider_id,
            version="1.0",
            description="test",
            datasets=(Dataset.DAILY_BARS,),
            requires_registration=False,
        )
        self.outcome = outcome

    def fetch_daily_bars(
        self,
        symbols: tuple[str, ...],
        start: date,
        end: date,
        adjustment: Adjustment,
    ) -> DataBatch[DailyBar]:
        if isinstance(self.outcome, ProviderError):
            raise self.outcome
        return self.outcome


def test_range_sync_falls_back_as_one_batch_and_publishes_lineage() -> None:
    trade_dates = (date(2026, 7, 29), date(2026, 7, 30))
    primary = FakeProvider(
        "primary",
        ProviderError(
            provider_id="primary",
            error_code="timeout",
            message="upstream timeout",
            retryable=True,
        ),
    )
    fallback = FakeProvider(
        "fallback",
        _batch(
            "fallback",
            tuple(_bar(symbol, day) for day in trade_dates for symbol in SYMBOLS),
        ),
    )
    synchronizer = MarketDataSynchronizer(
        providers=(primary, fallback),
        quality_gate=DailyBarQualityGate(min_coverage=1),
    )

    result = synchronizer.fetch_range(
        start=trade_dates[0],
        end=trade_dates[-1],
        symbols=SYMBOLS,
    )

    assert result.status is MarketSyncStatus.UPDATED
    assert [attempt.outcome for attempt in result.attempts] == [
        "provider_error",
        "accepted",
    ]
    assert len(result.partitions) == 2
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        synchronizer.publish(session, result)
        published = DataRepository(session).get_published_daily_range(
            Dataset.DAILY_BARS,
            trade_dates[0],
            trade_dates[-1],
        )
        assert [item.provider_id for item in published] == [
            "fallback",
            "fallback",
        ]
        assert len({item.source_batch_id for item in published}) == 1


def test_range_sync_treats_all_empty_sources_as_no_data() -> None:
    empty = tuple(
        FakeProvider(provider_id, _batch(provider_id, ()))
        for provider_id in ("primary", "fallback")
    )

    result = MarketDataSynchronizer(
        providers=empty,
        quality_gate=DailyBarQualityGate(),
    ).fetch_range(
        start=date(2026, 7, 30),
        end=date(2026, 7, 30),
        symbols=SYMBOLS,
    )

    assert result.status is MarketSyncStatus.NO_DATA
    assert all(attempt.outcome == "no_data" for attempt in result.attempts)


def test_range_sync_reports_quality_failure_as_non_retryable() -> None:
    incomplete = tuple(
        FakeProvider(
            provider_id,
            _batch(provider_id, (_bar("sh.600000", date(2026, 7, 30)),)),
        )
        for provider_id in ("primary", "fallback")
    )

    with pytest.raises(MarketSyncFailure) as error:
        MarketDataSynchronizer(
            providers=incomplete,
            quality_gate=DailyBarQualityGate(min_coverage=1),
        ).fetch_range(
            start=date(2026, 7, 30),
            end=date(2026, 7, 30),
            symbols=SYMBOLS,
        )

    assert error.value.retryable is False
    assert all(
        attempt.outcome == "quality_rejected"
        for attempt in error.value.attempts
    )
