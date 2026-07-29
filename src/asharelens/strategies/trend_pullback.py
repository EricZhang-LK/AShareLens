"""Rising-trend pullback strategy with volume-contraction confirmation."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from asharelens.core.models import (
    SelectionCandidate,
    SelectionReason,
    StrategyContext,
)
from asharelens.core.strategy import StrategyMetadata


class TrendPullbackParams(BaseModel):
    """Trend, pullback and volume thresholds exposed to Web forms."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trend_ma_period: int = Field(
        default=60,
        ge=20,
        le=250,
        title="趋势均线周期",
    )
    slope_lookback: int = Field(
        default=10,
        ge=1,
        le=60,
        title="均线上升比较周期",
    )
    recent_high_lookback: int = Field(
        default=20,
        ge=5,
        le=250,
        title="近期高点窗口",
    )
    min_pullback_pct: float = Field(
        default=0.03,
        ge=0,
        lt=1,
        title="最小回撤比例",
    )
    max_pullback_pct: float = Field(
        default=0.12,
        gt=0,
        lt=1,
        title="最大回撤比例",
    )
    volume_window: int = Field(
        default=10,
        ge=2,
        le=120,
        title="成交量比较窗口",
    )
    max_volume_ratio: float = Field(
        default=0.8,
        gt=0,
        le=2,
        title="最大缩量比例",
    )

    @model_validator(mode="after")
    def validate_pullback_band(self) -> TrendPullbackParams:
        if self.min_pullback_pct >= self.max_pullback_pct:
            raise ValueError("min_pullback_pct must be less than max_pullback_pct")
        return self


class TrendPullbackStrategy:
    """Select controlled low-volume pullbacks inside a rising trend."""

    metadata = StrategyMetadata(
        strategy_id="trend_pullback",
        name="上升趋势回调",
        version="1.0.0",
        description="长期均线上升时筛选从近期高点适度缩量回撤的股票。",
        min_history_sessions=70,
    )

    def parameter_model(self) -> type[BaseModel]:
        return TrendPullbackParams

    def generate(
        self,
        context: StrategyContext,
        params: TrendPullbackParams,
    ) -> tuple[SelectionCandidate, ...]:
        required = max(
            params.trend_ma_period + params.slope_lookback,
            params.recent_high_lookback,
            params.volume_window + 1,
        )
        candidates: list[SelectionCandidate] = []
        for symbol, observations in sorted(context.bars.items()):
            ordered = sorted(observations, key=lambda bar: bar.trade_date)
            if len(ordered) < required:
                candidates.append(
                    SelectionCandidate(
                        symbol=symbol,
                        signal_date=context.signal_date,
                        selected=False,
                        reasons=(
                            SelectionReason(
                                code="insufficient_history",
                                message=(
                                    f"需要至少 {required} 个交易日，"
                                    f"当前只有 {len(ordered)} 个。"
                                ),
                            ),
                        ),
                        metrics={"history_sessions": float(len(ordered))},
                    )
                )
                continue

            closes = [bar.close for bar in ordered]
            volumes = [bar.volume for bar in ordered]
            current_ma = _mean(closes[-params.trend_ma_period :])
            past_ma = _mean(
                closes[
                    -params.trend_ma_period
                    - params.slope_lookback : -params.slope_lookback
                ]
            )
            current_close = closes[-1]
            recent_high = max(closes[-params.recent_high_lookback :])
            pullback = 1 - current_close / recent_high
            previous_volume = _mean(
                [float(value) for value in volumes[-params.volume_window - 1 : -1]]
            )
            volume_ratio = volumes[-1] / previous_volume if previous_volume else 2.0

            reasons: list[SelectionReason] = []
            if current_ma <= past_ma:
                reasons.append(
                    SelectionReason(
                        code="trend_ma_not_rising",
                        message="长期均线相对比较期没有上升。",
                    )
                )
            if current_close <= current_ma:
                reasons.append(
                    SelectionReason(
                        code="close_below_trend_ma",
                        message="收盘价未站在趋势均线上方。",
                    )
                )
            if pullback < params.min_pullback_pct:
                reasons.append(
                    SelectionReason(
                        code="pullback_too_shallow",
                        message="相对近期高点的回撤小于配置下限。",
                    )
                )
            if pullback > params.max_pullback_pct:
                reasons.append(
                    SelectionReason(
                        code="pullback_too_deep",
                        message="相对近期高点的回撤超过配置上限。",
                    )
                )
            if volume_ratio > params.max_volume_ratio:
                reasons.append(
                    SelectionReason(
                        code="volume_not_contracted",
                        message="当前成交量没有收缩到配置比例以内。",
                    )
                )
            selected = not reasons
            if selected:
                reasons.append(
                    SelectionReason(
                        code="trend_pullback_confirmed",
                        message="长期趋势上升、回撤幅度适中且成交量收缩。",
                    )
                )
            metrics = {
                "close": round(current_close, 6),
                "ma_current": round(current_ma, 6),
                "ma_past": round(past_ma, 6),
                "recent_high": round(recent_high, 6),
                "pullback_pct": round(pullback, 10),
                "volume_ratio": round(volume_ratio, 10),
            }
            candidates.append(
                SelectionCandidate(
                    symbol=symbol,
                    signal_date=context.signal_date,
                    selected=selected,
                    score=_score(
                        current_ma=current_ma,
                        past_ma=past_ma,
                        pullback=pullback,
                        volume_ratio=volume_ratio,
                        params=params,
                    ),
                    reasons=tuple(reasons),
                    metrics=metrics,
                )
            )

        ordered_candidates = sorted(
            candidates,
            key=lambda candidate: (
                -int(candidate.selected),
                -candidate.score,
                candidate.symbol,
            ),
        )
        return tuple(
            candidate.model_copy(update={"rank": rank})
            for rank, candidate in enumerate(ordered_candidates, start=1)
        )


def _score(
    *,
    current_ma: float,
    past_ma: float,
    pullback: float,
    volume_ratio: float,
    params: TrendPullbackParams,
) -> float:
    trend_score = _clamp((current_ma / past_ma - 1) * 20)
    midpoint = (params.min_pullback_pct + params.max_pullback_pct) / 2
    half_width = (params.max_pullback_pct - params.min_pullback_pct) / 2
    pullback_score = _clamp(1 - abs(pullback - midpoint) / half_width)
    volume_score = _clamp(1 - volume_ratio / params.max_volume_ratio)
    return round((trend_score + pullback_score + volume_score) / 3, 10)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
