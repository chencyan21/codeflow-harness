from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASKS_PATH = ROOT / "benchmark" / "tasks" / "harness_bench.yaml"
DEFAULT_WORKSPACES_DIR = ROOT / "benchmark" / "workspaces"

TaskItem = dict[str, Any]

IGNORE_PATTERNS = (
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "*.pyc",
    "*.egg-info",
)


def project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def run_command(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(f"{' '.join(cmd)} failed in {cwd}: {message}")
    return result


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
) -> Path:
    source = project_path(task["source_repo"])
    if not source.exists():
        raise RuntimeError(f"Source repo does not exist for {task['id']}: {source}")

    destination = workspaces_dir / str(task["id"])
    if destination.exists():
        if not clean:
            return destination
        shutil.rmtree(destination)

    workspaces_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(*IGNORE_PATTERNS),
    )
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
    return destination
