from __future__ import annotations

from codeflow.harness.sensors import SEVERITY_ORDER
from codeflow.models import CheckResult, HarnessSensorReport

HIGH_RISK_PATTERNS = [
    "auth",
    "permission",
    "migration",
    ".env",
    "secret",
    "password",
    "token",
    "delete",
    "drop",
]

MEDIUM_RISK_PATTERNS = [
    "api",
    "schema",
    "model",
    "database",
    "config",
]


def score_risk(diff: str) -> tuple[str, list[str]]:
    lower = diff.lower()
    risks: list[str] = []

    for pattern in HIGH_RISK_PATTERNS:
        if pattern in lower:
            risks.append(f"High-risk keyword found in diff: {pattern}")

    if risks:
        return "high", risks

    for pattern in MEDIUM_RISK_PATTERNS:
        if pattern in lower:
            risks.append(f"Medium-risk keyword found in diff: {pattern}")

    if risks:
        return "medium", risks

    return "low", ["No obvious high-risk pattern detected."]


def build_review_report(
    task: str,
    branch: str,
    diff: str,
    check_results: list[CheckResult],
    sensor_report: HarnessSensorReport | None = None,
) -> str:
    risk_level, risks = score_risk(diff)
    if sensor_report and SEVERITY_ORDER[sensor_report.max_severity] > SEVERITY_ORDER[risk_level]:
        risk_level = sensor_report.max_severity
    changed_lines = len(diff.splitlines())
    check_summary = "\n".join(
        f"- {result.command}: {'PASS' if result.success else 'FAIL'}" for result in check_results
    ) or "- no checks configured"
    risk_text = "\n".join(f"- {item}" for item in risks)
    sensor_text = "- no sensor report"
    blocking_text = "- none"
    if sensor_report:
        sensor_text = "\n".join(
            f"- {result.name}: {'PASS' if result.passed else 'FAIL'} / {result.severity} / {result.message}"
            for result in sensor_report.results
        )
        blocking_text = "\n".join(f"- {reason}" for reason in sensor_report.blocking_reasons) or "- none"
    recommendation = (
        "Commit is allowed after human review."
        if all(result.success for result in check_results)
        and (sensor_report is None or sensor_report.overall_passed)
        else "Do not commit until validation passes."
    )

    return f"""
# CodeFlow Review Report

## 任务
{task}

## 分支
{branch}

## 验证结果
{check_summary}

## 风险等级
{risk_level}

## 风险说明
{risk_text}

## Sensor Report
{sensor_text}

## Blocking Reasons
{blocking_text}

## Diff 大小
{changed_lines} diff lines

## 建议
{recommendation}
""".strip()
