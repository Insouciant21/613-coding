"""Docker Engine implementation of the sandbox runtime port."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from coding613.domain.sandbox import CommandResult, SandboxHandle, SandboxSpec, WorkArtifact

from .artifacts import ArtifactExporter
from .docker_config import container_options
from .workspace import Workspace, WorkspaceManager


class SandboxRuntimeError(RuntimeError):
    """A Docker lifecycle or command operation failed."""


_TIMED_OUT = object()


@dataclass
class _RuntimeRecord:
    handle: SandboxHandle
    container: Any
    workspace: Workspace
    spec: SandboxSpec
    terminated: bool = False


class DockerSandboxRuntime:
    def __init__(
        self,
        docker_client: Any,
        workspace_manager: WorkspaceManager,
        artifact_exporter: ArtifactExporter,
    ) -> None:
        self._docker = docker_client
        self._workspaces = workspace_manager
        self._artifacts = artifact_exporter
        self._records: dict[int, _RuntimeRecord] = {}

    def create(self, spec: SandboxSpec) -> SandboxHandle:
        workspace = self._workspaces.create(
            spec.workspace_path,
            run_id=str(uuid4()),
            worker_id=spec.worker_id,
        )
        container: Any | None = None
        try:
            container = self._docker.containers.create(**container_options(spec, workspace.path))
            container.start()
            handle = SandboxHandle(workspace_path=workspace.path)
            self._records[id(handle)] = _RuntimeRecord(handle, container, workspace, spec)
            return handle
        except Exception as exc:
            cleanup_error: Exception | None = None
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception as remove_error:  # noqa: BLE001
                    cleanup_error = remove_error
            try:
                self._workspaces.cleanup(workspace)
            except Exception as workspace_error:  # noqa: BLE001
                cleanup_error = cleanup_error or workspace_error
            if cleanup_error is not None:
                exc.add_note("sandbox creation cleanup encountered an error")
            raise SandboxRuntimeError(f"sandbox container unavailable: {exc}") from exc

    def execute(self, handle: SandboxHandle, command: tuple[str, ...] | list[str]) -> CommandResult:
        record = self._record(handle)
        command_tuple = tuple(command)
        if not command_tuple:
            raise ValueError("command must not be empty")
        started = time.monotonic()
        try:
            raw = self._exec_with_timeout(record, list(command_tuple))
        except TimeoutError:
            self._terminate(record)
            return CommandResult(
                command=command_tuple,
                duration_seconds=time.monotonic() - started,
                timed_out=True,
            )
        except Exception as exc:
            raise SandboxRuntimeError(f"sandbox command failed: {exc}") from exc
        duration = time.monotonic() - started
        if raw is _TIMED_OUT:
            return CommandResult(
                command=command_tuple,
                duration_seconds=duration,
                timed_out=True,
            )
        stdout, stderr = self._output_bytes(getattr(raw, "output", b""))
        stdout, stderr, truncated = self._cap_output(
            stdout,
            stderr,
            record.spec.resource_limits.output_bytes,
        )
        return CommandResult(
            command=command_tuple,
            exit_code=getattr(raw, "exit_code", None),
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            duration_seconds=duration,
            output_truncated=truncated,
        )

    def export(self, handle: SandboxHandle) -> WorkArtifact:
        record = self._record(handle)
        return self._artifacts.collect(record.workspace, record.workspace.baseline)

    def destroy(self, handle: SandboxHandle) -> None:
        record = self._record(handle)
        errors: list[Exception] = []
        if not record.terminated:
            try:
                record.container.stop()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
        try:
            record.container.remove(force=True)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        try:
            self._workspaces.cleanup(record.workspace)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        self._records.pop(id(handle), None)
        if errors:
            raise SandboxRuntimeError("sandbox cleanup failed") from errors[0]

    def _record(self, handle: SandboxHandle) -> _RuntimeRecord:
        record = self._records.get(id(handle))
        if record is None or record.handle is not handle:
            raise SandboxRuntimeError("sandbox handle is unknown or destroyed")
        return record

    @staticmethod
    def _exec_with_timeout(record: _RuntimeRecord, command: list[str]) -> Any:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            record.container.exec_run,
            command,
            workdir="/workspace",
            demux=True,
        )
        try:
            return future.result(timeout=record.spec.resource_limits.timeout_seconds)
        except FutureTimeout:
            future.cancel()
            DockerSandboxRuntime._terminate(record)
            return _TIMED_OUT
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _terminate(record: _RuntimeRecord) -> None:
        if record.terminated:
            return
        record.container.kill()
        record.terminated = True

    @staticmethod
    def _output_bytes(output: Any) -> tuple[bytes, bytes]:
        if isinstance(output, tuple):
            stdout, stderr = output
            return DockerSandboxRuntime._as_bytes(stdout), DockerSandboxRuntime._as_bytes(stderr)
        return DockerSandboxRuntime._as_bytes(output), b""

    @staticmethod
    def _as_bytes(value: Any) -> bytes:
        if value is None:
            return b""
        if isinstance(value, bytes):
            return value
        return str(value).encode("utf-8")

    @staticmethod
    def _cap_output(stdout: bytes, stderr: bytes, limit: int) -> tuple[bytes, bytes, bool]:
        if len(stdout) + len(stderr) <= limit:
            return stdout, stderr, False
        if len(stdout) >= limit:
            return stdout[:limit], b"", True
        remaining = limit - len(stdout)
        return stdout, stderr[:remaining], True
