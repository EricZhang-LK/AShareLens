from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest

from asharelens.data.models import Adjustment, Dataset
from asharelens.data.provider import ProviderError
from asharelens.data.providers.akshare import AkShareProvider, AkShareSdkGateway

FIXED_NOW = datetime(2026, 7, 29, 10, tzinfo=UTC)


class FakeAkShareGateway:
    version = "1.18.81"

    def __init__(self) -> None:
        self.instrument_rows: list[dict[str, object]] = []
        self.calendar_rows: list[dict[str, object]] = []
        self.daily_rows: list[dict[str, object]] = []
        self.daily_calls: list[dict[str, str]] = []
        self.failure: Exception | None = None

    def fetch_instruments(self) -> list[dict[str, object]]:
        if self.failure is not None:
            raise self.failure
        return self.instrument_rows

    def fetch_open_dates(self) -> list[dict[str, object]]:
        if self.failure is not None:
            raise self.failure
        return self.calendar_rows

    def fetch_daily(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str,
    ) -> list[dict[str, object]]:
        if self.failure is not None:
            raise self.failure
        self.daily_calls.append(
            {
                "symbol": symbol,
                "start_date": start_date,
                "end_date": end_date,
                "adjust": adjust,
            }
        )
        return self.daily_rows


def _provider(gateway: FakeAkShareGateway) -> AkShareProvider:
    return AkShareProvider(gateway=gateway, clock=lambda: FIXED_NOW)


def test_missing_optional_sdk_has_actionable_error() -> None:
    with (
        patch(
            "asharelens.data.providers.akshare.importlib.import_module",
            side_effect=ModuleNotFoundError,
        ),
        pytest.raises(ProviderError) as error,
    ):
        AkShareSdkGateway()

    assert error.value.error_code == "dependency_missing"
    assert error.value.retryable is False
    assert "asharelens[akshare]" in str(error.value)


def test_current_instruments_include_beijing_and_reject_historical_snapshot() -> None:
    gateway = FakeAkShareGateway()
    gateway.instrument_rows = [
        {"code": "600000", "name": "浦发银行"},
        {"code": "000001", "name": "平安银行"},
        {"code": "430047", "name": "诺思兰德"},
        {"code": "510300", "name": "沪深300ETF"},
    ]

    batch = _provider(gateway).fetch_instruments(date(2026, 7, 29))

    assert [record.symbol for record in batch.records] == [
        "sh.600000",
        "sz.000001",
        "bj.430047",
    ]
    assert all(record.is_active for record in batch.records)
    with pytest.raises(ProviderError) as error:
        _provider(gateway).fetch_instruments(date(2020, 1, 1))
    assert error.value.error_code == "point_in_time_unsupported"
    assert error.value.retryable is False


def test_calendar_synthesizes_closed_days_from_open_dates() -> None:
    gateway = FakeAkShareGateway()
    gateway.calendar_rows = [
        {"trade_date": date(2026, 7, 27)},
        {"trade_date": "2026-07-29"},
    ]

    batch = _provider(gateway).fetch_calendar(
        date(2026, 7, 27),
        date(2026, 7, 29),
    )

    assert batch.dataset is Dataset.TRADING_CALENDAR
    assert [(row.trade_date, row.is_open) for row in batch.records] == [
        (date(2026, 7, 27), True),
        (date(2026, 7, 28), False),
        (date(2026, 7, 29), True),
    ]


@pytest.mark.parametrize(
    ("adjustment", "expected"),
    [
        (Adjustment.NONE, ""),
        (Adjustment.FORWARD, "qfq"),
        (Adjustment.BACKWARD, "hfq"),
    ],
)
def test_daily_bars_normalize_units_and_adjustment(
    adjustment: Adjustment,
    expected: str,
) -> None:
    gateway = FakeAkShareGateway()
    gateway.daily_rows = [
        {
            "日期": "2026-07-28",
            "股票代码": "430047",
            "开盘": 12.1,
            "最高": 12.5,
            "最低": 12.0,
            "收盘": 12.4,
            "成交量": 1234,
            "成交额": 1_530_000,
        }
    ]

    batch = _provider(gateway).fetch_daily_bars(
        ("bj.430047",),
        date(2026, 7, 28),
        date(2026, 7, 28),
        adjustment,
    )

    assert gateway.daily_calls[0] == {
        "symbol": "430047",
        "start_date": "20260728",
        "end_date": "20260728",
        "adjust": expected,
    }
    bar = batch.records[0]
    assert bar.symbol == "bj.430047"
    assert bar.volume == 123_400
    assert bar.amount == 1_530_000
    assert batch.request["upstream_version"] == "1.18.81"
    assert len(batch.content_hash) == 64


def test_upstream_failure_becomes_sanitized_retryable_error() -> None:
    gateway = FakeAkShareGateway()
    gateway.failure = RuntimeError(
        "request https://user:secret@example.test failed token=hidden"
    )

    with pytest.raises(ProviderError) as error:
        _provider(gateway).fetch_calendar(date(2026, 7, 28), date(2026, 7, 29))

    assert error.value.error_code == "upstream_query_failed"
    assert error.value.retryable is True
    assert "secret" not in str(error.value)
    assert "hidden" not in str(error.value)


def test_healthcheck_reports_failure_without_exception_details() -> None:
    gateway = FakeAkShareGateway()
    gateway.failure = RuntimeError("private upstream failure")

    health = _provider(gateway).healthcheck()

    assert health.ok is False
    assert health.checked_at == FIXED_NOW
    assert health.message == "AkShare 上游不可用"
