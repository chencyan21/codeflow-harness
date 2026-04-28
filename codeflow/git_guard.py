from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


def run_cmd(cmd: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)


def ensure_git_repo(repo: str) -> None:
    result = run_cmd(["git", "rev-parse", "--is-inside-work-tree"], repo)
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise RuntimeError(f"{repo} is not a Git repository")


def ensure_clean_worktree(repo: str) -> None:
    result = run_cmd(["git", "status", "--porcelain"], repo)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to inspect Git worktree")
    if result.stdout.strip():
        raise RuntimeError("Git worktree is not clean. Commit or stash changes first.")


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text)
    text = text.strip("-")
    return text[:40] or "task"


def create_ai_branch(repo: str, task: str) -> str:
    branch = f"ai/{slugify(task)}-{datetime.now().strftime('%m%d-%H%M%S')}"
    result = run_cmd(["git", "checkout", "-b", branch], repo)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Failed to create branch {branch}")
    return branch


def get_diff(repo: str) -> str:
    result = run_cmd(["git", "diff"], repo)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to read git diff")
    return result.stdout


def get_untracked_files(repo: str) -> list[str]:
    result = run_cmd(["git", "ls-files", "--others", "--exclude-standard"], repo)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to list untracked files")
    return [line for line in result.stdout.splitlines() if line]


def commit_changes(repo: str, message: str) -> None:
    add = run_cmd(["git", "add", "."], repo)
    if add.returncode != 0:
        raise RuntimeError(add.stderr.strip() or "git add failed")

    commit = run_cmd(["git", "commit", "-m", message], repo)
    if commit.returncode != 0:
        raise RuntimeError(commit.stderr.strip() or "git commit failed")


def _remove_empty_parents(path: Path, stop_at: Path) -> None:
    parent = path.parent
    while parent != stop_at and parent.is_relative_to(stop_at):
        try:
            parent.rmdir()
        except OSError:
            return
        parent = parent.parent


def _remove_untracked_files(repo: str) -> None:
    root = Path(repo).resolve()
    for item in get_untracked_files(repo):
        path = (root / item).resolve()
        if not path.is_relative_to(root) or path == root:
            raise RuntimeError(f"Refusing to remove unsafe untracked path: {item}")
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            try:
                path.unlink()
            except FileNotFoundError:
                continue
        _remove_empty_parents(path, root)


def rollback(repo: str, *, remove_untracked: bool = False) -> None:
    result = run_cmd(["git", "restore", "."], repo)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git restore failed")
    if remove_untracked:
        _remove_untracked_files(repo)
