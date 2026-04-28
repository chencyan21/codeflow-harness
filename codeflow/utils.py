from __future__ import annotations

from pathlib import Path


def read_project_rules(repo: str) -> str:
    path = Path(repo) / ".codeflow" / "project_rules.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return """Default project rules:
- Keep changes minimal.
- Do not delete existing tests.
- Do not modify .env or secret files.
- Run required checks before reporting success.
"""


def tail_text(text: str, limit: int = 8000) -> str:
    return text[-limit:] if len(text) > limit else text
