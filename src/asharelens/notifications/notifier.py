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


class DuplicateNotifier(ValueError):
    """A process cannot register two transports under one public ID."""


class UnknownNotifier(LookupError):
    """A persisted delivery references a notifier absent from this process."""


class NotifierPlugin(Protocol):
    """Transport boundary; messages are already rendered."""

    metadata: NotifierMetadata

    def send(
        self,
        message: NotificationMessage,
        *,
        idempotency_key: str,
    ) -> DeliveryReceipt:
        """Deliver one message or raise `NotificationError`."""
        ...


class NotifierRegistry:
    """Resolve configured notifier plugins without exposing their secrets."""

    def __init__(self) -> None:
        self._plugins: dict[str, NotifierPlugin] = {}

    def register(self, plugin: NotifierPlugin) -> None:
        """Register one plugin under its metadata ID."""

        notifier_id = plugin.metadata.notifier_id
        if notifier_id in self._plugins:
            raise DuplicateNotifier(notifier_id)
        self._plugins[notifier_id] = plugin

    def resolve(self, notifier_id: str) -> NotifierPlugin:
        """Return a configured plugin or fail with only its public ID."""

        try:
            return self._plugins[notifier_id]
        except KeyError:
            raise UnknownNotifier(
                f"no notifier registered for {notifier_id!r}"
            ) from None
