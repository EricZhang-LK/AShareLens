"""Cross-sectional total-return momentum and RPS ranking."""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field, model_validator

from asharelens.core.models import (
    SelectionCandidate,
    SelectionReason,
    StrategyContext,
)
from asharelens.core.strategy import StrategyMetadata


class MomentumRpsParams(BaseModel):
    """Configurable observation window and cross-sectional cutoff."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lookback_sessions: int = Field(
        default=120,
        ge=5,
        le=500,
        title="动量观察交易日",
    )
    skip_recent_sessions: int = Field(
        default=5,
        ge=0,
        le=60,
        title="跳过最近交易日",
    )
    top_percentile: float = Field(
        default=0.2,
        gt=0,
        le=1,
        title="入选前百分比",
    )
    minimum_return: float = Field(
        default=0,
        ge=-1,
        le=10,
        title="最低区间收益率",
    )

    @model_validator(mode="after")
    def validate_window(self) -> MomentumRpsParams:
        if self.lookback_sessions <= self.skip_recent_sessions:
            raise ValueError("lookback_sessions must exceed skip_recent_sessions")
        return self


class MomentumRpsStrategy:
    """Rank point-in-time returns and select the strongest percentile."""

    metadata = StrategyMetadata(
        strategy_id="momentum_rps",
        name="横截面动量 / RPS",
        version="1.0.0",
        description="按可配置区间收益率进行横截面排名，选取相对强势股票。",
        min_history_sessions=121,
    )

    def parameter_model(self) -> type[BaseModel]:
        return MomentumRpsParams

    def generate(
        self,
        context: StrategyContext,
        params: MomentumRpsParams,
    ) -> tuple[SelectionCandidate, ...]:
        required = params.lookback_sessions + 1
        momentum: list[tuple[str, float]] = []
        insufficient: list[tuple[str, int]] = []
        for symbol, observations in sorted(context.bars.items()):
            ordered = sorted(observations, key=lambda bar: bar.trade_date)
            if len(ordered) < required:
                insufficient.append((symbol, len(ordered)))
                continue
            start_close = ordered[-params.lookback_sessions - 1].close
            end_index = len(ordered) - params.skip_recent_sessions - 1
            end_close = ordered[end_index].close
            momentum.append((symbol, end_close / start_close - 1))

        ranked = sorted(momentum, key=lambda item: (-item[1], item[0]))
        selected_count = (
            max(1, math.ceil(len(ranked) * params.top_percentile)) if ranked else 0
        )
        results: list[SelectionCandidate] = []
        population = len(ranked)
        for rank, (symbol, total_return) in enumerate(ranked, start=1):
            rps_score = (
                1.0
                if population == 1
                else (population - rank) / (population - 1)
            )
            rank_selected = rank <= selected_count
            selected = rank_selected and total_return >= params.minimum_return
            if selected:
                reason = SelectionReason(
                    code="momentum_rank_selected",
                    message=(
                        f"区间收益排名第 {rank}/{population}，"
                        "位于配置的强势分位。"
                    ),
                )
            elif rank_selected:
                reason = SelectionReason(
                    code="momentum_below_minimum",
                    message=(
                        f"排名进入前 {params.top_percentile:.0%}，"
                        "但区间收益低于最低门槛。"
                    ),
                )
            else:
                reason = SelectionReason(
                    code="momentum_rank_not_selected",
                    message=(
                        f"区间收益排名第 {rank}/{population}，"
                        "未进入配置的强势分位。"
                    ),
                )
            results.append(
                SelectionCandidate(
                    symbol=symbol,
                    signal_date=context.signal_date,
                    selected=selected,
                    score=rps_score,
                    rank=rank,
                    reasons=(reason,),
                    metrics={
                        "momentum_return": round(total_return, 10),
                        "rps_score": round(rps_score, 10),
                        "lookback_sessions": float(params.lookback_sessions),
                        "skip_recent_sessions": float(
                            params.skip_recent_sessions
                        ),
                    },
                )
            )

        next_rank = len(results) + 1
        for offset, (symbol, history_sessions) in enumerate(
            sorted(insufficient),
        ):
            results.append(
                SelectionCandidate(
                    symbol=symbol,
                    signal_date=context.signal_date,
                    selected=False,
                    rank=next_rank + offset,
                    reasons=(
                        SelectionReason(
                            code="insufficient_history",
                            message=(
                                f"需要至少 {required} 个交易日，"
                                f"当前只有 {history_sessions} 个。"
                            ),
                        ),
                    ),
                    metrics={"history_sessions": float(history_sessions)},
                )
            )
        return tuple(results)
