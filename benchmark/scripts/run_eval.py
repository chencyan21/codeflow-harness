from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from _harness_bench_common import (
    DEFAULT_TASKS_PATH,
    DEFAULT_WORKSPACES_DIR,
    ROOT,
    load_tasks,
    prepare_workspace,
    project_path,
    select_tasks,
)
from summarize_results import build_markdown_report

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from codeflow.diff_reviewer import score_risk  # noqa: E402
from codeflow.git_guard import get_changed_files  # noqa: E402
from codeflow.harness.sensors import SEVERITY_ORDER  # noqa: E402
from codeflow.models import CodeFlowConfig, HarnessSensorReport, RunState  # noqa: E402
from codeflow.runner import run_codeflow  # noqa: E402
from codeflow.test_gate import all_checks_passed  # noqa: E402

UNSAFE_SENSOR_NAMES = {
    "allowed_path",
    "dependency_change",
    "forbidden_path",
    "forbidden_path_write",
    "max_diff",
    "secret_like_content",
    "test_deletion",
}


def _sensor_by_name(report: HarnessSensorReport | None) -> dict[str, dict[str, Any]]:
    if not report:
        return {}
    return {result.name: result.model_dump() for result in report.results}


def _sensor_failed(sensors: dict[str, dict[str, Any]], name: str) -> bool:
    result = sensors.get(name)
    return bool(result and not result.get("passed", False))


def _max_risk_level(*levels: str) -> str:
    return max(levels, key=lambda level: SEVERITY_ORDER.get(level, -1))


def _state_record(
    task: dict[str, Any],
    *,
    method: str,
    workspace: Path,
    state: RunState,
    runtime_seconds: float,
) -> dict[str, Any]:
    sensors = _sensor_by_name(state.sensor_report)
    review_risk_level, review_risks = score_risk(state.diff)
    sensor_risk_level = state.sensor_report.max_severity if state.sensor_report else "unknown"
    risk_level = _max_risk_level(sensor_risk_level, review_risk_level)
    unsafe_diff = any(_sensor_failed(sensors, name) for name in UNSAFE_SENSOR_NAMES) or (
        review_risk_level == "high"
    )
    missing_test = sensors.get("missing_test_change", {}).get("severity") == "medium"

    try:
        changed_files = get_changed_files(str(workspace))
    except RuntimeError:
        changed_files = []

    return {
        "id": task["id"],
        "dataset": task.get("dataset", "harness_bench"),
        "method": method,
        "source_repo": task["source_repo"],
        "workspace": str(workspace),
        "status": state.status,
        "checks_passed": all_checks_passed(state.check_results),
        "repair_rounds": state.repair_round,
        "risk_level": risk_level,
        "review_risk_level": review_risk_level,
        "review_risks": review_risks,
        "unsafe_diff": unsafe_diff,
        "test_deleted": _sensor_failed(sensors, "test_deletion"),
        "forbidden_path_modified": _sensor_failed(sensors, "forbidden_path"),
        "forbidden_path_write": _sensor_failed(sensors, "forbidden_path_write"),
        "secret_like_content": _sensor_failed(sensors, "secret_like_content"),
        "missing_test_warning": missing_test,
        "no_change": _sensor_failed(sensors, "no_change"),
        "runtime_seconds": round(runtime_seconds, 3),
        "error_type": None,
        "error": None,
        "blocking_reasons": state.sensor_report.blocking_reasons if state.sensor_report else [],
        "changed_files": changed_files,
        "sensor_results": sensors,
        "check_results": [result.model_dump() for result in state.check_results],
        "expected_type": task.get("expected_type"),
        "risk_tags": task.get("risk_tags", []),
    }


def _error_record(
    task: dict[str, Any],
    *,
    method: str,
    workspace: Path | None,
    exc: Exception,
    runtime_seconds: float,
) -> dict[str, Any]:
    return {
        "id": task.get("id", "unknown"),
        "dataset": task.get("dataset", "harness_bench"),
        "method": method,
        "source_repo": task.get("source_repo"),
        "workspace": str(workspace) if workspace else None,
        "status": "error",
        "checks_passed": False,
        "repair_rounds": 0,
        "risk_level": "unknown",
        "review_risk_level": "unknown",
        "review_risks": [],
        "unsafe_diff": False,
        "test_deleted": False,
        "forbidden_path_modified": False,
        "forbidden_path_write": False,
        "secret_like_content": False,
        "missing_test_warning": False,
        "no_change": False,
        "runtime_seconds": round(runtime_seconds, 3),
        "error_type": exc.__class__.__name__,
        "error": str(exc),
        "blocking_reasons": [],
        "changed_files": [],
        "sensor_results": {},
        "check_results": [],
        "expected_type": task.get("expected_type"),
        "risk_tags": task.get("risk_tags", []),
    }


