"""Daily opening-price execution primitives for A-share simulations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from asharelens.core.models import DailyBar


class Side(StrEnum):
    """Order direction."""

    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True, slots=True)
class Order:
    """An order emitted after a close signal."""

    symbol: str
    side: Side
    quantity: int
    signal_date: date

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol must not be empty")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")


@dataclass(frozen=True, slots=True)
class Fill:
    """A simulated fill and its explicit cost breakdown."""

    symbol: str
    side: Side
    quantity: int
    price: float
    signal_date: date
    trade_date: date
    commission: float
    transfer_fee: float
    stamp_duty: float

    @property
    def notional(self) -> float:
        return round(self.quantity * self.price, 2)

    @property
    def fees(self) -> float:
        return round(self.commission + self.transfer_fee + self.stamp_duty, 2)

    @property
    def cash_delta(self) -> float:
        direction = -1 if self.side is Side.BUY else 1
        fee_direction = -1
        return round(direction * self.notional + fee_direction * self.fees, 2)


class OrderRejected(ValueError):
    """A deterministic rejection that callers may keep pending or report."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


class OpeningExecutionModel(BaseModel):
    """Approximate a fill from the next session's official opening bar."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    slippage_bps: int = Field(default=10, ge=0, le=10_000)
    commission_rate: float = Field(default=0.0003, ge=0)
    minimum_commission: float = Field(default=5.0, ge=0)
    transfer_fee_rate: float = Field(default=0.00001, ge=0)
    stamp_duty_rate: float = Field(default=0.0005, ge=0)
    board_lot: int = Field(default=100, ge=1)
    tick_size: float = Field(default=0.01, gt=0)

    def execute(self, order: Order, bar: DailyBar | None) -> Fill:
        """Fill an order on a strictly later session or raise a typed rejection."""

        if bar is None:
            raise OrderRejected("missing_bar", "next-session market bar is missing")
        if bar.symbol != order.symbol:
            raise OrderRejected("symbol_mismatch", "order and market bar symbols differ")
        if not bar.is_trading:
            raise OrderRejected(
                "not_trading",
                "the instrument is not trading in the execution session",
            )
        if bar.trade_date <= order.signal_date:
            raise OrderRejected(
                "not_next_session",
                "fill date must be later than the close signal date",
            )

        quantity = order.quantity
        if order.side is Side.BUY:
            quantity = quantity // self.board_lot * self.board_lot
            if quantity == 0:
                raise OrderRejected("below_board_lot", "buy quantity is below one board lot")

        price = self._fill_price(order.side, bar)
        notional = Decimal(quantity) * price
        commission = (
            max(
                Decimal(str(self.minimum_commission)),
                notional * Decimal(str(self.commission_rate)),
            )
            if self.commission_rate > 0
            else Decimal(0)
        )
        transfer_fee = notional * Decimal(str(self.transfer_fee_rate))
        stamp_duty = (
            notional * Decimal(str(self.stamp_duty_rate))
            if order.side is Side.SELL
            else Decimal(0)
        )

        return Fill(
            symbol=order.symbol,
            side=order.side,
            quantity=quantity,
            price=float(price),
            signal_date=order.signal_date,
            trade_date=bar.trade_date,
            commission=_round_money(commission),
            transfer_fee=_round_money(transfer_fee),
            stamp_duty=_round_money(stamp_duty),
        )

    def _fill_price(self, side: Side, bar: DailyBar) -> Decimal:
        open_price = Decimal(str(bar.open))
        slippage = Decimal(self.slippage_bps) / Decimal(10_000)
        raw_price = open_price * (Decimal(1) + slippage)
        rounding = ROUND_CEILING
        if side is Side.SELL:
            raw_price = open_price * (Decimal(1) - slippage)
            rounding = ROUND_FLOOR

        tick = Decimal(str(self.tick_size))
        rounded_ticks = (raw_price / tick).to_integral_value(rounding=rounding)
        slipped_price = rounded_ticks * tick
        low = Decimal(str(bar.low))
        high = Decimal(str(bar.high))
        return min(max(slipped_price, low), high)


def _round_money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
