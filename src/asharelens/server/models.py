"""Stable public API models."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import Field

from asharelens.core.models import FrozenModel, SelectionCandidate


class HealthResponse(FrozenModel):
    """Database-independent process liveness."""

    service: Literal["asharelens"] = "asharelens"
    status: Literal["ok"] = "ok"
    version: str = Field(min_length=1)


class ErrorDetail(FrozenModel):
    """One safe, localized API failure."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    details: dict[str, Any] | None = None


class ErrorEnvelope(FrozenModel):
    """Consistent error wrapper consumed by the Web client."""

    error: ErrorDetail


class StrategyCatalogItem(FrozenModel):
    """Strategy discovery record consumed by automatic forms."""

    strategy_id: str
    name: str
    version: str
    description: str
    min_history_sessions: int
    parameter_schema: dict[str, Any]
    demo_supported: bool
    demo_limitation: str | None = None


class StrategyCatalogResponse(FrozenModel):
    """Stable ordered strategy collection."""

    items: tuple[StrategyCatalogItem, ...]


class ProviderCatalogItem(FrozenModel):
    """Credential-free market-data provider capabilities."""

    provider_id: str
    name: str
    version: str
    description: str
    datasets: tuple[str, ...]
    requires_registration: bool
    role: Literal["default", "supplemental", "optional"]


class ProviderCatalogResponse(FrozenModel):
    """Stable configured provider ordering."""

    items: tuple[ProviderCatalogItem, ...]


class ParameterValidationRequest(FrozenModel):
    """Untrusted strategy values emitted by a schema-generated form."""

    parameters: dict[str, Any] = Field(default_factory=dict)


class ParameterValidationResponse(FrozenModel):
    """Plugin-normalized strategy parameters including defaults."""

    strategy_id: str
    parameters: dict[str, Any]


class DemoBacktestRequest(FrozenModel):
    """Bounded deterministic research run for local onboarding."""

    strategy_id: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    sessions: int = Field(default=160, ge=40, le=500)
    initial_cash: float = Field(default=100_000, gt=0, le=1_000_000_000)
    top_n: int = Field(default=3, ge=1, le=50)
    max_weight: float = Field(default=0.34, gt=0, le=1)


class BacktestSummary(FrozenModel):
    """Reader-facing headline metrics."""

    sessions: int
    initial_cash: float
    final_nav: float
    total_return_pct: float
    max_drawdown_pct: float
    selected_signals: int
    orders: int
    fills: int


class BacktestCosts(FrozenModel):
    """Explicit simulated execution costs."""

    commission: float
    transfer_fee: float
    stamp_duty: float
    total: float


class NavPointResponse(FrozenModel):
    """One chart-ready valuation point."""

    trade_date: date
    cash: float
    market_value: float
    total_value: float


class DemoBacktestResponse(FrozenModel):
    """Complete bounded demo result with explanations and provenance."""

    strategy_id: str
    strategy_version: str
    parameters: dict[str, Any]
    is_demo: Literal[True] = True
    data_source: Literal["deterministic_synthetic"] = "deterministic_synthetic"
    warning: str
    fingerprint: str
    summary: BacktestSummary
    costs: BacktestCosts
    nav: tuple[NavPointResponse, ...]
    latest_candidates: tuple[SelectionCandidate, ...]
