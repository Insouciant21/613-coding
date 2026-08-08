"""FastAPI application factory."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from .routes.events import router as events_router
from .routes.runs import router as runs_router


def create_app(services: Any) -> FastAPI:
    app = FastAPI(title="613 Coding")
    app.state.services = services
    app.include_router(runs_router)
    app.include_router(events_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
