"""One-time exact-action approval state."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from coding_harness.domain.actions import ToolCall
from coding_harness.domain.models import ApprovalRequest, ApprovalStatus
from coding_harness.domain.models_base import DomainModel
from coding_harness.ports.policy import PolicyDecision, PolicyEffect


class ApprovalError(RuntimeError):
    pass


class ApprovalNotFoundError(ApprovalError):
    pass


class StaleApprovalError(ApprovalError):
    pass


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ApprovalResolution(DomainModel):
    request_id: UUID
    run_id: UUID
    decision: ApprovalDecision
    action_fingerprint: str = Field(min_length=64, max_length=64)
    resolved_at: datetime


class ApprovalService:
    def __init__(
        self,
        run_id: UUID,
        clock: Callable[[], datetime] | None = None,
        ttl: timedelta = timedelta(minutes=5),
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("approval ttl must be positive")
        self.run_id = run_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ttl = ttl
        self._requests: dict[UUID, ApprovalRequest] = {}
        self._approved: dict[str, list[datetime]] = {}

    def request(self, decision: PolicyDecision) -> ApprovalRequest:
        if decision.effect is not PolicyEffect.ASK or decision.action is None:
            raise ApprovalError("approval request requires an ASK decision with an action")
        now = self._now()
        request = ApprovalRequest(
            run_id=self.run_id,
            action=decision.action,
            reason=decision.reason,
            created_at=now,
            expires_at=now + self._ttl,
        )
        self._requests[request.id] = request
        return request

    def resolve(
        self, request_id: UUID, decision: ApprovalDecision
    ) -> ApprovalResolution:
        request = self.get_request(request_id)
        now = self._now()
        if request.status is not ApprovalStatus.PENDING:
            raise StaleApprovalError("approval request is no longer pending")
        if request.expires_at is None:
            raise StaleApprovalError("approval request has no expiration")
        status = (
            ApprovalStatus.APPROVED
            if decision is ApprovalDecision.APPROVE
            else ApprovalStatus.REJECTED
        )
        self._requests[request_id] = request.model_copy(
            update={"status": status, "resolved_at": now}
        )
        fingerprint = self._fingerprint(request.action)
        if decision is ApprovalDecision.APPROVE:
            self._approved.setdefault(fingerprint, []).append(request.expires_at)
        return ApprovalResolution(
            request_id=request_id,
            run_id=self.run_id,
            decision=decision,
            action_fingerprint=fingerprint,
            resolved_at=now,
        )

    def get_request(self, request_id: UUID) -> ApprovalRequest:
        request = self._requests.get(request_id)
        if request is None:
            raise ApprovalNotFoundError(str(request_id))
        now = self._now()
        if (
            request.status is ApprovalStatus.PENDING
            and request.expires_at is not None
            and now >= request.expires_at
        ):
            request = request.model_copy(
                update={"status": ApprovalStatus.EXPIRED, "resolved_at": now}
            )
            self._requests[request_id] = request
        return request

    def consume(self, call: ToolCall) -> bool:
        fingerprint = self._fingerprint(call)
        now = self._now()
        expirations = [
            expiration
            for expiration in self._approved.get(fingerprint, [])
            if expiration > now
        ]
        if not expirations:
            self._approved.pop(fingerprint, None)
            return False
        expirations.sort()
        expirations.pop(0)
        if expirations:
            self._approved[fingerprint] = expirations
        else:
            self._approved.pop(fingerprint, None)
        return True

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("approval clock must return timezone-aware timestamps")
        return now

    @staticmethod
    def _fingerprint(call: ToolCall) -> str:
        encoded = json.dumps(
            call.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(encoded).hexdigest()
