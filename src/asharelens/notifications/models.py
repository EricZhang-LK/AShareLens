"""Channel-neutral notification values."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from asharelens.core.models import FrozenModel


class MessageFormat(StrEnum):
    """Body representation understood by a Notifier."""

    TEXT = "text"
    MARKDOWN = "markdown"


class DeliveryStatus(StrEnum):
    """Sanitized transport outcome."""

    SENT = "sent"


class NotificationMessage(FrozenModel):
    """Deterministic message passed to transport plugins."""

    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    format: MessageFormat


class DeliveryReceipt(FrozenModel):
    """Provider-neutral successful-delivery evidence."""

    notifier_id: str = Field(min_length=1)
    status: DeliveryStatus = DeliveryStatus.SENT
    delivered_at: datetime
    external_id: str | None = None
