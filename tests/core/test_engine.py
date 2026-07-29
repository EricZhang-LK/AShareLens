from datetime import date

import pytest

from asharelens.core.engine import DailyCycleEngine
from asharelens.core.execution import OpeningExecutionModel
from asharelens.demo.data import generate_demo_bars
from asharelens.strategies.moving_average import (
    MovingAverageParams,
    MovingAverageStrategy,
)


def make_engine() -> DailyCycleEngine[MovingAverageParams]:
    return DailyCycleEngine(
        strategy=MovingAverageStrategy(),
        params=MovingAverageParams(fast_period=10, slow_period=30, confirm_days=3),
        execution_model=OpeningExecutionModel(
            slippage_bps=0,
            commission_rate=0,
            minimum_commission=0,
            transfer_fee_rate=0,
            stamp_duty_rate=0,
        ),
        initial_cash=100_000,
        top_n=1,
        max_weight=1,
    )


def test_engine_runs_close_signal_to_next_open_fill_chronologically() -> None:
    bars = generate_demo_bars(date(2026, 1, 5), sessions=80)

    result = make_engine().run(bars)

    assert any(candidate.selected for candidate in result.candidates)
    assert result.fills
    assert all(fill.trade_date > fill.signal_date for fill in result.fills)
    assert all(point.cash >= 0 for point in result.nav)
    assert result.nav[-1].total_value > 0
    assert len(result.fingerprint) == 64


def test_run_and_public_process_session_use_the_same_daily_cycle() -> None:
    bars = generate_demo_bars(date(2026, 1, 5), sessions=80)
    engine = make_engine()
    complete = engine.run(bars)
    state = engine.initial_state()
    manual_fills = []
    manual_nav = []

    session_dates = sorted(
        {bar.trade_date for observations in bars.values() for bar in observations}
    )
    for session_date in session_dates:
        history = {
            symbol: tuple(bar for bar in observations if bar.trade_date <= session_date)
            for symbol, observations in bars.items()
        }
        outcome = engine.process_session(state, session_date, history)
        state = outcome.state
        manual_fills.extend(outcome.fills)
        manual_nav.append(outcome.nav)

    assert tuple(manual_fills) == complete.fills
    assert tuple(manual_nav) == complete.nav


def test_engine_rejects_empty_market_data() -> None:
    with pytest.raises(ValueError, match="market data must not be empty"):
        make_engine().run({})
