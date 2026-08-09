"""One-time exact-action approval state."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from coding613.domain.actions import ToolCall
from coding613.domain.models import ApprovalRequest, ApprovalStatus
from coding613.domain.models_base import DomainModel
from coding613.ports.policy import PolicyDecision, PolicyEffect
from coding613.ports.storage import ApprovalStore


def action_fingerprint(call: ToolCall) -> str:
    """Return the stable fingerprint used for one-time exact-action approval."""

    encoded = json.dumps(
        call.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


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


class ApprovalClaim(DomainModel):
    request: ApprovalRequest
    acquired: bool


class ApprovalService:
    def __init__(
        self,
        run_id: UUID,
        store: ApprovalStore,
        clock: Callable[[], datetime] | None = None,
        ttl: timedelta = timedelta(minutes=5),
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("approval ttl must be positive")
        self.run_id = run_id
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ttl = ttl

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
        self._store.save_approval(request)
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
        resolved = request.model_copy(
            update={"status": status, "resolved_at": now}
        )
        if not self._store.compare_and_set_approval(
            request_id, ApprovalStatus.PENDING, resolved
        ):
            raise StaleApprovalError("approval request is no longer pending")
        fingerprint = action_fingerprint(request.action)
        return ApprovalResolution(
            request_id=request_id,
            run_id=self.run_id,
            decision=decision,
            action_fingerprint=fingerprint,
            resolved_at=now,
        )

    def get_request(self, request_id: UUID) -> ApprovalRequest:
        request = self._store.get_approval(request_id)
        if request is None:
            raise ApprovalNotFoundError(str(request_id))
        if request.run_id != self.run_id:
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
            self._store.compare_and_set_approval(
                request_id, ApprovalStatus.PENDING, request
            )
        return request

    def claim(self, request_id: UUID, call: ToolCall) -> ApprovalClaim:
        request = self.get_request(request_id)
        if request.status is not ApprovalStatus.APPROVED:
            return ApprovalClaim(request=request, acquired=False)
        now = self._now()
        if request.expires_at is None or request.expires_at <= now:
            expired = request.model_copy(
                update={"status": ApprovalStatus.EXPIRED, "resolved_at": now}
            )
            self._store.compare_and_set_approval(
                request_id, ApprovalStatus.APPROVED, expired
            )
            return ApprovalClaim(request=request, acquired=False)
        if action_fingerprint(request.action) != action_fingerprint(call):
            return ApprovalClaim(request=request, acquired=False)
        executing = request.model_copy(update={"status": ApprovalStatus.EXECUTING})
        return ApprovalClaim(
            request=executing,
            acquired=self._store.compare_and_set_approval(
                request_id, ApprovalStatus.APPROVED, executing
            ),
        )

    def complete_claim(self, request_id: UUID) -> None:
        request = self.get_request(request_id)
        consumed = request.model_copy(update={"status": ApprovalStatus.CONSUMED})
        if not self._store.compare_and_set_approval(
            request_id, ApprovalStatus.EXECUTING, consumed
        ):
            raise StaleApprovalError("approval claim is no longer executing")

    def invalidate(self, request_id: UUID) -> None:
        request, rejected = self.invalidation_update(request_id)
        if not self._store.compare_and_set_approval(
            request_id, request.status, rejected
        ):
            raise StaleApprovalError("approval request is no longer active")

    def invalidation_update(
        self, request_id: UUID
    ) -> tuple[ApprovalRequest, ApprovalRequest]:
        request = self.get_request(request_id)
        if request.status not in {ApprovalStatus.PENDING, ApprovalStatus.APPROVED}:
            raise StaleApprovalError("approval request cannot be invalidated")
        rejected = request.model_copy(
            update={"status": ApprovalStatus.REJECTED, "resolved_at": self._now()}
        )
        return request, rejected

    def consume(self, call: ToolCall, request_id: UUID | None = None) -> bool:
        fingerprint = action_fingerprint(call)
        requests = (
            [self.get_request(request_id)]
            if request_id is not None
            else self._store.list_approvals(self.run_id)
        )
        for request in requests:
            if action_fingerprint(request.action) != fingerprint:
                continue
            claim = self.claim(request.id, call)
            if claim.acquired:
                self.complete_claim(request.id)
                return True
        return False

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("approval clock must return timezone-aware timestamps")
        return now
