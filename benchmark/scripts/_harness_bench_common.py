from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASKS_PATH = ROOT / "benchmark" / "tasks" / "harness_bench.yaml"
DEFAULT_WORKSPACES_DIR = ROOT / "benchmark" / "workspaces"
SETUP_DONE_MARKER = ".codeflow-benchmark-setup-done"

TaskItem = dict[str, Any]

IGNORE_PATTERNS = (
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "*.pyc",
    "*.egg-info",
)

BENCHMARK_GIT_EXCLUDE_PATTERNS = (
    ".codeflow-benchmark/",
    "__pycache__/",
    "*.py[cod]",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    ".tox/",
    ".nox/",
    ".coverage",
    "htmlcov/",
    "uv.lock",
)

BENCHMARK_META_DIR = ".codeflow-benchmark"


def project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def portable_path(path: Path | str, *, root: Path = ROOT) -> str:
    resolved = Path(path)
    try:
        return str(resolved.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def run_command(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(f"{' '.join(cmd)} failed in {cwd}: {message}")
    return result


def run_shell_command(
    command: str,
    cwd: Path,
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        shell=True,
        env=env,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(f"{command} failed in {cwd}: {message}")
    return result


def git_output(args: list[str], cwd: Path) -> str | None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def repo_git_metadata(repo: Path = ROOT) -> dict[str, Any]:
    status = git_output(["status", "--porcelain"], repo)
    return {
        "commit": git_output(["rev-parse", "HEAD"], repo),
        "branch": git_output(["branch", "--show-current"], repo),
        "dirty": bool(status),
    }


def benchmark_env(*, proxy: str | None = None) -> dict[str, str]:
    env = os.environ.copy()
    if proxy:
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            env[key] = proxy
    return env


def benchmark_platform_metadata() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def write_benchmark_git_exclude(repo: Path) -> None:
    exclude_path = repo / ".git" / "info" / "exclude"
    if not exclude_path.exists():
        return
    existing = exclude_path.read_text(encoding="utf-8", errors="replace")
    additions = [
        pattern for pattern in BENCHMARK_GIT_EXCLUDE_PATTERNS if pattern not in existing.splitlines()
    ]
    if additions:
        exclude_path.write_text(
            existing.rstrip() + "\n" + "\n".join(additions) + "\n",
            encoding="utf-8",
        )


def _hash_workspace_files(repo: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in repo.rglob("*") if item.is_file()):
        relative = path.relative_to(repo)
        if relative.parts and relative.parts[0] in {".git", BENCHMARK_META_DIR}:
            continue
        if "__pycache__" in relative.parts or ".pytest_cache" in relative.parts:
            continue
        digest.update(str(relative).encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            continue
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def write_workspace_manifest(
    repo: Path,
    task: TaskItem,
    *,
    source_repo: Path,
    setup_commands: list[str],
    setup_status: str,
    setup_runtime_seconds: float,
    setup_error: str | None = None,
    source_kind: str | None = None,
    upstream_repo: str | None = None,
    base_commit: str | None = None,
    test_patch_applied: bool | None = None,
) -> Path:
    meta_dir = repo / BENCHMARK_META_DIR
    meta_dir.mkdir(parents=True, exist_ok=True)
    git_head = git_output(["rev-parse", "HEAD"], repo)
    metadata = task.get("metadata", {}) if isinstance(task.get("metadata"), dict) else {}
    source = task.get("source", {}) if isinstance(task.get("source"), dict) else {}
    manifest = {
        "schema_version": 1,
        "task_id": task.get("id"),
        "dataset": task.get("dataset", "harness_bench"),
        "workspace": portable_path(repo),
        "source_repo": portable_path(source_repo),
        "created_at": utc_now_iso(),
        "source_kind": source_kind or source.get("kind") or metadata.get("source_kind") or "unknown",
        "upstream_repo": upstream_repo or source.get("upstream") or metadata.get("repo"),
        "base_commit": base_commit or source.get("base_commit") or metadata.get("base_commit"),
        "test_patch_applied": test_patch_applied,
        "setup_commands": setup_commands,
        "setup_status": setup_status,
        "setup_runtime_seconds": round(setup_runtime_seconds, 3),
        "setup_error": setup_error,
        "python_version": platform.python_version(),
        "git_head": git_head,
        "baseline_commit": git_head,
        "files_hash": _hash_workspace_files(repo),
    }
    manifest_path = meta_dir / "workspace_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def setup_already_done(repo: Path) -> bool:
    return (repo / SETUP_DONE_MARKER).exists()


def mark_setup_done(repo: Path, commands: list[str]) -> None:
    if not commands:
        return
    (repo / SETUP_DONE_MARKER).write_text(
        "Generated by benchmark setup commands.\n"
        + "\n".join(commands)
        + "\n",
        encoding="utf-8",
    )


def _load_jsonl_tasks(path: Path) -> list[TaskItem]:
    tasks = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise RuntimeError(f"Task item #{line_number} is not a mapping in {path}")
        tasks.append(item)
    return tasks


def _load_yaml_tasks(path: Path) -> list[TaskItem]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if isinstance(data, dict):
        data = data.get("tasks", [])
    if not isinstance(data, list):
        raise RuntimeError(f"Task file must contain a YAML list: {path}")
    return data


def load_tasks(path: Path) -> list[TaskItem]:
    data = _load_jsonl_tasks(path) if path.suffix == ".jsonl" else _load_yaml_tasks(path)
    tasks: list[TaskItem] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(f"Task item #{index} is not a mapping in {path}")
        if "id" not in item:
            raise RuntimeError(f"Task item #{index} is missing id in {path}")
        if "source_repo" not in item:
            raise RuntimeError(f"Task {item['id']} is missing source_repo")
        if "task" not in item:
            raise RuntimeError(f"Task {item['id']} is missing task")
        tasks.append(item)
    return tasks


def select_tasks(
    tasks: list[TaskItem],
    *,
    task_ids: list[str] | None = None,
    limit: int | None = None,
) -> list[TaskItem]:
    selected = tasks
    if task_ids:
        wanted = set(task_ids)
        selected = [task for task in selected if str(task["id"]) in wanted]
        missing = wanted - {str(task["id"]) for task in selected}
        if missing:
            raise RuntimeError(f"Unknown task id(s): {', '.join(sorted(missing))}")
    if limit is not None:
        selected = selected[:limit]
    return selected


def prepare_workspace(
    task: TaskItem,
    *,
    workspaces_dir: Path = DEFAULT_WORKSPACES_DIR,
    clean: bool = False,
    env: dict[str, str] | None = None,
) -> Path:
    source = project_path(task["source_repo"])
    if not source.exists():
        raise RuntimeError(f"Source repo does not exist for {task['id']}: {source}")

    destination = workspaces_dir / str(task["id"])
    if destination.exists():
        if not clean:
            write_benchmark_git_exclude(destination)
            manifest = destination / BENCHMARK_META_DIR / "workspace_manifest.json"
            if not manifest.exists() and (destination / ".git").exists():
                write_workspace_manifest(
                    destination,
                    task,
                    source_repo=source,
                    setup_commands=[str(command) for command in task.get("setup_commands", []) or []],
                    setup_status="reused",
                    setup_runtime_seconds=0.0,
                )
            return destination
        shutil.rmtree(destination)

    workspaces_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(*IGNORE_PATTERNS),
    )
    setup_commands = [str(command) for command in task.get("setup_commands", []) or []]
    setup_status = "not_required"
    setup_error: str | None = None
    setup_start = time.perf_counter()
    if setup_commands and not setup_already_done(destination):
        setup_status = "passed"
        try:
            for command in setup_commands:
                run_shell_command(command, destination, env=env)
            mark_setup_done(destination, setup_commands)
        except Exception as exc:
            setup_status = "failed"
            setup_error = str(exc)
            raise
    setup_runtime = time.perf_counter() - setup_start
    run_command(["git", "init"], destination)
    run_command(["git", "add", "."], destination)
    run_command(
        [
            "git",
            "-c",
            "user.email=codeflow@example.local",
            "-c",
            "user.name=CodeFlow",
            "commit",
            "-m",
            "baseline",
        ],
        destination,
    )
    write_benchmark_git_exclude(destination)
    write_workspace_manifest(
        destination,
        task,
        source_repo=source,
        setup_commands=setup_commands,
        setup_status=setup_status,
        setup_runtime_seconds=setup_runtime,
        setup_error=setup_error,
    )
    return destination
