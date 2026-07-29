from datetime import date

import pytest
from pydantic import ValidationError

from asharelens.core.models import (
    FundamentalMetric,
    FundamentalSnapshot,
    StrategyContext,
)
from asharelens.strategies.value_quality import (
    ValueQualityParams,
    ValueQualityStrategy,
)


def _fundamental(
    symbol: str,
    **overrides: float,
) -> FundamentalSnapshot:
    values = {
        "pe_ttm": 8,
        "pb": 1.2,
        "roe_ttm": 18,
        "revenue_growth_yoy": 15,
        "net_profit_growth_yoy": 20,
        "debt_to_assets": 40,
    }
    values.update(overrides)
    return FundamentalSnapshot(
        symbol=symbol,
        period_end=date(2025, 12, 31),
        available_on=date(2026, 3, 30),
        metrics=tuple(
            FundamentalMetric(name=name, value=value)
            for name, value in values.items()
        ),
    )


def test_value_quality_schema_exposes_thresholds() -> None:
    schema = ValueQualityParams.model_json_schema()

    assert schema["properties"]["max_pe_ttm"]["exclusiveMinimum"] == 0
    assert schema["properties"]["min_roe_ttm"]["title"] == "最低 ROE(TTM)%"
    with pytest.raises(ValidationError):
        ValueQualityParams(max_pe_ttm=0)


def test_value_quality_selects_complete_passing_snapshot_with_explanation() -> None:
    context = StrategyContext(
        signal_date=date(2026, 4, 1),
        bars={},
        fundamentals={
            "sh.600000": (_fundamental("sh.600000"),),
            "sz.000001": (_fundamental("sz.000001", pe_ttm=50),),
        },
    )

    results = ValueQualityStrategy().generate(context, ValueQualityParams())

    passing = next(result for result in results if result.symbol == "sh.600000")
    expensive = next(result for result in results if result.symbol == "sz.000001")
    assert passing.selected is True
    assert passing.reasons[0].code == "value_quality_passed"
    assert passing.metrics["pe_ttm"] == 8
    assert expensive.selected is False
    assert "pe_above_max" in {reason.code for reason in expensive.reasons}
    assert passing.rank == 1
    assert passing.score > expensive.score


def test_value_quality_reports_missing_metrics_and_snapshot() -> None:
    incomplete = FundamentalSnapshot(
        symbol="sh.600001",
        period_end=date(2025, 12, 31),
        available_on=date(2026, 3, 30),
        metrics=(FundamentalMetric(name="pe_ttm", value=8),),
    )
    context = StrategyContext(
        signal_date=date(2026, 4, 1),
        bars={"sh.600002": ()},
        fundamentals={"sh.600001": (incomplete,)},
    )

    results = ValueQualityStrategy().generate(context, ValueQualityParams())

    incomplete_result = next(
        result for result in results if result.symbol == "sh.600001"
    )
    missing_result = next(
        result for result in results if result.symbol == "sh.600002"
    )
    assert incomplete_result.reasons[0].code == "missing_fundamental_metrics"
    assert "roe_ttm" in incomplete_result.data_warnings
    assert missing_result.reasons[0].code == "missing_fundamentals"


def test_value_quality_rejects_stale_snapshot_and_ranks_ties_by_symbol() -> None:
    older = FundamentalSnapshot(
        symbol="sh.600003",
        period_end=date(2023, 12, 31),
        available_on=date(2024, 3, 30),
        metrics=_fundamental("sh.600003").metrics,
    )
    equal_a = _fundamental("sh.600001")
    equal_b = _fundamental("sh.600002")
    context = StrategyContext(
        signal_date=date(2026, 4, 1),
        bars={},
        fundamentals={
            "sh.600002": (equal_b,),
            "sh.600001": (equal_a,),
            "sh.600003": (older,),
        },
    )

    results = ValueQualityStrategy().generate(
        context,
        ValueQualityParams(max_snapshot_age_days=550),
    )

    assert [result.symbol for result in results[:2]] == [
        "sh.600001",
        "sh.600002",
    ]
    stale = next(result for result in results if result.symbol == "sh.600003")
    assert stale.selected is False
    assert "fundamentals_stale" in {reason.code for reason in stale.reasons}
