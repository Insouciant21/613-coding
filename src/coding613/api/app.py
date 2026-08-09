"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .routes.events import router as events_router
from .routes.runs import router as runs_router


def create_app(services: Any) -> FastAPI:
    app = FastAPI(title="613 Coding")
    app.state.services = services
    web_root = Path(__file__).parents[1] / "web"
    app.mount("/static", StaticFiles(directory=web_root / "static"), name="static")
    app.include_router(runs_router)
    app.include_router(events_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (web_root / "templates" / "index.html").read_text(encoding="utf-8")

    return app
