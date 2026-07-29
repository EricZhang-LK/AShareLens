from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

import asharelens.cli as cli_module
from asharelens.data.models import Dataset
from asharelens.data.provider import ProviderHealth, ProviderMetadata


class FakeProvider:
    metadata = ProviderMetadata(
        provider_id="baostock",
        name="BaoStock",
        version="1.0.0",
        description="test provider",
        datasets=(Dataset.DAILY_BARS,),
        requires_registration=False,
    )

    def __init__(self, health: ProviderHealth) -> None:
        self._health = health

    def healthcheck(self) -> ProviderHealth:
        return self._health


def test_provider_list_identifies_optional_zero_registration_default() -> None:
    result = CliRunner().invoke(cli_module.app, ["provider", "list"])

    assert result.exit_code == 0
    assert "baostock" in result.stdout
    assert "默认" in result.stdout
    assert "免注册" in result.stdout
    assert "可选安装" in result.stdout


def test_provider_check_prints_sanitized_failure_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider(
        ProviderHealth(
            provider_id="baostock",
            ok=False,
            checked_at=datetime(2026, 7, 29, 10, tzinfo=UTC),
            message="匿名登录失败",
            latency_ms=50,
        )
    )
    monkeypatch.setattr(
        cli_module,
        "_provider_registry",
        lambda: {"baostock": provider},
    )

    result = CliRunner().invoke(
        cli_module.app,
        ["provider", "check", "baostock"],
    )

    assert result.exit_code == 1
    assert "匿名登录失败" in result.stdout
    assert "Traceback" not in result.stdout
