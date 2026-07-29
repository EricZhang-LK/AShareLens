from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from asharelens.runner.job_repository import (
    IdempotencyConflict,
    JobRepository,
    LeaseLost,
)
from asharelens.runner.models import JobStatus
from asharelens.storage.database import Base, create_database_engine

NOW = datetime(2026, 7, 29, 7, 0, 0)


@pytest.fixture
def session() -> Session:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as database_session:
        yield database_session


def test_enqueue_is_idempotent_and_rejects_conflicting_payload(
    session: Session,
) -> None:
    repository = JobRepository(session)

    first = repository.enqueue(
        job_type="daily_selection",
        idempotency_key="plan-a:2026-07-29",
        payload={"plan_id": "plan-a"},
        now=NOW,
    )
    duplicate = repository.enqueue(
        job_type="daily_selection",
        idempotency_key="plan-a:2026-07-29",
        payload={"plan_id": "plan-a"},
        now=NOW,
    )

    assert duplicate.id == first.id
    with pytest.raises(IdempotencyConflict):
        repository.enqueue(
            job_type="daily_selection",
            idempotency_key="plan-a:2026-07-29",
            payload={"plan_id": "another-plan"},
            now=NOW,
        )


def test_claim_prefers_priority_and_records_lease_ownership(
    session: Session,
) -> None:
    repository = JobRepository(session)
    repository.enqueue(
        job_type="backtest",
        idempotency_key="low",
        payload={},
        priority=0,
        now=NOW,
    )
    high = repository.enqueue(
        job_type="daily_selection",
        idempotency_key="high",
        payload={},
        priority=10,
        now=NOW,
    )

    claimed = repository.claim(
        queue="default",
        worker_id="runner-a",
        now=NOW,
        lease_for=timedelta(seconds=30),
    )

    assert claimed is not None
    assert claimed.id == high.id
    assert claimed.status is JobStatus.RUNNING
    assert claimed.attempt == 1
    assert claimed.leased_by == "runner-a"
    assert claimed.lease_expires_at == NOW + timedelta(seconds=30)


def test_only_current_lease_owner_can_heartbeat_and_complete(
    session: Session,
) -> None:
    repository = JobRepository(session)
    job = repository.enqueue(
        job_type="daily_selection",
        idempotency_key="owned",
        payload={},
        now=NOW,
    )
    claimed = repository.claim(
        queue="default",
        worker_id="runner-a",
        now=NOW,
        lease_for=timedelta(seconds=30),
    )
    assert claimed is not None

    with pytest.raises(LeaseLost):
        repository.heartbeat(
            job.id,
            worker_id="runner-b",
            now=NOW + timedelta(seconds=5),
            lease_for=timedelta(seconds=30),
        )

    heartbeat = repository.heartbeat(
        job.id,
        worker_id="runner-a",
        now=NOW + timedelta(seconds=5),
        lease_for=timedelta(seconds=30),
    )
    assert heartbeat.lease_expires_at == NOW + timedelta(seconds=35)

    completed = repository.complete(
        job.id,
        worker_id="runner-a",
        result={"selected": 3},
        now=NOW + timedelta(seconds=10),
    )
    assert completed.status is JobStatus.SUCCEEDED
    assert completed.result == {"selected": 3}
    assert completed.leased_by is None
    assert completed.finished_at == NOW + timedelta(seconds=10)


def test_retry_wait_respects_backoff_and_max_attempts(session: Session) -> None:
    repository = JobRepository(session)
    job = repository.enqueue(
        job_type="sync_data",
        idempotency_key="sync:2026-07-29",
        payload={},
        max_attempts=2,
        now=NOW,
    )
    assert repository.claim(
        queue="default",
        worker_id="runner-a",
        now=NOW,
        lease_for=timedelta(seconds=30),
    )

    retrying = repository.fail(
        job.id,
        worker_id="runner-a",
        error="temporary provider error",
        retryable=True,
        retry_delay=timedelta(minutes=5),
        now=NOW + timedelta(seconds=1),
    )
    assert retrying.status is JobStatus.RETRY_WAIT
    assert retrying.available_at == NOW + timedelta(minutes=5, seconds=1)
    assert repository.claim(
        queue="default",
        worker_id="runner-a",
        now=NOW + timedelta(minutes=4),
        lease_for=timedelta(seconds=30),
    ) is None

    second_claim = repository.claim(
        queue="default",
        worker_id="runner-a",
        now=NOW + timedelta(minutes=6),
        lease_for=timedelta(seconds=30),
    )
    assert second_claim is not None
    assert second_claim.attempt == 2

    failed = repository.fail(
        job.id,
        worker_id="runner-a",
        error="still unavailable",
        retryable=True,
        retry_delay=timedelta(minutes=5),
        now=NOW + timedelta(minutes=6, seconds=1),
    )
    assert failed.status is JobStatus.FAILED
    assert failed.finished_at == NOW + timedelta(minutes=6, seconds=1)


def test_failure_summary_redacts_common_credentials(session: Session) -> None:
    repository = JobRepository(session)
    job = repository.enqueue(
        job_type="sync_data",
        idempotency_key="redaction",
        payload={},
        now=NOW,
    )
    repository.claim(
        queue="default",
        worker_id="runner-a",
        now=NOW,
        lease_for=timedelta(seconds=30),
    )

    failed = repository.fail(
        job.id,
        worker_id="runner-a",
        error=(
            "mysql+pymysql://user:database-secret@mysql/asharelens "
            "token=provider-token api_key=provider-key"
        ),
        retryable=False,
        retry_delay=timedelta(0),
        now=NOW + timedelta(seconds=1),
    )

    assert failed.last_error is not None
    assert "database-secret" not in failed.last_error
    assert "provider-token" not in failed.last_error
    assert "provider-key" not in failed.last_error
    assert failed.last_error.count("***") == 3


def test_reaper_recovers_expired_lease_and_exhausts_terminal_job(
    session: Session,
) -> None:
    repository = JobRepository(session)
    recoverable = repository.enqueue(
        job_type="backtest",
        idempotency_key="recoverable",
        payload={},
        max_attempts=2,
        now=NOW,
    )
    repository.claim(
        queue="default",
        worker_id="lost-worker",
        now=NOW,
        lease_for=timedelta(seconds=10),
    )

    recovered = repository.reap_expired(now=NOW + timedelta(seconds=11))

    assert recovered == 1
    recovered_job = repository.get(recoverable.id)
    assert recovered_job.status is JobStatus.QUEUED
    assert recovered_job.leased_by is None

    terminal = repository.enqueue(
        job_type="notification",
        idempotency_key="terminal",
        payload={},
        max_attempts=1,
        priority=100,
        now=NOW + timedelta(seconds=20),
    )
    repository.claim(
        queue="default",
        worker_id="lost-worker",
        now=NOW + timedelta(seconds=20),
        lease_for=timedelta(seconds=10),
    )
    repository.reap_expired(now=NOW + timedelta(seconds=31))

    terminal_job = repository.get(terminal.id)
    assert terminal_job.status is JobStatus.FAILED
    assert terminal_job.finished_at == NOW + timedelta(seconds=31)
