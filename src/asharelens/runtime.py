"""Production composition root for providers, notifiers and Runner executors."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from asharelens.config import RuntimeSettings
from asharelens.data.provider import DataProviderPlugin
from asharelens.data.providers.akshare import AkShareProvider
from asharelens.data.providers.baostock import BaoStockProvider
from asharelens.data.providers.tushare import TushareProvider
from asharelens.notifications.console import ConsoleNotifier
from asharelens.notifications.notifier import NotifierRegistry
from asharelens.notifications.webhook import WebhookNotifier
from asharelens.runner.executor import ExecutorRegistry
from asharelens.runner.worker import utc_now_naive
from asharelens.runner.workflows.daily_pipeline import (
    DailyPipelineExecutor,
    DailyPipelineService,
)
from asharelens.runner.workflows.notification_delivery import (
    NotificationDeliveryExecutor,
)
from asharelens.strategies.registry import StrategyRegistry


class RuntimeConfigurationError(ValueError):
    """Environment configuration references an unavailable runtime component."""


def build_provider_registry(
    settings: RuntimeSettings,
) -> dict[str, DataProviderPlugin]:
    """Construct only configured providers in declared fallback order."""

    factories: dict[str, Callable[[], DataProviderPlugin]] = {
        "baostock": BaoStockProvider,
        "akshare": AkShareProvider,
        "tushare": lambda: TushareProvider(token=settings.tushare_token),
    }
    missing = tuple(
        provider_id
        for provider_id in settings.provider_ids
        if provider_id not in factories
    )
    if missing:
        raise RuntimeConfigurationError(
            f"未知数据源：{', '.join(missing)}"
        )
    return {
        provider_id: factories[provider_id]()
        for provider_id in settings.provider_ids
    }


def build_notifier_registry(settings: RuntimeSettings) -> NotifierRegistry:
    """Construct credential-bearing transports without persisting their secrets."""

    registry = NotifierRegistry()
    registry.register(ConsoleNotifier())
    if settings.webhook_url:
        try:
            registry.register(
                WebhookNotifier(
                    notifier_id="webhook",
                    url=settings.webhook_url,
                )
            )
        except ValueError as error:
            raise RuntimeConfigurationError(
                "Webhook 地址必须是无内嵌凭据的 HTTPS URL"
            ) from error
    available = {"console"}
    if settings.webhook_url:
        available.add("webhook")
    missing = tuple(
        notifier_id
        for notifier_id in settings.notifier_ids
        if notifier_id not in available
    )
    if missing:
        raise RuntimeConfigurationError(
            f"通知渠道未配置：{', '.join(missing)}"
        )
    return registry


def build_executor_registry(
    *,
    session_factory: sessionmaker[Session],
    settings: RuntimeSettings,
    clock: Callable[[], datetime] = utc_now_naive,
) -> ExecutorRegistry:
    """Register all job adapters; Workers still claim only their own queue."""

    pipeline = build_daily_pipeline_service(
        session_factory=session_factory,
        settings=settings,
        clock=clock,
    )
    registry = ExecutorRegistry()
    registry.register(
        "daily.pipeline",
        DailyPipelineExecutor(service=pipeline, clock=clock),
    )
    registry.register(
        "notification.deliver",
        NotificationDeliveryExecutor(
            session_factory=session_factory,
            notifiers=build_notifier_registry(settings),
            clock=clock,
        ),
    )
    return registry


def build_daily_pipeline_service(
    *,
    session_factory: sessionmaker[Session],
    settings: RuntimeSettings,
    clock: Callable[[], datetime] = utc_now_naive,
) -> DailyPipelineService:
    """Compose the synchronous daily workflow for CLI and Runner reuse."""

    return DailyPipelineService(
        session_factory=session_factory,
        providers=build_provider_registry(settings),
        strategies=StrategyRegistry(),
        clock=clock,
    )
