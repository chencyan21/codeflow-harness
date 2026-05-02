from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from collections import Counter
from datetime import datetime
from html import escape
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
        latest_run_dir = get_latest_run_dir(repo)
        if latest_run_dir is None:
            raise RuntimeError("No CodeFlow runs found for this repository.")
        return latest_run_dir
    raise RuntimeError("Specify --latest or --run-id.")


def load_run_state(run_dir: Path) -> dict[str, Any]:
    state_path = run_dir / "state.json"
    if not state_path.exists():
        return {"run_id": run_dir.name, "run_dir": str(run_dir)}
    loaded = json.loads(state_path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {"run_id": run_dir.name, "run_dir": str(run_dir)}


def search_run_states(
    repo: str,
    *,
    query: str | None = None,
    status: str | None = None,
    risk_level: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    query_lower = query.lower() if query else None
    for run_dir in list_run_dirs(repo):
        state = load_run_state(run_dir)
        if status and state.get("status") != status:
            continue
        if risk_level and state.get("risk_level") != risk_level:
            continue
        searchable = " ".join(
            str(state.get(key, "")) for key in ("run_id", "task", "branch", "status", "risk_level")
        ).lower()
        if query_lower and query_lower not in searchable:
            continue
        state.setdefault("run_id", run_dir.name)
        state["run_dir"] = str(run_dir)
        matches.append(state)
        if len(matches) >= limit:
            break
    return matches


def summarize_run_states(repo: str, *, limit: int | None = None) -> dict[str, Any]:
    run_dirs = list_run_dirs(repo)
    if limit is not None:
        run_dirs = run_dirs[:limit]
    states = [load_run_state(run_dir) for run_dir in run_dirs]
    status_counts = Counter(str(state.get("status", "unknown")) for state in states)
    risk_counts = Counter(str(state.get("risk_level", "unknown")) for state in states)
    daily_counts = Counter(str(state.get("run_id", ""))[:8] or "unknown" for state in states)
    failed_runs = [
        {
            "run_id": state.get("run_id"),
            "task": state.get("task"),
            "status": state.get("status"),
            "risk_level": state.get("risk_level"),
        }
        for state in states
        if state.get("status") not in {"checks_passed", "committed", "kept_uncommitted"}
    ]
    checks_passed = sum(1 for state in states if state.get("checks_passed"))
    sensors_passed = sum(1 for state in states if state.get("sensor_passed"))
    repair_rounds = [int(state.get("repair_round", 0) or 0) for state in states]
    return {
        "total_runs": len(states),
        "status_counts": dict(sorted(status_counts.items())),
        "risk_counts": dict(sorted(risk_counts.items())),
        "daily_counts": dict(sorted(daily_counts.items())),
        "failed_runs": failed_runs[:20],
        "checks_passed": checks_passed,
        "sensor_passed": sensors_passed,
        "average_repair_rounds": round(sum(repair_rounds) / len(repair_rounds), 2)
        if repair_rounds
        else 0.0,
        "latest_run_id": run_dirs[0].name if run_dirs else None,
    }


def build_runs_dashboard_html(repo: str, *, limit: int = 100) -> str:
    runs = search_run_states(repo, limit=limit)
    summary = summarize_run_states(repo, limit=limit)
    rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(item.get('run_id', '')))}</td>"
        f"<td>{escape(str(item.get('status', '')))}</td>"
        f"<td>{escape(str(item.get('risk_level', '')))}</td>"
        f"<td>{escape(str(item.get('task', '')))}</td>"
        f"<td>{escape(str(item.get('run_dir', '')))}</td>"
        "</tr>"
        for item in runs
    )
    failed = "\n".join(
        f"<li>{escape(str(item.get('run_id', '')))}: "
        f"{escape(str(item.get('status', '')))} - {escape(str(item.get('task', '')))}</li>"
        for item in summary["failed_runs"]
    ) or "<li>none</li>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>CodeFlow Runs Dashboard</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 24px; color: #1f2937; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #d1d5db; padding: 6px 8px; text-align: left; }}
    th {{ background: #f3f4f6; }}
    code, pre {{ background: #f3f4f6; padding: 2px 4px; }}
  </style>
</head>
<body>
  <h1>CodeFlow Runs Dashboard</h1>
  <p>Total runs: {summary["total_runs"]}</p>
  <p>Checks passed: {summary["checks_passed"]}/{summary["total_runs"]}</p>
  <p>Sensors passed: {summary["sensor_passed"]}/{summary["total_runs"]}</p>
  <h2>Status Counts</h2>
  <pre>{escape(json.dumps(summary["status_counts"], ensure_ascii=False, indent=2))}</pre>
  <h2>Daily Counts</h2>
  <pre>{escape(json.dumps(summary["daily_counts"], ensure_ascii=False, indent=2))}</pre>
  <h2>Recent Failed Runs</h2>
  <ul>{failed}</ul>
  <h2>Runs</h2>
  <table>
    <thead><tr><th>Run ID</th><th>Status</th><th>Risk</th><th>Task</th><th>Run Dir</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</body>
</html>
"""


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


def _is_prompt_artifact(path: Path) -> bool:
    name = path.name
    return (
        name == "initial_prompt.md"
        or (name.startswith("repair_prompt_") and name.endswith(".md"))
        or (name.startswith("prompt_") and name.endswith(".txt"))
    )


def export_run_dir(
    run_dir: Path,
    out_path: Path,
    *,
    include_logs: bool = False,
    include_trajectory: bool = False,
    include_prompts: bool = False,
) -> Path:
    if not run_dir.is_dir():
        raise RuntimeError(f"Run directory does not exist: {run_dir}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_run_dir = run_dir.resolve()
    resolved_out_path = out_path.resolve()
    if resolved_out_path == resolved_run_dir or resolved_run_dir in resolved_out_path.parents:
        raise RuntimeError("Export output path must be outside the run directory.")
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
            if _is_prompt_artifact(path) and not include_prompts:
                continue
            archive.write(path, path.relative_to(run_dir))
    return out_path


def copy_artifact(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
