"""Immutable domain values shared by strategies and engines."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    """Base model that rejects unknown fields and assignment."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class DailyBar(FrozenModel):
    """One normalized daily OHLCV observation."""

    symbol: str = Field(min_length=1)
    trade_date: date
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: int = Field(ge=0)
    amount: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_price_range(self) -> DailyBar:
        if self.low > min(self.open, self.close):
            raise ValueError("low must not exceed open or close")
        if self.high < max(self.open, self.close):
            raise ValueError("high must not be below open or close")
        if self.low > self.high:
            raise ValueError("low must not exceed high")
        return self


class SelectionReason(FrozenModel):
    """A stable, machine-readable explanation item."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class SelectionCandidate(FrozenModel):
    """One strategy decision, including evidence for selection or exclusion."""

    symbol: str = Field(min_length=1)
    signal_date: date
    selected: bool
    score: float = Field(default=0.0, ge=0, le=1)
    rank: int | None = Field(default=None, ge=1)
    reasons: tuple[SelectionReason, ...] = ()
    metrics: dict[str, float] = Field(default_factory=dict)
    data_warnings: tuple[str, ...] = ()


class StrategyContext(FrozenModel):
    """Point-in-time data visible to a strategy for one close signal."""

    signal_date: date
    bars: dict[str, tuple[DailyBar, ...]]

    @model_validator(mode="after")
    def reject_future_or_mismatched_bars(self) -> StrategyContext:
        for symbol, observations in self.bars.items():
            for bar in observations:
                if bar.symbol != symbol:
                    raise ValueError(f"bar symbol {bar.symbol} does not match key {symbol}")
                if bar.trade_date > self.signal_date:
                    raise ValueError(
                        f"bar date {bar.trade_date} is later than signal_date {self.signal_date}"
                    )
        return self

