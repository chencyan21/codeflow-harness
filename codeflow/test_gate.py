from __future__ import annotations

import subprocess

from codeflow.models import CheckResult
from codeflow.utils import tail_text


def run_checks(repo: str, checks: list[str]) -> list[CheckResult]:
    results: list[CheckResult] = []

    for command in checks:
        result = subprocess.run(
            command,
            cwd=repo,
            shell=True,
            text=True,
            capture_output=True,
        )
        results.append(
            CheckResult(
                command=command,
                success=result.returncode == 0,
                returncode=result.returncode,
                stdout=tail_text(result.stdout),
                stderr=tail_text(result.stderr),
            )
        )

    return results


def all_checks_passed(results: list[CheckResult]) -> bool:
    return all(result.success for result in results)


def failed_checks(results: list[CheckResult]) -> list[CheckResult]:
    return [result for result in results if not result.success]
