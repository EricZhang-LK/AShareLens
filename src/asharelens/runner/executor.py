"""Stable executor registry used by the durable Worker."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from asharelens.runner.models import JobSnapshot

type Heartbeat = Callable[[], None]
type JobExecutor = Callable[[JobSnapshot, Heartbeat], dict[str, Any]]


class DuplicateExecutor(ValueError):
    """Raised when one job type is registered twice."""


class UnknownJobType(LookupError):
    """Raised when a durable job has no installed executor."""


class PermanentJobError(RuntimeError):
    """An expected job error that must not be retried."""


class RetryableJobError(RuntimeError):
    """An expected transient error with an explicit retry delay."""

    def __init__(
        self,
        message: str,
        *,
        retry_delay: timedelta,
    ) -> None:
        if retry_delay < timedelta(0):
            raise ValueError("retry_delay must not be negative")
        super().__init__(message)
        self.retry_delay = retry_delay


class ExecutorRegistry:
    """Map persisted job types to in-process executor adapters."""

    def __init__(self) -> None:
        self._executors: dict[str, JobExecutor] = {}

    def register(self, job_type: str, executor: JobExecutor) -> None:
        """Register exactly one executor for a non-empty job type."""

        if not job_type:
            raise ValueError("job_type must not be empty")
        if job_type in self._executors:
            raise DuplicateExecutor(job_type)
        self._executors[job_type] = executor

    def resolve(self, job_type: str) -> JobExecutor:
        """Return the executor or reject an undeployable durable job."""

        try:
            return self._executors[job_type]
        except KeyError:
            raise UnknownJobType(f"no executor registered for {job_type!r}") from None
