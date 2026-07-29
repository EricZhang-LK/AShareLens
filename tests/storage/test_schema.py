from sqlalchemy import Engine, inspect
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from asharelens.storage.database import Base, create_database_engine
from asharelens.storage.models import (
    DailyBarRow,
    DataPartitionRow,
    IngestionBatchRow,
    PublishedPartitionRow,
)


def test_schema_creates_on_in_memory_sqlite_for_repository_tests() -> None:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")

    Base.metadata.create_all(engine)

    assert set(inspect(engine).get_table_names()) == {
        "daily_bars",
        "data_partitions",
        "ingestion_batches",
        "published_partitions",
    }


def test_mysql_ddl_uses_innodb_utf8mb4_and_decimal_prices() -> None:
    ddl = str(
        CreateTable(DailyBarRow.__table__).compile(dialect=mysql.dialect())
    ).upper()

    assert "ENGINE=INNODB" in ddl
    assert "CHARSET=UTF8MB4" in ddl
    assert "DECIMAL(18, 6)" in ddl
    assert " FLOAT" not in ddl


def test_schema_declares_required_idempotency_constraints() -> None:
    constraint_names = {
        constraint.name
        for table in (
            IngestionBatchRow.__table__,
            DataPartitionRow.__table__,
            PublishedPartitionRow.__table__,
        )
        for constraint in table.constraints
        if constraint.name is not None
    }

    assert {
        "uq_ingestion_batch_source",
        "uq_data_partition_content",
        "pk_published_partition",
    } <= constraint_names


def test_database_factory_returns_sqlalchemy_engine() -> None:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")

    assert isinstance(engine, Engine)
