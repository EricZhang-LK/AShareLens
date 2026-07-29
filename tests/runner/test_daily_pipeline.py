import hashlib
import json
from datetime import UTC, date, datetime

from sqlalchemy import func, select

from asharelens.core.models import DailyBar
from asharelens.data.models import Adjustment, DataBatch, Dataset
from asharelens.data.provider import ProviderMetadata
from asharelens.demo.data import generate_demo_bars
from asharelens.runner.models import JobStatus
from asharelens.runner.workflows.daily_pipeline import (
    DailyPipelineRequest,
    DailyPipelineService,
    DailyPipelineStatus,
)
from asharelens.storage.database import (
    Base,
    create_database_engine,
    create_session_factory,
)
from asharelens.storage.models import (
    NotificationDeliveryRow,
    RunnerJobRow,
    SimulationAccountRow,
    SimulationRunRow,
)
from asharelens.strategies.registry import StrategyRegistry


class HistoricalProvider:
    metadata = ProviderMetadata(
        provider_id="history",
        name="history",
        version="1.0",
        description="deterministic history",
        datasets=(Dataset.DAILY_BARS,),
        requires_registration=False,
    )

    def __init__(self, bars: dict[str, tuple[DailyBar, ...]]) -> None:
        self.bars = bars

    def fetch_daily_bars(
        self,
        symbols: tuple[str, ...],
        start: date,
        end: date,
        adjustment: Adjustment,
    ) -> DataBatch[DailyBar]:
        records = tuple(
            bar
            for symbol in symbols
            for bar in self.bars[symbol]
            if start <= bar.trade_date <= end
        )
        evidence = json.dumps(
            [bar.model_dump(mode="json") for bar in records],
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(evidence.encode()).hexdigest()
        return DataBatch[DailyBar](
            dataset=Dataset.DAILY_BARS,
            provider_id="history",
            provider_version="1.0",
            fetched_at=datetime(2026, 7, 30, tzinfo=UTC),
            request={"start": start.isoformat(), "end": end.isoformat()},
            source_batch_id=f"history-{end.isoformat()}",
            content_hash=digest,
            records=records,
        )


def _request(target_date: date, symbols: tuple[str, ...]) -> DailyPipelineRequest:
    return DailyPipelineRequest(
        account_name="每日研究组合",
        target_date=target_date,
        symbols=symbols,
        provider_ids=("history",),
        strategy_id="moving_average",
        strategy_parameters={
            "fast_period": 10,
            "slow_period": 30,
            "confirm_days": 3,
        },
        lookback_calendar_days=120,
        initial_cash=100_000,
        top_n=1,
        max_weight=1,
        notifier_ids=("console",),
    )


def test_daily_pipeline_creates_then_advances_account_and_enqueues_latest() -> None:
    bars = generate_demo_bars(date(2026, 1, 5), sessions=45)
    symbols = tuple(sorted(bars))
    session_dates = sorted(
        {bar.trade_date for observations in bars.values() for bar in observations}
    )
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    service = DailyPipelineService(
        session_factory=factory,
        providers={"history": HistoricalProvider(bars)},
        strategies=StrategyRegistry(entry_points_provider=lambda: ()),
        clock=lambda: datetime(2026, 7, 30, tzinfo=UTC),
    )

    first = service.run(_request(session_dates[39], symbols))
    second = service.run(_request(session_dates[40], symbols))
    duplicate = service.run(_request(session_dates[40], symbols))

    assert first.status is DailyPipelineStatus.COMPLETED
    assert first.processed_sessions == (session_dates[39],)
    assert second.processed_sessions == (session_dates[40],)
    assert duplicate.status is DailyPipelineStatus.NO_NEW_SESSION
    assert duplicate.processed_sessions == ()

    with factory() as session:
        assert session.scalar(
            select(func.count()).select_from(SimulationAccountRow)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(SimulationRunRow)
        ) == 2
        assert session.scalar(
            select(func.count()).select_from(NotificationDeliveryRow)
        ) == 2
        jobs = tuple(
            session.scalars(
                select(RunnerJobRow).order_by(RunnerJobRow.created_at)
            )
        )
        assert len(jobs) == 2
        assert all(job.queue == "notifications" for job in jobs)
        assert all(job.status == JobStatus.QUEUED.value for job in jobs)
