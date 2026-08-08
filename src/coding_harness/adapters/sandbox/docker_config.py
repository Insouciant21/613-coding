"""Translate validated sandbox specs into constrained Docker options."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from coding_harness.domain.sandbox import SandboxSpec


def container_options(spec: SandboxSpec, workspace_path: Path) -> dict[str, Any]:
    """Build a complete, explicit container configuration without host credentials."""

    limits = spec.resource_limits
    return {
        "image": spec.image_digest,
        "command": ["sleep", "infinity"],
        "detach": True,
        "working_dir": "/workspace",
        "user": spec.run_as_user,
        "read_only": spec.read_only_root,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        # ALLOWLIST remains isolated until SANDBOX-04 supplies an exact Docker network.
        "network_disabled": True,
        "pids_limit": limits.pids,
        "mem_limit": limits.memory_bytes,
        "nano_cpus": 1_000_000_000,
        # Requires a Docker storage driver with project-quota support.
        "storage_opt": {"size": str(limits.disk_bytes)},
        "volumes": {str(workspace_path): {"bind": "/workspace", "mode": "rw"}},
    }
