from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from collections import Counter
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

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


def get_run_index_path(repo: str) -> Path:
    return get_codeflow_dir(repo) / "index.jsonl"


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


def load_review_summary(run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "review_summary.json"
    if not summary_path.exists():
        return {}
    loaded = json.loads(summary_path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _run_record(run_dir: Path) -> dict[str, Any]:
    state = load_run_state(run_dir)
    state.setdefault("run_id", run_dir.name)
    state["run_dir"] = str(run_dir)
    review_summary = load_review_summary(run_dir)
    if review_summary:
        state["review_summary"] = review_summary
        state["finding_counts"] = _finding_counts(review_summary)
        state["finding_categories"] = _finding_categories(review_summary)
        state["high_risk_files"] = _high_risk_files(review_summary)
    return state


def _finding_counts(review_summary: dict[str, Any]) -> dict[str, int]:
    counter = Counter(
        str(item.get("severity", "unknown"))
        for item in review_summary.get("findings", [])
        if isinstance(item, dict)
    )
    return dict(sorted(counter.items()))


def _finding_categories(review_summary: dict[str, Any]) -> dict[str, int]:
    counter = Counter(
        str(item.get("category", "unknown"))
        for item in review_summary.get("findings", [])
        if isinstance(item, dict)
    )
    return dict(sorted(counter.items()))


def _high_risk_files(review_summary: dict[str, Any]) -> list[str]:
    files = {
        str(item.get("file"))
        for item in review_summary.get("findings", [])
        if isinstance(item, dict) and item.get("severity") == "high" and item.get("file")
    }
    return sorted(files)


def _created_at_from_run_id(run_id: str) -> str:
    prefix = run_id[:15]
    try:
        return datetime.strptime(prefix, "%Y%m%d-%H%M%S").isoformat()
    except ValueError:
        return ""


def build_run_index_entry(run_dir: Path) -> dict[str, Any]:
    record = _run_record(run_dir)
    run_id = str(record.get("run_id") or run_dir.name)
    return {
        "run_id": run_id,
        "created_at": _created_at_from_run_id(run_id),
        "task": record.get("task"),
        "branch": record.get("branch"),
        "status": record.get("status"),
        "risk_level": record.get("risk_level"),
        "checks_passed": record.get("checks_passed"),
        "sensor_passed": record.get("sensor_passed"),
        "repair_round": record.get("repair_round", 0),
        "finding_counts": record.get("finding_counts", {}),
        "finding_categories": record.get("finding_categories", {}),
        "high_risk_files": record.get("high_risk_files", []),
        "run_dir": str(run_dir),
    }


def load_run_index(repo: str) -> list[dict[str, Any]]:
    path = get_run_index_path(repo)
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        loaded = json.loads(line)
        if isinstance(loaded, dict):
            entries.append(loaded)
    return sorted(entries, key=lambda item: str(item.get("run_id", "")), reverse=True)


def update_run_index(repo: str, run_dir: Path) -> None:
    path = get_run_index_path(repo)
    entry = build_run_index_entry(run_dir)
    entries = [item for item in load_run_index(repo) if item.get("run_id") != entry["run_id"]]
    entries.append(entry)
    entries = sorted(entries, key=lambda item: str(item.get("run_id", "")), reverse=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in entries),
        encoding="utf-8",
    )


def _indexed_or_scanned_records(repo: str) -> list[dict[str, Any]]:
    indexed = load_run_index(repo)
    if indexed:
        return indexed
    return [_run_record(run_dir) for run_dir in list_run_dirs(repo)]


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
    for state in _indexed_or_scanned_records(repo):
        if status and state.get("status") != status:
            continue
        if risk_level and state.get("risk_level") != risk_level:
            continue
        searchable = " ".join(
            str(state.get(key, "")) for key in ("run_id", "task", "branch", "status", "risk_level")
        ).lower()
        if query_lower and query_lower not in searchable:
            continue
        matches.append(state)
        if len(matches) >= limit:
            break
    return matches


def summarize_run_states(repo: str, *, limit: int | None = None) -> dict[str, Any]:
    records = _indexed_or_scanned_records(repo)
    if limit is not None:
        records = records[:limit]
    states = records
    status_counts = Counter(str(state.get("status", "unknown")) for state in states)
    risk_counts = Counter(str(state.get("risk_level", "unknown")) for state in states)
    daily_counts = Counter(str(state.get("run_id", ""))[:8] or "unknown" for state in states)
    finding_counts: Counter[str] = Counter()
    finding_categories: Counter[str] = Counter()
    high_risk_files: Counter[str] = Counter()
    for state in states:
        finding_counts.update(
            {str(key): int(value) for key, value in (state.get("finding_counts") or {}).items()}
        )
        finding_categories.update(
            {str(key): int(value) for key, value in (state.get("finding_categories") or {}).items()}
        )
        high_risk_files.update(str(path) for path in state.get("high_risk_files") or [])
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
        "finding_counts": dict(sorted(finding_counts.items())),
        "finding_categories": dict(sorted(finding_categories.items())),
        "high_risk_files": dict(sorted(high_risk_files.items())),
        "average_repair_rounds": round(sum(repair_rounds) / len(repair_rounds), 2)
        if repair_rounds
        else 0.0,
        "latest_run_id": states[0].get("run_id") if states else None,
    }


