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
    benchmark_env,
    load_tasks,
    prepare_workspace,
    project_path,
    select_tasks,
)
from summarize_results import build_markdown_report

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from codeflow.diff_reviewer import build_review_report, score_risk  # noqa: E402
from codeflow.git_guard import (  # noqa: E402
    create_ai_branch,
    ensure_clean_worktree,
    ensure_git_repo,
    get_changed_files,
    get_diff,
)
from codeflow.harness.policy import load_harness_policy  # noqa: E402
from codeflow.harness.sensors import SEVERITY_ORDER  # noqa: E402
from codeflow.mini_runner import run_mini_agent  # noqa: E402
from codeflow.models import CodeFlowConfig, HarnessSensorReport, RunState  # noqa: E402
from codeflow.prompt_builder import build_initial_prompt, build_repair_prompt  # noqa: E402
from codeflow.runner import run_codeflow  # noqa: E402
from codeflow.spec_builder import build_spec  # noqa: E402
from codeflow.test_gate import all_checks_passed  # noqa: E402
from codeflow.test_gate import failed_checks, run_checks  # noqa: E402
from codeflow.utils import read_project_rules  # noqa: E402

UNSAFE_SENSOR_NAMES = {
    "allowed_path",
    "dependency_change",
    "forbidden_path",
    "forbidden_path_write",
    "max_diff",
    "secret_like_content",
    "test_deletion",
}

EVAL_METHODS = ("raw_mini", "checks_only", "codeflow_basic", "codeflow_full")


def _should_retry_record(record: dict[str, Any], *, method: str, attempt: int, max_attempts: int) -> bool:
    if attempt >= max_attempts or method == "checks_only":
        return False
    successful_statuses = {"checks_passed", "committed", "kept_uncommitted"}
    return (
        record.get("status") == "error"
        or record.get("status") not in successful_statuses
        or not record.get("checks_passed", False)
        or bool(record.get("unsafe_diff"))
    )


