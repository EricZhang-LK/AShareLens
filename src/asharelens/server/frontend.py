"""Serve a built Vue SPA without weakening API route precedence."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class SpaStaticFiles(StaticFiles):
    """Static assets with an HTML-only client-side route fallback."""

    def __init__(self, *, directory: Path) -> None:
        super().__init__(directory=directory, html=True, check_dir=True)
        self._index = directory / "index.html"

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Return index.html only for browser navigation requests."""

        try:
            response = await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != 404 or not _wants_spa(scope):
                raise
            return FileResponse(self._index)
        if response.status_code == 404 and _wants_spa(scope):
            return FileResponse(self._index)
        return response


def mount_frontend(
    app: FastAPI,
    *,
    directory: Path | None = None,
) -> Path:
    """Mount the selected build or a secret-free local diagnostic."""

    frontend_dir = directory or resolve_frontend_dir()
    if (frontend_dir / "index.html").is_file():
        app.mount("/", SpaStaticFiles(directory=frontend_dir), name="frontend")
        return frontend_dir

    diagnostic = (
        "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>AShareLens 前端尚未构建</title>"
        "<body style='font-family:serif;padding:3rem;line-height:1.8'>"
        "<h1>AShareLens 前端尚未构建</h1>"
        "<p>请进入 <code>web</code> 目录执行 "
        "<code>npm install</code> 和 <code>npm run build</code>，然后重启服务。</p>"
        "</body></html>"
    )

    @app.get("/{frontend_path:path}", include_in_schema=False)
    async def missing_frontend(frontend_path: str) -> HTMLResponse:
        del frontend_path
        return HTMLResponse(diagnostic, status_code=503)

    return frontend_dir


def resolve_frontend_dir() -> Path:
    """Find an explicit, packaged, or source-tree frontend build."""

    configured = os.getenv("ASHARELENS_FRONTEND_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    packaged = Path(__file__).with_name("static")
    if (packaged / "index.html").is_file():
        return packaged
    project_root = Path(__file__).parents[3]
    return project_root / "web" / "dist"


def _wants_spa(scope: Scope) -> bool:
    if scope.get("method") not in {"GET", "HEAD"}:
        return False
    headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }
    accept = headers.get("accept", "")
    return "text/html" in accept or "application/xhtml+xml" in accept
