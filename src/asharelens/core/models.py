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
    is_trading: bool = True
    is_st: bool = False

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


class FundamentalMetric(FrozenModel):
    """One immutable, named point-in-time fundamental value."""

    name: str = Field(min_length=1)
    value: float


class FundamentalSnapshot(FrozenModel):
    """Financial and valuation values visible from one publication date."""

    symbol: str = Field(min_length=1)
    period_end: date
    available_on: date
    metrics: tuple[FundamentalMetric, ...]

    @model_validator(mode="after")
    def validate_snapshot(self) -> FundamentalSnapshot:
        if self.available_on < self.period_end:
            raise ValueError("available_on must not precede period_end")
        names = [metric.name for metric in self.metrics]
        if len(names) != len(set(names)):
            raise ValueError("metric names must be unique")
        return self

    def metric(self, name: str) -> float | None:
        """Return one metric without exposing mutable state."""

        return next(
            (metric.value for metric in self.metrics if metric.name == name),
            None,
        )


class StrategyContext(FrozenModel):
    """Point-in-time data visible to a strategy for one close signal."""

    signal_date: date
    bars: dict[str, tuple[DailyBar, ...]]
    fundamentals: dict[str, tuple[FundamentalSnapshot, ...]] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def reject_future_or_mismatched_data(self) -> StrategyContext:
        for symbol, observations in self.bars.items():
            for bar in observations:
                if bar.symbol != symbol:
                    raise ValueError(f"bar symbol {bar.symbol} does not match key {symbol}")
                if bar.trade_date > self.signal_date:
                    raise ValueError(
                        f"bar date {bar.trade_date} is later than signal_date {self.signal_date}"
                    )
        for symbol, snapshots in self.fundamentals.items():
            for snapshot in snapshots:
                if snapshot.symbol != symbol:
                    raise ValueError(
                        f"fundamental symbol {snapshot.symbol} does not match key {symbol}"
                    )
                if snapshot.available_on > self.signal_date:
                    raise ValueError(
                        f"fundamental available_on {snapshot.available_on} "
                        f"is later than signal_date {self.signal_date}"
                    )
        return self

    def latest_fundamental(self, symbol: str) -> FundamentalSnapshot | None:
        """Return the latest publication visible in this context."""

        snapshots = self.fundamentals.get(symbol, ())
        if not snapshots:
            return None
        return max(
            snapshots,
            key=lambda snapshot: (snapshot.available_on, snapshot.period_end),
        )
