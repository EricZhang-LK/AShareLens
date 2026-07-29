"""Secret-safe environment configuration for local and container runtimes."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from asharelens.core.execution import OpeningExecutionModel
from asharelens.data.models import Adjustment
from asharelens.runner.workflows.daily_pipeline import (
    DailyPipelineConfiguration,
)


class RuntimeSettings(BaseModel):
    """Validated process settings; secrets are excluded from representations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    database_url: str = Field(
        default="sqlite+pysqlite:///./asharelens.db",
        min_length=1,
        repr=False,
    )
    provider_ids: tuple[str, ...] = ("baostock",)
    symbols: tuple[str, ...] = (
        "sh.600000",
        "sz.000001",
        "sz.000858",
    )
    strategy_id: str = "moving_average"
    strategy_parameters: dict[str, Any] = Field(default_factory=dict)
    account_name: str = "AShareLens 默认研究组合"
    lookback_calendar_days: int = Field(default=550, ge=30, le=3650)
    adjustment: Adjustment = Adjustment.NONE
    min_coverage: float = Field(default=0.98, ge=0, le=1)
    initial_cash: float = Field(default=1_000_000, gt=0)
    top_n: int = Field(default=10, ge=1, le=500)
    max_weight: float = Field(default=0.1, gt=0, le=1)
    execution_model: OpeningExecutionModel = Field(
        default_factory=OpeningExecutionModel
    )
    notifier_ids: tuple[str, ...] = ("console",)
    webhook_url: str | None = Field(default=None, repr=False)
    tushare_token: str | None = Field(default=None, repr=False)
    schedule_name: str = "AShareLens 每日选股"
    schedule_time: time = time(18)
    schedule_timezone: str = "Asia/Shanghai"
    schedule_weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)

    @field_validator("provider_ids", "symbols", "notifier_ids")
    @classmethod
    def unique_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if not normalized or any(not value for value in normalized):
            raise ValueError("configuration lists must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("configuration lists must contain unique values")
        return normalized

    @field_validator("schedule_weekdays")
    @classmethod
    def valid_weekdays(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        normalized = tuple(sorted(set(values)))
        if not normalized or any(value < 0 or value > 6 for value in normalized):
            raise ValueError("schedule weekdays must be integers from 0 to 6")
        return normalized

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> RuntimeSettings:
        """Parse documented variables without mutating the process environment."""

        source = environ if environ is not None else os.environ
        values: dict[str, object] = {}
        scalar_names = {
            "ASHARELENS_DATABASE_URL": "database_url",
            "ASHARELENS_STRATEGY": "strategy_id",
            "ASHARELENS_ACCOUNT_NAME": "account_name",
            "ASHARELENS_WEBHOOK_URL": "webhook_url",
            "TUSHARE_TOKEN": "tushare_token",
            "ASHARELENS_SCHEDULE_NAME": "schedule_name",
            "ASHARELENS_SCHEDULE_TIME": "schedule_time",
            "ASHARELENS_SCHEDULE_TIMEZONE": "schedule_timezone",
            "ASHARELENS_ADJUSTMENT": "adjustment",
        }
        for environment_name, field_name in scalar_names.items():
            if environment_name in source:
                values[field_name] = source[environment_name]

        list_names = {
            "ASHARELENS_PROVIDERS": "provider_ids",
            "ASHARELENS_SYMBOLS": "symbols",
            "ASHARELENS_NOTIFIERS": "notifier_ids",
        }
        for environment_name, field_name in list_names.items():
            if environment_name in source:
                values[field_name] = _csv(source[environment_name])

        integer_names = {
            "ASHARELENS_LOOKBACK_DAYS": "lookback_calendar_days",
            "ASHARELENS_TOP_N": "top_n",
        }
        for environment_name, field_name in integer_names.items():
            if environment_name in source:
                values[field_name] = int(source[environment_name])

        float_names = {
            "ASHARELENS_MIN_COVERAGE": "min_coverage",
            "ASHARELENS_INITIAL_CASH": "initial_cash",
            "ASHARELENS_MAX_WEIGHT": "max_weight",
        }
        for environment_name, field_name in float_names.items():
            if environment_name in source:
                values[field_name] = float(source[environment_name])

        if "ASHARELENS_SCHEDULE_WEEKDAYS" in source:
            values["schedule_weekdays"] = tuple(
                int(value)
                for value in _csv(source["ASHARELENS_SCHEDULE_WEEKDAYS"])
            )
        if source.get("ASHARELENS_STRATEGY_PARAMS", "").strip():
            values["strategy_parameters"] = _json_object(
                source["ASHARELENS_STRATEGY_PARAMS"],
                name="ASHARELENS_STRATEGY_PARAMS",
            )
        if source.get("ASHARELENS_EXECUTION_MODEL", "").strip():
            values["execution_model"] = _json_object(
                source["ASHARELENS_EXECUTION_MODEL"],
                name="ASHARELENS_EXECUTION_MODEL",
            )
        return cls.model_validate(values)

    def daily_configuration(self) -> DailyPipelineConfiguration:
        """Build the credential-free payload persisted in Runner schedules."""

        return DailyPipelineConfiguration(
            account_name=self.account_name,
            symbols=self.symbols,
            provider_ids=self.provider_ids,
            strategy_id=self.strategy_id,
            strategy_parameters=self.strategy_parameters,
            lookback_calendar_days=self.lookback_calendar_days,
            adjustment=self.adjustment,
            min_coverage=self.min_coverage,
            initial_cash=self.initial_cash,
            top_n=self.top_n,
            max_weight=self.max_weight,
            execution_model=self.execution_model,
            notifier_ids=self.notifier_ids,
            target_timezone=self.schedule_timezone,
        )


def _csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _json_object(value: str, *, name: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        raise ValueError(f"{name} must contain valid JSON") from None
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} must contain a JSON object")
    return parsed
