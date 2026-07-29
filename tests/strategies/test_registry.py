from dataclasses import dataclass

import pytest
from pydantic import BaseModel, ConfigDict, Field

from asharelens.core.models import SelectionCandidate, StrategyContext
from asharelens.core.strategy import StrategyMetadata
from asharelens.strategies.registry import (
    BuiltInStrategyRegistry,
    DuplicateStrategy,
    StrategyNotFound,
    StrategyPluginLoadError,
    StrategyRegistry,
)


def test_registry_exposes_four_builtins_and_parameter_schemas() -> None:
    registry = BuiltInStrategyRegistry()

    descriptors = registry.describe()

    assert [descriptor.strategy_id for descriptor in descriptors] == [
        "momentum_rps",
        "moving_average",
        "trend_pullback",
        "value_quality",
    ]
    for descriptor in descriptors:
        assert descriptor.name
        assert descriptor.version == "1.0.0"
        assert descriptor.parameter_schema["type"] == "object"
        assert descriptor.parameter_schema["additionalProperties"] is False


def test_registry_returns_plugin_and_rejects_unknown_id() -> None:
    registry = BuiltInStrategyRegistry()

    assert registry.get("moving_average").metadata.name == "均线趋势"
    with pytest.raises(StrategyNotFound):
        registry.get("unknown")


class ExampleParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    threshold: float = Field(default=0.5, ge=0, le=1)


class ExampleStrategy:
    metadata = StrategyMetadata(
        strategy_id="example_plugin",
        name="示例插件",
        version="2.1.0",
        description="通过 Python entry point 安装的示例策略。",
        min_history_sessions=1,
    )

    def parameter_model(self) -> type[BaseModel]:
        return ExampleParams

    def generate(
        self,
        context: StrategyContext,
        params: ExampleParams,
    ) -> tuple[SelectionCandidate, ...]:
        return ()


@dataclass
class FakeEntryPoint:
    name: str
    value: object

    def load(self) -> object:
        return self.value


def test_registry_discovers_installed_strategy_and_generates_schema() -> None:
    registry = StrategyRegistry(
        entry_points_provider=lambda: (
            FakeEntryPoint("example", ExampleStrategy),
        )
    )

    descriptor = registry.describe_one("example_plugin")

    assert descriptor.name == "示例插件"
    assert descriptor.parameter_schema["properties"]["threshold"]["default"] == 0.5
    assert registry.validate_parameters("example_plugin", {}).model_dump() == {
        "threshold": 0.5
    }


def test_registry_rejects_duplicate_or_invalid_installed_plugins() -> None:
    with pytest.raises(DuplicateStrategy, match="moving_average"):
        StrategyRegistry(
            entry_points_provider=lambda: (
                FakeEntryPoint("collision", MovingAverageClone),
            )
        )

    with pytest.raises(StrategyPluginLoadError, match="broken"):
        StrategyRegistry(
            entry_points_provider=lambda: (
                FakeEntryPoint("broken", object()),
            )
        )


class MovingAverageClone(ExampleStrategy):
    metadata = ExampleStrategy.metadata.model_copy(
        update={"strategy_id": "moving_average"}
    )


def test_registry_rejects_incompatible_plugin_api() -> None:
    incompatible = ExampleStrategy()
    incompatible.metadata = incompatible.metadata.model_copy(
        update={"plugin_api_version": "99.0"}
    )

    with pytest.raises(StrategyPluginLoadError, match="plugin API"):
        StrategyRegistry(
            entry_points_provider=lambda: (
                FakeEntryPoint("future", incompatible),
            )
        )
