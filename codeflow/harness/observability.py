from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from codeflow.git_guard import slugify


def _git_dir(repo: str) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=repo,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"{repo} is not a Git repository")
    path = Path(result.stdout.strip())
    return path if path.is_absolute() else Path(repo) / path


def get_codeflow_dir(repo: str) -> Path:
    path = _git_dir(repo) / "codeflow"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_runs_dir(repo: str) -> Path:
    path = get_codeflow_dir(repo) / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_run_dir(repo: str, task: str) -> Path:
    runs_dir = get_runs_dir(repo)
    base_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{slugify(task)}"
    run_dir = runs_dir / base_id
    counter = 1
    while run_dir.exists():
        counter += 1
        run_dir = runs_dir / f"{base_id}-{counter}"
    run_dir.mkdir(parents=True)
    return run_dir


def list_run_dirs(repo: str) -> list[Path]:
    runs_dir = get_runs_dir(repo)
    return sorted(
        [path for path in runs_dir.iterdir() if path.is_dir()],
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )


def get_latest_run_dir(repo: str) -> Path | None:
    runs = list_run_dirs(repo)
    return runs[0] if runs else None


def get_run_dir(repo: str, run_id: str | None = None, *, latest: bool = False) -> Path:
    if run_id:
        run_dir = get_runs_dir(repo) / run_id
        if not run_dir.is_dir():
            raise RuntimeError(f"CodeFlow run not found: {run_id}")
        return run_dir
    if latest or run_id is None:
        run_dir = get_latest_run_dir(repo)
        if run_dir is None:
            raise RuntimeError("No CodeFlow runs found for this repository.")
        return run_dir
    raise RuntimeError("Specify --latest or --run-id.")


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def export_run_dir(
    run_dir: Path,
    out_path: Path,
    *,
    include_logs: bool = False,
    include_trajectory: bool = False,
) -> Path:
    if not run_dir.is_dir():
        raise RuntimeError(f"Run directory does not exist: {run_dir}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(run_dir.rglob("*")):
            if path.is_dir():
                continue
            name = path.name
            if name.endswith(".log") and not include_logs:
                continue
            if name.endswith(".trajectory.json") and not include_trajectory:
                continue
            archive.write(path, path.relative_to(run_dir))
    return out_path


def copy_artifact(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
