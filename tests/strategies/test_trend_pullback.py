from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from asharelens.core.models import DailyBar, StrategyContext
from asharelens.strategies.trend_pullback import (
    TrendPullbackParams,
    TrendPullbackStrategy,
)


def _trend_bars(
    symbol: str,
    *,
    final_close: float,
    final_volume: int = 500,
    sessions: int = 80,
) -> tuple[DailyBar, ...]:
    start = date(2026, 1, 1)
    closes = [10 + index * 0.15 for index in range(sessions - 1)]
    closes.append(final_close)
    return tuple(
        DailyBar(
            symbol=symbol,
            trade_date=start + timedelta(days=index),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=final_volume if index == sessions - 1 else 1000,
            amount=close * 1000,
        )
        for index, close in enumerate(closes)
    )


def test_trend_pullback_schema_validates_pullback_band() -> None:
    schema = TrendPullbackParams.model_json_schema()

    assert schema["properties"]["trend_ma_period"]["minimum"] == 20
    assert schema["properties"]["max_volume_ratio"]["maximum"] == 2
    with pytest.raises(ValidationError, match="min_pullback_pct must be less"):
        TrendPullbackParams(min_pullback_pct=0.2, max_pullback_pct=0.1)


def test_trend_pullback_selects_rising_low_volume_pullback() -> None:
    bars = _trend_bars("sh.600001", final_close=19.3)
    context = StrategyContext(
        signal_date=bars[-1].trade_date,
        bars={"sh.600001": bars},
    )

    result = TrendPullbackStrategy().generate(
        context,
        TrendPullbackParams(
            trend_ma_period=40,
            slope_lookback=10,
            recent_high_lookback=20,
            min_pullback_pct=0.03,
            max_pullback_pct=0.12,
            volume_window=10,
            max_volume_ratio=0.8,
        ),
    )[0]

    assert result.selected is True
    assert result.reasons[0].code == "trend_pullback_confirmed"
    assert 0.03 <= result.metrics["pullback_pct"] <= 0.12
    assert result.metrics["volume_ratio"] == 0.5
    assert result.metrics["ma_current"] > result.metrics["ma_past"]


def test_trend_pullback_explains_failed_conditions() -> None:
    bars = _trend_bars(
        "sh.600001",
        final_close=14,
        final_volume=2000,
    )
    context = StrategyContext(
        signal_date=bars[-1].trade_date,
        bars={"sh.600001": bars},
    )

    result = TrendPullbackStrategy().generate(
        context,
        TrendPullbackParams(
            trend_ma_period=40,
            slope_lookback=10,
            recent_high_lookback=20,
            max_pullback_pct=0.12,
            volume_window=10,
            max_volume_ratio=0.8,
        ),
    )[0]

    reason_codes = {reason.code for reason in result.reasons}
    assert result.selected is False
    assert "pullback_too_deep" in reason_codes
    assert "volume_not_contracted" in reason_codes


def test_trend_pullback_reports_insufficient_history() -> None:
    bars = _trend_bars("sh.600001", final_close=12, sessions=30)
    context = StrategyContext(
        signal_date=bars[-1].trade_date,
        bars={"sh.600001": bars},
    )

    result = TrendPullbackStrategy().generate(
        context,
        TrendPullbackParams(trend_ma_period=40, slope_lookback=10),
    )[0]

    assert result.selected is False
    assert result.reasons[0].code == "insufficient_history"
