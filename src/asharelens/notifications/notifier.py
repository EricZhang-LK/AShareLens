"""Stable protocol implemented by notification transports."""

from __future__ import annotations

from typing import Protocol

from pydantic import Field

from asharelens.core.models import FrozenModel
from asharelens.notifications.models import DeliveryReceipt, NotificationMessage


class NotifierMetadata(FrozenModel):
    """Discovery metadata safe for Web and logs."""

    notifier_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    plugin_api_version: str = "1.0"


class NotificationError(RuntimeError):
    """Secret-free delivery failure with retry semantics."""

    def __init__(
        self,
        *,
        notifier_id: str,
        error_code: str,
        message: str,
        retryable: bool,
    ) -> None:
        self.notifier_id = notifier_id
        self.error_code = error_code
        self.retryable = retryable
        super().__init__(message)


class NotifierPlugin(Protocol):
    """Transport boundary; messages are already rendered."""

    metadata: NotifierMetadata

    def send(self, message: NotificationMessage) -> DeliveryReceipt:
        """Deliver one message or raise `NotificationError`."""
        ...
