from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

from codeflow.models import CheckResult
from codeflow.redaction import redact_text
from codeflow.utils import tail_text

SHELL_CHECK_PREFIX = "shell:"


def check_command_executable_exists(command: str, *, allow_shell: bool = False) -> bool:
    stripped = command.strip()
    if stripped.startswith(SHELL_CHECK_PREFIX):
        return allow_shell and bool(stripped.removeprefix(SHELL_CHECK_PREFIX).strip())
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    return bool(parts and (shutil.which(parts[0]) or Path(parts[0]).exists()))


def run_check(repo: str, command: str, *, allow_shell: bool = False) -> CheckResult:
    stripped = command.strip()
    if stripped.startswith(SHELL_CHECK_PREFIX):
        if not allow_shell:
            return CheckResult(
                command=command,
                success=False,
                returncode=126,
                stdout="",
                stderr="Shell check is disabled by policy. Set allow_shell_checks: true to permit it.",
            )
        shell_command = stripped.removeprefix(SHELL_CHECK_PREFIX).strip()
        if not shell_command:
            return CheckResult(
                command=command,
                success=False,
                returncode=127,
                stdout="",
                stderr="Empty shell check command.",
            )
        result = subprocess.run(
            shell_command,
            cwd=repo,
            shell=True,
            text=True,
            capture_output=True,
        )
        return CheckResult(
            command=command,
            success=result.returncode == 0,
            returncode=result.returncode,
            stdout=redact_text(tail_text(result.stdout)),
            stderr=redact_text(tail_text(result.stderr)),
        )

    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return CheckResult(
            command=command,
            success=False,
            returncode=127,
            stdout="",
            stderr=f"Invalid check command: {exc}",
        )
    if not parts:
        return CheckResult(
            command=command,
            success=False,
            returncode=127,
            stdout="",
            stderr="Empty check command.",
        )
    try:
        result = subprocess.run(
            parts,
            cwd=repo,
            shell=False,
            text=True,
            capture_output=True,
        )
    except OSError as exc:
        return CheckResult(
            command=command,
            success=False,
            returncode=127,
            stdout="",
            stderr=str(exc),
        )
    return CheckResult(
        command=command,
        success=result.returncode == 0,
        returncode=result.returncode,
        stdout=redact_text(tail_text(result.stdout)),
        stderr=redact_text(tail_text(result.stderr)),
    )


def run_checks(repo: str, checks: list[str], *, allow_shell: bool = False) -> list[CheckResult]:
    results: list[CheckResult] = []

    for command in checks:
        results.append(run_check(repo, command, allow_shell=allow_shell))

    return results


def all_checks_passed(results: list[CheckResult]) -> bool:
    return all(result.success for result in results)


def failed_checks(results: list[CheckResult]) -> list[CheckResult]:
    return [result for result in results if not result.success]
