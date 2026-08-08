from __future__ import annotations

from coding_harness.application.role_policies import role_policy
from coding_harness.domain.tasks import WorkerRole


def test_planner_and_observer_roles_are_read_only() -> None:
    for role in (WorkerRole.PLANNER, WorkerRole.TESTER, WorkerRole.REVIEWER, WorkerRole.SECURITY):
        policy = role_policy(role)
        assert policy.allow_writes is False
        assert "read_file" in policy.allowed_tools
        assert "edit_file" not in policy.allowed_tools


def test_coder_is_scoped_to_explicit_write_tools() -> None:
    policy = role_policy(WorkerRole.CODER)

    assert policy.allow_writes is True
    assert {"read_file", "edit_file", "write_file"}.issubset(policy.allowed_tools)
    assert "network_request" not in policy.allowed_tools
