from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt

from codeflow.diff_reviewer import build_review_report, build_review_summary
from codeflow.git_guard import (
    commit_changes,
    create_ai_branch,
    get_changed_files,
    ensure_clean_worktree,
    ensure_git_repo,
    get_diff,
    rollback,
)
from codeflow.harness.builtin_sensors import run_builtin_sensors, should_attempt_repair
from codeflow.harness.governance import prompt_governance_action
from codeflow.harness.observability import create_run_dir, update_run_index, write_json, write_text
from codeflow.harness.policy import load_harness_policy
from codeflow.mini_runner import run_mini_agent
from codeflow.models import (
    CheckResult,
    CodeFlowConfig,
    HarnessPolicy,
    HarnessSensorReport,
    RunState,
    SensorContext,
)
from codeflow.prompt_builder import build_initial_prompt, build_repair_prompt
from codeflow.redaction import redact_text
from codeflow.semantic import (
    enhance_spec_with_semantics,
    review_diff_with_semantics,
    semantic_review_required_for_paths,
)
from codeflow.spec_builder import build_spec
from codeflow.test_gate import all_checks_passed, failed_checks, run_checks
from codeflow.utils import read_project_rules

console = Console()


def _artifact(state: RunState, name: str, path: Path) -> None:
    state.artifacts[name] = str(path)


def _record_mini_result(state: RunState, result: object, index: int) -> None:
    log_path = getattr(result, "log_path", str(result))
    trajectory_path = getattr(result, "trajectory_path", "")
    events_path = getattr(result, "events_path", "")
    state.mini_runs.append(str(log_path))
    _artifact(state, f"mini_run_{index}_log", Path(str(log_path)))
    if trajectory_path:
        _artifact(state, f"mini_run_{index}_trajectory", Path(str(trajectory_path)))
    if events_path:
        _artifact(state, f"mini_run_{index}_events", Path(str(events_path)))


def _write_final_state(state: RunState) -> None:
    if not state.run_dir:
        return
    run_dir = Path(state.run_dir)
    state_dump = state.model_dump()
    state_dump["diff"] = redact_text(state_dump.get("diff", ""))
    write_json(
        run_dir / "state.json",
        {
            **state_dump,
            "checks_passed": all_checks_passed(state.check_results),
            "sensor_passed": state.sensor_report.overall_passed if state.sensor_report else None,
            "risk_level": state.review_summary.risk_level
            if state.review_summary
            else (state.sensor_report.max_severity if state.sensor_report else "unknown"),
        },
    )
    _artifact(state, "state", run_dir / "state.json")
    update_run_index(state.repo, run_dir)


def _verify(
    repo: str,
    task: str,
    policy: HarnessPolicy,
) -> tuple[list[CheckResult], str, list[str], HarnessSensorReport]:
    results = run_checks(repo, policy.required_checks, allow_shell=policy.allow_shell_checks)
    diff = get_diff(repo)
    changed_files = get_changed_files(repo)
    sensor_report = run_builtin_sensors(
        SensorContext(
            repo=repo,
            task=task,
            diff=diff,
            changed_files=changed_files,
            policy=policy,
            check_results=results,
        )
    )
    return results, diff, changed_files, sensor_report


def _status_for_verification(checks_passed: bool, sensor_report: HarnessSensorReport) -> str:
    if checks_passed and sensor_report.overall_passed:
        return "checks_passed"
    if not checks_passed:
        return "checks_failed"
    return "sensor_failed"


def _commit_block_reason(
    state: RunState,
    policy: HarnessPolicy,
    *,
    allow_high_risk_commit: bool,
) -> tuple[str, str] | None:
    checks_passed = all_checks_passed(state.check_results)
    if policy.block_commit_on_failed_checks and not checks_passed:
        return "validation checks failed", "commit_refused_checks_failed"
    if state.sensor_report and policy.block_commit_on_failed_checks and not state.sensor_report.overall_passed:
        return (
            "; ".join(state.sensor_report.blocking_reasons) or "blocking sensors failed",
            "commit_refused_sensor_failed",
        )
    if (
        state.sensor_report
        and policy.block_commit_on_high_risk
        and state.sensor_report.max_severity == "high"
        and not allow_high_risk_commit
    ):
        return (
            "high-risk sensor findings require --allow-high-risk-commit",
            "commit_refused_high_risk",
        )
    if (
        state.semantic_review
        and policy.block_commit_on_high_risk
        and state.semantic_review.get("risk_level") == "high"
        and not allow_high_risk_commit
    ):
        return (
            "high-risk semantic review findings require --allow-high-risk-commit",
            "commit_refused_high_risk",
        )
    semantic_required = policy.require_semantic_review or semantic_review_required_for_paths(
        policy,
        state.changed_files,
    )
    semantic_failed_closed = (
        not policy.semantic_fail_open
        and state.semantic_review is not None
        and state.semantic_review.get("status") != "completed"
    )
    if (semantic_required or semantic_failed_closed) and (
        not state.semantic_review or state.semantic_review.get("status") != "completed"
    ):
        return ("semantic review is required but did not complete", "commit_refused_semantic_review")
    return None


