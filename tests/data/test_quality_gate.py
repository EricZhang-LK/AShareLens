from datetime import date

from asharelens.core.models import DailyBar
from asharelens.data.models import Dataset
from asharelens.data.partition import DataPartition, PartitionKey
from asharelens.data.quality import DailyBarQualityGate, QualitySeverity

TRADE_DATE = date(2026, 7, 1)


def make_bar(
    symbol: str,
    *,
    volume: int = 1000,
    is_trading: bool = True,
) -> DailyBar:
    return DailyBar(
        symbol=symbol,
        trade_date=TRADE_DATE,
        open=10,
        high=10.1,
        low=9.9,
        close=10,
        volume=volume,
        amount=10_000 if volume else 0,
        is_trading=is_trading,
    )


def make_partition(records: tuple[DailyBar, ...]) -> DataPartition:
    return DataPartition.create(
        key=PartitionKey(dataset=Dataset.DAILY_BARS, partition_date=TRADE_DATE),
        provider_id="fixture",
        provider_version="1",
        source_batch_id="batch-1",
        source_content_hash="a" * 64,
        schema_version="1",
        records=records,
    )


def test_duplicate_symbol_and_date_is_a_failure() -> None:
    report = DailyBarQualityGate().evaluate(
        make_partition((make_bar("sh.600000"), make_bar("sh.600000"))),
        expected_symbols=("sh.600000",),
    )

    assert report.publishable is False
    assert report.issues[0].code == "duplicate_record"
    assert report.issues[0].severity is QualitySeverity.FAILURE


def test_coverage_below_threshold_is_a_failure() -> None:
    report = DailyBarQualityGate(min_coverage=1).evaluate(
        make_partition((make_bar("sh.600000"),)),
        expected_symbols=("sh.600000", "sz.000001"),
    )

    assert report.coverage == 0.5
    assert any(issue.code == "coverage_below_threshold" for issue in report.issues)
    assert report.publishable is False


def test_zero_volume_trading_record_is_a_publishable_warning() -> None:
    report = DailyBarQualityGate().evaluate(
        make_partition((make_bar("sh.600000", volume=0),)),
        expected_symbols=("sh.600000",),
    )

    assert [issue.code for issue in report.issues] == ["zero_volume"]
    assert report.publishable is True
    assert report.degraded is True


def test_suspended_record_does_not_raise_zero_volume_warning() -> None:
    report = DailyBarQualityGate().evaluate(
        make_partition((make_bar("sh.600000", volume=0, is_trading=False),)),
        expected_symbols=("sh.600000",),
    )

    assert report.issues == ()
    assert report.publishable is True
    assert report.degraded is False


def test_complete_partition_passes_quality_gate() -> None:
    report = DailyBarQualityGate().evaluate(
        make_partition((make_bar("sh.600000"), make_bar("sz.000001"))),
        expected_symbols=("sh.600000", "sz.000001"),
    )

    assert report.coverage == 1
    assert report.issues == ()
    assert report.publishable is True
