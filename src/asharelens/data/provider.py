"""Stable interfaces implemented by concrete market-data Providers."""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from pydantic import Field, field_validator

from asharelens.core.models import DailyBar, FrozenModel
from asharelens.data.models import (
    Adjustment,
    DataBatch,
    Dataset,
    Instrument,
    TradingSession,
)


class ProviderMetadata(FrozenModel):
    """Discovery and compatibility metadata for a data plugin."""

    provider_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    plugin_api_version: str = Field(default="1.0", min_length=1)
    datasets: tuple[Dataset, ...]
    requires_registration: bool


class ProviderHealth(FrozenModel):
    """Sanitized health-check result suitable for the Web and CLI."""

    provider_id: str = Field(min_length=1)
    ok: bool
    checked_at: datetime
    message: str = Field(min_length=1)
    latency_ms: int | None = Field(default=None, ge=0)

    @field_validator("checked_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        return value


class ProviderError(RuntimeError):
    """Provider-neutral failure with stable retry and diagnostic semantics."""

    def __init__(
        self,
        *,
        provider_id: str,
        error_code: str,
        message: str,
        retryable: bool,
    ) -> None:
        self.provider_id = provider_id
        self.error_code = error_code
        self.retryable = retryable
        super().__init__(message)


class DataProviderPlugin(Protocol):
    """Capabilities required from a trusted market-data plugin."""

    metadata: ProviderMetadata

    def healthcheck(self) -> ProviderHealth:
        """Check upstream availability without returning credentials."""
        ...

    def fetch_instruments(self, as_of: date) -> DataBatch[Instrument]:
        """Fetch the instrument universe known on one date."""
        ...

    def fetch_calendar(self, start: date, end: date) -> DataBatch[TradingSession]:
        """Fetch trading and non-trading dates in an inclusive range."""
        ...

    def fetch_daily_bars(
        self,
        symbols: tuple[str, ...],
        start: date,
        end: date,
        adjustment: Adjustment,
    ) -> DataBatch[DailyBar]:
        """Fetch a complete daily-bar request or raise ProviderError."""
        ...
