"""Transactional MySQL-backed task broker."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from asharelens.runner.models import JobSnapshot, JobStatus
from asharelens.storage.models import RunnerJobRow

_URL_PASSWORD = re.compile(
    r"(?P<prefix>[a-z][a-z0-9+.-]*://[^:/\s]+:)[^@\s]+@",
    flags=re.IGNORECASE,
)
_NAMED_SECRET = re.compile(
    r"(?P<name>\b(?:password|passwd|token|secret|api_key)\s*=\s*)[^\s,;]+",
    flags=re.IGNORECASE,
)


class JobNotFound(LookupError):
    """Raised when a requested job does not exist."""


class LeaseLost(RuntimeError):
    """Raised when a Worker no longer owns a live job lease."""


class IdempotencyConflict(ValueError):
    """Raised when an idempotency key is reused for different work."""


class JobRepository:
    """Persist job transitions without owning commit or rollback."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(
        self,
        *,
        job_type: str,
        idempotency_key: str,
        payload: dict[str, Any],
        now: datetime,
        queue: str = "default",
        priority: int = 0,
        available_at: datetime | None = None,
        max_attempts: int = 3,
    ) -> JobSnapshot:
        """Create one logical task, or return its identical prior enqueue."""

        if not job_type or not idempotency_key or not queue:
            raise ValueError("job_type, idempotency_key and queue must not be empty")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        _assert_json_object(payload, name="payload")
        current = _as_naive_utc(now)
        first_available = _as_naive_utc(available_at or current)

        existing = self._find_idempotent(job_type, idempotency_key)
        if existing is not None:
            self._assert_same_enqueue(
                existing,
                queue=queue,
                payload=payload,
                priority=priority,
                max_attempts=max_attempts,
            )
            return _snapshot(existing)

        row = RunnerJobRow(
            id=str(uuid4()),
            queue=queue,
            job_type=job_type,
            idempotency_key=idempotency_key,
            status=JobStatus.QUEUED.value,
            priority=priority,
            available_at=first_available,
            attempt=0,
            max_attempts=max_attempts,
            payload=dict(payload),
            result=None,
            leased_by=None,
            lease_expires_at=None,
            heartbeat_at=None,
            last_error=None,
            created_at=current,
            updated_at=current,
            finished_at=None,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError:
            existing = self._find_idempotent(job_type, idempotency_key)
            if existing is None:
                raise
            self._assert_same_enqueue(
                existing,
                queue=queue,
                payload=payload,
                priority=priority,
                max_attempts=max_attempts,
            )
            return _snapshot(existing)
        return _snapshot(row)

    def claim(
        self,
        *,
        queue: str,
        worker_id: str,
        now: datetime,
        lease_for: timedelta,
    ) -> JobSnapshot | None:
        """Claim the next due job using a renewable exclusive lease."""

        _validate_lease(worker_id, lease_for)
        current = _as_naive_utc(now)
        statement = (
            select(RunnerJobRow)
            .where(
                RunnerJobRow.queue == queue,
                RunnerJobRow.status.in_(
                    (JobStatus.QUEUED.value, JobStatus.RETRY_WAIT.value)
                ),
                RunnerJobRow.available_at <= current,
                RunnerJobRow.attempt < RunnerJobRow.max_attempts,
            )
            .order_by(
                RunnerJobRow.priority.desc(),
                RunnerJobRow.available_at,
                RunnerJobRow.created_at,
                RunnerJobRow.id,
            )
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        row = self._session.scalar(statement)
        if row is None:
            return None

        row.status = JobStatus.RUNNING.value
        row.attempt += 1
        row.leased_by = worker_id
        row.heartbeat_at = current
        row.lease_expires_at = current + lease_for
        row.updated_at = current
        row.last_error = None
        self._session.flush()
        return _snapshot(row)

    def heartbeat(
        self,
        job_id: str,
        *,
        worker_id: str,
        now: datetime,
        lease_for: timedelta,
    ) -> JobSnapshot:
        """Renew a lease only while its current owner still holds it."""

        _validate_lease(worker_id, lease_for)
        current = _as_naive_utc(now)
        row = self._owned_running_job(job_id, worker_id, current)
        row.heartbeat_at = current
        row.lease_expires_at = current + lease_for
        row.updated_at = current
        self._session.flush()
        return _snapshot(row)

    def complete(
        self,
        job_id: str,
        *,
        worker_id: str,
        result: dict[str, Any],
        now: datetime,
    ) -> JobSnapshot:
        """Finish a job successfully while holding its lease."""

        _assert_json_object(result, name="result")
        current = _as_naive_utc(now)
        row = self._owned_running_job(job_id, worker_id, current)
        row.status = JobStatus.SUCCEEDED.value
        row.result = dict(result)
        row.last_error = None
        row.finished_at = current
        row.updated_at = current
        _clear_lease(row)
        self._session.flush()
        return _snapshot(row)

    def fail(
        self,
        job_id: str,
        *,
        worker_id: str,
        error: str,
        retryable: bool,
        retry_delay: timedelta,
        now: datetime,
    ) -> JobSnapshot:
        """Record a safe failure and either schedule retry or finish terminally."""

        if retry_delay < timedelta(0):
            raise ValueError("retry_delay must not be negative")
        current = _as_naive_utc(now)
        row = self._owned_running_job(job_id, worker_id, current)
        row.last_error = _safe_error(error)
        row.result = None
        row.updated_at = current
        _clear_lease(row)
        if retryable and row.attempt < row.max_attempts:
            row.status = JobStatus.RETRY_WAIT.value
            row.available_at = current + retry_delay
            row.finished_at = None
        else:
            row.status = JobStatus.FAILED.value
            row.finished_at = current
        self._session.flush()
        return _snapshot(row)

    def reap_expired(self, *, now: datetime) -> int:
        """Recover every unlocked expired lease visible to this transaction."""

        current = _as_naive_utc(now)
        statement = (
            select(RunnerJobRow)
            .where(
                RunnerJobRow.status == JobStatus.RUNNING.value,
                RunnerJobRow.lease_expires_at <= current,
            )
            .order_by(RunnerJobRow.lease_expires_at, RunnerJobRow.id)
            .with_for_update(skip_locked=True)
        )
        rows = tuple(self._session.scalars(statement))
        for row in rows:
            row.last_error = "worker lease expired"
            row.updated_at = current
            _clear_lease(row)
            if row.attempt < row.max_attempts:
                row.status = JobStatus.QUEUED.value
                row.available_at = current
                row.finished_at = None
            else:
                row.status = JobStatus.FAILED.value
                row.finished_at = current
        self._session.flush()
        return len(rows)

    def get(self, job_id: str) -> JobSnapshot:
        """Return one immutable job snapshot."""

        row = self._session.get(RunnerJobRow, job_id)
        if row is None:
            raise JobNotFound(job_id)
        return _snapshot(row)

    def _find_idempotent(
        self,
        job_type: str,
        idempotency_key: str,
    ) -> RunnerJobRow | None:
        statement: Select[tuple[RunnerJobRow]] = select(RunnerJobRow).where(
            RunnerJobRow.job_type == job_type,
            RunnerJobRow.idempotency_key == idempotency_key,
        )
        return self._session.scalar(statement)

    @staticmethod
    def _assert_same_enqueue(
        row: RunnerJobRow,
        *,
        queue: str,
        payload: dict[str, Any],
        priority: int,
        max_attempts: int,
    ) -> None:
        if (
            row.queue != queue
            or row.payload != payload
            or row.priority != priority
            or row.max_attempts != max_attempts
        ):
            raise IdempotencyConflict(
                f"idempotency key {row.idempotency_key!r} already describes different work"
            )

    def _owned_running_job(
        self,
        job_id: str,
        worker_id: str,
        now: datetime,
    ) -> RunnerJobRow:
        statement = (
            select(RunnerJobRow)
            .where(RunnerJobRow.id == job_id)
            .with_for_update()
        )
        row = self._session.scalar(statement)
        if row is None:
            raise JobNotFound(job_id)
        if (
            row.status != JobStatus.RUNNING.value
            or row.leased_by != worker_id
            or row.lease_expires_at is None
            or row.lease_expires_at <= now
        ):
            raise LeaseLost(job_id)
        return row


def _snapshot(row: RunnerJobRow) -> JobSnapshot:
    return JobSnapshot(
        id=row.id,
        queue=row.queue,
        job_type=row.job_type,
        idempotency_key=row.idempotency_key,
        status=JobStatus(row.status),
        priority=row.priority,
        available_at=row.available_at,
        attempt=row.attempt,
        max_attempts=row.max_attempts,
        payload=dict(row.payload),
        result=dict(row.result) if row.result is not None else None,
        leased_by=row.leased_by,
        lease_expires_at=row.lease_expires_at,
        heartbeat_at=row.heartbeat_at,
        last_error=row.last_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
        finished_at=row.finished_at,
    )


def _clear_lease(row: RunnerJobRow) -> None:
    row.leased_by = None
    row.lease_expires_at = None
    row.heartbeat_at = None


def _validate_lease(worker_id: str, lease_for: timedelta) -> None:
    if not worker_id:
        raise ValueError("worker_id must not be empty")
    if lease_for <= timedelta(0):
        raise ValueError("lease_for must be positive")


def _as_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _assert_json_object(value: dict[str, Any], *, name: str) -> None:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a JSON object") from error


def _safe_error(error: str) -> str:
    compact = " ".join(error.split())
    redacted = _URL_PASSWORD.sub(r"\g<prefix>***@", compact)
    redacted = _NAMED_SECRET.sub(r"\g<name>***", redacted)
    return (redacted or "unspecified job failure")[:2000]
