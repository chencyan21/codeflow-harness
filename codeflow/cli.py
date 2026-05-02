from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from codeflow.doctor import run_doctor
from codeflow.harness.observability import export_run_dir, get_run_dir, list_run_dirs
from codeflow.init_project import init_project
from codeflow.models import CodeFlowConfig
from codeflow.runner import run_codeflow

app = typer.Typer(help="CodeFlow Harness: trusted execution harness for mini-swe-agent v2")
console = Console()


@app.callback()
def main() -> None:
    """CodeFlow Harness command line interface."""


@app.command()
def run(
    repo: Annotated[str, typer.Option(help="Path to target Git repository")],
    task: Annotated[str, typer.Option(help="Natural language coding task")],
    checks: Annotated[list[str] | None, typer.Option(help="Validation commands")] = None,
    max_repair_rounds: Annotated[
        int | None, typer.Option(help="Maximum repair attempts, capped at 3")
    ] = None,
    model: Annotated[str | None, typer.Option(help="Model name passed to mini-swe-agent")] = None,
    mini_config: Annotated[
        str | None, typer.Option(help="mini-swe-agent config path or config spec")
    ] = None,
    no_commit: Annotated[bool, typer.Option(help="Do not commit automatically")] = False,
    dry_run: Annotated[bool, typer.Option(help="Build prompt but do not run agent")] = False,
    allow_high_risk_commit: Annotated[
        bool, typer.Option(help="Allow commit when high-risk sensors are present")
    ] = False,
) -> None:
    config = CodeFlowConfig(
        repo=repo,
        task=task,
        checks=list(checks) if checks is not None else None,
        max_repair_rounds=max_repair_rounds,
        model=model,
        mini_config=mini_config,
        no_commit=no_commit,
        dry_run=dry_run,
        allow_high_risk_commit=allow_high_risk_commit,
    )
    try:
        state = run_codeflow(config)
    except Exception as exc:
        console.print(f"[bold red]CodeFlow failed:[/bold red] {exc}")
        raise typer.Exit(1) from exc
    if state.status == "dry_run":
        console.print(state.report)


def _load_state(run_dir: Path) -> dict:
    state_path = run_dir / "state.json"
    if not state_path.exists():
        return {"run_id": run_dir.name, "run_dir": str(run_dir)}
    return json.loads(state_path.read_text(encoding="utf-8"))