def _retry_manifest_record(
    *,
    task: dict[str, Any],
    method: str,
    attempt: int,
    max_attempts: int,
    record: dict[str, Any],
    will_retry: bool,
    model: str | None,
    workspace: Path | None,
) -> dict[str, Any]:
    return {
        "id": task.get("id", "unknown"),
        "dataset": task.get("dataset", "harness_bench"),
        "method": method,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "will_retry": will_retry,
        "status": record.get("status"),
        "checks_passed": record.get("checks_passed", False),
        "runtime_seconds": record.get("runtime_seconds"),
        "error_type": record.get("error_type"),
        "error": record.get("error"),
        "model": model,
        "workspace": str(workspace) if workspace else record.get("workspace"),
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


def _mini_log_path(result: object) -> str:
    return str(getattr(result, "log_path", result))


def _direct_state(
    *,
    task: dict[str, Any],
    workspace: Path,
    method: str,
    model: str | None,
    max_repair_rounds: int | None,
) -> RunState:
    repo = str(workspace.resolve())
    ensure_git_repo(repo)
    ensure_clean_worktree(repo)

    policy = load_harness_policy(
        repo,
        cli_checks=task.get("checks"),
        cli_max_repair_rounds=max_repair_rounds,
    )
    rules = read_project_rules(repo)
    spec = build_spec(task["task"])

    if method == "checks_only":
        state = RunState(repo=repo, task=task["task"], branch="baseline", rules=rules, spec=spec, policy=policy)
        state.check_results = run_checks(repo, policy.required_checks)
        state.diff = get_diff(repo)
        state.status = "checks_passed" if all_checks_passed(state.check_results) else "checks_failed"
        state.report = build_review_report(
            task=task["task"],
            branch=state.branch,
            diff=state.diff,
            check_results=state.check_results,
            sensor_report=None,
        )
        state.commit_action = "skipped"
        return state

    branch = create_ai_branch(repo, task["task"])
    state = RunState(repo=repo, task=task["task"], branch=branch, rules=rules, spec=spec, policy=policy)

    if method == "raw_mini":
        prompt = task["task"]
        max_rounds = 0
    else:
        prompt = build_initial_prompt(
            task=task["task"],
            spec=spec,
            rules=rules,
            checks=policy.required_checks,
            policy=None,
        )
        max_rounds = policy.max_repair_rounds if method == "codeflow_basic" else 0

    state.mini_runs.append(_mini_log_path(run_mini_agent(repo=repo, prompt=prompt, model=model)))

    for round_idx in range(max_rounds + 1):
        state.check_results = run_checks(repo, policy.required_checks)
        state.diff = get_diff(repo)
        state.status = "checks_passed" if all_checks_passed(state.check_results) else "checks_failed"
        if state.status == "checks_passed" or round_idx >= max_rounds:
            break

        repair_prompt = build_repair_prompt(
            task=task["task"],
            spec=spec,
            rules=rules,
            failed_results=failed_checks(state.check_results),
            checks=policy.required_checks,
            policy=None,
            sensor_report=None,
        )
        state.mini_runs.append(
            _mini_log_path(run_mini_agent(repo=repo, prompt=repair_prompt, model=model))
        )
        state.repair_round = round_idx + 1

    state.report = build_review_report(
        task=task["task"],
        branch=branch,
        diff=state.diff,
        check_results=state.check_results,
        sensor_report=None,
    )
    state.commit_action = "skipped"
    return state


def _run_task(
    *,
    task: dict[str, Any],
    workspace: Path,
    method: str,
    model: str | None,
    max_repair_rounds: int | None,
) -> RunState:
    if method == "codeflow_full":
        config = CodeFlowConfig(
            repo=str(workspace),
            task=task["task"],
            checks=task.get("checks"),
            max_repair_rounds=max_repair_rounds,
            model=model,
            no_commit=True,
        )
        return run_codeflow(config)
    return _direct_state(
        task=task,
        workspace=workspace,
        method=method,
        model=model,
        max_repair_rounds=max_repair_rounds,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CodeFlow-Harness-Bench.")
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS_PATH), help="Task YAML path")
    parser.add_argument("--method", default="codeflow_full", choices=EVAL_METHODS)
    parser.add_argument("--task-id", action="append", help="Run only this task id")
    parser.add_argument("--limit", type=int, help="Run only the first N selected tasks")
    parser.add_argument("--model", help="Model name passed to mini-swe-agent")
    parser.add_argument("--max-repair-rounds", type=int, help="Override repair rounds")
    parser.add_argument(
        "--max-task-attempts",
        type=int,
        default=1,
        help="Maximum attempts per task; failed real-agent runs can be retried.",
    )
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
    parser.add_argument("--proxy", help="Proxy URL for setup commands, for example http://127.0.0.1:10087")
    args = parser.parse_args()
    if args.max_task_attempts < 1:
        parser.error("--max-task-attempts must be >= 1")

    tasks_path = project_path(args.tasks)
    workspaces_dir = project_path(args.workspaces_dir)
    out_dir = project_path(args.out_dir) if args.out_dir else ROOT / "benchmark" / "results" / args.method
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = select_tasks(load_tasks(tasks_path), task_ids=args.task_id, limit=args.limit)
    old_mini_command = _set_mini_command(args.fake_mini, args.mini_command)
    env = benchmark_env(proxy=args.proxy)
    results: list[dict[str, Any]] = []
    retry_manifest: list[dict[str, Any]] = []
    result_prefix = tasks_path.stem
    retry_manifest_path = out_dir / f"{result_prefix}_retry_manifest.json"

    try:
        for task in tasks:
            final_record: dict[str, Any] | None = None
            for attempt in range(1, args.max_task_attempts + 1):
                start = time.perf_counter()
                workspace: Path | None = None
                try:
                    workspace = prepare_workspace(
                        task,
                        workspaces_dir=workspaces_dir,
                        clean=not args.reuse_workspaces or attempt > 1,
                        env=env,
                    )
                    state = _run_task(
                        task=task,
                        workspace=workspace,
                        method=args.method,
                        model=args.model,
                        max_repair_rounds=args.max_repair_rounds,
                    )
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
                record["attempts"] = attempt
                will_retry = _should_retry_record(
                    record,
                    method=args.method,
                    attempt=attempt,
                    max_attempts=args.max_task_attempts,
                )
                retry_manifest.append(
                    _retry_manifest_record(
                        task=task,
                        method=args.method,
                        attempt=attempt,
                        max_attempts=args.max_task_attempts,
                        record=record,
                        will_retry=will_retry,
                        model=args.model,
                        workspace=workspace,
                    )
                )
                retry_manifest_path.write_text(
                    json.dumps(retry_manifest, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(
                    f"{record['id']}: {record['status']} "
                    f"attempt {attempt}/{args.max_task_attempts} ({record['runtime_seconds']}s)"
                )
                final_record = record
                if not will_retry:
                    break
            if final_record is None:
                final_record = _error_record(
                    task,
                    method=args.method,
                    workspace=workspace,
                    exc=RuntimeError("Task did not produce a result record."),
                    runtime_seconds=0.0,
                )
            results.append(final_record)
    finally:
        _restore_mini_command(old_mini_command)

    results_path = out_dir / f"{result_prefix}_results.json"
    report_path = out_dir / f"{result_prefix}_report.md"
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(build_markdown_report(results), encoding="utf-8")
    print(f"wrote {results_path}")
    print(f"wrote {report_path}")
    print(f"wrote {retry_manifest_path}")


if __name__ == "__main__":
    main()
