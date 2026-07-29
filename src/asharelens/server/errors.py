"""Secret-safe FastAPI error responses."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from asharelens.server.models import ErrorDetail, ErrorEnvelope

_HTTP_ERRORS: dict[int, tuple[str, str]] = {
    404: ("not_found", "请求的资源不存在。"),
    405: ("method_not_allowed", "该请求方法不可用。"),
}


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
        content=envelope.model_dump(mode="json"),
    )
