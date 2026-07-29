"""Generic secret-safe HTTPS JSON webhook notification plugin."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib import error, request
from urllib.parse import urlsplit

from asharelens.notifications.models import DeliveryReceipt, NotificationMessage
from asharelens.notifications.notifier import (
    NotificationError,
    NotifierMetadata,
)


@dataclass(frozen=True, slots=True)
class WebhookResponse:
    """Minimal transport response without provider body or secrets."""

    status_code: int
    external_id: str | None = None


class WebhookTransport(Protocol):
    """Injectable HTTP boundary for deterministic tests."""

    def post_json(
        self,
        *,
        url: str,
        payload: dict[str, object],
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> WebhookResponse:
        """POST a JSON object and return sanitized response metadata."""
        ...


class UrllibWebhookTransport:
    """Small standard-library HTTPS transport."""

    def post_json(
        self,
        *,
        url: str,
        payload: dict[str, object],
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> WebhookResponse:
        """Send compact UTF-8 JSON without retaining a response body."""

        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        outbound = request.Request(
            url,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(outbound, timeout=timeout_seconds) as response:
                return WebhookResponse(
                    status_code=response.status,
                    external_id=_external_id(response.headers),
                )
        except error.HTTPError as exc:
            try:
                return WebhookResponse(
                    status_code=exc.code,
                    external_id=_external_id(exc.headers),
                )
            finally:
                exc.close()


class WebhookNotifier:
    """Send a channel-neutral payload to a user-configured relay."""

    def __init__(
        self,
        *,
        notifier_id: str,
        url: str,
        transport: WebhookTransport | None = None,
        timeout_seconds: float = 10,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not notifier_id:
            raise ValueError("notifier_id must not be empty")
        _validate_https_url(url)
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.metadata = NotifierMetadata(
            notifier_id=notifier_id,
            name="Generic HTTPS Webhook",
            version="1.0.0",
            description="POST channel-neutral JSON to a configured HTTPS relay.",
        )
        self._url = url
        self._transport = transport or UrllibWebhookTransport()
        self._timeout_seconds = timeout_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    def send(
        self,
        message: NotificationMessage,
        *,
        idempotency_key: str,
    ) -> DeliveryReceipt:
        """Deliver a message with end-to-end deduplication evidence."""

        _validate_idempotency_key(idempotency_key)
        payload: dict[str, object] = {
            "idempotency_key": idempotency_key,
            "title": message.title,
            "body": message.body,
            "format": message.format.value,
        }
        try:
            response = self._transport.post_json(
                url=self._url,
                payload=payload,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Idempotency-Key": idempotency_key,
                },
                timeout_seconds=self._timeout_seconds,
            )
        except OSError as exc:
            raise NotificationError(
                notifier_id=self.metadata.notifier_id,
                error_code="transport_unavailable",
                message="webhook transport is temporarily unavailable",
                retryable=True,
            ) from exc

        if not 200 <= response.status_code < 300:
            raise NotificationError(
                notifier_id=self.metadata.notifier_id,
                error_code=f"http_{response.status_code}",
                message=f"webhook returned HTTP {response.status_code}",
                retryable=_is_retryable_status(response.status_code),
            )
        return DeliveryReceipt(
            notifier_id=self.metadata.notifier_id,
            delivered_at=self._clock(),
            external_id=response.external_id,
        )


def _validate_https_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError(
            "webhook URL must be HTTPS, contain a host, and exclude credentials/fragments"
        )


def _validate_idempotency_key(value: str) -> None:
    if not value or len(value) > 160 or "\r" in value or "\n" in value:
        raise ValueError("idempotency_key must be 1..160 header-safe characters")


def _external_id(headers: object) -> str | None:
    get = getattr(headers, "get", None)
    if not callable(get):
        return None
    value = get("X-Request-Id") or get("X-Message-Id")
    return str(value)[:256] if value else None


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {408, 425, 429} or status_code >= 500
