from __future__ import annotations

from codeflow.models import CheckResult, Spec


def build_initial_prompt(task: str, spec: Spec, rules: str, checks: list[str]) -> str:
    criteria = "\n".join(f"- {item}" for item in spec.acceptance_criteria)
    constraints = "\n".join(f"- {item}" for item in spec.constraints)
    checks_text = "\n".join(f"- {item}" for item in checks)

    return f"""
You are working inside a local Git repository.

User task:
{task}

Structured spec:
Goal: {spec.goal}

Acceptance criteria:
{criteria}

Constraints:
{constraints}

Project rules:
{rules}

Required validation commands:
{checks_text}

Instructions:
1. Inspect the repository before editing.
2. Make the minimal necessary code changes.
3. Add or update tests when appropriate.
4. Do not claim success unless the required validation commands can pass.
5. Do not modify unrelated files.
""".strip()


def build_repair_prompt(
    task: str,
    spec: Spec,
    rules: str,
    failed_results: list[CheckResult],
    checks: list[str],
) -> str:
    failure_logs = "\n\n".join(
        (
            f"Command: {result.command}\n"
            f"Return code: {result.returncode}\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
        for result in failed_results
    )
    checks_text = "\n".join(f"- {item}" for item in checks)

    return f"""
The previous implementation did not pass validation.

Original task:
{task}

Goal:
{spec.goal}

Project rules:
{rules}

Failed validation logs:
{failure_logs}

Required validation commands:
{checks_text}

Please fix the implementation with minimal changes.
Do not delete tests.
Do not bypass tests.
Do not modify unrelated files.
""".strip()
