"""Short-transaction Worker and expired-lease Reaper."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy.orm import Session, sessionmaker

from asharelens.runner.executor import (
    ExecutorRegistry,
    PermanentJobError,
    RetryableJobError,
    UnknownJobType,
)
from asharelens.runner.job_repository import JobRepository, LeaseLost
from asharelens.runner.models import JobSnapshot, JobStatus

type Clock = Callable[[], datetime]


class WorkerOutcome(StrEnum):
    """Observable outcome of one Worker polling cycle."""

    IDLE = "idle"
    SUCCEEDED = "succeeded"
    RETRY_SCHEDULED = "retry_scheduled"
    FAILED = "failed"
    LEASE_LOST = "lease_lost"


@dataclass(frozen=True, slots=True)
class WorkerRun:
    """Small diagnostic result suitable for CLI logs and metrics."""

    outcome: WorkerOutcome
    job_id: str | None
    job_type: str | None


def utc_now_naive() -> datetime:
    """Return current UTC in MySQL-compatible naive form."""

    return datetime.now(UTC).replace(tzinfo=None)


class Worker:
    """Claim one job, execute outside locks, then persist one transition."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        registry: ExecutorRegistry,
        worker_id: str,
        queue: str = "default",
        lease_for: timedelta = timedelta(minutes=5),
        default_retry_delay: timedelta = timedelta(minutes=1),
        clock: Clock = utc_now_naive,
    ) -> None:
        if not worker_id or not queue:
            raise ValueError("worker_id and queue must not be empty")
        if lease_for <= timedelta(0):
            raise ValueError("lease_for must be positive")
        if default_retry_delay < timedelta(0):
            raise ValueError("default_retry_delay must not be negative")
        self._session_factory = session_factory
        self._registry = registry
        self._worker_id = worker_id
        self._queue = queue
        self._lease_for = lease_for
        self._default_retry_delay = default_retry_delay
        self._clock = clock

    def run_once(self) -> WorkerRun:
        """Execute at most one due job."""

        with self._session_factory.begin() as session:
            job = JobRepository(session).claim(
                queue=self._queue,
                worker_id=self._worker_id,
                now=self._clock(),
                lease_for=self._lease_for,
            )
        if job is None:
            return WorkerRun(WorkerOutcome.IDLE, None, None)

        try:
            executor = self._registry.resolve(job.job_type)
            result = executor(job, self._heartbeat_callback(job.id))
        except RetryableJobError as error:
            return self._record_failure(
                job,
                error=error,
                retryable=True,
                retry_delay=error.retry_delay,
            )
        except (PermanentJobError, UnknownJobType) as error:
            return self._record_failure(
                job,
                error=error,
                retryable=False,
                retry_delay=timedelta(0),
            )
        except LeaseLost:
            return WorkerRun(WorkerOutcome.LEASE_LOST, job.id, job.job_type)
        except Exception as error:
            return self._record_failure(
                job,
                error=error,
                retryable=True,
                retry_delay=self._default_retry_delay,
            )

        try:
            with self._session_factory.begin() as session:
                completed = JobRepository(session).complete(
                    job.id,
                    worker_id=self._worker_id,
                    result=result,
                    now=self._clock(),
                )
        except LeaseLost:
            return WorkerRun(WorkerOutcome.LEASE_LOST, job.id, job.job_type)
        return WorkerRun(
            _outcome_for_status(completed.status),
            completed.id,
            completed.job_type,
        )

    def _heartbeat_callback(self, job_id: str) -> Callable[[], None]:
        def heartbeat() -> None:
            with self._session_factory.begin() as session:
                JobRepository(session).heartbeat(
                    job_id,
                    worker_id=self._worker_id,
                    now=self._clock(),
                    lease_for=self._lease_for,
                )

        return heartbeat

    def _record_failure(
        self,
        job: JobSnapshot,
        *,
        error: Exception,
        retryable: bool,
        retry_delay: timedelta,
    ) -> WorkerRun:
        summary = f"{type(error).__name__}: {error}"
        try:
            with self._session_factory.begin() as session:
                failed = JobRepository(session).fail(
                    job.id,
                    worker_id=self._worker_id,
                    error=summary,
                    retryable=retryable,
                    retry_delay=retry_delay,
                    now=self._clock(),
                )
        except LeaseLost:
            return WorkerRun(WorkerOutcome.LEASE_LOST, job.id, job.job_type)
        return WorkerRun(
            _outcome_for_status(failed.status),
            failed.id,
            failed.job_type,
        )


class Reaper:
    """Recover jobs whose Worker disappeared without releasing its lease."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        clock: Clock = utc_now_naive,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    def run_once(self) -> int:
        """Reap one transaction's visible expired leases."""

        with self._session_factory.begin() as session:
            return JobRepository(session).reap_expired(now=self._clock())


def _outcome_for_status(status: JobStatus) -> WorkerOutcome:
    if status is JobStatus.SUCCEEDED:
        return WorkerOutcome.SUCCEEDED
    if status is JobStatus.RETRY_WAIT:
        return WorkerOutcome.RETRY_SCHEDULED
    if status is JobStatus.FAILED:
        return WorkerOutcome.FAILED
    raise ValueError(f"unexpected terminal Worker status: {status}")
