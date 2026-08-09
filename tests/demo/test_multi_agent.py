from __future__ import annotations

from coding613.demo.multi_agent import run_multi_agent_demo


def test_multi_agent_demo_exposes_supervisor_feedback_approval_and_integration() -> None:
    summary = run_multi_agent_demo()

    assert summary.state == "completed"
    assert summary.feedback_repaired is True
    assert summary.approval_granted is True
    assert summary.integration_applied is True
    assert summary.final_validation_passed is True
    assert summary.total_calls == 5
    assert "graph.created" in summary.events
