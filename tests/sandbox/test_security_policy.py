from __future__ import annotations

from pathlib import Path

import pytest

from coding613.application.policy import SandboxPolicyConfig
from coding613.application.sandbox_policy import SandboxPolicy
from coding613.domain.models import PermissionMode
from coding613.domain.sandbox import (
    CommandResult,
    NetworkPolicy,
    ResourceLimits,
    SandboxSpec,
)


def _spec(tmp_path: Path, **updates: object) -> SandboxSpec:
    values: dict[str, object] = {
        "image_digest": "sha256:" + "a" * 64,
        "workspace_path": tmp_path,
        "worker_id": "worker-1",
    }
    values.update(updates)
    return SandboxSpec(**values)


def test_default_policy_denies_network_and_records_hard_defaults(tmp_path: Path) -> None:
    decision = SandboxPolicy().validate(
        _spec(tmp_path),
        PermissionMode.AUTONOMOUS,
        SandboxPolicyConfig(),
    )

    assert decision.allowed is True
    assert decision.network_policy is NetworkPolicy.DENY
    assert decision.approved_networks == ()
    assert decision.rule_id == "sandbox.default_deny"


def test_allowlisted_network_requires_exact_approved_entries(tmp_path: Path) -> None:
    spec = _spec(tmp_path, network_policy=NetworkPolicy.ALLOWLIST)
    denied = SandboxPolicy().validate(spec, PermissionMode.BYPASS, SandboxPolicyConfig())
    approved = SandboxPolicy().validate(
        spec,
        PermissionMode.AUTONOMOUS,
        SandboxPolicyConfig(network_allowlist=("pypi.org",), allow_network=True),
    )

    assert denied.allowed is False
    assert denied.rule_id == "hard.network_not_approved"
    assert approved.allowed is True
    assert approved.approved_networks == ("pypi.org",)


@pytest.mark.parametrize("mode", [PermissionMode.AUTONOMOUS, PermissionMode.BYPASS])
@pytest.mark.parametrize(
    "field, value",
    [("run_as_user", 0), ("capabilities", ("SYS_ADMIN",)), ("read_only_root", False)],
)
def test_permission_mode_cannot_override_hard_worker_constraints(
    tmp_path: Path, mode: PermissionMode, field: str, value: object
) -> None:
    spec = SandboxSpec.model_construct(
        image_digest="sha256:" + "a" * 64,
        workspace_path=tmp_path,
        worker_id="worker-1",
        run_as_user=65532,
        capabilities=(),
        read_only_root=True,
    )
    object.__setattr__(spec, field, value)

    decision = SandboxPolicy().validate(spec, mode, SandboxPolicyConfig())

    assert decision.allowed is False
    assert decision.rule_id.startswith("hard.")


def test_policy_rejects_unpinned_image_and_over_budget_resources(tmp_path: Path) -> None:
    unpinned = SandboxSpec.model_construct(
        image_digest="python:3.12",
        workspace_path=tmp_path,
        worker_id="worker-1",
        run_as_user=65532,
        capabilities=(),
        read_only_root=True,
        network_policy=NetworkPolicy.DENY,
        resource_limits=ResourceLimits(),
        environment_allowlist=(),
    )
    over_budget = _spec(tmp_path, resource_limits=ResourceLimits(memory_bytes=1024 * 1024 * 1024))

    assert SandboxPolicy().validate(unpinned, PermissionMode.BALANCED, SandboxPolicyConfig()).rule_id == "hard.image_digest"
    assert SandboxPolicy().validate(
        over_budget,
        PermissionMode.BYPASS,
        SandboxPolicyConfig(max_limits=ResourceLimits(memory_bytes=512)),
    ).rule_id == "hard.resource_limit"


def test_policy_rejects_credential_environment_names(tmp_path: Path) -> None:
    spec = _spec(tmp_path, environment_allowlist=("AWS_SECRET_ACCESS_KEY",))

    decision = SandboxPolicy().validate(spec, PermissionMode.BYPASS, SandboxPolicyConfig())

    assert decision.allowed is False
    assert decision.rule_id == "hard.credential_environment"


def test_resource_result_maps_timeout_and_output_overflow(tmp_path: Path) -> None:
    config = SandboxPolicyConfig()
    policy = SandboxPolicy()

    timeout = policy.evaluate_result(
        CommandResult(command=("sleep",), timed_out=True), config
    )
    output = policy.evaluate_result(
        CommandResult(command=("cat",), output_truncated=True), config
    )

    assert timeout.resource_exhausted is True
    assert timeout.rule_id == "resource.timeout"
    assert output.resource_exhausted is True
    assert output.rule_id == "resource.output_limit"
