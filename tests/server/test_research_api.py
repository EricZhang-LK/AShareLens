from fastapi.testclient import TestClient

from asharelens.server.app import create_app


def test_catalogs_are_stable_and_safe_without_optional_sdks() -> None:
    client = TestClient(create_app())

    strategies = client.get("/api/v1/strategies")
    providers = client.get("/api/v1/providers")

    assert strategies.status_code == 200
    strategy_items = strategies.json()["items"]
    assert [item["strategy_id"] for item in strategy_items] == [
        "momentum_rps",
        "moving_average",
        "trend_pullback",
        "value_quality",
    ]
    moving_average = next(
        item for item in strategy_items if item["strategy_id"] == "moving_average"
    )
    assert moving_average["parameter_schema"]["properties"]["fast_period"][
        "default"
    ] == 20
    assert moving_average["demo_supported"] is True
    value_quality = next(
        item for item in strategy_items if item["strategy_id"] == "value_quality"
    )
    assert value_quality["demo_supported"] is False
    assert value_quality["demo_limitation"]

    assert providers.status_code == 200
    provider_items = providers.json()["items"]
    assert [item["provider_id"] for item in provider_items] == [
        "baostock",
        "akshare",
        "tushare",
    ]
    assert provider_items[0]["role"] == "default"
    assert provider_items[0]["requires_registration"] is False
    assert provider_items[2]["requires_registration"] is True


def test_strategy_parameters_are_normalized_by_the_plugin_model() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/strategies/moving_average/validate",
        json={"parameters": {"fast_period": 12, "slow_period": 48}},
    )

    assert response.status_code == 200
    assert response.json() == {
        "strategy_id": "moving_average",
        "parameters": {
            "confirm_days": 3,
            "fast_period": 12,
            "slow_period": 48,
        },
    }


def test_invalid_strategy_parameters_return_field_level_problem() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/strategies/moving_average/validate",
        headers={"X-Request-ID": "validation-42"},
        json={"parameters": {"fast_period": 1}},
    )

    assert response.status_code == 422
    problem = response.json()["error"]
    assert problem["code"] == "invalid_strategy_parameters"
    assert problem["message"] == "策略参数校验失败。"
    assert problem["request_id"] == "validation-42"
    assert problem["details"]["fields"][0]["field"] == "fast_period"
    assert "url" not in problem["details"]["fields"][0]


def test_unknown_strategy_uses_public_not_found_error() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/strategies/not-installed/validate",
        json={"parameters": {}},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "strategy_not_found"


def test_demo_backtest_is_deterministic_and_explainable() -> None:
    client = TestClient(create_app())
    request = {
        "strategy_id": "moving_average",
        "parameters": {
            "fast_period": 10,
            "slow_period": 30,
            "confirm_days": 3,
        },
        "sessions": 90,
        "initial_cash": 100000,
        "top_n": 2,
        "max_weight": 0.5,
    }

    first = client.post("/api/v1/backtests/demo", json=request)
    second = client.post("/api/v1/backtests/demo", json=request)

    assert first.status_code == 200
    assert second.status_code == 200
    body = first.json()
    assert body == second.json()
    assert body["is_demo"] is True
    assert body["data_source"] == "deterministic_synthetic"
    assert len(body["fingerprint"]) == 64
    assert body["summary"]["sessions"] == 90
    assert body["summary"]["initial_cash"] == 100000
    assert len(body["nav"]) == 90
    assert len(body["latest_candidates"]) == 3
    assert all(item["reasons"] for item in body["latest_candidates"])
    assert body["costs"]["total"] >= 0
    assert "投资建议" in body["warning"]


def test_demo_fingerprint_covers_portfolio_and_execution_configuration() -> None:
    client = TestClient(create_app())
    base = {
        "strategy_id": "moving_average",
        "parameters": {
            "fast_period": 10,
            "slow_period": 30,
            "confirm_days": 3,
        },
        "sessions": 60,
        "initial_cash": 100000,
        "top_n": 1,
        "max_weight": 1,
    }

    original = client.post("/api/v1/backtests/demo", json=base).json()
    changed = client.post(
        "/api/v1/backtests/demo",
        json={**base, "initial_cash": 200000},
    ).json()

    assert original["fingerprint"] != changed["fingerprint"]


def test_value_quality_demo_refuses_to_fabricate_fundamentals() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/backtests/demo",
        json={
            "strategy_id": "value_quality",
            "parameters": {},
            "sessions": 90,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "demo_dataset_unsupported"
