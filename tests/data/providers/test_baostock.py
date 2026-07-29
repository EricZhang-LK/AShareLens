from datetime import UTC, date, datetime

import pytest

from asharelens.data.models import Adjustment, Dataset
from asharelens.data.provider import ProviderError
from asharelens.data.providers.baostock import BaoStockProvider


class FakeResultSet:
    def __init__(
        self,
        fields: list[str],
        rows: list[list[str]],
        *,
        error_code: str = "0",
        error_msg: str = "success",
    ) -> None:
        self.fields = fields
        self.rows = rows
        self.error_code = error_code
        self.error_msg = error_msg
        self.index = 0

    def next(self) -> bool:
        return self.index < len(self.rows)

    def get_row_data(self) -> list[str]:
        row = self.rows[self.index]
        self.index += 1
        return row


class FakeGateway:
    def __init__(self) -> None:
        self.login_result = FakeResultSet([], [])
        self.stock_result = FakeResultSet([], [])
        self.calendar_result = FakeResultSet([], [])
        self.history_result = FakeResultSet([], [])
        self.logout_calls = 0
        self.history_calls: list[dict[str, str]] = []

    def login(self) -> FakeResultSet:
        return self.login_result

    def logout(self) -> FakeResultSet:
        self.logout_calls += 1
        return FakeResultSet([], [])

    def query_all_stock(self, day: str) -> FakeResultSet:
        return self.stock_result

    def query_trade_dates(self, start_date: str, end_date: str) -> FakeResultSet:
        return self.calendar_result

    def query_history_k_data_plus(
        self,
        code: str,
        fields: str,
        *,
        start_date: str,
        end_date: str,
        frequency: str,
        adjustflag: str,
    ) -> FakeResultSet:
        self.history_calls.append(
            {
                "code": code,
                "fields": fields,
                "start_date": start_date,
                "end_date": end_date,
                "frequency": frequency,
                "adjustflag": adjustflag,
            }
        )
        return self.history_result


FIXED_NOW = datetime(2026, 7, 29, 10, tzinfo=UTC)


def make_provider(gateway: FakeGateway) -> BaoStockProvider:
    return BaoStockProvider(gateway=gateway, clock=lambda: FIXED_NOW)


def test_login_failure_becomes_stable_provider_error() -> None:
    gateway = FakeGateway()
    gateway.login_result = FakeResultSet(
        [],
        [],
        error_code="10001001",
        error_msg="login failed",
    )

    with pytest.raises(ProviderError) as error:
        make_provider(gateway).fetch_calendar(date(2026, 7, 1), date(2026, 7, 2))

    assert error.value.error_code == "authentication_failed"
    assert error.value.provider_id == "baostock"
    assert error.value.retryable is True
    assert gateway.logout_calls == 0


def test_daily_rows_map_to_normalized_bars_and_skip_non_trading_rows() -> None:
    gateway = FakeGateway()
    gateway.history_result = FakeResultSet(
        [
            "date",
            "code",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "tradestatus",
            "isST",
        ],
        [
            [
                "2026-07-27",
                "sh.600000",
                "9.0000",
                "9.1300",
                "8.9600",
                "9.0500",
                "55723092",
                "504617086.9800",
                "1",
                "1",
            ],
            ["2026-07-28", "sh.600000", "", "", "", "", "", "", "0", "1"],
        ],
    )

    batch = make_provider(gateway).fetch_daily_bars(
        ("sh.600000",),
        date(2026, 7, 27),
        date(2026, 7, 28),
        Adjustment.NONE,
    )

    assert batch.dataset is Dataset.DAILY_BARS
    assert batch.provider_id == "baostock"
    assert batch.fetched_at == FIXED_NOW
    assert len(batch.content_hash) == 64
    assert len(batch.records) == 1
    assert batch.records[0].close == 9.05
    assert batch.records[0].volume == 55_723_092
    assert batch.records[0].is_trading is True
    assert batch.records[0].is_st is True
    assert gateway.logout_calls == 1


@pytest.mark.parametrize(
    ("adjustment", "adjustflag"),
    [
        (Adjustment.NONE, "3"),
        (Adjustment.FORWARD, "2"),
        (Adjustment.BACKWARD, "1"),
    ],
)
def test_adjustment_maps_to_baostock_flag(
    adjustment: Adjustment,
    adjustflag: str,
) -> None:
    gateway = FakeGateway()
    gateway.history_result = FakeResultSet(
        [
            "date",
            "code",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "tradestatus",
            "isST",
        ],
        [],
    )

    make_provider(gateway).fetch_daily_bars(
        ("sh.600000",),
        date(2026, 7, 27),
        date(2026, 7, 28),
        adjustment,
    )

    assert gateway.history_calls[0]["adjustflag"] == adjustflag


def test_query_failure_is_converted_and_logout_still_runs() -> None:
    gateway = FakeGateway()
    gateway.history_result = FakeResultSet(
        [],
        [],
        error_code="10002007",
        error_msg="network error",
    )

    with pytest.raises(ProviderError) as error:
        make_provider(gateway).fetch_daily_bars(
            ("sh.600000",),
            date(2026, 7, 27),
            date(2026, 7, 28),
            Adjustment.NONE,
        )

    assert error.value.error_code == "upstream_query_failed"
    assert gateway.logout_calls == 1


def test_instrument_query_filters_non_a_share_codes() -> None:
    gateway = FakeGateway()
    gateway.stock_result = FakeResultSet(
        ["code", "tradeStatus", "code_name"],
        [
            ["sh.000001", "1", "上证综合指数"],
            ["sh.600000", "1", "浦发银行"],
            ["sz.000001", "0", "平安银行"],
            ["sh.510300", "1", "沪深300ETF"],
        ],
    )

    batch = make_provider(gateway).fetch_instruments(date(2026, 7, 28))

    assert [instrument.symbol for instrument in batch.records] == [
        "sh.600000",
        "sz.000001",
    ]
    assert batch.records[0].is_active is True
    assert batch.records[1].is_active is False
    assert gateway.logout_calls == 1


def test_calendar_query_maps_open_and_closed_days() -> None:
    gateway = FakeGateway()
    gateway.calendar_result = FakeResultSet(
        ["calendar_date", "is_trading_day"],
        [["2026-07-27", "1"], ["2026-07-28", "0"]],
    )

    batch = make_provider(gateway).fetch_calendar(
        date(2026, 7, 27),
        date(2026, 7, 28),
    )

    assert [session.is_open for session in batch.records] == [True, False]
    assert gateway.logout_calls == 1
