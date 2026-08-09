"""Deterministic composition of hard sandbox rules and operator approvals."""

from __future__ import annotations

import re

from coding613.application.policy import SandboxPolicyConfig
from coding613.domain.models import PermissionMode
from coding613.domain.models_base import DomainModel
from coding613.domain.sandbox import CommandResult, NetworkPolicy, ResourceLimits, SandboxSpec


class SandboxDecision(DomainModel):
    allowed: bool
    rule_id: str
    reason: str
    network_policy: NetworkPolicy = NetworkPolicy.DENY
    approved_networks: tuple[str, ...] = ()
    resource_exhausted: bool = False


class SandboxPolicy:
    _DIGEST = re.compile(r"sha256:[0-9a-fA-F]{64}")
    _CREDENTIAL_NAMES = frozenset(
        {
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "SSH_AUTH_SOCK",
        }
    )

    def validate(
        self,
        spec: SandboxSpec,
        mode: PermissionMode,
        config: SandboxPolicyConfig,
    ) -> SandboxDecision:
        del mode  # Mode cannot relax hard sandbox constraints.
        if self._DIGEST.fullmatch(spec.image_digest) is None:
            return self._deny("hard.image_digest", "image must use a pinned sha256 digest")
        if config.approved_images and spec.image_digest not in config.approved_images:
            return self._deny("hard.image_not_approved", "image digest is not approved")
        if spec.run_as_user == 0:
            return self._deny("hard.root_user", "sandbox workers cannot run as root")
        if spec.capabilities:
            return self._deny("hard.capabilities", "sandbox capabilities must be dropped")
        if not spec.read_only_root:
            return self._deny("hard.read_only_root", "sandbox root must be read-only")
        if set(spec.environment_allowlist) & self._CREDENTIAL_NAMES:
            return self._deny("hard.credential_environment", "credential environment is forbidden")
        if not set(spec.environment_allowlist).issubset(config.environment_allowlist):
            return self._deny("hard.environment_not_approved", "environment is not approved")
        if not self._within_limits(spec.resource_limits, config.max_limits):
            return self._deny("hard.resource_limit", "sandbox resource exceeds configured bound")
        if spec.network_policy is NetworkPolicy.ALLOWLIST:
            if not config.allow_network or not config.network_allowlist:
                return self._deny("hard.network_not_approved", "network allowlist is not approved")
            return SandboxDecision(
                allowed=True,
                rule_id="network.allowlist",
                reason="exact network allowlist approved",
                network_policy=spec.network_policy,
                approved_networks=config.network_allowlist,
            )
        return SandboxDecision(
            allowed=True,
            rule_id="sandbox.default_deny",
            reason="network denied by default",
            network_policy=NetworkPolicy.DENY,
        )

    def evaluate_result(self, result: CommandResult, config: SandboxPolicyConfig) -> SandboxDecision:
        del config
        if result.timed_out:
            return self._resource("resource.timeout", "command exceeded timeout")
        if result.resource_exhausted:
            return self._resource("resource.limit", "sandbox resource was exhausted")
        if result.output_truncated:
            return self._resource("resource.output_limit", "command output exceeded cap")
        return SandboxDecision(
            allowed=True,
            rule_id="result.within_limits",
            reason="command stayed within sandbox limits",
        )

    @staticmethod
    def _within_limits(actual: ResourceLimits, maximum: ResourceLimits) -> bool:
        return (
            actual.cpu_seconds <= maximum.cpu_seconds
            and actual.memory_bytes <= maximum.memory_bytes
            and actual.pids <= maximum.pids
            and actual.disk_bytes <= maximum.disk_bytes
            and actual.timeout_seconds <= maximum.timeout_seconds
            and actual.output_bytes <= maximum.output_bytes
        )

    @staticmethod
    def _deny(rule_id: str, reason: str) -> SandboxDecision:
        return SandboxDecision(allowed=False, rule_id=rule_id, reason=reason)

    @staticmethod
    def _resource(rule_id: str, reason: str) -> SandboxDecision:
        return SandboxDecision(
            allowed=False,
            rule_id=rule_id,
            reason=reason,
            resource_exhausted=True,
        )