def run_codeflow(config: CodeFlowConfig) -> RunState:
    repo = str(Path(config.repo).expanduser().resolve())
    ensure_git_repo(repo)
    ensure_clean_worktree(repo)

    rules = read_project_rules(repo)
    policy = load_harness_policy(
        repo,
        cli_checks=config.checks,
        cli_max_repair_rounds=config.max_repair_rounds,
    )
    spec = build_spec(config.task)
    spec, semantic_spec = enhance_spec_with_semantics(
        task=config.task,
        rules=rules,
        policy=policy,
        base_spec=spec,
    )
    run_dir = create_run_dir(repo, config.task)
    run_id = run_dir.name

    prompt = build_initial_prompt(
        task=config.task,
        spec=spec,
        rules=rules,
        checks=policy.required_checks,
        policy=policy,
    )
    write_json(run_dir / "policy.json", policy.model_dump())
    write_json(run_dir / "spec.json", spec.model_dump())
    if semantic_spec:
        write_json(run_dir / "semantic_spec.json", semantic_spec)
    write_text(run_dir / "initial_prompt.md", prompt)

    if config.dry_run:
        state = RunState(
            repo=repo,
            task=config.task,
            branch="",
            run_id=run_id,
            run_dir=str(run_dir),
            rules=rules,
            spec=spec,
            policy=policy,
        )
        state.report = prompt
        state.status = "dry_run"
        state.commit_action = "not_requested"
        _artifact(state, "policy", run_dir / "policy.json")
        _artifact(state, "spec", run_dir / "spec.json")
        if semantic_spec:
            _artifact(state, "semantic_spec", run_dir / "semantic_spec.json")
        _artifact(state, "initial_prompt", run_dir / "initial_prompt.md")
        write_text(run_dir / "diff.patch", "")
        write_text(run_dir / "review_report.md", prompt)
        _artifact(state, "diff", run_dir / "diff.patch")
        _artifact(state, "review_report", run_dir / "review_report.md")
        _write_final_state(state)
        return state

    branch = create_ai_branch(repo, config.task)
    state = RunState(
        repo=repo,
        task=config.task,
        branch=branch,
        run_id=run_id,
        run_dir=str(run_dir),
        rules=rules,
        spec=spec,
        policy=policy,
    )
    _artifact(state, "policy", run_dir / "policy.json")
    _artifact(state, "spec", run_dir / "spec.json")
    if semantic_spec:
        _artifact(state, "semantic_spec", run_dir / "semantic_spec.json")
    _artifact(state, "initial_prompt", run_dir / "initial_prompt.md")
    console.print(f"[bold green]Created branch:[/bold green] {branch}")

    console.print("[bold]Running mini-swe-agent...[/bold]")
    mini_result = run_mini_agent(
        repo=repo,
        prompt=prompt,
        run_dir=run_dir,
        run_index=0,
        model=config.model,
        mini_config=config.mini_config,
        policy=policy,
    )
    _record_mini_result(state, mini_result, 0)

    for round_idx in range(policy.max_repair_rounds + 1):
        console.print(f"[bold]Running validation checks, round {round_idx}...[/bold]")
        results, diff, changed_files, sensor_report = _verify(repo, config.task, policy)
        state.check_results = results
        state.diff = diff
        state.changed_files = changed_files
        state.sensor_report = sensor_report
        checks_path = run_dir / f"checks_round_{round_idx}.json"
        sensors_path = run_dir / f"sensor_report_round_{round_idx}.json"
        write_json(checks_path, [result.model_dump() for result in results])
        write_json(sensors_path, sensor_report.model_dump())
        _artifact(state, f"checks_round_{round_idx}", checks_path)
        _artifact(state, f"sensor_report_round_{round_idx}", sensors_path)

        if all_checks_passed(results) and sensor_report.overall_passed:
            state.status = "checks_passed"
            break

        state.status = _status_for_verification(all_checks_passed(results), sensor_report)
        if round_idx >= policy.max_repair_rounds:
            break

        if not should_attempt_repair(sensor_report):
            state.status = "review_required"
            break

        repair_prompt = build_repair_prompt(
            task=config.task,
            spec=spec,
            rules=rules,
            failed_results=failed_checks(results),
            checks=policy.required_checks,
            policy=policy,
            sensor_report=sensor_report,
        )
        repair_round = round_idx + 1
        repair_path = run_dir / f"repair_prompt_{repair_round}.md"
        write_text(repair_path, repair_prompt)
        _artifact(state, f"repair_prompt_{repair_round}", repair_path)
        state.repair_history.append(
            {
                "round": repair_round,
                "reason": state.status,
                "result": "repair_prompt_created",
            }
        )

        console.print(f"[yellow]Verification failed. Repair round {repair_round}...[/yellow]")
        mini_result = run_mini_agent(
            repo=repo,
            prompt=repair_prompt,
            run_dir=run_dir,
            run_index=repair_round,
            model=config.model,
            mini_config=config.mini_config,
            policy=policy,
        )
        _record_mini_result(state, mini_result, repair_round)
        state.repair_round = repair_round

    state.semantic_review = review_diff_with_semantics(
        task=config.task,
        diff=state.diff,
        changed_files=state.changed_files,
        check_results=state.check_results,
        sensor_report=state.sensor_report,
        policy=policy,
    )
    semantic_required = policy.require_semantic_review or semantic_review_required_for_paths(
        policy,
        state.changed_files,
    )
    if state.semantic_review:
        semantic_review_path = run_dir / "semantic_review.json"
        write_json(semantic_review_path, state.semantic_review)
        _artifact(state, "semantic_review", semantic_review_path)
        if state.semantic_review.get("status") != "completed" and (
            semantic_required or not policy.semantic_fail_open
        ):
            state.status = "review_required"

    state.review_summary = build_review_summary(
        diff=redact_text(state.diff),
        check_results=state.check_results,
        sensor_report=state.sensor_report,
        changed_files=state.changed_files,
        semantic_review=state.semantic_review,
    )
    review_summary_path = run_dir / "review_summary.json"
    write_json(review_summary_path, state.review_summary)
    _artifact(state, "review_summary", review_summary_path)

    state.report = build_review_report(
        task=config.task,
        branch=branch,
        diff=redact_text(state.diff),
        check_results=state.check_results,
        sensor_report=state.sensor_report,
        spec=spec,
        status=state.status,
        repair_round=state.repair_round,
        mini_runs=state.mini_runs,
        run_dir=str(run_dir),
        changed_files=state.changed_files,
        repair_history=state.repair_history,
        semantic_review=state.semantic_review,
        review_summary=state.review_summary,
    )
    write_text(run_dir / "diff.patch", redact_text(state.diff))
    write_text(run_dir / "review_report.md", state.report)
    _artifact(state, "diff", run_dir / "diff.patch")
    _artifact(state, "review_report", run_dir / "review_report.md")

    console.print(state.report)

    if config.no_commit:
        state.commit_action = "skipped"
        _write_final_state(state)
        return state

    decision = prompt_governance_action(
        state,
        console=console,
        prompt_ask=Prompt.ask,
    )
    if decision == "refused":
        _write_final_state(state)
        return state

    if decision == "commit":
        if policy.rerun_checks_before_commit:
            console.print("[bold]Rerunning validation before commit...[/bold]")
            results, diff, changed_files, sensor_report = _verify(repo, config.task, policy)
            state.check_results = results
            state.diff = diff
            state.changed_files = changed_files
            state.sensor_report = sensor_report
            state.status = _status_for_verification(all_checks_passed(results), sensor_report)
            checks_path = run_dir / "checks_round_commit.json"
            sensors_path = run_dir / "sensor_report_round_commit.json"
            write_json(checks_path, [result.model_dump() for result in results])
            write_json(sensors_path, sensor_report.model_dump())
            _artifact(state, "checks_round_commit", checks_path)
            _artifact(state, "sensor_report_round_commit", sensors_path)

        block_reason = _commit_block_reason(
            state,
            policy,
            allow_high_risk_commit=config.allow_high_risk_commit,
        )
        if block_reason:
            reason, status = block_reason
            console.print(f"[red]Refusing to commit because {reason}.[/red]")
            state.status = status
            state.commit_action = "refused"
            _write_final_state(state)
            return state
        commit_changes(repo, f"codeflow: {config.task[:60]}")
        state.status = "committed"
        state.commit_action = "committed"
    elif decision == "rollback":
        rollback(repo, remove_untracked=True)
        state.status = "rolled_back"
        state.commit_action = "rolled_back"
    else:
        state.status = "kept_uncommitted"
        state.commit_action = "kept"

    _write_final_state(state)
    return state
