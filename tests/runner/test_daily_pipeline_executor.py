from datetime import date, datetime

from asharelens.runner.job_repository import JobRepository
from asharelens.runner.workflows.daily_pipeline import (
    DailyPipelineExecutor,
    DailyPipelineResult,
    DailyPipelineStatus,
)
from asharelens.storage.database import (
    Base,
    create_database_engine,
    create_session_factory,
)


class RecordingPipeline:
    def __init__(self) -> None:
        self.target_date: date | None = None

    def run(self, request):
        self.target_date = request.target_date
        return DailyPipelineResult(
            status=DailyPipelineStatus.COMPLETED,
            provider_id="baostock",
            published_partitions=20,
            processed_sessions=(request.target_date,),
            latest_fingerprint="a" * 64,
            notification_ids=("delivery-1",),
        )


def test_executor_derives_china_date_from_persisted_schedule_fire() -> None:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    configuration = {
        "account_name": "测试组合",
        "symbols": ["sh.600000"],
        "provider_ids": ["baostock"],
        "strategy_id": "moving_average",
        "lookback_calendar_days": 120,
        "notifier_ids": ["console"],
        "target_timezone": "Asia/Shanghai",
    }
    with factory.begin() as session:
        queued = JobRepository(session).enqueue(
            job_type="daily.pipeline",
            idempotency_key="daily:one",
            payload={
                "input": configuration,
                "schedule": {
                    "id": "schedule-1",
                    "planned_fire_at": "2026-07-30T10:00:00Z",
                },
            },
            now=datetime(2026, 7, 30, 10),
        )
    recording = RecordingPipeline()
    heartbeats = 0

    def heartbeat() -> None:
        nonlocal heartbeats
        heartbeats += 1

    result = DailyPipelineExecutor(
        service=recording,  # type: ignore[arg-type]
        clock=lambda: datetime(2020, 1, 1),
    )(queued, heartbeat)

    assert recording.target_date == date(2026, 7, 30)
    assert result["status"] == "completed"
    assert result["processed_sessions"] == ["2026-07-30"]
    assert heartbeats == 2
