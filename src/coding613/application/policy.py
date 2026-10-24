"""Deterministic repository policy evaluation."""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, ClassVar

from pydantic import Field, field_validator, model_validator

from coding613.domain.actions import ToolCall
from coding613.domain.events import redact_payload
from coding613.domain.models import PermissionMode
from coding613.domain.models_base import DomainModel
from coding613.domain.permissions import PermissionRule
from coding613.domain.sandbox import ResourceLimits
from coding613.ports.policy import PolicyDecision, PolicyEffect


class RepositoryPolicyConfig(DomainModel):
    repository_root: Path
    validation_commands: tuple[tuple[str, ...], ...] = ()
    allow_network: bool = False
    allow_dependency_install: bool = False
    allow_git_writes: bool = False
    allow_writes: bool = True
    denied_tools: frozenset[str] = Field(default_factory=frozenset)
    permission_rules: tuple[PermissionRule, ...] = ()

    @field_validator("repository_root")
    @classmethod
    def canonicalize_root(cls, value: Path) -> Path:
        root = value.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("repository_root must be a directory")
        return root

    @model_validator(mode="after")
    def validate_permission_rules(self) -> RepositoryPolicyConfig:
        keys = [(rule.scope, rule.pattern) for rule in self.permission_rules]
        if len(keys) != len(set(keys)):
            raise ValueError("permission rules must be unique by scope and pattern")
        return self


class SandboxPolicyConfig(DomainModel):
    """Operator-approved bounds for one worker sandbox."""

    max_limits: ResourceLimits = Field(default_factory=ResourceLimits)
    allow_network: bool = False
    network_allowlist: tuple[str, ...] = ()
    environment_allowlist: frozenset[str] = Field(default_factory=frozenset)
    approved_images: frozenset[str] = Field(default_factory=frozenset)


