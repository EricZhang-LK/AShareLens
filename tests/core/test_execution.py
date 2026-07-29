from datetime import date

import pytest

from asharelens.core.execution import (
    OpeningExecutionModel,
    Order,
    OrderRejected,
    Side,
)
from asharelens.core.models import DailyBar


def make_bar(*, trade_date: date = date(2026, 1, 6)) -> DailyBar:
    return DailyBar(
        symbol="demo.000001",
        trade_date=trade_date,
        open=10,
        high=10.2,
        low=9.8,
        close=10.1,
        volume=1_000_000,
        amount=10_000_000,
    )


def test_buy_fills_at_adverse_slipped_next_open_and_board_lot() -> None:
    model = OpeningExecutionModel(
        slippage_bps=10,
        commission_rate=0,
        minimum_commission=0,
        transfer_fee_rate=0,
        stamp_duty_rate=0,
    )

    fill = model.execute(
        Order("demo.000001", Side.BUY, 1234, date(2026, 1, 5)),
        make_bar(),
    )

    assert fill.quantity == 1200
    assert fill.price == 10.01
    assert fill.trade_date == date(2026, 1, 6)
    assert fill.cash_delta == -12_012


def test_sell_applies_adverse_slippage_and_sell_side_fees() -> None:
    model = OpeningExecutionModel(
        slippage_bps=10,
        commission_rate=0.001,
        minimum_commission=5,
        transfer_fee_rate=0,
        stamp_duty_rate=0.0005,
    )

    fill = model.execute(
        Order("demo.000001", Side.SELL, 1000, date(2026, 1, 5)),
        make_bar(),
    )

    assert fill.price == 9.99
    assert fill.quantity == 1000
    assert fill.commission == 9.99
    assert fill.stamp_duty == 5.0
    assert fill.cash_delta == 9_975.01


def test_execution_rejects_same_day_fill() -> None:
    model = OpeningExecutionModel()

    with pytest.raises(OrderRejected) as error:
        model.execute(
            Order("demo.000001", Side.BUY, 100, date(2026, 1, 6)),
            make_bar(),
        )

    assert error.value.reason_code == "not_next_session"


def test_execution_rejects_missing_market_bar() -> None:
    model = OpeningExecutionModel()

    with pytest.raises(OrderRejected) as error:
        model.execute(
            Order("demo.000001", Side.BUY, 100, date(2026, 1, 5)),
            None,
        )

    assert error.value.reason_code == "missing_bar"


def test_execution_rejects_non_trading_session() -> None:
    model = OpeningExecutionModel()
    suspended = make_bar().model_copy(update={"is_trading": False})

    with pytest.raises(OrderRejected) as error:
        model.execute(
            Order("demo.000001", Side.BUY, 100, date(2026, 1, 5)),
            suspended,
        )

    assert error.value.reason_code == "not_trading"


def test_order_rejects_non_positive_quantity() -> None:
    with pytest.raises(ValueError, match="quantity must be positive"):
        Order("demo.000001", Side.BUY, 0, date(2026, 1, 5))
