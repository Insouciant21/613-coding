"""Offline demonstration of the container sandbox boundaries."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from coding613.application.policy import (
    PolicyEngine,
    RepositoryPolicyConfig,
    SandboxPolicyConfig,
)
from coding613.application.sandbox_policy import SandboxPolicy
from coding613.domain.actions import ToolCall
from coding613.domain.models import PermissionMode
from coding613.domain.models_base import DomainModel
from coding613.domain.sandbox import CommandResult, NetworkPolicy, SandboxHandle, SandboxSpec
from coding613.ports.policy import PolicyEffect
from coding613.ports.sandbox import SandboxRuntime


class SandboxDemoSummary(DomainModel):
    isolated_workers: bool
    dangerous_mount_blocked: bool
    docker_socket_blocked: bool
    network_denied: bool
    resource_timeout_mapped: bool
    artifact_exported: bool
    cleanup_completed: bool


def run_sandbox_demo(runtime: SandboxRuntime) -> SandboxDemoSummary:
    with tempfile.TemporaryDirectory(prefix="613-sandbox-demo-") as temporary:
        root = Path(temporary)
        repositories = (_git_repo(root / "worker-a"), _git_repo(root / "worker-b"))
        specs = tuple(
            SandboxSpec(
                image_digest="sha256:" + "a" * 64,
                workspace_path=repository,
                worker_id=f"demo-worker-{index}",
                network_policy=NetworkPolicy.DENY,
            )
            for index, repository in enumerate(repositories, start=1)
        )
        handles = []
        values: tuple[bool, bool, bool, bool, bool, bool] | None = None
        try:
            handles = [runtime.create(spec) for spec in specs]
            isolated = handles[0].id != handles[1].id and handles[0].workspace_path != handles[1].workspace_path
            dangerous = PolicyEngine().evaluate(
                ToolCall(
                    name="run_command",
                    arguments={"argv": ["docker", "run", "--privileged", "worker"]},
                ),
                RepositoryPolicyConfig(repository_root=repositories[0]),
                PermissionMode.AUTONOMOUS,
            )
            socket = PolicyEngine().evaluate(
                ToolCall(name="read_file", arguments={"path": "/var/run/docker.sock"}),
                RepositoryPolicyConfig(repository_root=repositories[0]),
                PermissionMode.AUTONOMOUS,
            )
            network = SandboxPolicy().validate(
                specs[0], PermissionMode.AUTONOMOUS, SandboxPolicyConfig()
            )
            timeout = SandboxPolicy().evaluate_result(
                CommandResult(command=("sleep", "timeout"), timed_out=True),
                SandboxPolicyConfig(),
            )
            runtime.execute(handles[0], ("printf", "sandbox-demo"))
            artifact = runtime.export(handles[0])
            values = (
                isolated,
                dangerous.effect is PolicyEffect.DENY,
                socket.effect is PolicyEffect.DENY,
                network.network_policy is NetworkPolicy.DENY,
                timeout.resource_exhausted,
                artifact.version >= 1,
            )
        finally:
            for handle in handles:
                runtime.destroy(handle)
        cleanup = all(_is_destroyed(runtime, handle) for handle in handles)
        assert values is not None
        return SandboxDemoSummary(
            isolated_workers=values[0],
            dangerous_mount_blocked=values[1],
            docker_socket_blocked=values[2],
            network_denied=values[3],
            resource_timeout_mapped=values[4],
            artifact_exported=values[5],
            cleanup_completed=cleanup,
        )


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "worker.py").write_text("print('sandbox')\n", encoding="utf-8")
    return path


def _is_destroyed(runtime: SandboxRuntime, handle: SandboxHandle) -> bool:
    try:
        runtime.export(handle)
    except Exception:  # noqa: BLE001
        return True
    return False
