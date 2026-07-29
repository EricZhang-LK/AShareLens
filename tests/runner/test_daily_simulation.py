from datetime import date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from asharelens.core.engine import DailyCycleEngine
from asharelens.core.execution import OpeningExecutionModel
from asharelens.demo.data import generate_demo_bars
from asharelens.runner.workflows.daily_simulation import (
    DailySimulationService,
    SimulationReplayConflict,
)
from asharelens.storage.database import Base, create_database_engine
from asharelens.storage.models import (
    SimulationCandidateRow,
    SimulationFillRow,
    SimulationOrderRow,
    SimulationRunRow,
)
from asharelens.strategies.moving_average import (
    MovingAverageParams,
    MovingAverageStrategy,
)


@pytest.fixture
def session() -> Session:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as database_session:
        yield database_session


def _engine() -> DailyCycleEngine[MovingAverageParams]:
    return DailyCycleEngine(
        strategy=MovingAverageStrategy(),
        params=MovingAverageParams(fast_period=10, slow_period=30, confirm_days=3),
        execution_model=OpeningExecutionModel(
            slippage_bps=0,
            commission_rate=0,
            minimum_commission=0,
            transfer_fee_rate=0,
            stamp_duty_rate=0,
        ),
        initial_cash=100_000,
        top_n=1,
        max_weight=1,
    )


def test_daily_simulation_matches_historical_shared_engine(
    session: Session,
) -> None:
    bars = generate_demo_bars(date(2026, 1, 5), sessions=80)
    engine = _engine()
    historical = engine.run(bars)
    service = DailySimulationService(session, engine=engine)
    account = service.create_account(name="等价性账户", now=datetime(2026, 1, 1))
    daily_candidates = []
    daily_orders = []
    daily_fills = []
    daily_nav = []

    session_dates = sorted(
        {bar.trade_date for observations in bars.values() for bar in observations}
    )
    for session_date in session_dates:
        history = {
            symbol: tuple(
                bar for bar in observations if bar.trade_date <= session_date
            )
            for symbol, observations in bars.items()
        }
        run = service.process_session(
            account_id=account.id,
            session_date=session_date,
            history=history,
            partition_ids=(f"synthetic:{session_date.isoformat()}",),
            now=datetime(2026, 7, 29, 8),
        )
        daily_candidates.extend(run.candidates)
        daily_orders.extend(run.orders)
        daily_fills.extend(run.fills)
        daily_nav.append(run.nav)

    assert tuple(daily_candidates) == historical.candidates
    assert tuple(daily_orders) == historical.orders
    assert tuple(daily_fills) == historical.fills
    assert tuple(daily_nav) == historical.nav
    assert len(run.fingerprint) == 64
    assert len(run.input_state_hash) == 64
    assert len(run.output_state_hash) == 64


def test_daily_simulation_is_idempotent_without_duplicate_ledgers(
    session: Session,
) -> None:
    bars = generate_demo_bars(date(2026, 1, 5), sessions=35)
    engine = _engine()
    service = DailySimulationService(session, engine=engine)
    account = service.create_account(name="幂等账户", now=datetime(2026, 1, 1))
    session_date = max(bar.trade_date for bar in bars["demo.000001"])

    first = service.process_session(
        account_id=account.id,
        session_date=session_date,
        history=bars,
        partition_ids=("partition-35",),
        now=datetime(2026, 7, 29, 8),
    )
    duplicate = service.process_session(
        account_id=account.id,
        session_date=session_date,
        history=bars,
        partition_ids=("partition-35",),
        now=datetime(2026, 7, 29, 8, 1),
    )

    assert duplicate == first
    assert session.scalar(select(func.count()).select_from(SimulationRunRow)) == 1
    assert session.scalar(
        select(func.count()).select_from(SimulationCandidateRow)
    ) == len(first.candidates)
    assert session.scalar(
        select(func.count()).select_from(SimulationOrderRow)
    ) == len(first.orders)
    assert session.scalar(
        select(func.count()).select_from(SimulationFillRow)
    ) == len(first.fills)


def test_daily_simulation_rejects_changed_inputs_for_completed_date(
    session: Session,
) -> None:
    bars = generate_demo_bars(date(2026, 1, 5), sessions=35)
    service = DailySimulationService(session, engine=_engine())
    account = service.create_account(name="冲突账户", now=datetime(2026, 1, 1))
    session_date = max(bar.trade_date for bar in bars["demo.000001"])
    service.process_session(
        account_id=account.id,
        session_date=session_date,
        history=bars,
        partition_ids=("partition-original",),
        now=datetime(2026, 7, 29, 8),
    )

    with pytest.raises(SimulationReplayConflict):
        service.process_session(
            account_id=account.id,
            session_date=session_date,
            history=bars,
            partition_ids=("partition-revised",),
            now=datetime(2026, 7, 29, 8, 1),
        )


def test_daily_simulation_rejects_changed_execution_configuration(
    session: Session,
) -> None:
    bars = generate_demo_bars(date(2026, 1, 5), sessions=35)
    original = DailySimulationService(session, engine=_engine())
    account = original.create_account(
        name="执行配置冲突账户",
        now=datetime(2026, 1, 1),
    )
    session_date = max(bar.trade_date for bar in bars["demo.000001"])
    first = original.process_session(
        account_id=account.id,
        session_date=session_date,
        history=bars,
        partition_ids=("partition-35",),
        now=datetime(2026, 7, 29, 8),
    )
    changed_engine = DailyCycleEngine(
        strategy=MovingAverageStrategy(),
        params=MovingAverageParams(fast_period=10, slow_period=30, confirm_days=3),
        execution_model=OpeningExecutionModel(
            slippage_bps=25,
            commission_rate=0,
            minimum_commission=0,
            transfer_fee_rate=0,
            stamp_duty_rate=0,
        ),
        initial_cash=100_000,
        top_n=2,
        max_weight=0.5,
    )

    assert first.execution_config["top_n"] == 1
    with pytest.raises(SimulationReplayConflict):
        DailySimulationService(session, engine=changed_engine).process_session(
            account_id=account.id,
            session_date=session_date,
            history=bars,
            partition_ids=("partition-35",),
            now=datetime(2026, 7, 29, 8, 1),
        )
