"""Point-in-time value and business-quality multi-factor strategy."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from asharelens.core.models import (
    SelectionCandidate,
    SelectionReason,
    StrategyContext,
)
from asharelens.core.strategy import StrategyMetadata

REQUIRED_METRICS = (
    "pe_ttm",
    "pb",
    "roe_ttm",
    "revenue_growth_yoy",
    "net_profit_growth_yoy",
    "debt_to_assets",
)


class ValueQualityParams(BaseModel):
    """Hard quality gates exposed to generated Web forms."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_pe_ttm: float = Field(
        default=30,
        gt=0,
        le=500,
        title="最高 PE(TTM)",
    )
    max_pb: float = Field(default=4, gt=0, le=100, title="最高 PB")
    min_roe_ttm: float = Field(
        default=10,
        ge=-100,
        le=200,
        title="最低 ROE(TTM)%",
    )
    min_revenue_growth_yoy: float = Field(
        default=0,
        ge=-100,
        le=1000,
        title="最低营收同比增长%",
    )
    min_net_profit_growth_yoy: float = Field(
        default=0,
        ge=-100,
        le=5000,
        title="最低净利润同比增长%",
    )
    max_debt_to_assets: float = Field(
        default=70,
        ge=0,
        le=100,
        title="最高资产负债率%",
    )
    max_snapshot_age_days: int = Field(
        default=550,
        ge=1,
        le=2000,
        title="财务快照最长年龄（日）",
    )


class ValueQualityStrategy:
    """Select reasonably valued, profitable and growing businesses."""

    metadata = StrategyMetadata(
        strategy_id="value_quality",
        name="价值质量多因子",
        version="1.0.0",
        description="以时点 PE、PB、ROE、增长和负债率筛选价值质量公司。",
        min_history_sessions=1,
    )

    def parameter_model(self) -> type[BaseModel]:
        return ValueQualityParams

    def generate(
        self,
        context: StrategyContext,
        params: ValueQualityParams,
    ) -> tuple[SelectionCandidate, ...]:
        candidates: list[SelectionCandidate] = []
        universe = sorted(set(context.bars) | set(context.fundamentals))
        for symbol in universe:
            snapshot = context.latest_fundamental(symbol)
            if snapshot is None:
                candidates.append(
                    SelectionCandidate(
                        symbol=symbol,
                        signal_date=context.signal_date,
                        selected=False,
                        reasons=(
                            SelectionReason(
                                code="missing_fundamentals",
                                message="信号日没有可见的基本面快照。",
                            ),
                        ),
                        data_warnings=("fundamentals_missing",),
                    )
                )
                continue

            values = {
                name: snapshot.metric(name) for name in REQUIRED_METRICS
            }
            missing = tuple(
                name for name, value in values.items() if value is None
            )
            if missing:
                candidates.append(
                    SelectionCandidate(
                        symbol=symbol,
                        signal_date=context.signal_date,
                        selected=False,
                        reasons=(
                            SelectionReason(
                                code="missing_fundamental_metrics",
                                message="基本面快照缺少策略必需指标。",
                            ),
                        ),
                        metrics={
                            name: value
                            for name, value in values.items()
                            if value is not None
                        },
                        data_warnings=missing,
                    )
                )
                continue

            complete = {
                name: float(value)
                for name, value in values.items()
                if value is not None
            }
            age_days = (context.signal_date - snapshot.available_on).days
            reasons = _failure_reasons(complete, age_days, params)
            selected = not reasons
            if selected:
                reasons = [
                    SelectionReason(
                        code="value_quality_passed",
                        message="估值、盈利质量、增长和负债率均通过配置门槛。",
                    )
                ]
            metrics = {
                **complete,
                "fundamental_age_days": float(age_days),
            }
            candidates.append(
                SelectionCandidate(
                    symbol=symbol,
                    signal_date=context.signal_date,
                    selected=selected,
                    score=_score(complete, params),
                    reasons=tuple(reasons),
                    metrics=metrics,
                )
            )

        ordered = sorted(
            candidates,
            key=lambda candidate: (
                -int(candidate.selected),
                -candidate.score,
                candidate.symbol,
            ),
        )
        return tuple(
            candidate.model_copy(update={"rank": rank})
            for rank, candidate in enumerate(ordered, start=1)
        )


def _failure_reasons(
    values: dict[str, float],
    age_days: int,
    params: ValueQualityParams,
) -> list[SelectionReason]:
    checks = (
        (
            values["pe_ttm"] <= 0,
            "pe_non_positive",
            "PE(TTM) 非正，盈利不满足价值筛选要求。",
        ),
        (
            values["pe_ttm"] > params.max_pe_ttm,
            "pe_above_max",
            "PE(TTM) 高于配置上限。",
        ),
        (
            values["pb"] <= 0,
            "pb_non_positive",
            "PB 非正，账面价值指标不可用于本策略。",
        ),
        (
            values["pb"] > params.max_pb,
            "pb_above_max",
            "PB 高于配置上限。",
        ),
        (
            values["roe_ttm"] < params.min_roe_ttm,
            "roe_below_min",
            "ROE(TTM) 低于配置下限。",
        ),
        (
            values["revenue_growth_yoy"] < params.min_revenue_growth_yoy,
            "revenue_growth_below_min",
            "营收同比增长低于配置下限。",
        ),
        (
            values["net_profit_growth_yoy"]
            < params.min_net_profit_growth_yoy,
            "profit_growth_below_min",
            "净利润同比增长低于配置下限。",
        ),
        (
            values["debt_to_assets"] > params.max_debt_to_assets,
            "debt_above_max",
            "资产负债率高于配置上限。",
        ),
        (
            age_days > params.max_snapshot_age_days,
            "fundamentals_stale",
            "基本面快照超过配置的最长年龄。",
        ),
    )
    return [
        SelectionReason(code=code, message=message)
        for failed, code, message in checks
        if failed
    ]


def _score(
    values: dict[str, float],
    params: ValueQualityParams,
) -> float:
    components = (
        _clamp(1 - values["pe_ttm"] / params.max_pe_ttm),
        _clamp(1 - values["pb"] / params.max_pb),
        _clamp(values["roe_ttm"] / 30),
        _clamp((values["revenue_growth_yoy"] + 20) / 70),
        _clamp((values["net_profit_growth_yoy"] + 20) / 100),
        _clamp(1 - values["debt_to_assets"] / 100),
    )
    return round(sum(components) / len(components), 10)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
