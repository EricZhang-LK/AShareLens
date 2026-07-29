from datetime import date

import pytest
from pydantic import ValidationError

from asharelens.core.models import DailyBar, SelectionCandidate, StrategyContext
from asharelens.core.strategy import StrategyMetadata


def test_daily_bar_rejects_high_below_open() -> None:
    with pytest.raises(ValidationError):
        DailyBar(
            symbol="sh.600000",
            trade_date=date(2026, 7, 1),
            open=10,
            high=9,
            low=8,
            close=9,
            volume=1000,
            amount=9000,
        )


def test_candidate_preserves_structured_explanation() -> None:
    candidate = SelectionCandidate(
        symbol="sh.600000",
        signal_date=date(2026, 7, 1),
        selected=True,
        score=0.92,
        rank=1,
        reasons=[{"code": "ma_cross", "message": "短期均线高于长期均线"}],
        metrics={"ma_fast": 10.2, "ma_slow": 9.8},
    )

    assert candidate.reasons[0].code == "ma_cross"
    assert candidate.metrics["ma_fast"] == 10.2


def test_strategy_context_rejects_future_bars() -> None:
    future_bar = DailyBar(
        symbol="sh.600000",
        trade_date=date(2026, 7, 2),
        open=10,
        high=11,
        low=9,
        close=10.5,
        volume=1000,
        amount=10_000,
    )

    with pytest.raises(ValidationError, match="later than signal_date"):
        StrategyContext(signal_date=date(2026, 7, 1), bars={"sh.600000": (future_bar,)})


def test_strategy_metadata_schema_is_machine_readable() -> None:
    schema = StrategyMetadata.model_json_schema()
    assert schema["properties"]["plugin_api_version"]["type"] == "string"
