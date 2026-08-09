"""Bounded event retrieval route."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api")


@router.get("/runs/{run_id}/events")
def get_events(run_id: UUID, request: Request) -> Any:
    try:
        events = request.app.state.services.list_events(run_id)
        return sorted(events, key=lambda event: event.get("version", 0) if isinstance(event, dict) else 0)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="resource not found") from error
    except Exception as error:
        raise HTTPException(status_code=500, detail="application service failure") from error
