from datetime import datetime, time

import pytest
from sqlalchemy.orm import Session

from asharelens.runner.models import JobStatus
from asharelens.runner.scheduler import PersistentScheduler
from asharelens.storage.database import Base, create_database_engine
from asharelens.storage.models import RunnerJobRow


@pytest.fixture
def session() -> Session:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as database_session:
        yield database_session


def test_daily_schedule_uses_shanghai_boundary_and_emits_once(
    session: Session,
) -> None:
    scheduler = PersistentScheduler(session)
    schedule = scheduler.create_daily(
        name="每日收盘选股",
        job_type="daily_selection",
        local_time=time(15, 5),
        weekdays=(0, 1, 2, 3, 4),
        payload={"plan_id": "plan-a"},
        now=datetime(2026, 7, 29, 7, 0),
    )

    assert schedule.timezone == "Asia/Shanghai"
    assert schedule.next_fire_at == datetime(2026, 7, 29, 7, 5)
    assert scheduler.run_due(now=datetime(2026, 7, 29, 7, 4)).enqueued == ()

    first = scheduler.run_due(now=datetime(2026, 7, 29, 7, 5))
    repeated = scheduler.run_due(now=datetime(2026, 7, 29, 7, 5))

    assert len(first.enqueued) == 1
    assert first.enqueued[0].status is JobStatus.QUEUED
    assert first.enqueued[0].payload == {
        "input": {"plan_id": "plan-a"},
        "schedule": {
            "id": schedule.id,
            "planned_fire_at": "2026-07-29T07:05:00Z",
        },
    }
    assert repeated.enqueued == ()


def test_catch_up_emits_only_most_recent_bounded_fires(session: Session) -> None:
    scheduler = PersistentScheduler(session)
    schedule = scheduler.create_daily(
        name="补跑选股",
        job_type="daily_selection",
        local_time=time(15, 0),
        weekdays=(0, 1, 2, 3, 4, 5, 6),
        payload={},
        catch_up_limit=2,
        now=datetime(2026, 7, 27, 6, 0),
    )

    tick = scheduler.run_due(now=datetime(2026, 7, 29, 8, 0))

    assert [
        job.payload["schedule"]["planned_fire_at"]
        for job in tick.enqueued
    ] == [
        "2026-07-28T07:00:00Z",
        "2026-07-29T07:00:00Z",
    ]
    refreshed = scheduler.get(schedule.id)
    assert refreshed.next_fire_at == datetime(2026, 7, 30, 7, 0)


def test_disabled_schedule_does_not_enqueue(session: Session) -> None:
    scheduler = PersistentScheduler(session)
    schedule = scheduler.create_daily(
        name="已停用",
        job_type="daily_selection",
        local_time=time(15, 0),
        weekdays=(0, 1, 2, 3, 4),
        payload={},
        now=datetime(2026, 7, 29, 6, 0),
    )
    scheduler.set_enabled(
        schedule.id,
        enabled=False,
        now=datetime(2026, 7, 29, 6, 1),
    )

    tick = scheduler.run_due(now=datetime(2026, 7, 29, 8, 0))

    assert tick.enqueued == ()
    assert session.query(RunnerJobRow).count() == 0


def test_schedule_validates_weekdays_and_catch_up_limit(session: Session) -> None:
    scheduler = PersistentScheduler(session)

    with pytest.raises(ValueError):
        scheduler.create_daily(
            name="无工作日",
            job_type="probe",
            local_time=time(15),
            weekdays=(),
            payload={},
            now=datetime(2026, 7, 29, 6),
        )
    with pytest.raises(ValueError):
        scheduler.create_daily(
            name="无限补跑",
            job_type="probe",
            local_time=time(15),
            weekdays=(0,),
            payload={},
            catch_up_limit=0,
            now=datetime(2026, 7, 29, 6),
        )
