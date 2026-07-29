"""Classic moving-average trend strategy with structured explanations."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from asharelens.core.models import (
    SelectionCandidate,
    SelectionReason,
    StrategyContext,
)
from asharelens.core.strategy import StrategyMetadata


class MovingAverageParams(BaseModel):
    """Parameters exposed to both Python callers and generated Web forms."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fast_period: int = Field(default=20, ge=2, le=250, title="短期均线")
    slow_period: int = Field(default=60, ge=5, le=500, title="长期均线")
    confirm_days: int = Field(default=3, ge=1, le=20, title="确认天数")

    @model_validator(mode="after")
    def validate_period_order(self) -> MovingAverageParams:
        if self.fast_period >= self.slow_period:
            raise ValueError("fast_period must be less than slow_period")
        return self


class MovingAverageStrategy:
    """Select symbols whose fast average remains above the slow average."""

    metadata = StrategyMetadata(
        strategy_id="moving_average",
        name="均线趋势",
        version="1.0.0",
        description="短期均线持续高于长期均线时入选。",
        plugin_api_version="1.0",
        min_history_sessions=60,
    )

    def parameter_model(self) -> type[BaseModel]:
        return MovingAverageParams

    def generate(
        self,
        context: StrategyContext,
        params: MovingAverageParams,
    ) -> tuple[SelectionCandidate, ...]:
        unranked: list[SelectionCandidate] = []
        required_sessions = params.slow_period + params.confirm_days - 1

        for symbol, observations in sorted(context.bars.items()):
            closes = [bar.close for bar in observations]
            if len(closes) < required_sessions:
                unranked.append(
                    SelectionCandidate(
                        symbol=symbol,
                        signal_date=context.signal_date,
                        selected=False,
                        reasons=(
                            SelectionReason(
                                code="insufficient_history",
                                message=(
                                    f"需要至少 {required_sessions} 个交易日，"
                                    f"当前只有 {len(closes)} 个。"
                                ),
                            ),
                        ),
                        metrics={"history_sessions": float(len(closes))},
                    )
                )
                continue

            confirmation: list[bool] = []
            latest_fast = 0.0
            latest_slow = 0.0
            for lag in range(params.confirm_days):
                end = len(closes) - lag
                fast = sum(closes[end - params.fast_period : end]) / params.fast_period
                slow = sum(closes[end - params.slow_period : end]) / params.slow_period
                if lag == 0:
                    latest_fast = fast
                    latest_slow = slow
                confirmation.append(fast > slow)

            selected = all(confirmation)
            relative_strength = latest_fast / latest_slow - 1
            score = max(0.0, min(1.0, 0.5 + relative_strength * 10))
            reason = SelectionReason(
                code="ma_trend_confirmed" if selected else "ma_trend_not_confirmed",
                message=(
                    f"短期均线已连续 {params.confirm_days} 日高于长期均线。"
                    if selected
                    else f"短期均线未连续 {params.confirm_days} 日高于长期均线。"
                ),
            )
            unranked.append(
                SelectionCandidate(
                    symbol=symbol,
                    signal_date=context.signal_date,
                    selected=selected,
                    score=score,
                    reasons=(reason,),
                    metrics={
                        "ma_fast": round(latest_fast, 6),
                        "ma_slow": round(latest_slow, 6),
                    },
                )
            )

        ordered = sorted(
            unranked,
            key=lambda candidate: (-int(candidate.selected), -candidate.score, candidate.symbol),
        )
        return tuple(
            candidate.model_copy(update={"rank": rank})
            for rank, candidate in enumerate(ordered, start=1)
        )
