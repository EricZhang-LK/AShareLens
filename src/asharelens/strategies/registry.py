"""Validated discovery registry for built-in and installed strategies."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any, Protocol, cast

from pydantic import BaseModel

from asharelens.core.models import SelectionCandidate, StrategyContext
from asharelens.core.strategy import StrategyMetadata
from asharelens.strategies.momentum_rps import MomentumRpsStrategy
from asharelens.strategies.moving_average import MovingAverageStrategy
from asharelens.strategies.trend_pullback import TrendPullbackStrategy
from asharelens.strategies.value_quality import ValueQualityStrategy


class DiscoverableStrategy(Protocol):
    """Subset required to build catalogs and parameter forms."""

    metadata: StrategyMetadata

    def parameter_model(self) -> type[BaseModel]: ...

    def generate(
        self,
        context: StrategyContext,
        params: BaseModel,
    ) -> tuple[SelectionCandidate, ...]: ...


class StrategyEntryPoint(Protocol):
    """Small importlib entry-point surface used for deterministic tests."""

    name: str

    def load(self) -> object: ...


class StrategyNotFound(LookupError):
    """Raised when a strategy ID is not installed."""


class DuplicateStrategy(ValueError):
    """Two trusted plugins cannot claim the same stable strategy ID."""


class StrategyPluginLoadError(RuntimeError):
    """An installed entry point is incompatible or cannot be constructed."""


@dataclass(frozen=True, slots=True)
class StrategyDescriptor:
    """Web-safe metadata and JSON Schema for one strategy."""

    strategy_id: str
    name: str
    version: str
    description: str
    min_history_sessions: int
    parameter_schema: dict[str, Any]


PLUGIN_ENTRY_POINT_GROUP = "asharelens.strategies"
PLUGIN_API_VERSION = "1.0"


class StrategyRegistry:
    """Discover validated built-ins and trusted Python entry points."""

    def __init__(
        self,
        *,
        entry_points_provider: (
            Callable[[], tuple[StrategyEntryPoint, ...]] | None
        ) = None,
    ) -> None:
        plugins: tuple[DiscoverableStrategy, ...] = (
            cast(DiscoverableStrategy, MovingAverageStrategy()),
            cast(DiscoverableStrategy, MomentumRpsStrategy()),
            cast(DiscoverableStrategy, ValueQualityStrategy()),
            cast(DiscoverableStrategy, TrendPullbackStrategy()),
        )
        self._plugins: dict[str, DiscoverableStrategy] = {}
        for plugin in plugins:
            self._register(plugin)

        provider = entry_points_provider or _strategy_entry_points
        for entry_point in sorted(provider(), key=lambda item: item.name):
            self._register(_load_entry_point(entry_point))

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

    def describe_one(self, strategy_id: str) -> StrategyDescriptor:
        """Describe one installed strategy or raise `StrategyNotFound`."""

        plugin = self.get(strategy_id)
        return StrategyDescriptor(
            strategy_id=plugin.metadata.strategy_id,
            name=plugin.metadata.name,
            version=plugin.metadata.version,
            description=plugin.metadata.description,
            min_history_sessions=plugin.metadata.min_history_sessions,
            parameter_schema=plugin.parameter_model().model_json_schema(),
        )

    def validate_parameters(
        self,
        strategy_id: str,
        parameters: dict[str, Any],
    ) -> BaseModel:
        """Normalize public parameters with the plugin-owned Pydantic model."""

        return self.get(strategy_id).parameter_model().model_validate(parameters)

    def _register(self, plugin: DiscoverableStrategy) -> None:
        strategy_id = plugin.metadata.strategy_id
        if strategy_id in self._plugins:
            raise DuplicateStrategy(strategy_id)
        self._plugins[strategy_id] = plugin


BuiltInStrategyRegistry = StrategyRegistry


def _strategy_entry_points() -> tuple[StrategyEntryPoint, ...]:
    installed = entry_points(group=PLUGIN_ENTRY_POINT_GROUP)
    return cast(tuple[StrategyEntryPoint, ...], tuple(installed))


def _load_entry_point(entry_point: StrategyEntryPoint) -> DiscoverableStrategy:
    try:
        loaded = entry_point.load()
        candidate = loaded() if inspect.isclass(loaded) else loaded
    except Exception as error:
        raise StrategyPluginLoadError(
            f"strategy entry point {entry_point.name!r} could not be loaded"
        ) from error

    metadata = getattr(candidate, "metadata", None)
    parameter_model = getattr(candidate, "parameter_model", None)
    generate = getattr(candidate, "generate", None)
    if (
        not isinstance(metadata, StrategyMetadata)
        or not callable(parameter_model)
        or not callable(generate)
    ):
        raise StrategyPluginLoadError(
            f"strategy entry point {entry_point.name!r} has an invalid contract"
        )
    if metadata.plugin_api_version != PLUGIN_API_VERSION:
        raise StrategyPluginLoadError(
            f"strategy entry point {entry_point.name!r} requires unsupported "
            f"plugin API {metadata.plugin_api_version!r}"
        )
    try:
        model = parameter_model()
    except Exception as error:
        raise StrategyPluginLoadError(
            f"strategy entry point {entry_point.name!r} parameter model failed"
        ) from error
    if not inspect.isclass(model) or not issubclass(model, BaseModel):
        raise StrategyPluginLoadError(
            f"strategy entry point {entry_point.name!r} parameter model "
            "must inherit pydantic.BaseModel"
        )
    return cast(DiscoverableStrategy, candidate)
