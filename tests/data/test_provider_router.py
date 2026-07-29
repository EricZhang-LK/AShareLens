from datetime import UTC, date, datetime

import pytest

from asharelens.core.models import DailyBar
from asharelens.data.models import Adjustment, DataBatch, Dataset
from asharelens.data.provider import ProviderError, ProviderMetadata
from asharelens.data.quality import DailyBarQualityGate
from asharelens.data.router import AllProvidersFailed, ProviderRouter

TRADE_DATE = date(2026, 7, 1)
SYMBOLS = ("sh.600000", "sz.000001")


def make_bar(symbol: str, close: float) -> DailyBar:
    return DailyBar(
        symbol=symbol,
        trade_date=TRADE_DATE,
        open=close,
        high=close + 0.1,
        low=close - 0.1,
        close=close,
        volume=1000,
        amount=close * 1000,
    )


def make_batch(provider_id: str, records: tuple[DailyBar, ...]) -> DataBatch[DailyBar]:
    return DataBatch[DailyBar](
        dataset=Dataset.DAILY_BARS,
        provider_id=provider_id,
        provider_version="1",
        fetched_at=datetime(2026, 7, 1, 10, tzinfo=UTC),
        request={"start": "2026-07-01", "end": "2026-07-01"},
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
            version="1",
            description="test provider",
            datasets=(Dataset.DAILY_BARS,),
            requires_registration=False,
        )
        self.outcome = outcome
        self.calls = 0

    def fetch_daily_bars(
        self,
        symbols: tuple[str, ...],
        start: date,
        end: date,
        adjustment: Adjustment,
    ) -> DataBatch[DailyBar]:
        self.calls += 1
        if isinstance(self.outcome, ProviderError):
            raise self.outcome
        return self.outcome


def make_router(primary: FakeProvider, fallback: FakeProvider) -> ProviderRouter:
    return ProviderRouter(
        providers=(primary, fallback),
        quality_gate=DailyBarQualityGate(min_coverage=1),
    )


def test_healthy_primary_is_used_without_calling_fallback() -> None:
    primary = FakeProvider(
        "primary",
        make_batch("primary", tuple(make_bar(symbol, 10) for symbol in SYMBOLS)),
    )
    fallback = FakeProvider(
        "fallback",
        make_batch("fallback", tuple(make_bar(symbol, 20) for symbol in SYMBOLS)),
    )

    routed = make_router(primary, fallback).fetch_daily_partition(
        TRADE_DATE,
        SYMBOLS,
    )

    assert routed.partition.provider_id == "primary"
    assert primary.calls == 1
    assert fallback.calls == 0


def test_provider_error_causes_complete_fallback() -> None:
    primary = FakeProvider(
        "primary",
        ProviderError(
            provider_id="primary",
            error_code="upstream_timeout",
            message="timed out",
            retryable=True,
        ),
    )
    fallback = FakeProvider(
        "fallback",
        make_batch("fallback", tuple(make_bar(symbol, 20) for symbol in SYMBOLS)),
    )

    routed = make_router(primary, fallback).fetch_daily_partition(
        TRADE_DATE,
        SYMBOLS,
    )

    assert routed.partition.provider_id == "fallback"
    assert [attempt.outcome for attempt in routed.attempts] == [
        "provider_error",
        "accepted",
    ]


def test_quality_failure_switches_the_entire_partition_without_row_mixing() -> None:
    primary = FakeProvider(
        "primary",
        make_batch("primary", (make_bar("sh.600000", 10),)),
    )
    fallback = FakeProvider(
        "fallback",
        make_batch("fallback", tuple(make_bar(symbol, 20) for symbol in SYMBOLS)),
    )

    routed = make_router(primary, fallback).fetch_daily_partition(
        TRADE_DATE,
        SYMBOLS,
    )

    assert routed.partition.provider_id == "fallback"
    assert {bar.close for bar in routed.partition.records} == {20}
    assert {bar.symbol for bar in routed.partition.records} == set(SYMBOLS)
    assert [attempt.outcome for attempt in routed.attempts] == [
        "quality_rejected",
        "accepted",
    ]


def test_all_provider_failures_preserve_each_attempt() -> None:
    providers = tuple(
        FakeProvider(
            provider_id,
            ProviderError(
                provider_id=provider_id,
                error_code="unavailable",
                message=f"{provider_id} unavailable",
                retryable=True,
            ),
        )
        for provider_id in ("primary", "fallback")
    )
    router = ProviderRouter(
        providers=providers,
        quality_gate=DailyBarQualityGate(min_coverage=1),
    )

    with pytest.raises(AllProvidersFailed) as error:
        router.fetch_daily_partition(TRADE_DATE, SYMBOLS)

    assert [attempt.provider_id for attempt in error.value.attempts] == [
        "primary",
        "fallback",
    ]
    assert all(attempt.error_code == "unavailable" for attempt in error.value.attempts)
