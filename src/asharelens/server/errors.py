"""Secret-safe FastAPI error responses."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from asharelens.server.models import ErrorDetail, ErrorEnvelope

_HTTP_ERRORS: dict[int, tuple[str, str]] = {
    404: ("not_found", "请求的资源不存在。"),
    405: ("method_not_allowed", "该请求方法不可用。"),
}


class ApiProblem(RuntimeError):
    """Expected public API failure with safe structured details."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.details = details


async def http_error_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    """Translate framework HTTP errors into the stable public envelope."""

    if not isinstance(error, HTTPException):
        raise error
    code, message = _HTTP_ERRORS.get(
        error.status_code,
        ("http_error", "请求未能完成。"),
    )
    envelope = ErrorEnvelope(
        error=ErrorDetail(
            code=code,
            message=message,
            request_id=request.state.request_id,
        )
    )
    return JSONResponse(
        status_code=error.status_code,
        content=envelope.model_dump(mode="json", exclude_none=True),
    )


async def api_problem_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    """Serialize an anticipated application error without stack details."""

    if not isinstance(error, ApiProblem):
        raise error
    envelope = ErrorEnvelope(
        error=ErrorDetail(
            code=error.code,
            message=str(error),
            request_id=request.state.request_id,
            details=error.details,
        )
    )
    return JSONResponse(
        status_code=error.status_code,
        content=envelope.model_dump(mode="json", exclude_none=True),
    )
