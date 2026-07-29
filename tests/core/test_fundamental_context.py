from datetime import date

import pytest
from pydantic import ValidationError

from asharelens.core.models import (
    FundamentalMetric,
    FundamentalSnapshot,
    StrategyContext,
)


def _snapshot(
    *,
    symbol: str = "sh.600000",
    period_end: date = date(2025, 12, 31),
    available_on: date = date(2026, 3, 30),
    pe_ttm: float = 8.5,
) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=symbol,
        period_end=period_end,
        available_on=available_on,
        metrics=(FundamentalMetric(name="pe_ttm", value=pe_ttm),),
    )


def test_context_rejects_fundamental_published_after_signal_date() -> None:
    with pytest.raises(ValidationError, match="later than signal_date"):
        StrategyContext(
            signal_date=date(2026, 3, 29),
            bars={},
            fundamentals={"sh.600000": (_snapshot(),)},
        )


def test_context_rejects_fundamental_symbol_mismatch() -> None:
    with pytest.raises(ValidationError, match="does not match key"):
        StrategyContext(
            signal_date=date(2026, 4, 1),
            bars={},
            fundamentals={"sz.000001": (_snapshot(),)},
        )


def test_latest_fundamental_uses_latest_visible_publication() -> None:
    older = _snapshot(
        period_end=date(2025, 9, 30),
        available_on=date(2025, 10, 30),
        pe_ttm=10,
    )
    newer = _snapshot(pe_ttm=8.5)
    context = StrategyContext(
        signal_date=date(2026, 4, 1),
        bars={},
        fundamentals={"sh.600000": (newer, older)},
    )

    latest = context.latest_fundamental("sh.600000")

    assert latest == newer
    assert latest.metric("pe_ttm") == 8.5
    assert latest.metric("missing") is None
    assert context.latest_fundamental("sz.000001") is None


def test_fundamental_metrics_are_unique_and_immutable() -> None:
    with pytest.raises(ValidationError, match="metric names must be unique"):
        FundamentalSnapshot(
            symbol="sh.600000",
            period_end=date(2025, 12, 31),
            available_on=date(2026, 3, 30),
            metrics=(
                FundamentalMetric(name="roe_ttm", value=12),
                FundamentalMetric(name="roe_ttm", value=13),
            ),
        )

    metric = FundamentalMetric(name="roe_ttm", value=12)
    with pytest.raises(ValidationError):
        metric.value = 13
