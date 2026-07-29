from datetime import date

import pytest
from pydantic import ValidationError

from asharelens.core.models import StrategyContext
from asharelens.demo.data import generate_demo_bars
from asharelens.strategies.moving_average import (
    MovingAverageParams,
    MovingAverageStrategy,
)


def test_moving_average_schema_contains_web_constraints() -> None:
    schema = MovingAverageParams.model_json_schema()

    assert schema["properties"]["fast_period"]["minimum"] == 2
    assert schema["properties"]["slow_period"]["maximum"] == 500


def test_moving_average_rejects_fast_period_not_below_slow_period() -> None:
    with pytest.raises(ValidationError, match="fast_period must be less"):
        MovingAverageParams(fast_period=60, slow_period=20)


def test_moving_average_selects_rising_symbol_with_explanation() -> None:
    bars = generate_demo_bars(date(2026, 1, 5), sessions=80)
    context = StrategyContext(
        signal_date=max(observations[-1].trade_date for observations in bars.values()),
        bars=bars,
    )

    results = MovingAverageStrategy().generate(
        context,
        MovingAverageParams(fast_period=10, slow_period=30, confirm_days=3),
    )

    rising = next(item for item in results if item.symbol == "demo.000001")
    falling = next(item for item in results if item.symbol == "demo.000002")
    assert rising.selected is True
    assert rising.reasons[0].code == "ma_trend_confirmed"
    assert rising.metrics["ma_fast"] > rising.metrics["ma_slow"]
    assert falling.selected is False


def test_moving_average_excludes_symbol_with_insufficient_history() -> None:
    bars = generate_demo_bars(date(2026, 1, 5), sessions=20)
    context = StrategyContext(
        signal_date=max(observations[-1].trade_date for observations in bars.values()),
        bars=bars,
    )

    results = MovingAverageStrategy().generate(
        context,
        MovingAverageParams(fast_period=10, slow_period=30, confirm_days=3),
    )

    assert all(item.selected is False for item in results)
    assert all(item.reasons[0].code == "insufficient_history" for item in results)
