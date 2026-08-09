"""Deterministic planner/coder/tester/reviewer Supervisor demonstration."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from coding613.adapters.orchestration.integration_workspace import IntegrationWorkspace
from coding613.adapters.storage.sqlite import SqliteEventStore
from coding613.application.approvals import ApprovalDecision, ApprovalService
from coding613.application.artifact_integrator import ArtifactIntegrator
from coding613.application.policy import PolicyEngine, RepositoryPolicyConfig
from coding613.application.supervisor import Supervisor, SupervisorSummary
from coding613.domain.actions import ToolCall
from coding613.domain.models import PermissionMode, Run
from coding613.domain.sandbox import WorkArtifact
from coding613.domain.tasks import TaskNode, WorkerRole
from coding613.domain.worker import WorkerContext


class _ScriptedWorker:
    def __init__(self) -> None:
        self.calls: dict[str, int] = {}

    async def run(self, node: TaskNode, context: WorkerContext) -> WorkArtifact:
        del context
        self.calls[node.id] = self.calls.get(node.id, 0) + 1
        if node.id == "code" and self.calls[node.id] == 1:
            raise RuntimeError("objective test failure")
        if node.id == "code":
            return WorkArtifact(
                patch=(
                    "diff --git a/main.py b/main.py\n"
                    "--- a/main.py\n+++ b/main.py\n"
                    "@@ -1 +1 @@\n"
                    "-print('before')\n+print('after')\n"
                ),
                changed_files=("main.py",),
                summary="corrected patch",
            )
        return WorkArtifact(summary=f"{node.id} complete")


def run_multi_agent_demo() -> SupervisorSummary:
    with tempfile.TemporaryDirectory(prefix="613-multi-demo-") as temporary:
        root = Path(temporary)
        repo = _repo(root / "repo")
        worker = _ScriptedWorker()
        supervisor = Supervisor(
            workers={role: worker for role in WorkerRole},
            project_root=repo,
            max_total_calls=8,
        )
        graph_id = supervisor.create_graph(
            (
                TaskNode(id="plan", title="plan", role=WorkerRole.PLANNER),
                TaskNode(id="code", title="code", role=WorkerRole.CODER, dependencies=("plan",), max_attempts=2),
                TaskNode(id="test", title="test", role=WorkerRole.TESTER, dependencies=("code",)),
                TaskNode(id="review", title="review", role=WorkerRole.REVIEWER, dependencies=("test",)),
            )
        )
        summary = asyncio.run(supervisor.run(graph_id))
        code_artifact = summary.artifacts["code"]

        policy = PolicyEngine().evaluate(
            ToolCall(name="edit_file", arguments={"path": "main.py", "content": "print('after')\n"}),
            RepositoryPolicyConfig(repository_root=repo),
            PermissionMode.STRICT,
        )
        approvals_store = SqliteEventStore(root / "approval.sqlite")
        approval_run_id = uuid4()
        approvals_store.create_run(Run(id=approval_run_id, task="integrate worker artifact"))
        approvals = ApprovalService(run_id=approval_run_id, store=approvals_store)
        request = approvals.request(policy)
        resolution = approvals.resolve(request.id, ApprovalDecision.APPROVE)
        approval_granted = resolution.decision is ApprovalDecision.APPROVE

        integration = ArtifactIntegrator().apply(
            code_artifact,
            IntegrationWorkspace(repo, declared_write_set=("main.py",)),
        )
        validation_passed = (repo / "main.py").read_text(encoding="utf-8") == "print('after')\n"
        return summary.model_copy(
            update={
                "feedback_repaired": worker.calls.get("code") == 2,
                "approval_granted": approval_granted,
                "integration_applied": integration.applied,
                "final_validation_passed": validation_passed,
            }
        )


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "demo@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Demo"], check=True)
    (path / "main.py").write_text("print('before')\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "main.py"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "baseline"], check=True)
    return path
