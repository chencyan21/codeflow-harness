from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt

from codeflow.diff_reviewer import build_review_report
from codeflow.git_guard import (
    commit_changes,
    create_ai_branch,
    ensure_clean_worktree,
    ensure_git_repo,
    get_diff,
    rollback,
)
from codeflow.mini_runner import run_mini_agent
from codeflow.models import CodeFlowConfig, RunState
from codeflow.prompt_builder import build_initial_prompt, build_repair_prompt
from codeflow.spec_builder import build_spec
from codeflow.test_gate import all_checks_passed, failed_checks, run_checks
from codeflow.utils import read_project_rules

console = Console()


def run_codeflow(config: CodeFlowConfig) -> RunState:
    repo = str(Path(config.repo).expanduser().resolve())
    ensure_git_repo(repo)
    ensure_clean_worktree(repo)

    rules = read_project_rules(repo)
    spec = build_spec(config.task)

    prompt = build_initial_prompt(
        task=config.task,
        spec=spec,
        rules=rules,
        checks=config.checks,
    )

    if config.dry_run:
        state = RunState(repo=repo, task=config.task, branch="", rules=rules, spec=spec)
        state.report = prompt
        state.status = "dry_run"
        state.commit_action = "not_requested"
        return state

    branch = create_ai_branch(repo, config.task)
    state = RunState(repo=repo, task=config.task, branch=branch, rules=rules, spec=spec)
    console.print(f"[bold green]Created branch:[/bold green] {branch}")

    console.print("[bold]Running mini-swe-agent...[/bold]")
    log_path = run_mini_agent(
        repo=repo,
        prompt=prompt,
        model=config.model,
        mini_config=config.mini_config,
    )
    state.mini_runs.append(log_path)

    for round_idx in range(config.max_repair_rounds + 1):
        console.print(f"[bold]Running validation checks, round {round_idx}...[/bold]")
        results = run_checks(repo, config.checks)
        state.check_results = results

        if all_checks_passed(results):
            state.status = "checks_passed"
            break

        if round_idx >= config.max_repair_rounds:
            state.status = "checks_failed"
            break

        repair_prompt = build_repair_prompt(
            task=config.task,
            spec=spec,
            rules=rules,
            failed_results=failed_checks(results),
            checks=config.checks,
        )

        console.print(f"[yellow]Checks failed. Repair round {round_idx + 1}...[/yellow]")
        log_path = run_mini_agent(
            repo=repo,
            prompt=repair_prompt,
            model=config.model,
            mini_config=config.mini_config,
        )
        state.mini_runs.append(log_path)
        state.repair_round = round_idx + 1

    diff = get_diff(repo)
    state.diff = diff
    state.report = build_review_report(
        task=config.task,
        branch=branch,
        diff=diff,
        check_results=state.check_results,
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
        if not all_checks_passed(state.check_results):
            console.print("[red]Refusing to commit because checks failed.[/red]")
            state.status = "commit_refused_checks_failed"
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
