"""Minimal explainable momentum strategy distributed as a separate package."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from asharelens.core.models import (
    SelectionCandidate,
    SelectionReason,
    StrategyContext,
)
from asharelens.core.strategy import StrategyMetadata


class ExampleMomentumParams(BaseModel):
    """Fields automatically exposed as a Web form."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lookback: int = Field(default=20, ge=2, le=250, title="回看交易日")
    minimum_return: float = Field(
        default=0.05,
        ge=-1,
        le=10,
        title="最低区间收益率",
    )


class ExampleMomentumStrategy:
    """Select symbols whose close-to-close return clears a threshold."""

    metadata = StrategyMetadata(
        strategy_id="example_momentum",
        name="示例动量插件",
        version="0.1.0",
        description="展示独立 Python 包、自动参数表单与解释型信号。",
        plugin_api_version="1.0",
        min_history_sessions=2,
    )

    def parameter_model(self) -> type[BaseModel]:
        return ExampleMomentumParams

    def generate(
        self,
        context: StrategyContext,
        params: ExampleMomentumParams,
    ) -> tuple[SelectionCandidate, ...]:
        raw: list[SelectionCandidate] = []
        for symbol, observations in sorted(context.bars.items()):
            window = observations[-params.lookback :]
            if len(window) < 2:
                raw.append(
                    SelectionCandidate(
                        symbol=symbol,
                        signal_date=context.signal_date,
                        selected=False,
                        reasons=(
                            SelectionReason(
                                code="insufficient_history",
                                message="可见历史不足两个交易日。",
                            ),
                        ),
                        data_warnings=("history_shorter_than_lookback",),
                    )
                )
                continue

            period_return = window[-1].close / window[0].close - 1
            selected = period_return >= params.minimum_return
            raw.append(
                SelectionCandidate(
                    symbol=symbol,
                    signal_date=context.signal_date,
                    selected=selected,
                    score=max(0.0, min(1.0, (period_return + 1) / 2)),
                    reasons=(
                        SelectionReason(
                            code=(
                                "momentum_threshold_passed"
                                if selected
                                else "momentum_threshold_failed"
                            ),
                            message=(
                                f"区间收益率 {period_return:.2%}，"
                                f"阈值 {params.minimum_return:.2%}。"
                            ),
                        ),
                    ),
                    metrics={"period_return": period_return},
                )
            )

        selected_candidates = sorted(
            (candidate for candidate in raw if candidate.selected),
            key=lambda candidate: (-candidate.score, candidate.symbol),
        )
        ranks = {
            candidate.symbol: rank
            for rank, candidate in enumerate(selected_candidates, 1)
        }
        return tuple(
            candidate.model_copy(update={"rank": ranks.get(candidate.symbol)})
            for candidate in raw
        )
