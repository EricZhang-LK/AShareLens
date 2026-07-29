from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select
from typer.testing import CliRunner

from asharelens.cli import app
from asharelens.runner.job_repository import JobRepository
from asharelens.runner.models import JobStatus
from asharelens.runner.scheduler import PersistentScheduler
from asharelens.storage.database import (
    create_database_engine,
    create_session_factory,
)
from asharelens.storage.models import RunnerJobRow, RunnerScheduleRow


@pytest.fixture
def database_url(tmp_path: Path, monkeypatch) -> str:
    path = tmp_path / "runner.sqlite3"
    url = f"sqlite+pysqlite:///{path.as_posix()}"
    monkeypatch.setenv("ASHARELENS_DATABASE_URL", url)
    project_root = Path(__file__).parents[1]
    command.upgrade(Config(str(project_root / "alembic.ini")), "head")
    return url


def test_runner_doctor_reports_migration_and_queue_health(
    database_url: str,
) -> None:
    result = CliRunner().invoke(app, ["runner", "doctor"])
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    migration_head = ScriptDirectory.from_config(config).get_current_head()

    assert result.exit_code == 0
    assert "正常" in result.stdout
    assert migration_head is not None
    assert migration_head in result.stdout
    assert "待处理 0" in result.stdout


def test_runner_start_once_coordinates_all_components(database_url: str) -> None:
    result = CliRunner().invoke(app, ["runner", "start", "--once"])

    assert result.exit_code == 0
    assert "投递 0" in result.stdout
    assert "回收 0" in result.stdout
    assert "idle" in result.stdout


def test_runner_work_once_persists_unknown_type_as_failure(
    database_url: str,
) -> None:
    factory = create_session_factory(create_database_engine(database_url))
    with factory.begin() as session:
        job = JobRepository(session).enqueue(
            job_type="missing.executor",
            idempotency_key="missing:one",
            payload={},
            now=datetime(2026, 7, 29, 8),
        )

    result = CliRunner().invoke(app, ["runner", "work", "--once"])

    assert result.exit_code == 0
    assert "failed" in result.stdout
    with factory() as session:
        assert JobRepository(session).get(job.id).status is JobStatus.FAILED


def test_runner_schedule_and_reap_once(database_url: str) -> None:
    factory = create_session_factory(create_database_engine(database_url))
    with factory.begin() as session:
        PersistentScheduler(session).create_daily(
            name="CLI 日程",
            job_type="daily_selection",
            local_time=time(15),
            weekdays=(0, 1, 2, 3, 4, 5, 6),
            payload={},
            now=datetime(2020, 1, 1),
        )

    scheduled = CliRunner().invoke(app, ["runner", "schedule", "--once"])
    repeated = CliRunner().invoke(app, ["runner", "schedule", "--once"])

    assert scheduled.exit_code == 0
    assert "投递 1" in scheduled.stdout
    assert repeated.exit_code == 0
    assert "投递 0" in repeated.stdout

    claim_time = datetime.now(UTC).replace(tzinfo=None)
    with factory.begin() as session:
        claimed = JobRepository(session).claim(
            queue="default",
            worker_id="crashed-cli-worker",
            now=claim_time,
            lease_for=timedelta(microseconds=1),
        )
        assert claimed is not None

    reaped = CliRunner().invoke(app, ["runner", "reap", "--once"])

    assert reaped.exit_code == 0
    assert "回收 1" in reaped.stdout


def test_runner_init_and_manual_enqueue_are_idempotent(
    database_url: str,
) -> None:
    first = CliRunner().invoke(app, ["runner", "init"])
    repeated = CliRunner().invoke(app, ["runner", "init"])
    enqueued = CliRunner().invoke(
        app,
        ["runner", "enqueue-daily", "--date", "2026-07-30"],
    )
    duplicate = CliRunner().invoke(
        app,
        ["runner", "enqueue-daily", "--date", "2026-07-30"],
    )

    assert first.exit_code == 0
    assert repeated.exit_code == 0
    assert "日程已就绪" in repeated.stdout
    assert enqueued.exit_code == 0
    assert duplicate.exit_code == 0
    factory = create_session_factory(create_database_engine(database_url))
    with factory() as session:
        assert session.scalar(
            select(func.count()).select_from(RunnerScheduleRow)
        ) == 1
        jobs = tuple(session.scalars(select(RunnerJobRow)))
        assert len(jobs) == 1
        assert jobs[0].job_type == "daily.pipeline"
        assert jobs[0].queue == "default"
