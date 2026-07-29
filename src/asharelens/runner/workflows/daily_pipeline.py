"""End-to-end daily data, paper simulation and notification workflow."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session, sessionmaker

from asharelens.core.engine import DailyCycleEngine
from asharelens.core.execution import OpeningExecutionModel
from asharelens.core.models import DailyBar
from asharelens.data.models import Adjustment, Dataset
from asharelens.data.provider import DataProviderPlugin
from asharelens.data.quality import DailyBarQualityGate
from asharelens.notifications.render import render_daily_selection
from asharelens.runner.workflows.daily_simulation import DailySimulationService
from asharelens.runner.workflows.market_sync import (
    MarketDataSynchronizer,
    MarketSyncStatus,
)
from asharelens.storage.data_repository import DataRepository, PublishedDailyData
from asharelens.storage.notification_repository import NotificationRepository
from asharelens.storage.simulation_repository import (
    SimulationRepository,
    SimulationRunSnapshot,
)
from asharelens.strategies.registry import StrategyRegistry


class DailyPipelineRequest(BaseModel):
    """Validated, serializable inputs for one daily research cycle."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_name: str = Field(min_length=1, max_length=128)
    target_date: date
    symbols: tuple[str, ...] = Field(min_length=1)
    provider_ids: tuple[str, ...] = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    strategy_parameters: dict[str, Any] = Field(default_factory=dict)
    lookback_calendar_days: int = Field(default=550, ge=30, le=3650)
    adjustment: Adjustment = Adjustment.NONE
    min_coverage: float = Field(default=0.98, ge=0, le=1)
    initial_cash: float = Field(default=1_000_000, gt=0)
    top_n: int = Field(default=10, ge=1, le=500)
    max_weight: float = Field(default=0.1, gt=0, le=1)
    execution_model: OpeningExecutionModel = Field(
        default_factory=OpeningExecutionModel
    )
    notifier_ids: tuple[str, ...] = ("console",)

    @field_validator("symbols", "provider_ids", "notifier_ids")
    @classmethod
    def unique_non_empty_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("values must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("values must be unique")
        return normalized


class DailyPipelineStatus(StrEnum):
    """Stable operator-facing outcome."""

    COMPLETED = "completed"
    NO_DATA = "no_data"
    NO_NEW_SESSION = "no_new_session"


@dataclass(frozen=True, slots=True)
class DailyPipelineResult:
    """Evidence returned to Runner and manual invocations."""

    status: DailyPipelineStatus
    provider_id: str | None
    published_partitions: int
    processed_sessions: tuple[date, ...]
    latest_fingerprint: str | None
    notification_ids: tuple[str, ...]


class PipelineConfigurationError(ValueError):
    """Persisted job configuration cannot be executed safely."""


class CatchUpWindowTooShort(ValueError):
    """The requested history cannot bridge the paper account's last session."""


class DailyPipelineService:
    """Coordinate external fetches and one atomic local publication/run."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        providers: Mapping[str, DataProviderPlugin],
        strategies: StrategyRegistry,
        clock: Callable[[], datetime],
    ) -> None:
        self._session_factory = session_factory
        self._providers = dict(providers)
        self._strategies = strategies
        self._clock = clock

    def run(self, request: DailyPipelineRequest) -> DailyPipelineResult:
        """Synchronize, catch up the account, and enqueue the latest result."""

        providers = self._resolve_providers(request.provider_ids)
        plugin = self._strategies.get(request.strategy_id)
        params = plugin.parameter_model().model_validate(
            request.strategy_parameters
        )
        engine = DailyCycleEngine(
            strategy=plugin,
            params=params,
            execution_model=request.execution_model,
            initial_cash=request.initial_cash,
            top_n=request.top_n,
            max_weight=request.max_weight,
        )
        synchronizer = MarketDataSynchronizer(
            providers=providers,
            quality_gate=DailyBarQualityGate(
                min_coverage=request.min_coverage
            ),
        )
        start = request.target_date - timedelta(
            days=request.lookback_calendar_days
        )
        fetched = synchronizer.fetch_range(
            start=start,
            end=request.target_date,
            symbols=request.symbols,
            adjustment=request.adjustment,
        )
        if fetched.status is MarketSyncStatus.NO_DATA:
            return DailyPipelineResult(
                status=DailyPipelineStatus.NO_DATA,
                provider_id=None,
                published_partitions=0,
                processed_sessions=(),
                latest_fingerprint=None,
                notification_ids=(),
            )

        now = self._clock()
        with self._session_factory.begin() as session:
            published_ids = synchronizer.publish(session, fetched)
            published = DataRepository(session).get_published_daily_range(
                Dataset.DAILY_BARS,
                start,
                request.target_date,
            )
            result = self._advance_and_notify(
                session=session,
                request=request,
                engine=engine,
                published=published,
                now=now,
            )
        provider_id = fetched.batch.provider_id if fetched.batch is not None else None
        return DailyPipelineResult(
            status=result.status,
            provider_id=provider_id,
            published_partitions=len(published_ids),
            processed_sessions=result.processed_sessions,
            latest_fingerprint=result.latest_fingerprint,
            notification_ids=result.notification_ids,
        )

    def _advance_and_notify(
        self,
        *,
        session: Session,
        request: DailyPipelineRequest,
        engine: DailyCycleEngine[BaseModel],
        published: tuple[PublishedDailyData, ...],
        now: datetime,
    ) -> DailyPipelineResult:
        if not published:
            return DailyPipelineResult(
                status=DailyPipelineStatus.NO_DATA,
                provider_id=None,
                published_partitions=0,
                processed_sessions=(),
                latest_fingerprint=None,
                notification_ids=(),
            )

        simulation_repository = SimulationRepository(session)
        account = simulation_repository.get_account_by_name(
            request.account_name,
            for_update=True,
        )
        simulation = DailySimulationService(session, engine=engine)
        target_dates: tuple[date, ...]
        if account is None:
            account = simulation.create_account(
                name=request.account_name,
                now=now,
            )
            target_dates = (published[-1].partition_date,)
        else:
            if (
                account.last_session_date is not None
                and account.last_session_date < published[0].partition_date
                and published[0].partition_date - account.last_session_date
                > timedelta(days=7)
            ):
                raise CatchUpWindowTooShort(
                    "lookback window does not bridge the account's last session"
                )
            target_dates = tuple(
                item.partition_date
                for item in published
                if account.last_session_date is None
                or item.partition_date > account.last_session_date
            )
        if not target_dates:
            return DailyPipelineResult(
                status=DailyPipelineStatus.NO_NEW_SESSION,
                provider_id=None,
                published_partitions=0,
                processed_sessions=(),
                latest_fingerprint=None,
                notification_ids=(),
            )

        runs: list[SimulationRunSnapshot] = []
        for session_date in target_dates:
            visible = tuple(
                item
                for item in published
                if item.partition_date <= session_date
            )
            runs.append(
                simulation.process_session(
                    account_id=account.id,
                    session_date=session_date,
                    history=_history(visible),
                    partition_ids=tuple(item.partition_id for item in visible),
                    now=now,
                )
            )

        latest = runs[-1]
        message = render_daily_selection(
            account_name=account.name,
            run=latest,
        )
        notifications = NotificationRepository(session)
        delivery_ids = tuple(
            notifications.enqueue(
                notifier_id=notifier_id,
                dedupe_key=(
                    f"daily:{account.id}:{latest.session_date.isoformat()}:"
                    f"{latest.fingerprint}"
                ),
                message=message,
                now=now,
            ).id
            for notifier_id in request.notifier_ids
        )
        return DailyPipelineResult(
            status=DailyPipelineStatus.COMPLETED,
            provider_id=None,
            published_partitions=0,
            processed_sessions=tuple(run.session_date for run in runs),
            latest_fingerprint=latest.fingerprint,
            notification_ids=delivery_ids,
        )

    def _resolve_providers(
        self,
        provider_ids: tuple[str, ...],
    ) -> tuple[DataProviderPlugin, ...]:
        missing = tuple(
            provider_id
            for provider_id in provider_ids
            if provider_id not in self._providers
        )
        if missing:
            raise PipelineConfigurationError(
                f"unknown market data providers: {', '.join(missing)}"
            )
        return tuple(self._providers[provider_id] for provider_id in provider_ids)


def _history(
    published: tuple[PublishedDailyData, ...],
) -> dict[str, tuple[DailyBar, ...]]:
    grouped: defaultdict[str, list[DailyBar]] = defaultdict(list)
    for partition in published:
        for bar in partition.bars:
            grouped[bar.symbol].append(bar)
    return {
        symbol: tuple(sorted(observations, key=lambda bar: bar.trade_date))
        for symbol, observations in sorted(grouped.items())
    }
