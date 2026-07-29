from datetime import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from asharelens.notifications.models import MessageFormat, NotificationMessage
from asharelens.storage.database import Base, create_database_engine
from asharelens.storage.models import NotificationDeliveryRow, RunnerJobRow
from asharelens.storage.notification_repository import (
    NotificationConflict,
    NotificationRepository,
    NotificationStatus,
)

NOW = datetime(2026, 7, 29, 8)
MESSAGE = NotificationMessage(
    title="每日选股",
    body="结果正文",
    format=MessageFormat.MARKDOWN,
)


@pytest.fixture
def session() -> Session:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as database_session:
        yield database_session


def test_enqueue_is_idempotent_and_atomically_creates_durable_job(
    session: Session,
) -> None:
    repository = NotificationRepository(session)

    first = repository.enqueue(
        notifier_id="webhook.main",
        dedupe_key="account:date:run",
        message=MESSAGE,
        now=NOW,
    )
    duplicate = repository.enqueue(
        notifier_id="webhook.main",
        dedupe_key="account:date:run",
        message=MESSAGE,
        now=NOW,
    )

    assert duplicate == first
    assert first.status is NotificationStatus.PENDING
    assert session.scalar(
        select(func.count()).select_from(NotificationDeliveryRow)
    ) == 1
    job = session.scalar(select(RunnerJobRow))
    assert job is not None
    assert job.job_type == "notification.deliver"
    assert job.payload == {"delivery_id": first.id}

    with pytest.raises(NotificationConflict):
        repository.enqueue(
            notifier_id="webhook.main",
            dedupe_key="account:date:run",
            message=NotificationMessage(
                title="不同消息",
                body="different",
                format=MessageFormat.TEXT,
            ),
            now=NOW,
        )


def test_delivery_records_success_and_sanitized_terminal_failure(
    session: Session,
) -> None:
    repository = NotificationRepository(session)
    sent = repository.enqueue(
        notifier_id="webhook.main",
        dedupe_key="sent",
        message=MESSAGE,
        now=NOW,
    )
    failed = repository.enqueue(
        notifier_id="webhook.backup",
        dedupe_key="failed",
        message=MESSAGE,
        now=NOW,
    )

    sent_result = repository.mark_sent(
        sent.id,
        external_id="remote-123",
        now=NOW,
    )
    failed_result = repository.mark_failed(
        failed.id,
        error=(
            "https://user:webhook-secret@example.test "
            "token=provider-token"
        ),
        now=NOW,
    )

    assert sent_result.status is NotificationStatus.SENT
    assert sent_result.external_id == "remote-123"
    assert sent_result.delivered_at == NOW
    assert failed_result.status is NotificationStatus.FAILED
    assert failed_result.last_error is not None
    assert "webhook-secret" not in failed_result.last_error
    assert "provider-token" not in failed_result.last_error
