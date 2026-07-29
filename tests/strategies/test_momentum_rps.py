from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from asharelens.core.models import DailyBar, StrategyContext
from asharelens.strategies.momentum_rps import (
    MomentumRpsParams,
    MomentumRpsStrategy,
)


def _bars(symbol: str, closes: list[float]) -> tuple[DailyBar, ...]:
    start = date(2026, 1, 1)
    return tuple(
        DailyBar(
            symbol=symbol,
            trade_date=start + timedelta(days=index),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1000,
            amount=close * 1000,
        )
        for index, close in enumerate(closes)
    )


def test_momentum_schema_and_window_validation() -> None:
    schema = MomentumRpsParams.model_json_schema()

    assert schema["properties"]["lookback_sessions"]["minimum"] == 5
    assert schema["properties"]["top_percentile"]["exclusiveMinimum"] == 0
    with pytest.raises(ValidationError, match="lookback_sessions must exceed"):
        MomentumRpsParams(lookback_sessions=10, skip_recent_sessions=10)


def test_momentum_ranks_cross_section_and_selects_top_percentile() -> None:
    context = StrategyContext(
        signal_date=date(2026, 1, 12),
        bars={
            "sh.600001": _bars("sh.600001", [10 + index for index in range(12)]),
            "sh.600002": _bars("sh.600002", [10 + index * 0.5 for index in range(12)]),
            "sh.600003": _bars("sh.600003", [10 - index * 0.1 for index in range(12)]),
        },
    )

    results = MomentumRpsStrategy().generate(
        context,
        MomentumRpsParams(
            lookback_sessions=10,
            skip_recent_sessions=1,
            top_percentile=0.25,
            minimum_return=0,
        ),
    )

    assert [candidate.symbol for candidate in results] == [
        "sh.600001",
        "sh.600002",
        "sh.600003",
    ]
    assert [candidate.rank for candidate in results] == [1, 2, 3]
    assert [candidate.selected for candidate in results] == [True, False, False]
    assert results[0].reasons[0].code == "momentum_rank_selected"
    assert results[0].metrics["momentum_return"] > results[1].metrics["momentum_return"]
    assert results[0].score == 1
    assert results[-1].score == 0


def test_momentum_ties_are_broken_by_symbol() -> None:
    equal = [10 + index for index in range(12)]
    context = StrategyContext(
        signal_date=date(2026, 1, 12),
        bars={
            "sh.600002": _bars("sh.600002", equal),
            "sh.600001": _bars("sh.600001", equal),
        },
    )

    results = MomentumRpsStrategy().generate(
        context,
        MomentumRpsParams(
            lookback_sessions=10,
            skip_recent_sessions=1,
            top_percentile=0.5,
        ),
    )

    assert [candidate.symbol for candidate in results] == [
        "sh.600001",
        "sh.600002",
    ]
    assert results[0].selected is True
    assert results[1].selected is False


def test_momentum_reports_insufficient_history() -> None:
    context = StrategyContext(
        signal_date=date(2026, 1, 5),
        bars={"sh.600001": _bars("sh.600001", [10, 11, 12, 13, 14])},
    )

    result = MomentumRpsStrategy().generate(
        context,
        MomentumRpsParams(lookback_sessions=10, skip_recent_sessions=1),
    )[0]

    assert result.selected is False
    assert result.rank == 1
    assert result.reasons[0].code == "insufficient_history"
    assert result.metrics["history_sessions"] == 5
