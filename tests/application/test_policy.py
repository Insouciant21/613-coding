from __future__ import annotations

import os
from pathlib import Path

import pytest

from coding613.application.policy import PolicyEngine, RepositoryPolicyConfig
from coding613.domain.actions import ToolCall
from coding613.domain.models import PermissionMode
from coding613.domain.permissions import PermissionRule
from coding613.ports.policy import PolicyEffect


@pytest.fixture
def config(tmp_path: Path) -> RepositoryPolicyConfig:
    return RepositoryPolicyConfig(
        repository_root=tmp_path,
        validation_commands=(("pytest", "-q"),),
        allow_network=True,
        allow_dependency_install=True,
        allow_git_writes=True,
    )


@pytest.mark.parametrize(
    ("mode", "effect"),
    [
        (PermissionMode.STRICT, PolicyEffect.ASK),
        (PermissionMode.BALANCED, PolicyEffect.ALLOW),
        (PermissionMode.AUTONOMOUS, PolicyEffect.ALLOW),
    ],
)
def test_write_policy_varies_by_mode(
    config: RepositoryPolicyConfig, mode: PermissionMode, effect: PolicyEffect
) -> None:
    call = ToolCall(name="delete_file", arguments={"path": "src/a.py"})
    assert PolicyEngine().evaluate(call, config, mode).effect is effect


def test_delete_policy_honors_disabled_writes(config: RepositoryPolicyConfig) -> None:
    restricted = config.model_copy(update={"allow_writes": False})
    call = ToolCall(name="delete_file", arguments={"path": "src/a.py"})

    decision = PolicyEngine().evaluate(call, restricted, PermissionMode.AUTONOMOUS)

    assert decision.effect is PolicyEffect.DENY
    assert decision.rule_id == "config.writes_disabled"


def test_apply_patch_policy_varies_by_mode(config: RepositoryPolicyConfig) -> None:
    call = ToolCall(name="apply_patch", arguments={"patch": "--- /dev/null\n+++ b/a\n"})
    assert PolicyEngine().evaluate(call, config, PermissionMode.STRICT).effect is PolicyEffect.ASK
    assert PolicyEngine().evaluate(call, config, PermissionMode.BALANCED).effect is PolicyEffect.ALLOW
    assert (
        PolicyEngine()
        .evaluate(call, config.model_copy(update={"allow_writes": False}), PermissionMode.AUTONOMOUS)
        .effect
        is PolicyEffect.DENY
    )


def test_declared_validation_is_allowed_except_in_strict_mode(
    config: RepositoryPolicyConfig,
) -> None:
    call = ToolCall(name="run_command", arguments={"argv": ["pytest", "-q"]})
    engine = PolicyEngine()
    assert engine.evaluate(call, config, PermissionMode.STRICT).effect is PolicyEffect.ASK
    assert engine.evaluate(call, config, PermissionMode.BALANCED).effect is PolicyEffect.ALLOW


@pytest.mark.parametrize(
    "call",
    [
        ToolCall(name="read_file", arguments={"path": "../secret"}),
        ToolCall(name="read_file", arguments={"path": "/etc/passwd"}),
        ToolCall(name="read_file", arguments={"path": "/var/run/docker.sock"}),
        ToolCall(name="run_command", arguments={"argv": ["sudo", "rm", "-rf", "/"]}),
        ToolCall(name="run_command", arguments={"argv": ["sh", "-c", "rm -rf /"]}),
        ToolCall(name="run_command", arguments={"argv": ["docker", "run", "--privileged", "x"]}),
    ],
)
def test_hard_denials_cannot_be_bypassed(
    config: RepositoryPolicyConfig, call: ToolCall
) -> None:
    decision = PolicyEngine().evaluate(call, config, PermissionMode.AUTONOMOUS)
    assert decision.effect is PolicyEffect.DENY
    assert decision.rule_id.startswith("hard.")


def test_secret_bearing_action_is_hard_denied_before_persistence(
    config: RepositoryPolicyConfig,
) -> None:
    call = ToolCall(
        name="edit_file",
        arguments={"path": "settings.py", "content": "api_key=must-not-persist"},
    )

    decision = PolicyEngine().evaluate(call, config, PermissionMode.STRICT)

    assert decision.effect is PolicyEffect.DENY
    assert decision.rule_id == "hard.secret_material"


def test_credential_path_delete_is_hard_denied_in_autonomous_mode(
    config: RepositoryPolicyConfig,
) -> None:
    call = ToolCall(name="delete_file", arguments={"path": ".ssh/id_rsa"})
    decision = PolicyEngine().evaluate(call, config, PermissionMode.AUTONOMOUS)
    assert decision.effect is PolicyEffect.DENY
    assert decision.rule_id == "hard.credential_path"


