from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from asharelens.cli import app as cli_app
from asharelens.server.app import create_app


def _build_frontend(path: Path) -> Path:
    (path / "assets").mkdir(parents=True)
    (path / "index.html").write_text(
        "<!doctype html><title>AShareLens Test UI</title>",
        encoding="utf-8",
    )
    (path / "assets" / "app.js").write_text(
        "globalThis.asharelens = true;",
        encoding="utf-8",
    )
    return path


def test_built_frontend_uses_spa_fallback_after_api_routes(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(frontend_dir=_build_frontend(tmp_path / "dist")))

    index = client.get("/")
    spa_route = client.get(
        "/strategies",
        headers={"Accept": "text/html"},
    )
    asset = client.get("/assets/app.js")
    api = client.get("/api/v1/health")
    missing_api = client.get(
        "/api/v1/not-real",
        headers={"Accept": "text/html"},
    )

    assert index.status_code == 200
    assert "AShareLens Test UI" in index.text
    assert spa_route.status_code == 200
    assert "AShareLens Test UI" in spa_route.text
    assert asset.status_code == 200
    assert "asharelens = true" in asset.text
    assert api.headers["content-type"].startswith("application/json")
    assert api.json()["status"] == "ok"
    assert missing_api.status_code == 404
    assert missing_api.json()["error"]["code"] == "not_found"


def test_missing_frontend_build_has_actionable_local_diagnostic(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(frontend_dir=tmp_path / "missing"))

    response = client.get("/")

    assert response.status_code == 503
    assert "前端尚未构建" in response.text
    assert "npm run build" in response.text
    assert str(tmp_path) not in response.text
    assert client.get("/api/v1/health").status_code == 200


def test_web_cli_defaults_to_loopback(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(application: str, **options: object) -> None:
        calls.append({"application": application, **options})

    monkeypatch.setattr("uvicorn.run", fake_run)

    result = CliRunner().invoke(cli_app, ["web"])

    assert result.exit_code == 0
    assert calls == [
        {
            "application": "asharelens.server.app:app",
            "host": "127.0.0.1",
            "port": 8000,
            "reload": False,
        }
    ]


def test_web_cli_requires_explicit_network_binding_opt_in(monkeypatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: calls.append(args))

    rejected = CliRunner().invoke(
        cli_app,
        ["web", "--host", "0.0.0.0"],
    )
    accepted = CliRunner().invoke(
        cli_app,
        ["web", "--host", "0.0.0.0", "--allow-network"],
    )

    assert rejected.exit_code == 2
    assert "allow-network" in rejected.stdout
    assert accepted.exit_code == 0
    assert len(calls) == 1
