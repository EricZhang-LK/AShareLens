"""Zero-configuration notification preview."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from asharelens.notifications.models import DeliveryReceipt, NotificationMessage
from asharelens.notifications.notifier import NotifierMetadata


class ConsoleNotifier:
    """Write rendered messages to a caller-controlled local output."""

    metadata = NotifierMetadata(
        notifier_id="console",
        name="Console",
        version="1.0.0",
        description="Print notifications locally without credentials.",
    )

    def __init__(
        self,
        *,
        writer: Callable[[str], None] = print,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._writer = writer
        self._clock = clock or (lambda: datetime.now(UTC))

    def send(
        self,
        message: NotificationMessage,
        *,
        idempotency_key: str,
    ) -> DeliveryReceipt:
        """Print one already-rendered message."""

        if not idempotency_key:
            raise ValueError("idempotency_key must not be empty")
        self._writer(f"{message.title}\n{message.body}")
        return DeliveryReceipt(
            notifier_id=self.metadata.notifier_id,
            delivered_at=self._clock(),
        )
