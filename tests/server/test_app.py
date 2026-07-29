from fastapi.testclient import TestClient

from asharelens.server.app import create_app


def test_health_is_database_independent_and_versioned(monkeypatch) -> None:
    monkeypatch.setenv(
        "ASHARELENS_DATABASE_URL",
        "mysql+pymysql://broken:secret@127.0.0.1:1/unreachable",
    )
    client = TestClient(create_app())

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "service": "asharelens",
        "status": "ok",
        "version": "0.1.0",
    }
    assert len(response.headers["X-Request-ID"]) == 32


def test_openapi_metadata_and_paths_are_stable() -> None:
    client = TestClient(create_app())

    response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    assert document["info"]["title"] == "AShareLens API"
    assert document["info"]["version"] == "0.1.0"
    assert "/api/v1/health" in document["paths"]


def test_http_errors_use_request_id_envelope() -> None:
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/missing",
        headers={"X-Request-ID": "browser-request-42"},
    )

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "browser-request-42"
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "请求的资源不存在。",
            "request_id": "browser-request-42",
        }
    }


def test_invalid_request_id_is_replaced() -> None:
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/health",
        headers={"X-Request-ID": "not valid because spaces"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "not valid because spaces"
    assert len(response.headers["X-Request-ID"]) == 32
