"""Stable public API models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from asharelens.core.models import FrozenModel


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


class ErrorEnvelope(FrozenModel):
    """Consistent error wrapper consumed by the Web client."""

    error: ErrorDetail
