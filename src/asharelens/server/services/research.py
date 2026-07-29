"""Deterministic research services behind the Web API."""

from __future__ import annotations

from datetime import date

from asharelens.core.engine import DailyCycleEngine
from asharelens.core.execution import OpeningExecutionModel
from asharelens.data.provider import DataProviderPlugin
from asharelens.data.providers.akshare import AkShareProvider
from asharelens.data.providers.baostock import BaoStockProvider
from asharelens.data.providers.tushare import TushareProvider
from asharelens.demo.data import generate_demo_bars
from asharelens.server.models import (
    BacktestCosts,
    BacktestSummary,
    DemoBacktestRequest,
    DemoBacktestResponse,
    NavPointResponse,
    ParameterValidationResponse,
    ProviderCatalogItem,
    ProviderCatalogResponse,
    StrategyCatalogItem,
    StrategyCatalogResponse,
)
from asharelens.strategies.registry import StrategyRegistry

_DEMO_UNSUPPORTED = {
    "value_quality": "离线演示不伪造财务披露时点数据；请在配置基本面数据后运行该策略。"
}
_PROVIDER_ROLES = {
    "baostock": "default",
    "akshare": "supplemental",
    "tushare": "optional",
}


class DemoDatasetUnsupported(ValueError):
    """The deterministic demo intentionally lacks required source data."""


class ResearchService:
    """Coordinate registries and the shared chronological Core."""

    def __init__(
        self,
        *,
        strategies: StrategyRegistry | None = None,
        providers: tuple[DataProviderPlugin, ...] | None = None,
    ) -> None:
        self._strategies = strategies or StrategyRegistry()
        self._providers = providers or (
            BaoStockProvider(),
            AkShareProvider(),
            TushareProvider(),
        )

    def strategy_catalog(self) -> StrategyCatalogResponse:
        """Return form-ready strategy metadata in stable ID order."""

        return StrategyCatalogResponse(
            items=tuple(
                StrategyCatalogItem(
                    strategy_id=item.strategy_id,
                    name=item.name,
                    version=item.version,
                    description=item.description,
                    min_history_sessions=item.min_history_sessions,
                    parameter_schema=item.parameter_schema,
                    demo_supported=item.strategy_id not in _DEMO_UNSUPPORTED,
                    demo_limitation=_DEMO_UNSUPPORTED.get(item.strategy_id),
                )
                for item in self._strategies.describe()
            )
        )

    def provider_catalog(self) -> ProviderCatalogResponse:
        """Return metadata only; never import an optional provider SDK."""

        return ProviderCatalogResponse(
            items=tuple(
                ProviderCatalogItem(
                    provider_id=provider.metadata.provider_id,
                    name=provider.metadata.name,
                    version=provider.metadata.version,
                    description=provider.metadata.description,
                    datasets=tuple(
                        dataset.value for dataset in provider.metadata.datasets
                    ),
                    requires_registration=provider.metadata.requires_registration,
                    role=_PROVIDER_ROLES[provider.metadata.provider_id],
                )
                for provider in self._providers
            )
        )

    def validate_parameters(
        self,
        strategy_id: str,
        parameters: dict[str, object],
    ) -> ParameterValidationResponse:
        """Delegate all defaults and constraints to the Python plugin."""

        normalized = self._strategies.validate_parameters(strategy_id, parameters)
        return ParameterValidationResponse(
            strategy_id=strategy_id,
            parameters=normalized.model_dump(mode="json"),
        )

    def run_demo(self, request: DemoBacktestRequest) -> DemoBacktestResponse:
        """Run one bounded deterministic backtest through the production Core."""

        if request.strategy_id in _DEMO_UNSUPPORTED:
            raise DemoDatasetUnsupported(_DEMO_UNSUPPORTED[request.strategy_id])
        plugin = self._strategies.get(request.strategy_id)
        params = plugin.parameter_model().model_validate(request.parameters)
        bars = generate_demo_bars(date(2025, 1, 2), sessions=request.sessions)
        engine = DailyCycleEngine(
            strategy=plugin,
            params=params,
            execution_model=OpeningExecutionModel(),
            initial_cash=request.initial_cash,
            top_n=request.top_n,
            max_weight=request.max_weight,
        )
        result = engine.run(bars)
        latest_date = result.nav[-1].trade_date
        latest_candidates = tuple(
            candidate
            for candidate in result.candidates
            if candidate.signal_date == latest_date
        )
        commissions = round(sum(fill.commission for fill in result.fills), 2)
        transfer_fees = round(sum(fill.transfer_fee for fill in result.fills), 2)
        stamp_duties = round(sum(fill.stamp_duty for fill in result.fills), 2)
        final_nav = result.nav[-1].total_value
        return DemoBacktestResponse(
            strategy_id=plugin.metadata.strategy_id,
            strategy_version=plugin.metadata.version,
            parameters=params.model_dump(mode="json"),
            warning="确定性合成数据仅用于软件功能演示，不构成任何投资建议。",
            fingerprint=result.fingerprint,
            summary=BacktestSummary(
                sessions=len(result.nav),
                initial_cash=request.initial_cash,
                final_nav=final_nav,
                total_return_pct=round(
                    (final_nav / request.initial_cash - 1) * 100,
                    4,
                ),
                max_drawdown_pct=_max_drawdown_pct(
                    tuple(point.total_value for point in result.nav)
                ),
                selected_signals=sum(
                    candidate.selected for candidate in result.candidates
                ),
                orders=len(result.orders),
                fills=len(result.fills),
            ),
            costs=BacktestCosts(
                commission=commissions,
                transfer_fee=transfer_fees,
                stamp_duty=stamp_duties,
                total=round(commissions + transfer_fees + stamp_duties, 2),
            ),
            nav=tuple(
                NavPointResponse(
                    trade_date=point.trade_date,
                    cash=point.cash,
                    market_value=point.market_value,
                    total_value=point.total_value,
                )
                for point in result.nav
            ),
            latest_candidates=latest_candidates,
        )


def _max_drawdown_pct(values: tuple[float, ...]) -> float:
    peak = values[0]
    maximum = 0.0
    for value in values:
        peak = max(peak, value)
        maximum = max(maximum, (peak - value) / peak)
    return round(maximum * 100, 4)
