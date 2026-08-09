"""Pure-Python Git worktree inspection."""

from io import BytesIO
from pathlib import Path

from dulwich import porcelain


class GitTools:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve(strict=True)

    def diff(self) -> str:
        output = BytesIO()
        porcelain.diff(self.root, outstream=output)
        return output.getvalue().decode("utf-8", errors="replace")
