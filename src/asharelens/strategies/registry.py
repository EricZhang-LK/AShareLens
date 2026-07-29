"""Read-only discovery registry for built-in strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from asharelens.core.strategy import StrategyMetadata
from asharelens.strategies.momentum_rps import MomentumRpsStrategy
from asharelens.strategies.moving_average import MovingAverageStrategy
from asharelens.strategies.trend_pullback import TrendPullbackStrategy
from asharelens.strategies.value_quality import ValueQualityStrategy


class DiscoverableStrategy(Protocol):
    """Subset required to build catalogs and parameter forms."""

    metadata: StrategyMetadata

    def parameter_model(self) -> type[BaseModel]: ...


class StrategyNotFound(LookupError):
    """Raised when a strategy ID is not installed."""


@dataclass(frozen=True, slots=True)
class StrategyDescriptor:
    """Web-safe metadata and JSON Schema for one strategy."""

    strategy_id: str
    name: str
    version: str
    description: str
    min_history_sessions: int
    parameter_schema: dict[str, Any]


class BuiltInStrategyRegistry:
    """Discover the four deterministic first-party strategies."""

    def __init__(self) -> None:
        plugins: tuple[DiscoverableStrategy, ...] = (
            MovingAverageStrategy(),
            MomentumRpsStrategy(),
            ValueQualityStrategy(),
            TrendPullbackStrategy(),
        )
        self._plugins = {
            plugin.metadata.strategy_id: plugin for plugin in plugins
        }

    def get(self, strategy_id: str) -> DiscoverableStrategy:
        """Return one built-in strategy without constructing parameters."""

        try:
            return self._plugins[strategy_id]
        except KeyError:
            raise StrategyNotFound(strategy_id) from None

    def describe(self) -> tuple[StrategyDescriptor, ...]:
        """Return a stable catalog suitable for API serialization."""

        return tuple(
            StrategyDescriptor(
                strategy_id=plugin.metadata.strategy_id,
                name=plugin.metadata.name,
                version=plugin.metadata.version,
                description=plugin.metadata.description,
                min_history_sessions=plugin.metadata.min_history_sessions,
                parameter_schema=plugin.parameter_model().model_json_schema(),
            )
            for _, plugin in sorted(self._plugins.items())
        )
