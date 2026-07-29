"""Transactional notification ledger backed by the durable Runner queue."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from asharelens.notifications.models import NotificationMessage
from asharelens.runner.job_repository import JobRepository
from asharelens.storage.models import NotificationDeliveryRow

_URL_PASSWORD = re.compile(
    r"(?P<prefix>[a-z][a-z0-9+.-]*://[^:/\s]+:)[^@\s]+@",
    flags=re.IGNORECASE,
)
_NAMED_SECRET = re.compile(
    r"(?P<name>\b(?:password|passwd|token|secret|api_key)\s*=\s*)[^\s,;]+",
    flags=re.IGNORECASE,
)


class NotificationStatus(StrEnum):
    """Persisted delivery audit states."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class NotificationConflict(ValueError):
    """A dedupe key cannot describe a different message."""


class NotificationNotFound(LookupError):
    """A delivery ID does not exist."""


@dataclass(frozen=True, slots=True)
class NotificationSnapshot:
    """Immutable notification audit record."""

    id: str
    notifier_id: str
    dedupe_key: str
    message: NotificationMessage
    status: NotificationStatus
    external_id: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    delivered_at: datetime | None


class NotificationRepository:
    """Create notification and durable delivery job in one transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(
        self,
        *,
        notifier_id: str,
        dedupe_key: str,
        message: NotificationMessage,
        now: datetime,
        max_attempts: int = 3,
    ) -> NotificationSnapshot:
        """Persist one logical notification and its Runner job."""

        if not notifier_id or not dedupe_key:
            raise ValueError("notifier_id and dedupe_key must not be empty")
        existing = self._find(notifier_id, dedupe_key)
        message_payload = message.model_dump(mode="json")
        if existing is not None:
            if existing.message != message_payload:
                raise NotificationConflict(dedupe_key)
            return _snapshot(existing)

        current = _naive_utc(now)
        row = NotificationDeliveryRow(
            id=str(uuid4()),
            notifier_id=notifier_id,
            dedupe_key=dedupe_key,
            message=message_payload,
            status=NotificationStatus.PENDING.value,
            external_id=None,
            last_error=None,
            created_at=current,
            updated_at=current,
            delivered_at=None,
        )
        self._session.add(row)
        self._session.flush()
        JobRepository(self._session).enqueue(
            job_type="notification.deliver",
            idempotency_key=_job_idempotency_key(notifier_id, dedupe_key),
            payload={"delivery_id": row.id},
            queue="notifications",
            max_attempts=max_attempts,
            now=current,
        )
        return _snapshot(row)

    def get(self, delivery_id: str, *, for_update: bool = False) -> NotificationSnapshot:
        """Load a delivery, optionally locking it for a terminal transition."""

        statement = select(NotificationDeliveryRow).where(
            NotificationDeliveryRow.id == delivery_id
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        row = self._session.scalar(statement)
        if row is None:
            raise NotificationNotFound(delivery_id)
        return _snapshot(row)

    def mark_sent(
        self,
        delivery_id: str,
        *,
        external_id: str | None,
        now: datetime,
    ) -> NotificationSnapshot:
        """Record successful transport evidence idempotently."""

        row = self._locked_row(delivery_id)
        current = _naive_utc(now)
        row.status = NotificationStatus.SENT.value
        row.external_id = external_id
        row.last_error = None
        row.delivered_at = current
        row.updated_at = current
        self._session.flush()
        return _snapshot(row)

    def mark_failed(
        self,
        delivery_id: str,
        *,
        error: str,
        now: datetime,
    ) -> NotificationSnapshot:
        """Record a terminal secret-free failure."""

        row = self._locked_row(delivery_id)
        current = _naive_utc(now)
        row.status = NotificationStatus.FAILED.value
        row.last_error = _safe_error(error)
        row.updated_at = current
        row.delivered_at = None
        self._session.flush()
        return _snapshot(row)

    def _find(
        self,
        notifier_id: str,
        dedupe_key: str,
    ) -> NotificationDeliveryRow | None:
        return self._session.scalar(
            select(NotificationDeliveryRow).where(
                NotificationDeliveryRow.notifier_id == notifier_id,
                NotificationDeliveryRow.dedupe_key == dedupe_key,
            )
        )

    def _locked_row(self, delivery_id: str) -> NotificationDeliveryRow:
        row = self._session.scalar(
            select(NotificationDeliveryRow)
            .where(NotificationDeliveryRow.id == delivery_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise NotificationNotFound(delivery_id)
        return row


def _snapshot(row: NotificationDeliveryRow) -> NotificationSnapshot:
    return NotificationSnapshot(
        id=row.id,
        notifier_id=row.notifier_id,
        dedupe_key=row.dedupe_key,
        message=NotificationMessage.model_validate(row.message),
        status=NotificationStatus(row.status),
        external_id=row.external_id,
        last_error=row.last_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
        delivered_at=row.delivered_at,
    )


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _safe_error(error: str) -> str:
    compact = " ".join(error.split())
    redacted = _URL_PASSWORD.sub(r"\g<prefix>***@", compact)
    redacted = _NAMED_SECRET.sub(r"\g<name>***", redacted)
    return (redacted or "unspecified notification failure")[:2000]


def _job_idempotency_key(notifier_id: str, dedupe_key: str) -> str:
    """Fit arbitrary public dedupe keys into the Runner's bounded key column."""

    digest = sha256(f"{notifier_id}\0{dedupe_key}".encode()).hexdigest()
    return f"notification:{digest}"
