import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from asharelens.core.models import DailyBar
from asharelens.data.models import DataBatch, Dataset
from asharelens.data.partition import partition_daily_bars
from asharelens.data.quality import QualityReport
from asharelens.runner.job_repository import JobRepository
from asharelens.storage.data_repository import DataRepository
from asharelens.storage.database import (
    create_database_engine,
    create_session_factory,
)

pytestmark = pytest.mark.mysql


def test_mysql_84_migration_and_idempotent_publication() -> None:
    database_url = os.getenv("ASHARELENS_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("ASHARELENS_TEST_DATABASE_URL is not configured")

    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    command.downgrade(config, "base")
    try:
        command.upgrade(config, "head")
        engine = create_database_engine(database_url)
        factory = create_session_factory(engine)
        trade_date = date(2026, 7, 1)
        batch = DataBatch[DailyBar](
            dataset=Dataset.DAILY_BARS,
            provider_id="mysql-integration",
            provider_version="1",
            fetched_at=datetime(2026, 7, 1, 10, tzinfo=UTC),
            request={"date": trade_date.isoformat()},
            source_batch_id="mysql-batch-1",
            content_hash="a" * 64,
            records=(
                DailyBar(
                    symbol="sh.600000",
                    trade_date=trade_date,
                    open=10,
                    high=10.1,
                    low=9.9,
                    close=10,
                    volume=1000,
                    amount=10_000,
                ),
            ),
        )
        partition = partition_daily_bars(batch)[0]
        report = QualityReport(coverage=1, issues=())

        with factory.begin() as session:
            repository = DataRepository(session)
            repository.record_batch(batch)
            first = repository.publish_daily_partition(partition, report)
            second = repository.publish_daily_partition(partition, report)
            assert first == second

        with engine.connect() as connection:
            table = connection.execute(
                text(
                    """
                    SELECT ENGINE, TABLE_COLLATION
                    FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = 'daily_bars'
                    """
                )
            ).one()
            assert table.ENGINE == "InnoDB"
            assert table.TABLE_COLLATION.startswith("utf8mb4")
    finally:
        command.downgrade(config, "base")


def test_mysql_skip_locked_prevents_duplicate_concurrent_claim() -> None:
    database_url = os.getenv("ASHARELENS_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("ASHARELENS_TEST_DATABASE_URL is not configured")

    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    command.downgrade(config, "base")
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    now = datetime(2026, 7, 29, 8)
    first_session = factory()
    second_session = factory()
    try:
        command.upgrade(config, "head")
        with factory.begin() as enqueue_session:
            JobRepository(enqueue_session).enqueue(
                job_type="mysql_claim_probe",
                idempotency_key="one-job",
                payload={},
                now=now,
            )

        first = JobRepository(first_session).claim(
            queue="default",
            worker_id="worker-a",
            now=now,
            lease_for=timedelta(seconds=30),
        )
        second = JobRepository(second_session).claim(
            queue="default",
            worker_id="worker-b",
            now=now,
            lease_for=timedelta(seconds=30),
        )

        assert first is not None
        assert second is None
    finally:
        first_session.rollback()
        second_session.rollback()
        first_session.close()
        second_session.close()
        engine.dispose()
        command.downgrade(config, "base")
