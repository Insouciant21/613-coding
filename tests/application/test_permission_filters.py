from __future__ import annotations

from pathlib import Path

import pytest

from coding613.application.policy import PolicyEngine, RepositoryPolicyConfig
from coding613.domain.actions import ToolCall
from coding613.domain.models import PermissionMode
from coding613.domain.permissions import PermissionRule, ToolFilter
from coding613.ports.policy import PolicyEffect


def test_disallowed_tool_cannot_override_hard_secret_denial(tmp_path: Path) -> None:
    call = ToolCall(name="read_file", arguments={"path": "config", "token": "secret"})
    decision = PolicyEngine().evaluate(
        call,
        RepositoryPolicyConfig(repository_root=tmp_path),
        PermissionMode.AUTONOMOUS,
    )

    filtered = ToolFilter(disallowed=frozenset({"read_file"})).apply(call, decision)

    assert filtered.effect is PolicyEffect.DENY
    assert filtered.rule_id == "hard.secret_material"


def test_allowlist_denies_unlisted_safe_tool() -> None:
    call = ToolCall(name="read_file", arguments={"path": "README.md"})
    decision = PolicyEngine().evaluate(
        call,
        RepositoryPolicyConfig(repository_root=Path.cwd()),
        PermissionMode.BALANCED,
    )

    filtered = ToolFilter(allowed=frozenset({"git_diff"})).apply(call, decision)

    assert filtered.effect is PolicyEffect.DENY
    assert filtered.rule_id == "invocation.tool_not_allowed"


def test_bypass_cannot_override_invocation_disallow(tmp_path: Path) -> None:
    call = ToolCall(
        name="run_command", arguments={"argv": ["python", "-V"]}
    )
    allowed = PolicyEngine().evaluate(
        call,
        RepositoryPolicyConfig(repository_root=tmp_path),
        PermissionMode.BYPASS,
    )

    filtered = ToolFilter(disallowed=frozenset({"run_command"})).apply(
        call, allowed
    )

    assert filtered.effect is PolicyEffect.DENY
    assert filtered.rule_id == "invocation.tool_disallowed"


@pytest.mark.parametrize("pattern", ["/etc/passwd", "../secret", "src;rm -rf *", ".ssh/id_rsa"])
def test_path_permission_rule_rejects_escape_shell_and_credentials(pattern: str) -> None:
    with pytest.raises(ValueError):
        PermissionRule(scope="path", pattern=pattern, effect="deny")
