from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from asharelens.notifications.models import DeliveryReceipt, NotificationMessage
from asharelens.notifications.notifier import (
    DuplicateNotifier,
    NotificationError,
    NotifierMetadata,
    NotifierRegistry,
)
from asharelens.runner.executor import ExecutorRegistry
from asharelens.runner.job_repository import JobRepository
from asharelens.runner.models import JobStatus
from asharelens.runner.worker import Worker, WorkerOutcome
from asharelens.runner.workflows.notification_delivery import (
    NotificationDeliveryExecutor,
)
from asharelens.storage.database import (
    Base,
    create_database_engine,
    create_session_factory,
)
from asharelens.storage.notification_repository import (
    NotificationRepository,
    NotificationStatus,
)

NOW = datetime(2026, 7, 29, 8)
MESSAGE = NotificationMessage(title="每日选股", body="结果正文", format="markdown")


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


class FakeNotifier:
    def __init__(
        self,
        *,
        notifier_id: str = "webhook.main",
        error: NotificationError | None = None,
    ) -> None:
        self.metadata = NotifierMetadata(
            notifier_id=notifier_id,
            name="Fake",
            version="1.0",
            description="Test notifier",
        )
        self.error = error
        self.calls: list[tuple[NotificationMessage, str]] = []

    def send(
        self,
        message: NotificationMessage,
        *,
        idempotency_key: str,
    ) -> DeliveryReceipt:
        self.calls.append((message, idempotency_key))
        if self.error is not None:
            raise self.error
        return DeliveryReceipt(
            notifier_id=self.metadata.notifier_id,
            delivered_at=NOW,
            external_id="remote-42",
        )


def _enqueue(factory: sessionmaker[Session], *, notifier_id: str = "webhook.main") -> str:
    with factory.begin() as session:
        return NotificationRepository(session).enqueue(
            notifier_id=notifier_id,
            dedupe_key="account:date:run",
            message=MESSAGE,
            now=NOW,
        ).id


def _worker(
    factory: sessionmaker[Session],
    notifiers: NotifierRegistry,
) -> Worker:
    executors = ExecutorRegistry()
    executors.register(
        "notification.deliver",
        NotificationDeliveryExecutor(
            session_factory=factory,
            notifiers=notifiers,
            clock=lambda: NOW,
        ),
    )
    return Worker(
        session_factory=factory,
        registry=executors,
        worker_id="notification-worker",
        queue="notifications",
        clock=lambda: NOW,
    )


def test_notifier_registry_rejects_duplicate_public_id() -> None:
    registry = NotifierRegistry()
    registry.register(FakeNotifier())

    with pytest.raises(DuplicateNotifier):
        registry.register(FakeNotifier())


def test_worker_delivers_and_audits_notification(
    factory: sessionmaker[Session],
) -> None:
    delivery_id = _enqueue(factory)
    notifier = FakeNotifier()
    notifiers = NotifierRegistry()
    notifiers.register(notifier)

    result = _worker(factory, notifiers).run_once()

    assert result.outcome is WorkerOutcome.SUCCEEDED
    assert notifier.calls == [(MESSAGE, "account:date:run")]
    with factory() as session:
        delivery = NotificationRepository(session).get(delivery_id)
        job = JobRepository(session).get(result.job_id or "")
    assert delivery.status is NotificationStatus.SENT
    assert delivery.external_id == "remote-42"
    assert job.status is JobStatus.SUCCEEDED
    assert job.result == {
        "delivery_id": delivery_id,
        "external_id": "remote-42",
        "status": "sent",
    }


def test_replayed_success_does_not_send_twice(
    factory: sessionmaker[Session],
) -> None:
    delivery_id = _enqueue(factory)
    with factory.begin() as session:
        NotificationRepository(session).mark_sent(
            delivery_id,
            external_id="prior",
            now=NOW,
        )
    notifier = FakeNotifier()
    notifiers = NotifierRegistry()
    notifiers.register(notifier)

    result = _worker(factory, notifiers).run_once()

    assert result.outcome is WorkerOutcome.SUCCEEDED
    assert notifier.calls == []


def test_retryable_failure_keeps_delivery_pending(
    factory: sessionmaker[Session],
) -> None:
    delivery_id = _enqueue(factory)
    notifier = FakeNotifier(
        error=NotificationError(
            notifier_id="webhook.main",
            error_code="transport_unavailable",
            message="must-not-leak-secret-token",
            retryable=True,
        )
    )
    notifiers = NotifierRegistry()
    notifiers.register(notifier)

    result = _worker(factory, notifiers).run_once()

    assert result.outcome is WorkerOutcome.RETRY_SCHEDULED
    with factory() as session:
        delivery = NotificationRepository(session).get(delivery_id)
        job = JobRepository(session).get(result.job_id or "")
    assert delivery.status is NotificationStatus.PENDING
    assert job.status is JobStatus.RETRY_WAIT
    assert job.available_at == NOW + timedelta(minutes=1)
    assert "must-not-leak" not in (job.last_error or "")


def test_permanent_failure_and_unknown_notifier_are_audited(
    factory: sessionmaker[Session],
) -> None:
    permanent_id = _enqueue(factory)
    permanent = FakeNotifier(
        error=NotificationError(
            notifier_id="webhook.main",
            error_code="http_400",
            message="remote rejected request",
            retryable=False,
        )
    )
    configured = NotifierRegistry()
    configured.register(permanent)

    permanent_result = _worker(factory, configured).run_once()

    unknown_id = _enqueue(factory, notifier_id="webhook.missing")
    unknown_result = _worker(factory, NotifierRegistry()).run_once()

    assert permanent_result.outcome is WorkerOutcome.FAILED
    assert unknown_result.outcome is WorkerOutcome.FAILED
    with factory() as session:
        permanent_delivery = NotificationRepository(session).get(permanent_id)
        unknown_delivery = NotificationRepository(session).get(unknown_id)
    assert permanent_delivery.status is NotificationStatus.FAILED
    assert permanent_delivery.last_error == "http_400"
    assert unknown_delivery.status is NotificationStatus.FAILED
    assert unknown_delivery.last_error == "notifier_not_configured"
