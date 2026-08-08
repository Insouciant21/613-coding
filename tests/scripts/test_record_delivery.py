from __future__ import annotations

from pathlib import Path

import pytest

from scripts import record_delivery


def test_record_delivery_appends_structured_evidence_and_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    log = tmp_path / "AGENT_LOG.md"
    status = tmp_path / "DELIVERY_STATUS.md"
    log.write_text("# log\n", encoding="utf-8")
    status.write_text("# status\n", encoding="utf-8")
    monkeypatch.setattr(record_delivery, "AGENT_LOG_PATH", log)
    monkeypatch.setattr(record_delivery, "DELIVERY_STATUS_PATH", status)

    args = ["--task", "DELIVERY-X", "--status", "pass", "--command", "uv run pytest", "--result", "3 passed", "--commit", "HEAD"]
    assert record_delivery.record(args) is True
    first_log = log.read_text(encoding="utf-8")
    assert "Asia/Shanghai" in first_log and "uv run pytest" in first_log and "3 passed" in first_log
    assert record_delivery.record(args) is False
    assert log.read_text(encoding="utf-8") == first_log
    assert status.read_text(encoding="utf-8").count("DELIVERY-X") == 1


def test_record_delivery_keeps_failed_status_visible(tmp_path: Path, monkeypatch) -> None:
    log = tmp_path / "AGENT_LOG.md"
    status = tmp_path / "DELIVERY_STATUS.md"
    log.write_text("", encoding="utf-8")
    status.write_text("", encoding="utf-8")
    monkeypatch.setattr(record_delivery, "AGENT_LOG_PATH", log)
    monkeypatch.setattr(record_delivery, "DELIVERY_STATUS_PATH", status)
    assert record_delivery.record(["--task", "DELIVERY-Y", "--status", "fail", "--command", "docker build", "--result", "network reset", "--commit", "HEAD"]) is True
    assert "fail" in log.read_text(encoding="utf-8")
    assert "network reset" in status.read_text(encoding="utf-8")


def test_record_delivery_rejects_unknown_commit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(record_delivery, "AGENT_LOG_PATH", tmp_path / "log")
    monkeypatch.setattr(record_delivery, "DELIVERY_STATUS_PATH", tmp_path / "status")
    with pytest.raises(ValueError, match="commit"):
        record_delivery.record(["--task", "DELIVERY-Z", "--status", "pass", "--command", "true", "--result", "ok", "--commit", "not-a-commit"])
