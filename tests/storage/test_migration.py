from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from asharelens.storage.database import create_database_engine


def test_initial_migration_upgrades_and_downgrades_empty_database(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "migration.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("ASHARELENS_DATABASE_URL", database_url)
    project_root = Path(__file__).parents[2]
    config = Config(str(project_root / "alembic.ini"))

    command.upgrade(config, "head")

    engine = create_database_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    assert {
        "alembic_version",
        "daily_bars",
        "data_partitions",
        "ingestion_batches",
        "published_partitions",
    } <= tables

    command.downgrade(config, "base")

    remaining = set(inspect(engine).get_table_names())
    assert not {
        "daily_bars",
        "data_partitions",
        "ingestion_batches",
        "published_partitions",
    } & remaining
