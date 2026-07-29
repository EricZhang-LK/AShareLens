from datetime import date

import pytest

from asharelens.demo.data import generate_demo_bars


def test_demo_data_is_deterministic_and_has_three_symbols() -> None:
    first = generate_demo_bars(date(2026, 1, 5), sessions=80)
    second = generate_demo_bars(date(2026, 1, 5), sessions=80)

    assert first == second
    assert tuple(first) == ("demo.000001", "demo.000002", "demo.000003")
    assert all(len(bars) == 80 for bars in first.values())


def test_demo_data_contains_distinct_market_behaviors() -> None:
    bars = generate_demo_bars(date(2026, 1, 5), sessions=80)

    assert bars["demo.000001"][-1].close > bars["demo.000001"][0].close
    assert bars["demo.000002"][-1].close < bars["demo.000002"][0].close


def test_demo_data_only_contains_weekday_sessions() -> None:
    bars = generate_demo_bars(date(2026, 1, 10), sessions=5)
    dates = [bar.trade_date for bar in bars["demo.000001"]]

    assert dates[0] == date(2026, 1, 12)
    assert all(trade_date.weekday() < 5 for trade_date in dates)


def test_demo_data_rejects_non_positive_session_count() -> None:
    with pytest.raises(ValueError, match="sessions must be positive"):
        generate_demo_bars(date(2026, 1, 5), sessions=0)
