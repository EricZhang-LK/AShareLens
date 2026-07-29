"""Research catalog, validation and demo backtest routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import ValidationError

from asharelens.server.errors import ApiProblem
from asharelens.server.models import (
    DemoBacktestRequest,
    DemoBacktestResponse,
    ParameterValidationRequest,
    ParameterValidationResponse,
    ProviderCatalogResponse,
    StrategyCatalogResponse,
)
from asharelens.server.services.research import (
    DemoDatasetUnsupported,
    ResearchService,
)
from asharelens.strategies.registry import StrategyNotFound


def build_research_router(service: ResearchService) -> APIRouter:
    """Bind one injected service to versioned routes."""

    router = APIRouter(prefix="/api/v1")

    @router.get("/strategies", response_model=StrategyCatalogResponse)
    async def strategies() -> StrategyCatalogResponse:
        return service.strategy_catalog()

    @router.get("/providers", response_model=ProviderCatalogResponse)
    async def providers() -> ProviderCatalogResponse:
        return service.provider_catalog()

    @router.post(
        "/strategies/{strategy_id}/validate",
        response_model=ParameterValidationResponse,
    )
    async def validate_strategy(
        strategy_id: str,
        request: ParameterValidationRequest,
    ) -> ParameterValidationResponse:
        try:
            return service.validate_parameters(strategy_id, request.parameters)
        except StrategyNotFound:
            raise _strategy_not_found() from None
        except ValidationError as error:
            raise _invalid_parameters(error) from None

    @router.post("/backtests/demo", response_model=DemoBacktestResponse)
    async def demo_backtest(
        request: DemoBacktestRequest,
    ) -> DemoBacktestResponse:
        try:
            return service.run_demo(request)
        except StrategyNotFound:
            raise _strategy_not_found() from None
        except ValidationError as error:
            raise _invalid_parameters(error) from None
        except DemoDatasetUnsupported as error:
            raise ApiProblem(
                status_code=422,
                code="demo_dataset_unsupported",
                message=str(error),
            ) from None

    return router


def _strategy_not_found() -> ApiProblem:
    return ApiProblem(
        status_code=404,
        code="strategy_not_found",
        message="策略不存在或尚未安装。",
    )


def _invalid_parameters(error: ValidationError) -> ApiProblem:
    fields: list[dict[str, Any]] = []
    for item in error.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    ):
        location = ".".join(str(part) for part in item["loc"]) or "__root__"
        fields.append(
            {
                "field": location,
                "message": item["msg"],
                "type": item["type"],
            }
        )
    return ApiProblem(
        status_code=422,
        code="invalid_strategy_parameters",
        message="策略参数校验失败。",
        details={"fields": fields},
    )
