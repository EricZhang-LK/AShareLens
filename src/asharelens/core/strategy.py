"""Stable contracts for Python strategy plugins."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel, Field

from asharelens.core.models import FrozenModel, SelectionCandidate, StrategyContext


class StrategyMetadata(FrozenModel):
    """Metadata used for discovery, compatibility checks, and Web display."""

    strategy_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    plugin_api_version: str = Field(default="1.0", min_length=1)
    min_history_sessions: int = Field(ge=1)


ParamsT = TypeVar("ParamsT", bound=BaseModel, contravariant=True)


class StrategyPlugin(Protocol[ParamsT]):
    """Structural interface implemented by trusted strategy plugins."""

    metadata: StrategyMetadata

    def parameter_model(self) -> type[BaseModel]:
        """Return the Pydantic parameter type used to build a Web form."""
        ...

    def generate(
        self,
        context: StrategyContext,
        params: ParamsT,
    ) -> tuple[SelectionCandidate, ...]:
        """Generate point-in-time decisions for all visible instruments."""
        ...

