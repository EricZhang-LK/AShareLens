from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from typer.testing import CliRunner

from asharelens.cli import app


def test_database_check_reports_current_migration_revision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "doctor.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("ASHARELENS_DATABASE_URL", database_url)
    project_root = Path(__file__).parents[1]
    config = Config(str(project_root / "alembic.ini"))
    command.upgrade(config, "head")
    head_revision = ScriptDirectory.from_config(config).get_current_head()
    assert head_revision is not None

    result = CliRunner().invoke(app, ["database", "check"])

    assert result.exit_code == 0
    assert "sqlite" in result.stdout
    assert head_revision in result.stdout
    assert "正常" in result.stdout


def test_database_check_hides_password_for_unreachable_mysql() -> None:
    database_url = (
        "mysql+pymysql://asharelens:super-secret@127.0.0.1:1/"
        "asharelens?connect_timeout=1"
    )

    result = CliRunner().invoke(
        app,
        ["database", "check", "--url", database_url],
    )

    assert result.exit_code == 1
    assert "super-secret" not in result.stdout
    assert "***" in result.stdout
    assert "连接失败" in result.stdout
    assert "Traceback" not in result.stdout
