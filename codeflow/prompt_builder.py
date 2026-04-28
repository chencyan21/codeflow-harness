from __future__ import annotations

from codeflow.harness.guidance import build_guidance_context
from codeflow.harness.policy import format_policy_for_prompt
from codeflow.models import CheckResult, HarnessPolicy, HarnessSensorReport, Spec


def build_initial_prompt(
    task: str,
    spec: Spec,
    rules: str,
    checks: list[str],
    policy: HarnessPolicy | None = None,
) -> str:
    checks_text = "\n".join(f"- {item}" for item in checks)
    guidance = (
        build_guidance_context(spec, rules, policy)
        if policy
        else f"Structured spec:\nGoal: {spec.goal}\n\nProject rules:\n{rules}"
    )

    return f"""
You are working inside a local Git repository.

User task:
{task}

{guidance}

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
    policy: HarnessPolicy | None = None,
    sensor_report: HarnessSensorReport | None = None,
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
    policy_text = f"\n\n{format_policy_for_prompt(policy)}" if policy else ""
    sensor_text = ""
    if sensor_report:
        failed_sensors = "\n".join(
            f"- {result.name}: {result.severity}: {result.message}"
            for result in sensor_report.results
            if not result.passed or result.severity in {"medium", "high"}
        )
        blocking = "\n".join(f"- {reason}" for reason in sensor_report.blocking_reasons)
        sensor_text = f"""

Sensor report:
Overall passed: {sensor_report.overall_passed}
Max severity: {sensor_report.max_severity}

Failed or warning sensors:
{failed_sensors or "- none"}

Blocking reasons:
{blocking or "- none"}
"""

    return f"""
The previous implementation did not pass validation.

Original task:
{task}

Goal:
{spec.goal}

Project rules:
{rules}
{policy_text}

Failed validation logs:
{failure_logs}
{sensor_text}

Required validation commands:
{checks_text}

Please fix the implementation with minimal changes.
Do not delete tests.
Do not bypass tests.
Do not modify unrelated files.
""".strip()
