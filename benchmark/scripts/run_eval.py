from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from _harness_bench_common import (
    DEFAULT_TASKS_PATH,
    DEFAULT_WORKSPACES_DIR,
    ROOT,
    benchmark_env,
    benchmark_platform_metadata,
    load_tasks,
    portable_path,
    prepare_workspace,
    project_path,
    repo_git_metadata,
    select_tasks,
    utc_now_iso,
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
from codeflow.redaction import redact_text  # noqa: E402
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
MAX_TASK_ATTEMPTS = 10


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_").lower() or "run"


def _make_run_id(*, method: str, model: str | None, tasks_path: Path) -> str:
    timestamp = utc_now_iso().replace("-", "").replace(":", "").replace("Z", "Z")
    model_part = _safe_id(model or "default")
    return f"{timestamp}_{_safe_id(tasks_path.stem)}_{_safe_id(method)}_{model_part}"


def _provider_metadata(model: str | None) -> dict[str, Any]:
    dotenv = dotenv_values(ROOT / ".env") if (ROOT / ".env").exists() else {}
    base_url = (
        os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("LITELLM_BASE_URL")
        or os.environ.get("base_url")
        or dotenv.get("OPENAI_BASE_URL")
        or dotenv.get("LITELLM_BASE_URL")
        or dotenv.get("base_url")
    )
    provider = "unknown"
    if base_url:
        provider = "openai-compatible"
    elif model and "/" in model:
        provider = model.split("/", 1)[0]
    return {
        "model": model,
        "provider": provider,
        "base_url": redact_text(base_url) if base_url else None,
    }


def _patch_stats(diff: str) -> dict[str, int]:
    files: set[str] = set()
    additions = 0
    deletions = 0
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                files.add(parts[3].removeprefix("b/"))
        elif line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return {"files": len(files), "additions": additions, "deletions": deletions}


def _classify_error(error_type: str | None, error: str | None) -> str | None:
    if not error_type and not error:
        return None
    text = f"{error_type or ''} {error or ''}".lower()
    if "api" in text or "openai" in text or "litellm" in text or "rate limit" in text:
        return "llm_api_failed"
    if "llm provider not provided" in text or "provider list" in text:
        return "llm_api_failed"
    if "timeout" in text or "timed out" in text:
        return "llm_timeout" if "model" in text or "mini" in text else "checks_timeout"
    if "clone" in text or "checkout" in text or "git apply" in text:
        return "checkout_failed"
    if "temporary failure" in text or "name resolution" in text or "network" in text:
        return "network_failed"
    if "setup" in text or "pip" in text or "uv " in text or "dependency" in text:
        return "dependency_failed"
    if "policy_blocked" in text:
        return "policy_blocked"
    if "sensor" in text:
        return "sensor_blocked"
    if "dirty" in text or "worktree" in text:
        return "workspace_dirty"
    return "benchmark_runner_error"


def _error_context(error: str) -> str:
    marker = "See "
    if marker not in error:
        return error
    path_text = error.split(marker, 1)[1].strip()
    path = Path(path_text)
    if not path.exists():
        return error
    try:
        log_text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return error
    return f"{error}\n{log_text[-8000:]}"


def _status_category(record: dict[str, Any]) -> str | None:
    if record.get("error_category"):
        return str(record["error_category"])
    status = str(record.get("status", ""))
    if record.get("checks_passed"):
        return None
    if status == "checks_failed":
        return "checks_failed"
    if status == "sensor_failed":
        return "sensor_blocked"
    if status == "review_required":
        return "semantic_review_blocked" if record.get("review_risk_level") == "high" else "review_required"
    if record.get("no_change"):
        return "agent_no_change"
    return None


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
    run_id: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
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
    run_id: str,
    model: str | None,
    provider: dict[str, Any],
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

    record = {
        "run_id": run_id,
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
        "error_category": None,
        "error": None,
        "model": model,
        "provider": provider.get("provider"),
        "base_url": provider.get("base_url"),
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "estimated_cost_usd": None,
        "blocking_reasons": state.sensor_report.blocking_reasons if state.sensor_report else [],
        "changed_files": changed_files,
        "patch_stats": _patch_stats(state.diff),
        "artifact_paths": dict(state.artifacts),
        "sensor_results": sensors,
        "check_results": [result.model_dump() for result in state.check_results],
        "expected_type": task.get("expected_type"),
        "risk_tags": task.get("risk_tags", []),
    }
    record["error_category"] = _status_category(record)
    return record


def _error_record(
    task: dict[str, Any],
    *,
    method: str,
    workspace: Path | None,
    exc: Exception,
    runtime_seconds: float,
    run_id: str | None = None,
    model: str | None = None,
    provider: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error_type = exc.__class__.__name__
    error = str(exc)
    classified_context = _error_context(error)
    provider = provider or {}
    return {
        "run_id": run_id,
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
        "error_type": error_type,
        "error_category": _classify_error(error_type, classified_context),
        "error": error,
        "model": model,
        "provider": provider.get("provider"),
        "base_url": provider.get("base_url"),
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "estimated_cost_usd": None,
        "blocking_reasons": [],
        "changed_files": [],
        "patch_stats": {"files": 0, "additions": 0, "deletions": 0},
        "artifact_paths": {},
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


def _write_attempt_artifacts(
    *,
    out_dir: Path,
    task_id: str,
    attempt: int,
    state: RunState | None,
    record: dict[str, Any],
) -> dict[str, str]:
    artifact_dir = out_dir / "artifacts" / task_id / f"attempt_{attempt}"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    if state is not None:
        diff_path = artifact_dir / "diff.patch"
        checks_path = artifact_dir / "checks.json"
        sensors_path = artifact_dir / "sensors.json"
        review_path = artifact_dir / "review.md"
        diff_path.write_text(redact_text(state.diff), encoding="utf-8")
        checks_path.write_text(
            json.dumps([result.model_dump() for result in state.check_results], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        sensors_path.write_text(
            json.dumps(state.sensor_report.model_dump() if state.sensor_report else {}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        review_path.write_text(redact_text(state.report), encoding="utf-8")
        paths.update(
            {
                "attempt_diff": str(diff_path),
                "attempt_checks": str(checks_path),
                "attempt_sensors": str(sensors_path),
                "attempt_review": str(review_path),
            }
        )
        for name, path in state.artifacts.items():
            paths[name] = path
    else:
        error_path = artifact_dir / "error.json"
        error_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        paths["attempt_error"] = str(error_path)
    return paths


def _make_portable_artifact_paths(record: dict[str, Any]) -> None:
    artifacts = record.get("artifact_paths")
    if not isinstance(artifacts, dict):
        return
    record["artifact_paths"] = {
        str(name): portable_path(str(path)) if path else path
        for name, path in artifacts.items()
    }


def _write_run_manifest(
    *,
    path: Path,
    run_id: str,
    tasks_path: Path,
    out_dir: Path,
    method: str,
    model: str | None,
    max_repair_rounds: int | None,
    max_task_attempts: int,
    task_count: int,
    proxy: str | None,
    provider: dict[str, Any],
    status: str,
    started_at: str,
    completed_at: str | None = None,
    results: list[dict[str, Any]] | None = None,
) -> None:
    passed = sum(1 for item in results or [] if item.get("checks_passed"))
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "status": status,
        "created_at": started_at,
        "completed_at": completed_at,
        "git": repo_git_metadata(ROOT),
        "platform": benchmark_platform_metadata(),
        "tasks_file": portable_path(tasks_path),
        "task_count": task_count,
        "method": method,
        "model": model,
        "provider": provider.get("provider"),
        "base_url": provider.get("base_url"),
        "max_repair_rounds": max_repair_rounds,
        "max_task_attempts": max_task_attempts,
        "proxy_enabled": bool(proxy),
        "out_dir": portable_path(out_dir),
        "results_count": len(results or []),
        "checks_passed": passed,
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


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
    parser.add_argument("--run-id", help="Stable run id for manifests and result records")
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
    if args.max_task_attempts > MAX_TASK_ATTEMPTS:
        parser.error(f"--max-task-attempts must be <= {MAX_TASK_ATTEMPTS}")

    tasks_path = project_path(args.tasks)
    workspaces_dir = project_path(args.workspaces_dir)
    out_dir = project_path(args.out_dir) if args.out_dir else ROOT / "benchmark" / "results" / args.method
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = select_tasks(load_tasks(tasks_path), task_ids=args.task_id, limit=args.limit)
    run_id = args.run_id or _make_run_id(method=args.method, model=args.model, tasks_path=tasks_path)
    provider = _provider_metadata(args.model)
    started_at = utc_now_iso()
    run_manifest_path = out_dir / "run_manifest.json"
    _write_run_manifest(
        path=run_manifest_path,
        run_id=run_id,
        tasks_path=tasks_path,
        out_dir=out_dir,
        method=args.method,
        model=args.model,
        max_repair_rounds=args.max_repair_rounds,
        max_task_attempts=args.max_task_attempts,
        task_count=len(tasks),
        proxy=args.proxy,
        provider=provider,
        status="running",
        started_at=started_at,
    )
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
                state: RunState | None = None
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
                        run_id=run_id,
                        model=args.model,
                        provider=provider,
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
                        run_id=run_id,
                        model=args.model,
                        provider=provider,
                    )
                artifact_paths = _write_attempt_artifacts(
                    out_dir=out_dir,
                    task_id=str(task.get("id", "unknown")),
                    attempt=attempt,
                    state=state,
                    record=record,
                )
                record["artifact_paths"] = {**record.get("artifact_paths", {}), **artifact_paths}
                _make_portable_artifact_paths(record)
                record["attempts"] = attempt
                record["first_attempt_success"] = attempt == 1 and bool(record.get("checks_passed"))
                record["final_attempt"] = False
                record["error_category"] = _status_category(record)
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
                        run_id=run_id,
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
                    run_id=run_id,
                    model=args.model,
                    provider=provider,
                )
            final_record["final_attempt"] = True
            results.append(final_record)
    finally:
        _restore_mini_command(old_mini_command)

    results_path = out_dir / f"{result_prefix}_results.json"
    report_path = out_dir / f"{result_prefix}_report.md"
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(build_markdown_report(results), encoding="utf-8")
    _write_run_manifest(
        path=run_manifest_path,
        run_id=run_id,
        tasks_path=tasks_path,
        out_dir=out_dir,
        method=args.method,
        model=args.model,
        max_repair_rounds=args.max_repair_rounds,
        max_task_attempts=args.max_task_attempts,
        task_count=len(tasks),
        proxy=args.proxy,
        provider=provider,
        status="completed",
        started_at=started_at,
        completed_at=utc_now_iso(),
        results=results,
    )
    print(f"wrote {results_path}")
    print(f"wrote {report_path}")
    print(f"wrote {retry_manifest_path}")
    print(f"wrote {run_manifest_path}")


if __name__ == "__main__":
    main()
