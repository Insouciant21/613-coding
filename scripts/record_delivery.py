"""Append verified delivery evidence without inventing a pass state."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
AGENT_LOG_PATH = ROOT / "AGENT_LOG.md"
DELIVERY_STATUS_PATH = ROOT / "DELIVERY_STATUS.md"
VALID_STATUSES = {"pass", "fail", "blocked", "in_progress"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--status", choices=sorted(VALID_STATUSES), required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--commit", required=True)
    return parser


def _validate_commit(commit: str) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"{commit}^{{commit}}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(f"unknown commit: {commit}") from error
    return result.stdout.strip()


def record(argv: list[str] | None = None) -> bool:
    args = _parser().parse_args(argv)
    commit = _validate_commit(args.commit)
    marker = f"{args.task} | {commit}"
    existing = AGENT_LOG_PATH.read_text(encoding="utf-8") if AGENT_LOG_PATH.exists() else ""
    if marker in existing:
        return False
    timestamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S %Z (Asia/Shanghai)")
    entry = (
        f"\n### {timestamp} - {args.task}\n\n"
        f"- Evidence: {marker}\n"
        f"- Status: {args.status}\n"
        f"- Command: `{args.command}`\n"
        f"- Result: {args.result}\n"
    )
    AGENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    DELIVERY_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AGENT_LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(entry)
    with DELIVERY_STATUS_PATH.open("a", encoding="utf-8") as stream:
        stream.write(f"\n- {args.task} | {commit} | {args.status} | {args.result}\n")
    return True


def main() -> int:
    try:
        record()
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
