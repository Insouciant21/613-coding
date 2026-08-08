from __future__ import annotations

from pathlib import Path

from coding_harness.adapters.sandbox.fake import FakeSandboxRuntime
from coding_harness.demo.sandbox import run_sandbox_demo


def test_sandbox_demo_covers_isolation_policy_resources_artifact_and_cleanup(tmp_path: Path) -> None:
    summary = run_sandbox_demo(FakeSandboxRuntime())

    assert summary.isolated_workers is True
    assert summary.dangerous_mount_blocked is True
    assert summary.docker_socket_blocked is True
    assert summary.network_denied is True
    assert summary.resource_timeout_mapped is True
    assert summary.artifact_exported is True
    assert summary.cleanup_completed is True
