"""Deterministic repository policy evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from pydantic import Field, field_validator

from coding_harness.domain.actions import ToolCall
from coding_harness.domain.events import redact_payload
from coding_harness.domain.models import PermissionMode
from coding_harness.domain.models_base import DomainModel
from coding_harness.ports.policy import PolicyDecision, PolicyEffect


class RepositoryPolicyConfig(DomainModel):
    repository_root: Path
    validation_commands: tuple[tuple[str, ...], ...] = ()
    allow_network: bool = False
    allow_dependency_install: bool = False
    allow_git_writes: bool = False
    allow_writes: bool = True
    denied_tools: frozenset[str] = Field(default_factory=frozenset)

    @field_validator("repository_root")
    @classmethod
    def canonicalize_root(cls, value: Path) -> Path:
        root = value.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("repository_root must be a directory")
        return root


class PolicyEngine:
    _READ_TOOLS: ClassVar[frozenset[str]] = frozenset(
        {"git_diff", "list_files", "read_file", "search_files"}
    )
    _WRITE_TOOLS: ClassVar[frozenset[str]] = frozenset(
        {"apply_patch", "edit_file", "write_file"}
    )
    _NETWORK_TOOLS: ClassVar[frozenset[str]] = frozenset({"network_request"})
    _INSTALL_TOOLS: ClassVar[frozenset[str]] = frozenset({"install_dependency"})
    _GIT_WRITE_TOOLS: ClassVar[frozenset[str]] = frozenset(
        {"git_add", "git_commit", "git_push"}
    )
    _CREDENTIAL_PARTS: ClassVar[frozenset[str]] = frozenset(
        {".aws", ".gnupg", ".ssh", "credentials", "id_rsa", "id_ed25519"}
    )

    def evaluate(
        self,
        call: ToolCall,
        config: RepositoryPolicyConfig,
        mode: PermissionMode,
    ) -> PolicyDecision:
        hard_rule = self._hard_denial(call, config.repository_root)
        if hard_rule is not None:
            return self._decision(PolicyEffect.DENY, hard_rule, "hard safety rule", call)
        if call.name in config.denied_tools:
            return self._decision(
                PolicyEffect.DENY, "config.denied_tool", "repository policy denied tool", call
            )
        if call.name in self._READ_TOOLS:
            return self._decision(PolicyEffect.ALLOW, "mode.read", "safe read", call)
        if call.name in self._WRITE_TOOLS:
            if not config.allow_writes:
                return self._decision(
                    PolicyEffect.DENY, "config.writes_disabled", "repository writes disabled", call
                )
            effect = PolicyEffect.ASK if mode is PermissionMode.STRICT else PolicyEffect.ALLOW
            return self._decision(effect, f"mode.{mode.value}.write", "repository write", call)
        if call.name == "run_command":
            return self._command_decision(call, config, mode)
        if call.name in self._INSTALL_TOOLS:
            return self._scoped_sensitive(
                call, mode, config.allow_dependency_install, "dependency_install"
            )
        if call.name in self._NETWORK_TOOLS:
            return self._scoped_sensitive(call, mode, config.allow_network, "network")
        if call.name in self._GIT_WRITE_TOOLS:
            return self._scoped_sensitive(call, mode, config.allow_git_writes, "git_write")
        return self._decision(
            PolicyEffect.DENY, "policy.unknown_tool", "unknown tool category", call
        )

    def _command_decision(
        self,
        call: ToolCall,
        config: RepositoryPolicyConfig,
        mode: PermissionMode,
    ) -> PolicyDecision:
        argv = call.arguments.get("argv")
        if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
            return self._decision(
                PolicyEffect.DENY, "hard.invalid_argv", "command requires argv array", call
            )
        command = tuple(argv)
        if command in config.validation_commands:
            effect = PolicyEffect.ASK if mode is PermissionMode.STRICT else PolicyEffect.ALLOW
            return self._decision(
                effect, f"mode.{mode.value}.validation", "declared validation command", call
            )
        return self._decision(
            PolicyEffect.ASK, f"mode.{mode.value}.command", "undeclared command", call
        )

    def _scoped_sensitive(
        self,
        call: ToolCall,
        mode: PermissionMode,
        configured: bool,
        category: str,
    ) -> PolicyDecision:
        effect = (
            PolicyEffect.ALLOW
            if mode is PermissionMode.AUTONOMOUS and configured
            else PolicyEffect.ASK
        )
        return self._decision(
            effect, f"mode.{mode.value}.{category}", f"scoped {category}", call
        )

    def _hard_denial(self, call: ToolCall, root: Path) -> str | None:
        if redact_payload(call.arguments) != call.arguments:
            return "hard.secret_material"
        strings = tuple(self._strings(call.arguments))
        if any("/var/run/docker.sock" in value for value in strings):
            return "hard.docker_socket"
        for key in ("cwd", "path", "root", "target"):
            value = call.arguments.get(key)
            if isinstance(value, str):
                path_rule = self._path_rule(value, root)
                if path_rule is not None:
                    return path_rule
        argv = call.arguments.get("argv")
        if isinstance(argv, list) and all(isinstance(item, str) for item in argv):
            lowered = tuple(item.lower() for item in argv)
            if lowered and lowered[0] in {"sudo", "su", "shutdown", "reboot", "mkfs", "dd"}:
                return "hard.destructive_command"
            if "--privileged" in lowered or "/var/run/docker.sock" in lowered:
                return "hard.privileged_container"
            if lowered and lowered[0] == "rm" and any(item in {"/", "~"} for item in lowered):
                return "hard.destructive_command"
            if lowered and lowered[0] in {"bash", "sh", "zsh"} and "-c" in lowered:
                script = " ".join(lowered[lowered.index("-c") + 1 :])
                if any(
                    fragment in script
                    for fragment in ("rm -rf /", "rm -rf ~", "mkfs", "shutdown", "reboot")
                ):
                    return "hard.destructive_command"
        return None

    def _path_rule(self, value: str, root: Path) -> str | None:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            return "hard.repository_escape"
        if set(path.parts) & self._CREDENTIAL_PARTS:
            return "hard.credential_path"
        resolved = (root / path).resolve(strict=False)
        if not resolved.is_relative_to(root):
            return "hard.repository_escape"
        return None

    @classmethod
    def _strings(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [item for nested in value.values() for item in cls._strings(nested)]
        if isinstance(value, (list, tuple)):
            return [item for nested in value for item in cls._strings(nested)]
        return []

    @staticmethod
    def _decision(
        effect: PolicyEffect, rule_id: str, reason: str, call: ToolCall
    ) -> PolicyDecision:
        return PolicyDecision(effect=effect, rule_id=rule_id, reason=reason, action=call)
