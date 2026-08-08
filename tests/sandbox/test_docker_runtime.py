from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from coding_harness.adapters.sandbox.artifacts import ArtifactExporter
from coding_harness.adapters.sandbox.docker_runtime import (
    DockerSandboxRuntime,
    SandboxRuntimeError,
)
from coding_harness.adapters.sandbox.workspace import WorkspaceManager
from coding_harness.domain.sandbox import (
    CommandResult,
    NetworkPolicy,
    ResourceLimits,
    SandboxHandle,
    SandboxSpec,
)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "main.py").write_text("print('before')\n")
    subprocess.run(["git", "-C", str(repo), "add", "main.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "baseline"], check=True)
    return repo


class FakeContainer:
    id = "container-1"

    def __init__(self, events: list[str], *, exec_result: object | None = None) -> None:
        self.events = events
        self.exec_result = exec_result or SimpleNamespace(exit_code=0, output=b"ok\n")

    def start(self) -> None:
        self.events.append("start")

    def exec_run(self, command: list[str], **kwargs: object) -> object:
        self.events.append("exec:" + " ".join(command))
        return self.exec_result

    def stop(self, **kwargs: object) -> None:
        self.events.append("stop")

    def kill(self, **kwargs: object) -> None:
        self.events.append("kill")

    def remove(self, **kwargs: object) -> None:
        self.events.append("remove")


class FakeDocker:
    def __init__(self, container: FakeContainer | None = None, error: Exception | None = None) -> None:
        self.events: list[str] = []
        self.container = container or FakeContainer(self.events)
        self.error = error
        self.create_options: dict[str, object] | None = None

        class Containers:
            def __init__(self, owner: FakeDocker) -> None:
                self.owner = owner

            def create(self, **kwargs: object) -> FakeContainer:
                if self.owner.error is not None:
                    raise self.owner.error
                self.owner.create_options = kwargs
                self.owner.events.append("create")
                return self.owner.container

        self.containers = Containers(self)


def _spec(
    repo: Path,
    *,
    network_policy: NetworkPolicy = NetworkPolicy.DENY,
    timeout_seconds: float = 300.0,
) -> SandboxSpec:
    return SandboxSpec(
        image_digest="sha256:" + "a" * 64,
        workspace_path=repo,
        worker_id="worker-1",
        network_policy=network_policy,
        resource_limits=ResourceLimits(
            memory_bytes=64 * 1024 * 1024,
            pids=32,
            output_bytes=4,
            timeout_seconds=timeout_seconds,
        ),
    )


def _runtime(tmp_path: Path, docker: FakeDocker) -> DockerSandboxRuntime:
    manager = WorkspaceManager(tmp_path / "workspaces", declared_write_set=("main.py",))
    return DockerSandboxRuntime(docker, manager, ArtifactExporter(manager))


def test_create_configures_hardened_container_and_start_order(tmp_path: Path) -> None:
    docker = FakeDocker()
    runtime = _runtime(tmp_path, docker)

    handle = runtime.create(_spec(_repo(tmp_path)))

    assert handle.workspace_path.is_absolute()
    assert docker.events == ["create", "start"]
    assert docker.create_options is not None
    assert docker.create_options["image"] == "sha256:" + "a" * 64
    assert docker.create_options["user"] == 65532
    assert docker.create_options["read_only"] is True
    assert docker.create_options["network_disabled"] is True
    assert docker.create_options["cap_drop"] == ["ALL"]
    assert "/var/run/docker.sock" not in str(docker.create_options)
    runtime.destroy(handle)


def test_execute_maps_exit_and_caps_output(tmp_path: Path) -> None:
    docker = FakeDocker(FakeContainer([], exec_result=SimpleNamespace(exit_code=7, output=b"123456")))
    runtime = _runtime(tmp_path, docker)
    handle = runtime.create(_spec(_repo(tmp_path)))

    result = runtime.execute(handle, ("pytest", "-q"))

    assert isinstance(result, CommandResult)
    assert result.exit_code == 7
    assert result.stdout == "1234"
    assert result.output_truncated is True
    runtime.destroy(handle)


def test_execute_timeout_maps_to_timed_out_result(tmp_path: Path) -> None:
    class TimeoutContainer(FakeContainer):
        def exec_run(self, command: list[str], **kwargs: object) -> object:
            raise TimeoutError("execution exceeded limit")

    docker = FakeDocker(TimeoutContainer([]))
    runtime = _runtime(tmp_path, docker)
    handle = runtime.create(_spec(_repo(tmp_path)))

    result = runtime.execute(handle, ("sleep", "10"))

    assert result.timed_out is True
    assert result.exit_code is None
    runtime.destroy(handle)


def test_execute_enforces_runtime_timeout(tmp_path: Path) -> None:
    import time

    class SlowContainer(FakeContainer):
        def exec_run(self, command: list[str], **kwargs: object) -> object:
            time.sleep(0.05)
            return self.exec_result

    docker = FakeDocker(SlowContainer([]))
    runtime = _runtime(tmp_path, docker)
    handle = runtime.create(_spec(_repo(tmp_path), timeout_seconds=0.001))

    result = runtime.execute(handle, ("sleep", "10"))

    assert result.timed_out is True
    assert "kill" in docker.container.events
    runtime.destroy(handle)


def test_export_uses_workspace_artifact_and_destroy_cleans_in_finally(tmp_path: Path) -> None:
    docker = FakeDocker()
    runtime = _runtime(tmp_path, docker)
    handle = runtime.create(_spec(_repo(tmp_path)))
    workspace_path = handle.workspace_path
    (workspace_path / "main.py").write_text("print('after')\n")

    try:
        artifact = runtime.export(handle)
        assert artifact.changed_files == ("main.py",)
    finally:
        runtime.destroy(handle)

    assert not workspace_path.exists()
    assert docker.events[-2:] == ["stop", "remove"]


def test_missing_docker_daemon_cleans_workspace_and_raises(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, FakeDocker(error=RuntimeError("daemon unavailable")))

    with pytest.raises(SandboxRuntimeError, match="daemon"):
        runtime.create(_spec(_repo(tmp_path)))

    assert not any((tmp_path / "workspaces").iterdir())


def test_container_start_failure_removes_container_and_workspace(tmp_path: Path) -> None:
    class StartFailureContainer(FakeContainer):
        def start(self) -> None:
            self.events.append("start")
            raise RuntimeError("start failed")

    docker = FakeDocker(StartFailureContainer([]))
    runtime = _runtime(tmp_path, docker)

    with pytest.raises(SandboxRuntimeError, match="start failed"):
        runtime.create(_spec(_repo(tmp_path)))

    assert docker.events == ["create"]
    assert docker.container.events == ["start", "remove"]
    assert not any((tmp_path / "workspaces").iterdir())


def test_forged_handle_with_same_id_cannot_access_live_container(tmp_path: Path) -> None:
    docker = FakeDocker()
    runtime = _runtime(tmp_path, docker)
    handle = runtime.create(_spec(_repo(tmp_path)))
    forged = SandboxHandle(id=handle.id, workspace_path=handle.workspace_path)

    with pytest.raises(SandboxRuntimeError, match="unknown"):
        runtime.export(forged)
    runtime.destroy(handle)