def _set_mini_command(fake_mini: bool, mini_command: str | None) -> str | None:
    old_command = os.environ.get("CODEFLOW_MINI_COMMAND")
    if fake_mini:
        fake_path = ROOT / "benchmark" / "scripts" / "fake_mini.py"
        os.environ["CODEFLOW_MINI_COMMAND"] = f"{sys.executable} {fake_path}"
    elif mini_command:
        os.environ["CODEFLOW_MINI_COMMAND"] = mini_command
    return old_command


def _restore_mini_command(old_command: str | None) -> None:
    if old_command is None:
        os.environ.pop("CODEFLOW_MINI_COMMAND", None)
    else:
        os.environ["CODEFLOW_MINI_COMMAND"] = old_command


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CodeFlow-Harness-Bench.")
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS_PATH), help="Task YAML path")
    parser.add_argument("--method", default="codeflow_full", choices=["codeflow_full"])
    parser.add_argument("--task-id", action="append", help="Run only this task id")
    parser.add_argument("--limit", type=int, help="Run only the first N selected tasks")
    parser.add_argument("--model", help="Model name passed to mini-swe-agent")
    parser.add_argument("--max-repair-rounds", type=int, help="Override repair rounds")
    parser.add_argument("--mini-command", help="Override CODEFLOW_MINI_COMMAND")
    parser.add_argument("--fake-mini", action="store_true", help="Use deterministic fake mini")
    parser.add_argument(
        "--workspaces-dir",
        default=str(DEFAULT_WORKSPACES_DIR),
        help="Directory for prepared task repositories",
    )
    parser.add_argument(
        "--out-dir",
        help="Result directory, defaults to benchmark/results/{method}",
    )
    parser.add_argument(
        "--reuse-workspaces",
        action="store_true",
        help="Reuse existing workspaces instead of recreating them",
    )
    args = parser.parse_args()

    tasks_path = project_path(args.tasks)
    workspaces_dir = project_path(args.workspaces_dir)
    out_dir = project_path(args.out_dir) if args.out_dir else ROOT / "benchmark" / "results" / args.method
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = select_tasks(load_tasks(tasks_path), task_ids=args.task_id, limit=args.limit)
    old_mini_command = _set_mini_command(args.fake_mini, args.mini_command)
    results: list[dict[str, Any]] = []

    try:
        for task in tasks:
            start = time.perf_counter()
            workspace: Path | None = None
            try:
                workspace = prepare_workspace(
                    task,
                    workspaces_dir=workspaces_dir,
                    clean=not args.reuse_workspaces,
                )
                config = CodeFlowConfig(
                    repo=str(workspace),
                    task=task["task"],
                    checks=task.get("checks"),
                    max_repair_rounds=args.max_repair_rounds,
                    no_commit=True,
                )
                state = run_codeflow(config)
                runtime = time.perf_counter() - start
                record = _state_record(
                    task,
                    method=args.method,
                    workspace=workspace,
                    state=state,
                    runtime_seconds=runtime,
                )
                (out_dir / f"{task['id']}_review.md").write_text(
                    state.report,
                    encoding="utf-8",
                )
            except Exception as exc:
                runtime = time.perf_counter() - start
                record = _error_record(
                    task,
                    method=args.method,
                    workspace=workspace,
                    exc=exc,
                    runtime_seconds=runtime,
                )
            results.append(record)
            print(f"{record['id']}: {record['status']} ({record['runtime_seconds']}s)")
    finally:
        _restore_mini_command(old_mini_command)

    results_path = out_dir / "harness_bench_results.json"
    report_path = out_dir / "harness_bench_report.md"
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(build_markdown_report(results), encoding="utf-8")
    print(f"wrote {results_path}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
