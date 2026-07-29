from datetime import time

import pytest

from asharelens.config import RuntimeSettings
from asharelens.runtime import RuntimeConfigurationError, build_notifier_registry


def test_runtime_settings_parse_environment_and_keep_secrets_out_of_repr() -> None:
    settings = RuntimeSettings.from_env(
        {
            "ASHARELENS_DATABASE_URL": (
                "mysql+pymysql://user:database-secret@mysql/asharelens"
            ),
            "ASHARELENS_PROVIDERS": "baostock,akshare",
            "ASHARELENS_SYMBOLS": "sh.600000,sz.000001",
            "ASHARELENS_STRATEGY_PARAMS": '{"fast_period": 12}',
            "ASHARELENS_EXECUTION_MODEL": '{"slippage_bps": 5}',
            "ASHARELENS_NOTIFIERS": "console,webhook",
            "ASHARELENS_WEBHOOK_URL": "https://example.com/private-hook",
            "TUSHARE_TOKEN": "token-secret",
            "ASHARELENS_SCHEDULE_TIME": "18:35",
        }
    )

    assert settings.provider_ids == ("baostock", "akshare")
    assert settings.strategy_parameters == {"fast_period": 12}
    assert settings.execution_model.slippage_bps == 5
    assert settings.schedule_time == time(18, 35)
    representation = repr(settings)
    assert "database-secret" not in representation
    assert "private-hook" not in representation
    assert "token-secret" not in representation
    payload = settings.daily_configuration().model_dump(mode="json")
    assert "database_url" not in payload
    assert "webhook_url" not in payload
    assert "tushare_token" not in payload


def test_webhook_must_be_configured_when_selected() -> None:
    with pytest.raises(RuntimeConfigurationError, match="webhook"):
        build_notifier_registry(
            RuntimeSettings(notifier_ids=("webhook",))
        )


def test_invalid_json_configuration_fails_before_runtime_starts() -> None:
    with pytest.raises(ValueError, match="valid JSON"):
        RuntimeSettings.from_env(
            {"ASHARELENS_STRATEGY_PARAMS": "{not-json"}
        )