class PolicyEngine:
    _READ_TOOLS: ClassVar[frozenset[str]] = frozenset(
        {"git_diff", "list_files", "read_file", "search_files"}
    )
    _WRITE_TOOLS: ClassVar[frozenset[str]] = frozenset(
        {"apply_patch", "delete_file", "edit_file", "write_file"}
    )
    _NETWORK_TOOLS: ClassVar[frozenset[str]] = frozenset({"network_request"})
    _VALIDATION_TOOLS: ClassVar[frozenset[str]] = frozenset({"run_validation"})
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
            rule_id, detail = hard_rule
            return self._decision(
                PolicyEffect.DENY, rule_id, f"hard safety rule: {detail}", call
            )
        if call.name in config.denied_tools:
            return self._decision(
                PolicyEffect.DENY, "config.denied_tool", "repository policy denied tool", call
            )
        decision = self._repository_decision(call, config, mode)
        if decision.effect is PolicyEffect.DENY:
            return decision
        rule = self._matching_permission_rule(call, config.permission_rules, config.repository_root)
        if rule is not None and rule.effect == "deny":
            return self._decision(
                PolicyEffect.DENY,
                "config.permission_rule_denied",
                "project permission rule denied action",
                call,
            )
        if rule is not None and rule.effect == "allow" and decision.effect is PolicyEffect.ASK:
            decision = self._decision(
                PolicyEffect.ALLOW,
                "config.permission_rule_allowed",
                "project permission rule allowed action",
                call,
            )
        return self._apply_permission_mode(decision, mode)

    @staticmethod
    def _apply_permission_mode(
        decision: PolicyDecision, mode: PermissionMode
    ) -> PolicyDecision:
        if mode is PermissionMode.BYPASS and decision.effect is PolicyEffect.ASK:
            return decision.model_copy(update={"effect": PolicyEffect.ALLOW})
        return decision

    def _repository_decision(
        self,
        call: ToolCall,
        config: RepositoryPolicyConfig,
        mode: PermissionMode,
    ) -> PolicyDecision:
        if call.name in self._READ_TOOLS:
            return self._decision(PolicyEffect.ALLOW, "mode.read", "safe read", call)
        if call.name in self._WRITE_TOOLS:
            if not config.allow_writes:
                return self._decision(
                    PolicyEffect.DENY, "config.writes_disabled", "repository writes disabled", call
                )
            effect = PolicyEffect.ASK if mode is PermissionMode.STRICT else PolicyEffect.ALLOW
            return self._decision(effect, f"mode.{mode.value}.write", "repository write", call)
        if call.name in {"run_command", "run_shell"}:
            return self._command_decision(call, config, mode)
        if call.name in self._VALIDATION_TOOLS:
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

    @staticmethod
    def _matching_permission_rule(
        call: ToolCall,
        rules: tuple[PermissionRule, ...],
        root: Path,
    ) -> PermissionRule | None:
        for rule in rules:
            if rule.scope == "tool" and rule.pattern == call.name:
                return rule
            if rule.scope != "path":
                continue
            for value in PolicyEngine._path_values(call):
                normalized = PolicyEngine._normalize_rule_path(value, root)
                if normalized is not None and fnmatchcase(normalized, rule.pattern):
                    return rule
        return None

    @staticmethod
    def _path_values(call: ToolCall) -> tuple[str, ...]:
        values: list[str] = []
        for key in ("path", "cwd", "root", "target"):
            value = call.arguments.get(key)
            if isinstance(value, str):
                values.append(value)
        if call.name == "apply_patch":
            patch = call.arguments.get("patch")
            if isinstance(patch, str):
                for line in patch.splitlines():
                    if line.startswith(("--- ", "+++ ")):
                        path = line[4:].split("\t", 1)[0].strip()
                        if path != "/dev/null":
                            values.append(path[2:] if path[:2] in {"a/", "b/"} else path)
            operation = call.arguments.get("operation")
            if isinstance(operation, dict):
                operation_path = operation.get("path")
                if isinstance(operation_path, str):
                    values.append(operation_path)
        return tuple(values)

    @staticmethod
    def _normalize_rule_path(value: str, root: Path) -> str | None:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            return None
        resolved = (root / path).resolve(strict=False)
        if not resolved.is_relative_to(root):
            return None
        return path.as_posix().removeprefix("./")

    def _command_decision(
        self,
        call: ToolCall,
        config: RepositoryPolicyConfig,
        mode: PermissionMode,
    ) -> PolicyDecision:
        if call.name == "run_shell":
            commands = call.arguments.get("commands")
            if not isinstance(commands, list) or not commands:
                return self._decision(
                    PolicyEffect.DENY,
                    "hard.invalid_commands",
                    "shell requires a non-empty commands array",
                    call,
                )
            argv_values = [item.get("argv") for item in commands if isinstance(item, dict)]
            if len(argv_values) != len(commands):
                return self._decision(
                    PolicyEffect.DENY,
                    "hard.invalid_argv",
                    "every shell command requires an argv array",
                    call,
                )
            if not all(isinstance(argv, list) and all(isinstance(item, str) for item in argv) for argv in argv_values):
                return self._decision(
                    PolicyEffect.DENY,
                    "hard.invalid_argv",
                    "every shell command requires an argv array",
                    call,
                )
            if len(argv_values) == 1:
                call = call.model_copy(update={"arguments": {"argv": argv_values[0]}})
            else:
                return self._decision(
                    PolicyEffect.ASK,
                    f"mode.{mode.value}.command_batch",
                    "ordered shell command batch",
                    call,
                )
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

    def _hard_denial(self, call: ToolCall, root: Path) -> tuple[str, str] | None:
        # Returns (rule_id, offending detail) so denials can tell the model
        # exactly which value tripped the hard rule.
        if redact_payload(call.arguments) != call.arguments:
            return ("hard.secret_material", "arguments contained redacted secret material")
        strings = tuple(self._strings(call.arguments))
        for value in strings:
            if "/var/run/docker.sock" in value:
                return ("hard.docker_socket", value)
        for key in ("cwd", "path", "root", "target"):
            argument = call.arguments.get(key)
            if isinstance(argument, str):
                path_rule = self._path_rule(argument, root)
                if path_rule is not None:
                    return (path_rule, argument)
        if call.name == "apply_patch":
            patch = call.arguments.get("patch")
            if isinstance(patch, str):
                for line in patch.splitlines():
                    if not line.startswith(("--- ", "+++ ")):
                        continue
                    value = line[4:].split("\t", 1)[0].strip()
                    if value == "/dev/null":
                        continue
                    path_rule = self._path_rule(value, root)
                    if path_rule is not None:
                        return (path_rule, value)
            operation = call.arguments.get("operation")
            if isinstance(operation, dict):
                path = operation.get("path")
                if isinstance(path, str):
                    path_rule = self._path_rule(path, root)
                    if path_rule is not None:
                        return (path_rule, path)
        argv = call.arguments.get("argv")
        if isinstance(argv, list) and all(isinstance(item, str) for item in argv):
            lowered = tuple(item.lower() for item in argv)
            if lowered and lowered[0] in {"sudo", "su", "shutdown", "reboot", "mkfs", "dd"}:
                return ("hard.destructive_command", " ".join(lowered[:3]))
            if "--privileged" in lowered or "/var/run/docker.sock" in lowered:
                return ("hard.privileged_container", " ".join(lowered[:3]))
            if lowered and lowered[0] == "rm" and any(item in {"/", "~"} for item in lowered):
                return ("hard.destructive_command", " ".join(lowered[:3]))
            if lowered and lowered[0] in {"bash", "sh", "zsh"} and "-c" in lowered:
                script = " ".join(lowered[lowered.index("-c") + 1 :])
                for fragment in ("rm -rf /", "rm -rf ~", "mkfs", "shutdown", "reboot"):
                    if fragment in script:
                        return ("hard.destructive_command", fragment)
        commands = call.arguments.get("commands")
        if isinstance(commands, list):
            for command in commands:
                if not isinstance(command, dict):
                    continue
                nested = ToolCall(name="run_command", arguments=command)
                nested_rule = self._hard_denial(nested, root)
                if nested_rule is not None:
                    return nested_rule
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
