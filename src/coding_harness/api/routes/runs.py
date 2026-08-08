"""Run lifecycle routes."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from coding_harness.application.run_service import RunRequest

from ..schemas import ApprovalRequestBody, CreateRunRequest

router = APIRouter(prefix="/api")


def _service(request: Request) -> Any:
    return request.app.state.services.run_service


def _error(error: Exception) -> HTTPException:
    if isinstance(error, KeyError):
        return HTTPException(status_code=404, detail="resource not found")
    if isinstance(error, ValueError):
        return HTTPException(status_code=422, detail="invalid request")
    return HTTPException(status_code=500, detail="application service failure")


@router.post("/runs", status_code=status.HTTP_201_CREATED)
def create_run(payload: CreateRunRequest, request: Request) -> Any:
    try:
        return _service(request).create_run(
            RunRequest(task=payload.task, permission_mode=payload.permission_mode)
        )
    except Exception as error:
        raise _error(error) from error


@router.get("/runs/{run_id}")
def get_run(run_id: UUID, request: Request) -> Any:
    try:
        return _service(request).get_summary(run_id)
    except Exception as error:
        raise _error(error) from error


@router.post("/approvals/{approval_id}")
def resolve_approval(approval_id: UUID, payload: ApprovalRequestBody, request: Request) -> Any:
    try:
        method = _service(request).approve if payload.decision == "approve" else _service(request).reject
        return method(approval_id)
    except Exception as error:
        raise _error(error) from error


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: UUID, request: Request) -> Any:
    try:
        return _service(request).resume(run_id)
    except Exception as error:
        raise _error(error) from error


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: UUID, request: Request) -> Any:
    try:
        return _service(request).cancel(run_id)
    except Exception as error:
        raise _error(error) from error