@app.command()
def inspect(
    repo: Annotated[str, typer.Option(help="Path to target Git repository")],
    latest: Annotated[bool, typer.Option(help="Show latest run")] = False,
    run_id: Annotated[str | None, typer.Option(help="Specific run id")] = None,
    limit: Annotated[int, typer.Option(help="Number of recent runs to list")] = 1,
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    try:
        if run_id:
            runs = [get_run_dir(repo, run_id)]
        elif limit > 1 and not latest:
            runs = list_run_dirs(repo)[:limit]
            if not runs:
                raise RuntimeError("No CodeFlow runs found for this repository.")
        else:
            runs = [get_run_dir(repo, latest=True)]
    except Exception as exc:
        console.print(f"[bold red]CodeFlow inspect failed:[/bold red] {exc}")
        raise typer.Exit(1) from exc

    states = [_load_state(run_dir) for run_dir in runs]
    if json_output:
        console.print(json.dumps(states[0] if len(states) == 1 else states, ensure_ascii=False, indent=2))
        return

    if len(states) == 1:
        state = states[0]
        title = "Latest CodeFlow Run" if latest or run_id is None else "CodeFlow Run"
        console.print(f"[bold]{title}[/bold]")
        console.print(f"Run ID: {state.get('run_id') or runs[0].name}")
        console.print(f"Task: {state.get('task', '')}")
        console.print(f"Branch: {state.get('branch', '')}")
        console.print(f"Status: {state.get('status', '')}")
        console.print(f"Commit Action: {state.get('commit_action', '')}")
        console.print(f"Repair Rounds: {state.get('repair_round', 0)}")
        console.print(f"Risk Level: {state.get('risk_level', 'unknown')}")
        console.print(f"Checks: {'PASS' if state.get('checks_passed') else 'FAIL'}")
        console.print(f"Sensors: {'PASS' if state.get('sensor_passed') else 'FAIL'}")
        console.print(f"Report: {runs[0] / 'review_report.md'}")
        trajectories = sorted(runs[0].glob("mini_run_*.trajectory.json"))
        if trajectories:
            console.print(f"Trajectory: {trajectories[0]}")
        return

    console.print("[bold]Recent Runs[/bold]")
    for index, (run_dir, state) in enumerate(zip(runs, states), start=1):
        console.print(
            f"{index}. {run_dir.name}   {state.get('status', 'unknown')}   "
            f"{state.get('risk_level', 'unknown')}"
        )


@app.command()
def report(
    repo: Annotated[str, typer.Option(help="Path to target Git repository")],
    latest: Annotated[bool, typer.Option(help="Use latest run")] = False,
    run_id: Annotated[str | None, typer.Option(help="Specific run id")] = None,
    path_only: Annotated[bool, typer.Option(help="Print report path only")] = False,
) -> None:
    try:
        run_dir = get_run_dir(repo, run_id, latest=latest or run_id is None)
        report_path = run_dir / "review_report.md"
        if not report_path.exists():
            raise RuntimeError(f"review_report.md not found in {run_dir}")
    except Exception as exc:
        console.print(f"[bold red]CodeFlow report failed:[/bold red] {exc}")
        raise typer.Exit(1) from exc

    if path_only:
        console.print(str(report_path))
    else:
        console.print(report_path.read_text(encoding="utf-8"))


@app.command("export")
def export_command(
    repo: Annotated[str, typer.Option(help="Path to target Git repository")],
    out: Annotated[str, typer.Option(help="Zip output path")],
    latest: Annotated[bool, typer.Option(help="Use latest run")] = False,
    run_id: Annotated[str | None, typer.Option(help="Specific run id")] = None,
    include_logs: Annotated[bool, typer.Option(help="Include mini run logs")] = False,
    include_trajectory: Annotated[bool, typer.Option(help="Include mini trajectory files")] = False,
) -> None:
    try:
        run_dir = get_run_dir(repo, run_id, latest=latest or run_id is None)
        exported = export_run_dir(
            run_dir,
            Path(out),
            include_logs=include_logs,
            include_trajectory=include_trajectory,
        )
    except Exception as exc:
        console.print(f"[bold red]CodeFlow export failed:[/bold red] {exc}")
        raise typer.Exit(1) from exc
    console.print(str(exported))


@app.command()
def init(
    repo: Annotated[str, typer.Option(help="Path to target Git repository")],
    force: Annotated[bool, typer.Option(help="Overwrite existing CodeFlow config")] = False,
    template: Annotated[str, typer.Option(help="Template name")] = "python",
) -> None:
    if template != "python":
        console.print(f"[bold red]Unsupported template:[/bold red] {template}")
        raise typer.Exit(1)
    try:
        written = init_project(repo, force=force)
    except Exception as exc:
        console.print(f"[bold red]CodeFlow init failed:[/bold red] {exc}")
        raise typer.Exit(1) from exc
    for path in written:
        console.print(f"wrote {path}")


@app.command()
def doctor(
    repo: Annotated[str, typer.Option(help="Path to target Git repository")],
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
    skip_checks: Annotated[bool, typer.Option(help="Do not execute required checks")] = False,
    skip_llm: Annotated[bool, typer.Option(help="Do not validate LLM environment")] = False,
) -> None:
    try:
        results = run_doctor(repo, skip_checks=skip_checks, skip_llm=skip_llm)
    except Exception as exc:
        console.print(f"[bold red]CodeFlow doctor failed:[/bold red] {exc}")
        raise typer.Exit(1) from exc

    if json_output:
        console.print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    console.print("[bold]CodeFlow Doctor[/bold]")
    for item in results:
        status = "OK" if item["ok"] else "FAILED"
        console.print(f"{item['name']}: {status}")
        if item.get("message"):
            console.print(f"  Reason: {item['message']}")
        if item.get("suggestion"):
            console.print(f"  Suggestion: {item['suggestion']}")
