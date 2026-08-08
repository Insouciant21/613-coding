"""Role-specific tool capabilities for product workers."""

from __future__ import annotations

from coding_harness.domain.models_base import DomainModel
from coding_harness.domain.tasks import WorkerRole


class ToolPolicy(DomainModel):
    allowed_tools: frozenset[str]
    allow_writes: bool
    role: WorkerRole


_READ_TOOLS = frozenset({"read_file", "search_files", "list_files", "git_diff"})
_WRITE_TOOLS = frozenset({"edit_file", "write_file", "apply_patch"})


def role_policy(role: WorkerRole) -> ToolPolicy:
    if role is WorkerRole.CODER:
        return ToolPolicy(role=role, allowed_tools=_READ_TOOLS | _WRITE_TOOLS, allow_writes=True)
    return ToolPolicy(role=role, allowed_tools=_READ_TOOLS | {"run_command"}, allow_writes=False)
