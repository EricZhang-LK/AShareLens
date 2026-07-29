from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]


def test_docker_image_builds_frontend_and_runs_as_non_root() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM node:24-bookworm-slim AS web-build" in dockerfile
    assert "npm ci" in dockerfile
    assert "npm run build" in dockerfile
    assert "FROM python:3.12-slim-bookworm AS runtime" in dockerfile
    assert 'python -m pip install ".[server,data]"' in dockerfile
    assert "USER asharelens" in dockerfile
    assert "/api/v1/health" in dockerfile


def test_compose_separates_migration_and_queues_with_local_web_binding() -> None:
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "image: mysql:8.4" in compose
    assert 'command: ["alembic", "upgrade", "head"]' in compose
    assert 'command: ["asharelens", "runner", "init"]' in compose
    assert '"127.0.0.1:${ASHARELENS_PORT:-8000}:8000"' in compose
    assert "runner-notifications:" in compose
    assert "- notifications" in compose
    assert "mysql-data:/var/lib/mysql" in compose
    assert "3306:3306" not in compose


def test_example_environment_defaults_to_free_source_and_no_secret_file() -> None:
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    ignored = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "ASHARELENS_PROVIDERS=baostock" in example
    assert "ASHARELENS_NOTIFIERS=console" in example
    assert ".env" in ignored
