from datetime import UTC, datetime
from typing import Any

import pytest

from asharelens.notifications.console import ConsoleNotifier
from asharelens.notifications.models import (
    DeliveryStatus,
    MessageFormat,
    NotificationMessage,
)
from asharelens.notifications.notifier import NotificationError
from asharelens.notifications.webhook import WebhookNotifier, WebhookResponse

NOW = datetime(2026, 7, 29, 8, tzinfo=UTC)
MESSAGE = NotificationMessage(
    title="每日选股",
    body="共选出 2 只股票",
    format=MessageFormat.MARKDOWN,
)


class FakeTransport:
    def __init__(
        self,
        *,
        response: WebhookResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response or WebhookResponse(status_code=204)
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def post_json(
        self,
        *,
        url: str,
        payload: dict[str, object],
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> WebhookResponse:
        self.calls.append(
            {
                "url": url,
                "payload": payload,
                "headers": headers,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.error is not None:
            raise self.error
        return self.response


def test_console_notifier_provides_zero_config_preview() -> None:
    output: list[str] = []
    notifier = ConsoleNotifier(writer=output.append, clock=lambda: NOW)

    receipt = notifier.send(MESSAGE, idempotency_key="run:2026-07-29")

    assert output == ["每日选股\n共选出 2 只股票"]
    assert receipt.notifier_id == "console"
    assert receipt.status is DeliveryStatus.SENT
    assert receipt.delivered_at == NOW


def test_webhook_requires_https_without_embedded_credentials() -> None:
    for url in (
        "http://relay.example.test/hook",
        "https://user:password@relay.example.test/hook",
        "https:///missing-host",
    ):
        with pytest.raises(ValueError):
            WebhookNotifier(notifier_id="webhook.main", url=url)


def test_webhook_posts_neutral_json_with_idempotency_evidence() -> None:
    transport = FakeTransport(
        response=WebhookResponse(status_code=202, external_id="request-42")
    )
    notifier = WebhookNotifier(
        notifier_id="webhook.main",
        url="https://relay.example.test/private-hook-token",
        transport=transport,
        timeout_seconds=4.5,
        clock=lambda: NOW,
    )

    receipt = notifier.send(MESSAGE, idempotency_key="run:2026-07-29")

    assert receipt.external_id == "request-42"
    assert transport.calls == [
        {
            "url": "https://relay.example.test/private-hook-token",
            "payload": {
                "idempotency_key": "run:2026-07-29",
                "title": "每日选股",
                "body": "共选出 2 只股票",
                "format": "markdown",
            },
            "headers": {
                "Content-Type": "application/json; charset=utf-8",
                "Idempotency-Key": "run:2026-07-29",
            },
            "timeout_seconds": 4.5,
        }
    ]


@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [(400, False), (408, True), (429, True), (503, True)],
)
def test_webhook_classifies_non_success_status(
    status_code: int,
    retryable: bool,
) -> None:
    secret_url = "https://relay.example.test/secret-token"
    notifier = WebhookNotifier(
        notifier_id="webhook.main",
        url=secret_url,
        transport=FakeTransport(
            response=WebhookResponse(status_code=status_code)
        ),
    )

    with pytest.raises(NotificationError) as captured:
        notifier.send(MESSAGE, idempotency_key="dedupe")

    assert captured.value.retryable is retryable
    assert captured.value.error_code == f"http_{status_code}"
    assert secret_url not in str(captured.value)
    assert "secret-token" not in str(captured.value)


def test_webhook_timeout_is_retryable_and_secret_safe() -> None:
    notifier = WebhookNotifier(
        notifier_id="webhook.main",
        url="https://relay.example.test/secret-token",
        transport=FakeTransport(error=TimeoutError("secret-token")),
    )

    with pytest.raises(NotificationError) as captured:
        notifier.send(MESSAGE, idempotency_key="dedupe")

    assert captured.value.retryable is True
    assert captured.value.error_code == "transport_unavailable"
    assert "secret-token" not in str(captured.value)