def build_runs_dashboard_html(repo: str, *, limit: int = 100) -> str:
    runs = search_run_states(repo, limit=limit)
    summary = summarize_run_states(repo, limit=limit)
    runs_json = escape(json.dumps(runs, ensure_ascii=False))
    rows = "\n".join(
        "<tr "
        f"data-status='{escape(str(item.get('status', '')))}' "
        f"data-risk='{escape(str(item.get('risk_level', '')))}' "
        f"data-task='{escape(str(item.get('task', ''))).lower()}'>"
        f"<td>{escape(str(item.get('run_id', '')))}</td>"
        f"<td>{escape(str(item.get('status', '')))}</td>"
        f"<td>{escape(str(item.get('risk_level', '')))}</td>"
        f"<td>{escape(str(item.get('task', '')))}</td>"
        f"<td>{escape(json.dumps(item.get('finding_counts', {}), ensure_ascii=False))}</td>"
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
    label {{ display: inline-flex; flex-direction: column; gap: 4px; margin: 0 12px 12px 0; }}
    input, select {{ padding: 4px 6px; }}
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
  <h2>Finding Categories</h2>
  <pre>{escape(json.dumps(summary["finding_categories"], ensure_ascii=False, indent=2))}</pre>
  <h2>Recent Failed Runs</h2>
  <ul>{failed}</ul>
  <h2>Runs</h2>
  <div>
    <label>Status <select id="statusFilter"><option value="">all</option></select></label>
    <label>Risk <select id="riskFilter"><option value="">all</option></select></label>
    <label>Task Search <input id="taskFilter" type="search"></label>
    <label><input id="failedOnly" type="checkbox"> Failed only</label>
  </div>
  <table>
    <thead><tr><th>Run ID</th><th>Status</th><th>Risk</th><th>Task</th><th>Findings</th><th>Run Dir</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <script type="application/json" id="runs-data">{runs_json}</script>
  <script>
    const rows = Array.from(document.querySelectorAll('tbody tr'));
    const runs = JSON.parse(document.getElementById('runs-data').textContent);
    const statusFilter = document.getElementById('statusFilter');
    const riskFilter = document.getElementById('riskFilter');
    const taskFilter = document.getElementById('taskFilter');
    const failedOnly = document.getElementById('failedOnly');
    function fill(select, values) {{
      [...new Set(values.filter(Boolean))].sort().forEach(value => {{
        const option = document.createElement('option');
        option.value = value;
        option.textContent = value;
        select.appendChild(option);
      }});
    }}
    fill(statusFilter, runs.map(item => item.status));
    fill(riskFilter, runs.map(item => item.risk_level));
    function applyFilters() {{
      const task = taskFilter.value.toLowerCase();
      rows.forEach(row => {{
        const statusOk = !statusFilter.value || row.dataset.status === statusFilter.value;
        const riskOk = !riskFilter.value || row.dataset.risk === riskFilter.value;
        const taskOk = !task || row.dataset.task.includes(task);
        const failedOk = !failedOnly.checked || !['checks_passed', 'committed', 'kept_uncommitted'].includes(row.dataset.status);
        row.style.display = statusOk && riskOk && taskOk && failedOk ? '' : 'none';
      }});
    }}
    [statusFilter, riskFilter, taskFilter, failedOnly].forEach(item => item.addEventListener('input', applyFilters));
  </script>
</body>
</html>
"""


def handle_observability_request(repo: str, raw_path: str) -> tuple[int, str, bytes]:
    parsed = urlparse(raw_path)
    path = parsed.path.rstrip("/") or "/"
    query = parse_qs(parsed.query)
    if path in {"/", "/dashboard"}:
        limit = int(query.get("limit", ["100"])[0])
        return 200, "text/html; charset=utf-8", build_runs_dashboard_html(repo, limit=limit).encode()
    if path == "/api/runs":
        limit = int(query.get("limit", ["100"])[0])
        return _json_response(
            search_run_states(
                repo,
                query=_query_value(query, "q") or _query_value(query, "query"),
                status=_query_value(query, "status"),
                risk_level=_query_value(query, "risk") or _query_value(query, "risk_level"),
                limit=limit,
            )
        )
    if path == "/api/summary":
        return _json_response(summarize_run_states(repo))
    if path == "/api/findings":
        limit = int(query.get("limit", ["100"])[0])
        return _json_response(
            _list_findings(
                repo,
                category=_query_value(query, "category"),
                severity=_query_value(query, "severity"),
                limit=limit,
            )
        )
    if path == "/api/trends":
        return _json_response({"daily": summarize_run_states(repo).get("daily_counts", {})})
    if path == "/api/failures":
        limit = int(query.get("limit", ["100"])[0])
        return _json_response(summarize_run_states(repo).get("failed_runs", [])[:limit])
    if path.startswith("/api/runs/"):
        run_id = unquote(path.removeprefix("/api/runs/"))
        return _json_response(_run_record(get_run_dir(repo, run_id)))
    if path.startswith("/api/report/"):
        run_id = unquote(path.removeprefix("/api/report/"))
        report_path = get_run_dir(repo, run_id) / "review_report.md"
        if not report_path.exists():
            return 404, "text/plain; charset=utf-8", b"report not found"
        return 200, "text/markdown; charset=utf-8", report_path.read_bytes()
    if path.startswith("/api/artifacts/"):
        run_id = unquote(path.removeprefix("/api/artifacts/"))
        run_dir = get_run_dir(repo, run_id)
        artifacts = [str(path.relative_to(run_dir)) for path in sorted(run_dir.rglob("*")) if path.is_file()]
        return _json_response({"run_id": run_id, "artifacts": artifacts})
    return 404, "text/plain; charset=utf-8", b"not found"


def _query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _list_findings(
    repo: str,
    *,
    category: str | None = None,
    severity: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for record in search_run_states(repo, limit=max(limit, 1000)):
        run_dir = Path(str(record.get("run_dir", "")))
        if not run_dir.is_dir():
            continue
        summary = load_review_summary(run_dir)
        for item in summary.get("findings", []):
            if not isinstance(item, dict):
                continue
            if category and item.get("category") != category:
                continue
            if severity and item.get("severity") != severity:
                continue
            findings.append(
                {
                    "run_id": record.get("run_id"),
                    "task": record.get("task"),
                    "source": item.get("source"),
                    "severity": item.get("severity"),
                    "category": item.get("category"),
                    "file": item.get("file"),
                    "message": item.get("message"),
                    "recommendation": item.get("recommendation"),
                }
            )
            if len(findings) >= limit:
                return findings
    return findings


def _json_response(data: Any) -> tuple[int, str, bytes]:
    return 200, "application/json; charset=utf-8", (
        json.dumps(data, ensure_ascii=False, indent=2, default=_json_default) + "\n"
    ).encode()


def serve_observability(repo: str, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            status, content_type, body = handle_observability_request(repo, self.path)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    ThreadingHTTPServer((host, port), Handler).serve_forever()


def cleanup_runs(repo: str, *, keep: int = 100, dry_run: bool = True) -> dict[str, Any]:
    if keep < 0:
        raise RuntimeError("keep must be non-negative.")
    run_dirs = list_run_dirs(repo)
    delete_dirs = run_dirs[keep:]
    deleted: list[str] = []
    for run_dir in delete_dirs:
        deleted.append(run_dir.name)
        if not dry_run:
            shutil.rmtree(run_dir)
    if not dry_run:
        remaining = {path.name for path in list_run_dirs(repo)}
        entries = [item for item in load_run_index(repo) if str(item.get("run_id")) in remaining]
        index_path = get_run_index_path(repo)
        index_path.write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in entries),
            encoding="utf-8",
        )
    return {"dry_run": dry_run, "keep": keep, "deleted": deleted, "deleted_count": len(deleted)}


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
