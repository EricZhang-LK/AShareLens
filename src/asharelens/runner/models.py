"""Runner domain values independent of SQLAlchemy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class JobStatus(StrEnum):
    """Persisted states in the durable job state machine."""

    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    """Immutable job view passed across Runner boundaries."""

    id: str
    queue: str
    job_type: str
    idempotency_key: str
    status: JobStatus
    priority: int
    available_at: datetime
    attempt: int
    max_attempts: int
    payload: dict[str, Any]
    result: dict[str, Any] | None
    leased_by: str | None
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
