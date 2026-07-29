"""FastAPI application factory."""

from __future__ import annotations

import re
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from starlette.exceptions import HTTPException
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from asharelens.server.errors import (
    ApiProblem,
    api_problem_handler,
    http_error_handler,
)
from asharelens.server.frontend import mount_frontend
from asharelens.server.models import HealthResponse
from asharelens.server.routes.research import build_research_router
from asharelens.server.services.research import ResearchService

_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")


def create_app(
    *,
    research_service: ResearchService | None = None,
    frontend_dir: Path | None = None,
) -> FastAPI:
    """Construct one side-effect-free local API application."""

    app = FastAPI(
        title="AShareLens API",
        summary="可解释、可复现的本地 A 股量化研究 API",
        version=version("asharelens"),
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(ApiProblem, api_problem_handler)
    app.include_router(
        build_research_router(research_service or ResearchService()),
        tags=["research"],
    )

    @app.middleware("http")
    async def request_identity(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _REQUEST_ID.fullmatch(incoming) else uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.get(
        "/api/v1/health",
        response_model=HealthResponse,
        tags=["system"],
        summary="进程存活检查",
    )
    async def health() -> HealthResponse:
        return HealthResponse(version=version("asharelens"))

    @app.api_route(
        "/api/{unknown_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    async def unknown_api(unknown_path: str) -> None:
        del unknown_path
        raise HTTPException(status_code=404)

    mount_frontend(app, directory=frontend_dir)
    return app


app = create_app()
