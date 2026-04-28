from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from codeflow.git_guard import (
    create_ai_branch,
    ensure_clean_worktree,
    ensure_git_repo,
    get_diff,
    rollback,
    slugify,
)


def _run(cmd: list[str], cwd: Path) -> None:
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr or result.stdout


def _init_repo(path: Path) -> None:
    _run(["git", "init"], path)
    (path / "sample.txt").write_text("hello\n", encoding="utf-8")
    _run(["git", "add", "."], path)
    _run(
        [
            "git",
            "-c",
            "user.email=test@example.local",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "init",
        ],
        path,
    )


def test_git_guard_branch_diff_and_rollback(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    ensure_git_repo(str(tmp_path))
    ensure_clean_worktree(str(tmp_path))
    branch = create_ai_branch(str(tmp_path), "Add Due Date")
    (tmp_path / "sample.txt").write_text("hello\nworld\n", encoding="utf-8")

    assert branch.startswith("ai/add-due-date-")
    assert "world" in get_diff(str(tmp_path))

    rollback(str(tmp_path))
    assert (tmp_path / "sample.txt").read_text(encoding="utf-8") == "hello\n"


def test_get_diff_includes_untracked_files(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "new_file.py").write_text("print('new')\n", encoding="utf-8")

    diff = get_diff(str(tmp_path))

    assert "new_file.py" in diff
    assert "+print('new')" in diff


def test_clean_worktree_rejects_dirty_repo(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "sample.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="not clean"):
        ensure_clean_worktree(str(tmp_path))


def test_slugify_keeps_chinese_and_limits_length() -> None:
    assert slugify("给 Todo 增加 due_date 字段").startswith("给-todo-增加-due-date")
    assert len(slugify("x" * 100)) == 40