@pytest.mark.parametrize("path", [".ssh/id_rsa", ".aws/credentials", "nested/.gnupg/key"])
def test_apply_patch_credential_paths_are_hard_denied(
    config: RepositoryPolicyConfig, path: str
) -> None:
    call = ToolCall(
        name="apply_patch",
        arguments={"patch": f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new\n"},
    )
    decision = PolicyEngine().evaluate(call, config, PermissionMode.AUTONOMOUS)
    assert decision.effect is PolicyEffect.DENY
    assert decision.rule_id == "hard.credential_path"


def test_code_token_type_annotation_is_not_treated_as_secret(
    config: RepositoryPolicyConfig,
) -> None:
    call = ToolCall(
        name="edit_file",
        arguments={
            "path": "moves.ts",
            "content": "export function parseMove(token: string) { return token }",
        },
    )

    decision = PolicyEngine().evaluate(call, config, PermissionMode.AUTONOMOUS)

    assert decision.effect is PolicyEffect.ALLOW


def test_symlink_escape_and_memory_override_are_hard_denied(
    tmp_path: Path, config: RepositoryPolicyConfig
) -> None:
    outside = tmp_path.parent / "outside-policy"
    outside.mkdir(exist_ok=True)
    os.symlink(outside, tmp_path / "link")
    call = ToolCall(
        name="edit_file",
        arguments={"path": "link/pwned", "content": "x", "memory_override": "allow"},
    )
    assert PolicyEngine().evaluate(call, config, PermissionMode.AUTONOMOUS).effect is PolicyEffect.DENY


@pytest.mark.parametrize(
    ("call", "config_field"),
    [
        (ToolCall(name="install_dependency", arguments={"name": "x"}), "allow_dependency_install"),
        (ToolCall(name="network_request", arguments={"url": "https://example.invalid"}), "allow_network"),
        (ToolCall(name="git_commit", arguments={"message": "msg"}), "allow_git_writes"),
    ],
)
def test_sensitive_scoped_actions_ask_unless_autonomous_and_declared(
    config: RepositoryPolicyConfig, call: ToolCall, config_field: str
) -> None:
    engine = PolicyEngine()
    assert engine.evaluate(call, config, PermissionMode.BALANCED).effect is PolicyEffect.ASK
    assert engine.evaluate(call, config, PermissionMode.AUTONOMOUS).effect is PolicyEffect.ALLOW
    restricted = config.model_copy(update={config_field: False})
    assert engine.evaluate(call, restricted, PermissionMode.AUTONOMOUS).effect is PolicyEffect.ASK


def test_project_deny_rule_is_applied_after_hard_checks(
    config: RepositoryPolicyConfig,
) -> None:
    restricted = config.model_copy(
        update={
            "permission_rules": (
                PermissionRule(scope="tool", pattern="read_file", effect="deny"),
            )
        }
    )

    decision = PolicyEngine().evaluate(
        ToolCall(name="read_file", arguments={"path": "README.md"}),
        restricted,
        PermissionMode.AUTONOMOUS,
    )

    assert decision.effect is PolicyEffect.DENY
    assert decision.rule_id == "config.permission_rule_denied"


def test_project_allow_rule_can_resolve_an_approval_but_not_a_hard_denial(
    config: RepositoryPolicyConfig,
) -> None:
    allowed = config.model_copy(
        update={
            "permission_rules": (
                PermissionRule(scope="tool", pattern="edit_file", effect="allow"),
            )
        }
    )
    engine = PolicyEngine()
    edit = ToolCall(name="edit_file", arguments={"path": "src/a.py", "content": "x"})

    assert engine.evaluate(edit, allowed, PermissionMode.STRICT).effect is PolicyEffect.ALLOW

    hard = ToolCall(name="read_file", arguments={"path": "../secret"})
    hard_allowed = allowed.model_copy(
        update={
            "permission_rules": (
                PermissionRule(scope="path", pattern="README.md", effect="allow"),
            )
        }
    )
    hard_decision = engine.evaluate(hard, hard_allowed, PermissionMode.AUTONOMOUS)
    assert hard_decision.effect is PolicyEffect.DENY
    assert hard_decision.rule_id.startswith("hard.")


def test_project_path_rule_matches_normalized_repository_paths(
    config: RepositoryPolicyConfig,
) -> None:
    restricted = config.model_copy(
        update={
            "permission_rules": (
                PermissionRule(scope="path", pattern="src/private/**", effect="deny"),
            )
        }
    )

    decision = PolicyEngine().evaluate(
        ToolCall(name="read_file", arguments={"path": "src/private/key.txt"}),
        restricted,
        PermissionMode.AUTONOMOUS,
    )

    assert decision.effect is PolicyEffect.DENY
    assert decision.rule_id == "config.permission_rule_denied"
