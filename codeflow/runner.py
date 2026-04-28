from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt

from codeflow.diff_reviewer import build_review_report
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
from codeflow.spec_builder import build_spec
from codeflow.test_gate import all_checks_passed, failed_checks, run_checks
from codeflow.utils import read_project_rules

console = Console()


def _verify(
    repo: str,
    task: str,
    policy: HarnessPolicy,
) -> tuple[list[CheckResult], str, list[str], HarnessSensorReport]:
    results = run_checks(repo, policy.required_checks)
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

    prompt = build_initial_prompt(
        task=config.task,
        spec=spec,
        rules=rules,
        checks=policy.required_checks,
        policy=policy,
    )

    if config.dry_run:
        state = RunState(repo=repo, task=config.task, branch="", rules=rules, spec=spec, policy=policy)
        state.report = prompt
        state.status = "dry_run"
        state.commit_action = "not_requested"
        return state

    branch = create_ai_branch(repo, config.task)
    state = RunState(repo=repo, task=config.task, branch=branch, rules=rules, spec=spec, policy=policy)
    console.print(f"[bold green]Created branch:[/bold green] {branch}")

    console.print("[bold]Running mini-swe-agent...[/bold]")
    log_path = run_mini_agent(
        repo=repo,
        prompt=prompt,
        model=config.model,
        mini_config=config.mini_config,
    )
    state.mini_runs.append(log_path)

    for round_idx in range(policy.max_repair_rounds + 1):
        console.print(f"[bold]Running validation checks, round {round_idx}...[/bold]")
        results, diff, _changed_files, sensor_report = _verify(repo, config.task, policy)
        state.check_results = results
        state.diff = diff
        state.sensor_report = sensor_report

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

        console.print(f"[yellow]Verification failed. Repair round {round_idx + 1}...[/yellow]")
        log_path = run_mini_agent(
            repo=repo,
            prompt=repair_prompt,
            model=config.model,
            mini_config=config.mini_config,
        )
        state.mini_runs.append(log_path)
        state.repair_round = round_idx + 1

    state.report = build_review_report(
        task=config.task,
        branch=branch,
        diff=state.diff,
        check_results=state.check_results,
        sensor_report=state.sensor_report,
    )

    console.print(state.report)

    if config.no_commit:
        state.commit_action = "skipped"
        return state

    decision = Prompt.ask(
        "Choose action",
        choices=["commit", "rollback", "keep"],
        default="keep",
    )

    if decision == "commit":
        if policy.rerun_checks_before_commit:
            console.print("[bold]Rerunning validation before commit...[/bold]")
            results, diff, _changed_files, sensor_report = _verify(repo, config.task, policy)
            state.check_results = results
            state.diff = diff
            state.sensor_report = sensor_report
            state.status = _status_for_verification(all_checks_passed(results), sensor_report)

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

    return state
