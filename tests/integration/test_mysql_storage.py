import os
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from asharelens.core.models import DailyBar
from asharelens.data.models import DataBatch, Dataset
from asharelens.data.partition import partition_daily_bars
from asharelens.data.quality import QualityReport
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

