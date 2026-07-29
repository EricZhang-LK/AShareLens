import pytest

from asharelens.strategies.registry import (
    BuiltInStrategyRegistry,
    StrategyNotFound,
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
