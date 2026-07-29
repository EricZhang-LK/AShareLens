"""Provider-neutral market-data values."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import Field, field_validator

from asharelens.core.models import FrozenModel


class Dataset(StrEnum):
    """Stable names for versioned datasets."""

    INSTRUMENTS = "instruments"
    TRADING_CALENDAR = "trading_calendar"
    DAILY_BARS = "daily_bars"
    FUNDAMENTALS = "fundamentals"
    CORPORATE_ACTIONS = "corporate_actions"
    INDEX_MEMBERSHIP = "index_membership"


class Adjustment(StrEnum):
    """Price adjustment requested from a Provider."""

    NONE = "none"
    FORWARD = "forward"
    BACKWARD = "backward"


class Exchange(StrEnum):
    """Supported mainland A-share exchanges."""

    SHANGHAI = "sh"
    SHENZHEN = "sz"
    BEIJING = "bj"


class Instrument(FrozenModel):
    """One normalized A-share security."""

    symbol: str = Field(pattern=r"^(sh|sz|bj)\.\d{6}$")
    name: str = Field(min_length=1)
    listed_on: date | None = None
    delisted_on: date | None = None

    @property
    def exchange(self) -> Exchange:
        return Exchange(self.symbol[:2])


class TradingSession(FrozenModel):
    """One date in a Provider's mainland trading calendar."""

    trade_date: date
    is_open: bool


type RequestScalar = str | int | float | bool | None


class DataBatch[RecordT](FrozenModel):
    """Immutable normalized records with their ingestion lineage."""

    dataset: Dataset
    provider_id: str = Field(min_length=1)
    provider_version: str = Field(min_length=1)
    fetched_at: datetime
    request: dict[str, RequestScalar]
    source_batch_id: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_version: str = Field(default="1", min_length=1)
    records: tuple[RecordT, ...]

    @field_validator("fetched_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware")
        return value

