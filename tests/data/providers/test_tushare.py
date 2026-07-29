from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest

from asharelens.data.models import Adjustment, Dataset
from asharelens.data.provider import ProviderError
from asharelens.data.providers.tushare import TushareProvider, TushareSdkGateway

FIXED_NOW = datetime(2026, 7, 29, 10, tzinfo=UTC)


class FakeTushareGateway:
    version = "1.4.24"

    def __init__(self) -> None:
        self.stock_rows: dict[str, list[dict[str, object]]] = {}
        self.calendar_rows: list[dict[str, object]] = []
        self.date_rows: list[dict[str, object]] = []
        self.symbol_rows: dict[str, list[dict[str, object]]] = {}
        self.stock_calls: list[str] = []
        self.date_calls: list[str] = []
        self.symbol_calls: list[dict[str, str]] = []
        self.failure: Exception | None = None

    def fetch_stock_basic(self, list_status: str) -> list[dict[str, object]]:
        self._raise_failure()
        self.stock_calls.append(list_status)
        return self.stock_rows.get(list_status, [])

    def fetch_calendar(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, object]]:
        self._raise_failure()
        return self.calendar_rows

    def fetch_daily_by_date(self, trade_date: str) -> list[dict[str, object]]:
        self._raise_failure()
        self.date_calls.append(trade_date)
        return self.date_rows

    def fetch_daily_by_symbol(
        self,
        *,
        ts_code: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, object]]:
        self._raise_failure()
        self.symbol_calls.append(
            {
                "ts_code": ts_code,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        return self.symbol_rows.get(ts_code, [])

    def _raise_failure(self) -> None:
        if self.failure is not None:
            raise self.failure


def _provider(gateway: FakeTushareGateway) -> TushareProvider:
    return TushareProvider(gateway=gateway, clock=lambda: FIXED_NOW)


def test_missing_optional_sdk_has_actionable_error() -> None:
    with (
        patch(
            "asharelens.data.providers.tushare.importlib.import_module",
            side_effect=ModuleNotFoundError,
        ),
        pytest.raises(ProviderError) as error,
    ):
        TushareSdkGateway("not-a-real-token")

    assert error.value.error_code == "dependency_missing"
    assert "not-a-real-token" not in str(error.value)
    assert "asharelens[tushare]" in str(error.value)


def test_missing_token_is_actionable_and_never_echoes_secret(
    monkeypatch,
) -> None:
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

    with pytest.raises(ProviderError) as error:
        TushareProvider(clock=lambda: FIXED_NOW).fetch_calendar(
            date(2026, 7, 28),
            date(2026, 7, 29),
        )

    assert error.value.error_code == "configuration_missing"
    assert error.value.retryable is False
    assert "TUSHARE_TOKEN" in str(error.value)


def test_instruments_reconstruct_point_in_time_listing_universe() -> None:
    gateway = FakeTushareGateway()
    gateway.stock_rows = {
        "L": [
            {
                "ts_code": "600000.SH",
                "name": "浦发银行",
                "list_date": "19991110",
                "delist_date": None,
            },
            {
                "ts_code": "430047.BJ",
                "name": "诺思兰德",
                "list_date": "20201124",
                "delist_date": None,
            },
        ],
        "D": [
            {
                "ts_code": "000001.SZ",
                "name": "历史样本",
                "list_date": "19910403",
                "delist_date": "20200102",
            }
        ],
    }

    batch = _provider(gateway).fetch_instruments(date(2019, 12, 31))

    assert gateway.stock_calls == ["L", "D", "P", "G"]
    assert [instrument.symbol for instrument in batch.records] == [
        "sh.600000",
        "sz.000001",
    ]
    assert all(instrument.is_active for instrument in batch.records)
    assert batch.records[1].delisted_on == date(2020, 1, 2)


def test_calendar_maps_all_open_and_closed_dates() -> None:
    gateway = FakeTushareGateway()
    gateway.calendar_rows = [
        {"cal_date": "20260727", "is_open": "1"},
        {"cal_date": "20260728", "is_open": "0"},
    ]

    batch = _provider(gateway).fetch_calendar(
        date(2026, 7, 27),
        date(2026, 7, 28),
    )

    assert batch.dataset is Dataset.TRADING_CALENDAR
    assert [session.is_open for session in batch.records] == [True, False]


def test_single_day_uses_one_market_query_and_normalizes_units() -> None:
    gateway = FakeTushareGateway()
    gateway.date_rows = [
        {
            "ts_code": "600000.SH",
            "trade_date": "20260728",
            "open": 9.0,
            "high": 9.2,
            "low": 8.9,
            "close": 9.1,
            "vol": 1234.5,
            "amount": 11_230.5,
        },
        {
            "ts_code": "000001.SZ",
            "trade_date": "20260728",
            "open": 10.0,
            "high": 10.2,
            "low": 9.9,
            "close": 10.1,
            "vol": 2000,
            "amount": 20_100,
        },
    ]

    batch = _provider(gateway).fetch_daily_bars(
        ("sh.600000",),
        date(2026, 7, 28),
        date(2026, 7, 28),
        Adjustment.NONE,
    )

    assert gateway.date_calls == ["20260728"]
    assert gateway.symbol_calls == []
    assert len(batch.records) == 1
    assert batch.records[0].volume == 123_450
    assert batch.records[0].amount == 11_230_500
    assert batch.request["volume_unit"] == "shares"
    assert batch.request["amount_unit"] == "CNY"


def test_date_range_queries_each_symbol_for_complete_history() -> None:
    gateway = FakeTushareGateway()
    gateway.symbol_rows = {
        "600000.SH": [
            {
                "ts_code": "600000.SH",
                "trade_date": "20260727",
                "open": 9,
                "high": 9.1,
                "low": 8.9,
                "close": 9,
                "vol": 100,
                "amount": 900,
            }
        ],
        "000001.SZ": [],
    }

    batch = _provider(gateway).fetch_daily_bars(
        ("sh.600000", "sz.000001"),
        date(2026, 7, 27),
        date(2026, 7, 28),
        Adjustment.NONE,
    )

    assert gateway.date_calls == []
    assert gateway.symbol_calls == [
        {
            "ts_code": "600000.SH",
            "start_date": "20260727",
            "end_date": "20260728",
        },
        {
            "ts_code": "000001.SZ",
            "start_date": "20260727",
            "end_date": "20260728",
        },
    ]
    assert len(batch.records) == 1


def test_adjusted_request_is_rejected_without_silent_semantic_change() -> None:
    gateway = FakeTushareGateway()

    with pytest.raises(ProviderError) as error:
        _provider(gateway).fetch_daily_bars(
            ("sh.600000",),
            date(2026, 7, 28),
            date(2026, 7, 28),
            Adjustment.FORWARD,
        )

    assert error.value.error_code == "adjustment_unsupported"
    assert gateway.date_calls == []


def test_upstream_error_does_not_leak_token_or_url_password() -> None:
    gateway = FakeTushareGateway()
    gateway.failure = RuntimeError(
        "token=user-token mysql://user:database-password@host/db"
    )

    with pytest.raises(ProviderError) as error:
        _provider(gateway).fetch_calendar(date(2026, 7, 28), date(2026, 7, 29))

    assert error.value.error_code == "upstream_query_failed"
    assert "user-token" not in str(error.value)
    assert "database-password" not in str(error.value)
