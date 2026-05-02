from __future__ import annotations

from collections.abc import Callable

from rich.console import Console

from codeflow.harness.sensors import SEVERITY_ORDER
from codeflow.models import RunState
from codeflow.test_gate import all_checks_passed


ACTION_ALIASES = {
    "c": "commit",
    "commit": "commit",
    "r": "rollback",
    "rollback": "rollback",
    "k": "keep",
    "keep": "keep",
    "q": "keep",
    "quit": "keep",
    "d": "show-diff",
    "show-diff": "show-diff",
    "p": "show-report",
    "show-report": "show-report",
    "t": "show-checks",
    "show-checks": "show-checks",
    "s": "show-sensors",
    "show-sensors": "show-sensors",
    "f": "show-files",
    "show-files": "show-files",
}


def _risk_level(state: RunState) -> str:
    return state.sensor_report.max_severity if state.sensor_report else "unknown"


def _checks_summary(state: RunState) -> str:
    if not state.check_results:
        return "no checks configured"
    return "PASS" if all_checks_passed(state.check_results) else "FAIL"


def _sensors_summary(state: RunState) -> str:
    if not state.sensor_report:
        return "no sensors"
    warnings = [item for item in state.sensor_report.results if item.passed and item.severity in {"medium", "high"}]
    if state.sensor_report.overall_passed and warnings:
        return f"PASS with {len(warnings)} warning(s)"
    return "PASS" if state.sensor_report.overall_passed else "FAIL"


def print_governance_summary(state: RunState, console: Console) -> None:
    console.print("[bold]CodeFlow Governance[/bold]")
    console.print(f"Task: {state.task}")
    console.print(f"Branch: {state.branch}")
    console.print(f"Status: {state.status}")
    console.print(f"Risk Level: {_risk_level(state)}")
    console.print(f"Checks: {_checks_summary(state)}")
    console.print(f"Sensors: {_sensors_summary(state)}")
    console.print(f"Repair Rounds: {state.repair_round}")
    if state.changed_files:
        console.print("\nChanged Files:")
        for path in state.changed_files:
            console.print(f"- {path}")
    console.print(
        "\nOptions:\n"
        "[c] commit\n"
        "[r] rollback\n"
        "[k] keep\n"
        "[d] show diff\n"
        "[p] show report\n"
        "[t] show checks\n"
        "[s] show sensors\n"
        "[f] show changed files\n"
        "[q] quit"
    )


def _show_checks(state: RunState, console: Console) -> None:
    for result in state.check_results:
        status = "PASS" if result.success else "FAIL"
        console.print(f"{result.command}: {status} ({result.returncode})")
        if not result.success:
            if result.stdout:
                console.print(result.stdout)
            if result.stderr:
                console.print(result.stderr)


def _show_sensors(state: RunState, console: Console) -> None:
    if not state.sensor_report:
        console.print("No sensor report.")
        return
    for result in state.sensor_report.results:
        status = "PASS" if result.passed else "FAIL"
        console.print(f"{result.name}: {status} / {result.severity} / {result.message}")


def _show_files(state: RunState, console: Console) -> None:
    if not state.changed_files:
        console.print("No changed files.")
        return
    for path in state.changed_files:
        console.print(f"- {path}")


def prompt_governance_action(
    state: RunState,
    *,
    console: Console,
    prompt_ask: Callable[..., str],
) -> str:
    print_governance_summary(state, console)
    while True:
        raw_action = prompt_ask(
            "Choose action",
            choices=list(ACTION_ALIASES),
            default="keep",
        )
        action = ACTION_ALIASES[raw_action]
        if action == "show-diff":
            console.print(state.diff or "No diff.")
            continue
        if action == "show-report":
            console.print(state.report or "No report.")
            continue
        if action == "show-checks":
            _show_checks(state, console)
            continue
        if action == "show-sensors":
            _show_sensors(state, console)
            continue
        if action == "show-files":
            _show_files(state, console)
            continue
        if (
            action == "commit"
            and all_checks_passed(state.check_results)
            and state.sensor_report
            and state.sensor_report.overall_passed
            and SEVERITY_ORDER.get(_risk_level(state), 0) >= SEVERITY_ORDER["high"]
        ):
            confirmation = prompt_ask("Type CONFIRM HIGH RISK to commit", default="")
            if confirmation != "CONFIRM HIGH RISK":
                state.status = "commit_refused_high_risk"
                state.commit_action = "refused"
                return "refused"
        return action
