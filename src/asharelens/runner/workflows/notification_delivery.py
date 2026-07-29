"""Runner adapter for durable at-least-once notification delivery."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from asharelens.notifications.notifier import (
    NotificationError,
    NotifierRegistry,
    UnknownNotifier,
)
from asharelens.runner.executor import (
    Heartbeat,
    PermanentJobError,
    RetryableJobError,
)
from asharelens.runner.models import JobSnapshot
from asharelens.storage.notification_repository import (
    NotificationNotFound,
    NotificationRepository,
    NotificationStatus,
)

_SAFE_ERROR_CODE = re.compile(r"[a-z0-9_.-]{1,80}", flags=re.IGNORECASE)


class NotificationDeliveryExecutor:
    """Resolve, send, and audit one persisted notification."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        notifiers: NotifierRegistry,
        clock: Callable[[], datetime],
    ) -> None:
        self._session_factory = session_factory
        self._notifiers = notifiers
        self._clock = clock

    def __call__(
        self,
        job: JobSnapshot,
        heartbeat: Heartbeat,
    ) -> dict[str, object]:
        """Execute one delivery while preserving retry and dedupe semantics."""

        delivery_id = job.payload.get("delivery_id")
        if not isinstance(delivery_id, str) or not delivery_id:
            raise PermanentJobError("invalid notification delivery payload")

        try:
            with self._session_factory() as session:
                delivery = NotificationRepository(session).get(delivery_id)
        except NotificationNotFound:
            raise PermanentJobError("notification delivery does not exist") from None

        if delivery.status is NotificationStatus.SENT:
            return _result(
                delivery_id=delivery.id,
                external_id=delivery.external_id,
            )
        if delivery.status is NotificationStatus.FAILED:
            raise PermanentJobError("notification delivery already failed")

        try:
            notifier = self._notifiers.resolve(delivery.notifier_id)
        except UnknownNotifier:
            self._mark_failed(delivery.id, "notifier_not_configured")
            raise PermanentJobError("notification notifier is not configured") from None

        heartbeat()
        try:
            receipt = notifier.send(
                delivery.message,
                idempotency_key=delivery.dedupe_key,
            )
        except NotificationError as error:
            code = _safe_error_code(error.error_code)
            if error.retryable:
                raise RetryableJobError(
                    f"notification transport failed: {code}",
                    retry_delay=_retry_delay(job.attempt),
                ) from None
            self._mark_failed(delivery.id, code)
            raise PermanentJobError(
                f"notification transport rejected delivery: {code}"
            ) from None
        except Exception:
            raise RetryableJobError(
                "notification plugin failed unexpectedly",
                retry_delay=_retry_delay(job.attempt),
            ) from None

        if receipt.notifier_id != delivery.notifier_id:
            self._mark_failed(delivery.id, "invalid_notifier_receipt")
            raise PermanentJobError("notification plugin returned an invalid receipt")

        try:
            with self._session_factory.begin() as session:
                NotificationRepository(session).mark_sent(
                    delivery.id,
                    external_id=receipt.external_id,
                    now=receipt.delivered_at,
                )
        except Exception:
            raise RetryableJobError(
                "notification audit could not be persisted",
                retry_delay=_retry_delay(job.attempt),
            ) from None
        return _result(
            delivery_id=delivery.id,
            external_id=receipt.external_id,
        )

    def _mark_failed(self, delivery_id: str, error_code: str) -> None:
        with self._session_factory.begin() as session:
            NotificationRepository(session).mark_failed(
                delivery_id,
                error=error_code,
                now=self._clock(),
            )


def _retry_delay(attempt: int) -> timedelta:
    exponent = max(attempt - 1, 0)
    return min(timedelta(minutes=2**exponent), timedelta(minutes=30))


def _safe_error_code(value: str) -> str:
    return value if _SAFE_ERROR_CODE.fullmatch(value) else "plugin_error"


def _result(
    *,
    delivery_id: str,
    external_id: str | None,
) -> dict[str, object]:
    return {
        "delivery_id": delivery_id,
        "external_id": external_id,
        "status": NotificationStatus.SENT.value,
    }
