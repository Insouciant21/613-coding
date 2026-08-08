from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from coding_harness.adapters.sandbox.fake import FakeSandboxRuntime
from coding_harness.domain.sandbox import (
    CommandResult,
    NetworkPolicy,
    ResourceLimits,
    SandboxSpec,
    WorkArtifact,
)
from coding_harness.ports.sandbox import SandboxRuntime


def _spec(tmp_path: Path) -> SandboxSpec:
    return SandboxSpec(
        image_digest="sha256:" + "a" * 64,
        workspace_path=tmp_path,
        worker_id="worker-1",
    )


def test_sandbox_spec_rejects_unpinned_image_and_invalid_limits(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        SandboxSpec(image_digest="python:3.12", workspace_path=tmp_path, worker_id="w")
    with pytest.raises(ValidationError):
        ResourceLimits(cpu_seconds=0)


@pytest.mark.parametrize("field_name", ("cpu_seconds", "timeout_seconds"))
@pytest.mark.parametrize("value", (float("inf"), float("-inf")))
def test_resource_limits_reject_non_finite_duration_limits(
    field_name: str, value: float
) -> None:
    with pytest.raises(ValidationError):
        ResourceLimits(**{field_name: value})


def test_sandbox_defaults_are_non_root_read_only_and_default_deny(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    assert spec.network_policy is NetworkPolicy.DENY
    assert spec.read_only_root is True
    assert spec.run_as_user != 0
    assert spec.capabilities == ()
    assert spec.environment_allowlist == ()


def test_handle_is_opaque_and_runtime_satisfies_protocol(tmp_path: Path) -> None:
    runtime: SandboxRuntime = FakeSandboxRuntime()
    handle = runtime.create(_spec(tmp_path))
    assert isinstance(handle.id, UUID)
    assert handle.workspace_path == tmp_path
    assert "worker-1" not in str(handle.id)


def test_fake_runtime_records_order_and_exports_scripted_artifact(tmp_path: Path) -> None:
    expected_result = CommandResult(command=("pytest",), exit_code=1, stderr="failed")
    expected_artifact = WorkArtifact(
        patch="diff --git a/a.py b/a.py",
        changed_files=("a.py",),
        summary="one change",
    )
    runtime = FakeSandboxRuntime(
        command_results=(expected_result,), artifact=expected_artifact
    )
    handle = runtime.create(_spec(tmp_path))
    assert runtime.execute(handle, ("pytest",)) == expected_result
    assert runtime.export(handle) == expected_artifact
    runtime.destroy(handle)
    assert [call[0] for call in runtime.calls] == ["create", "execute", "export", "destroy"]


def test_fake_runtime_rejects_operations_after_destroy(tmp_path: Path) -> None:
    runtime = FakeSandboxRuntime()
    handle = runtime.create(_spec(tmp_path))
    runtime.destroy(handle)
    with pytest.raises(RuntimeError, match="destroyed"):
        runtime.export(handle)
