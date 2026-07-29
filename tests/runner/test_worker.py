from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from asharelens.runner.executor import (
    DuplicateExecutor,
    ExecutorRegistry,
    PermanentJobError,
    RetryableJobError,
)
from asharelens.runner.job_repository import JobRepository
from asharelens.runner.models import JobSnapshot, JobStatus
from asharelens.runner.worker import Reaper, Worker, WorkerOutcome
from asharelens.storage.database import (
    Base,
    create_database_engine,
    create_session_factory,
)

NOW = datetime(2026, 7, 29, 8)


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _enqueue(
    factory: sessionmaker[Session],
    *,
    job_type: str = "probe",
    max_attempts: int = 3,
) -> JobSnapshot:
    with factory.begin() as session:
        return JobRepository(session).enqueue(
            job_type=job_type,
            idempotency_key=f"{job_type}:one",
            payload={"value": 7},
            max_attempts=max_attempts,
            now=NOW,
        )


def _get(factory: sessionmaker[Session], job_id: str) -> JobSnapshot:
    with factory() as session:
        return JobRepository(session).get(job_id)


class ScriptedClock:
    def __init__(self, *values: datetime) -> None:
        self._values: Iterator[datetime] = iter(values)

    def __call__(self) -> datetime:
        return next(self._values)


def test_registry_rejects_duplicate_executor() -> None:
    registry = ExecutorRegistry()

    registry.register("probe", lambda job, heartbeat: {})

    with pytest.raises(DuplicateExecutor):
        registry.register("probe", lambda job, heartbeat: {})


def test_worker_dispatches_and_completes_job(factory: sessionmaker[Session]) -> None:
    job = _enqueue(factory)
    registry = ExecutorRegistry()
    received: list[JobSnapshot] = []

    def execute(snapshot: JobSnapshot, heartbeat: object) -> dict[str, Any]:
        received.append(snapshot)
        return {"answer": snapshot.payload["value"] * 2}

    registry.register("probe", execute)
    worker = Worker(
        session_factory=factory,
        registry=registry,
        worker_id="runner-a",
        clock=ScriptedClock(NOW, NOW + timedelta(seconds=1)),
    )

    run = worker.run_once()

    assert run.outcome is WorkerOutcome.SUCCEEDED
    assert received[0].id == job.id
    stored = _get(factory, job.id)
    assert stored.status is JobStatus.SUCCEEDED
    assert stored.result == {"answer": 14}


def test_unknown_job_type_is_permanent_failure(
    factory: sessionmaker[Session],
) -> None:
    job = _enqueue(factory, job_type="not_registered")
    worker = Worker(
        session_factory=factory,
        registry=ExecutorRegistry(),
        worker_id="runner-a",
        clock=ScriptedClock(NOW, NOW + timedelta(seconds=1)),
    )

    run = worker.run_once()

    assert run.outcome is WorkerOutcome.FAILED
    stored = _get(factory, job.id)
    assert stored.status is JobStatus.FAILED
    assert "not_registered" in (stored.last_error or "")


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_outcome"),
    [
        (
            RetryableJobError("provider timeout", retry_delay=timedelta(minutes=2)),
            JobStatus.RETRY_WAIT,
            WorkerOutcome.RETRY_SCHEDULED,
        ),
        (
            PermanentJobError("invalid strategy parameters"),
            JobStatus.FAILED,
            WorkerOutcome.FAILED,
        ),
        (
            RuntimeError("unexpected transient failure"),
            JobStatus.RETRY_WAIT,
            WorkerOutcome.RETRY_SCHEDULED,
        ),
    ],
)
def test_worker_classifies_executor_failures(
    factory: sessionmaker[Session],
    error: Exception,
    expected_status: JobStatus,
    expected_outcome: WorkerOutcome,
) -> None:
    job = _enqueue(factory)
    registry = ExecutorRegistry()

    def execute(snapshot: JobSnapshot, heartbeat: object) -> dict[str, Any]:
        raise error

    registry.register("probe", execute)
    worker = Worker(
        session_factory=factory,
        registry=registry,
        worker_id="runner-a",
        clock=ScriptedClock(NOW, NOW + timedelta(seconds=1)),
    )

    run = worker.run_once()

    assert run.outcome is expected_outcome
    assert _get(factory, job.id).status is expected_status


def test_executor_can_heartbeat_during_long_job(
    factory: sessionmaker[Session],
) -> None:
    job = _enqueue(factory)
    registry = ExecutorRegistry()
    observed_expiry: list[datetime | None] = []

    def execute(
        snapshot: JobSnapshot,
        heartbeat: object,
    ) -> dict[str, Any]:
        assert callable(heartbeat)
        heartbeat()
        observed_expiry.append(_get(factory, snapshot.id).lease_expires_at)
        return {}

    registry.register("probe", execute)
    worker = Worker(
        session_factory=factory,
        registry=registry,
        worker_id="runner-a",
        lease_for=timedelta(seconds=30),
        clock=ScriptedClock(
            NOW,
            NOW + timedelta(seconds=5),
            NOW + timedelta(seconds=6),
        ),
    )

    run = worker.run_once()

    assert run.outcome is WorkerOutcome.SUCCEEDED
    assert observed_expiry == [NOW + timedelta(seconds=35)]
    assert _get(factory, job.id).status is JobStatus.SUCCEEDED


def test_reaper_recovers_job_after_simulated_process_loss(
    factory: sessionmaker[Session],
) -> None:
    job = _enqueue(factory)
    with factory.begin() as session:
        claimed = JobRepository(session).claim(
            queue="default",
            worker_id="crashed-runner",
            now=NOW,
            lease_for=timedelta(seconds=30),
        )
        assert claimed is not None

    recovered = Reaper(
        session_factory=factory,
        clock=lambda: NOW + timedelta(seconds=31),
    ).run_once()

    assert recovered == 1
    assert _get(factory, job.id).status is JobStatus.QUEUED
