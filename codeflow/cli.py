from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console

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
