from __future__ import annotations

import re

from codeflow.harness.sensors import SEVERITY_ORDER
from codeflow.models import CheckResult, HarnessSensorReport, ReviewFinding, ReviewSummary, Spec

HIGH_RISK_PATTERNS = [
    "auth",
    "permission",
    "migration",
    ".env",
    "secret",
    "password",
    "access_token",
    "api_token",
    "auth_token",
    "refresh_token",
    "delete",
    "drop",
]

HIGH_RISK_PATH_PATTERNS = [
    "auth/",
    "authentication/",
    "permissions/",
    "migrations/",
    "secrets/",
    "credentials/",
]

MEDIUM_RISK_PATTERNS = [
    "api",
    "schema",
    "model",
    "database",
    "config",
]

MEDIUM_RISK_PATH_PATTERNS = [
    ".github/workflows/",
    ".codeflow/",
    "config/",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "poetry.lock",
    "uv.lock",
]

HIGH_RISK_ADDED_LINE_PATTERNS = [
    (re.compile(r"\bshutil\.rmtree\s*\("), "recursive deletion call added: shutil.rmtree"),
    (re.compile(r"\bos\.(remove|unlink|rmdir)\s*\("), "filesystem deletion call added"),
    (re.compile(r"\bPath\s*\([^)]*\)\.unlink\s*\("), "filesystem unlink call added"),
    (re.compile(r"\brm\s+-[^\n]*r[^\n]*f\b"), "destructive shell command added: rm -rf"),
    (re.compile(r"\b(drop\s+table|delete\s+from|truncate\s+table)\b"), "destructive SQL statement added"),
    (re.compile(r"\bchmod\s+777\b"), "over-broad file permission command added"),
]


def _contains_risk_pattern(diff: str, pattern: str) -> bool:
    if any(not char.isalnum() for char in pattern):
        return pattern in diff
    return re.search(rf"(?<![a-z0-9]){re.escape(pattern)}(?![a-z0-9])", diff) is not None


def _added_lines(diff: str) -> list[str]:
    return [
        line[1:].strip().lower()
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]


def _path_risks(changed_files: list[str] | None) -> tuple[list[str], list[str]]:
    high: list[str] = []
    medium: list[str] = []
    for path in changed_files or []:
        normalized = path.replace("\\", "/").lower()
        for pattern in HIGH_RISK_PATH_PATTERNS:
            if pattern in normalized:
                high.append(f"High-risk path changed: {path}")
                break
        else:
            for pattern in MEDIUM_RISK_PATH_PATTERNS:
                if normalized == pattern.rstrip("/") or pattern in normalized:
                    medium.append(f"Medium-risk path changed: {path}")
                    break
    return high, medium


def _behavioral_risks(diff: str) -> list[str]:
    risks: list[str] = []
    for line in _added_lines(diff):
        for pattern, message in HIGH_RISK_ADDED_LINE_PATTERNS:
            if pattern.search(line):
                risks.append(message)
    return risks


def score_risk(diff: str, changed_files: list[str] | None = None) -> tuple[str, list[str]]:
    lower = diff.lower()
    risks: list[str] = []

    path_high, path_medium = _path_risks(changed_files)
    risks.extend(path_high)

    for pattern in HIGH_RISK_PATTERNS:
        if _contains_risk_pattern(lower, pattern):
            risks.append(f"High-risk keyword found in diff: {pattern}")

    risks.extend(_behavioral_risks(diff))

    if risks:
        return "high", risks

    risks.extend(path_medium)

    for pattern in MEDIUM_RISK_PATTERNS:
        if _contains_risk_pattern(lower, pattern):
            risks.append(f"Medium-risk keyword found in diff: {pattern}")

    if risks:
        return "medium", risks

    return "low", ["No obvious high-risk pattern detected."]


def _escape_table(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _check_status(result: CheckResult) -> str:
    return "PASS" if result.success else "FAIL"


def _sensor_status(passed: bool, severity: str) -> str:
    if not passed:
        return "FAIL"
    if severity in {"medium", "high"}:
        return "WARN"
    return "PASS"


def _is_test_file(path: str) -> bool:
    return path.startswith("tests/") or "/tests/" in path or path.endswith("_test.py") or path.startswith("test_")


def _is_config_file(path: str) -> bool:
    return path in {
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "poetry.lock",
        "uv.lock",
    } or path.startswith(".codeflow/")


def _changed_file_groups(changed_files: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {
        "Source Files": [],
        "Test Files": [],
        "Config Files": [],
        "Unknown": [],
    }
    for path in changed_files:
        if _is_test_file(path):
            groups["Test Files"].append(path)
        elif _is_config_file(path):
            groups["Config Files"].append(path)
        elif path.endswith(".py"):
            groups["Source Files"].append(path)
        else:
            groups["Unknown"].append(path)
    return groups


def _list_or_none(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- none"


def _severity_from_risk(risk_level: str) -> str:
    return risk_level if risk_level in SEVERITY_ORDER else "medium"


def _first_path(details: dict) -> str | None:
    for key in ("path", "paths", "files", "changed_files"):
        value = details.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, list) and value:
            return str(value[0])
    return None


def _semantic_finding_message(item: object) -> tuple[str, str, str, str]:
    if isinstance(item, dict):
        severity = str(item.get("severity") or "medium").lower()
        if severity not in SEVERITY_ORDER:
            severity = "medium"
        return (
            severity,
            str(item.get("file") or "") or "",
            str(item.get("reason") or item.get("message") or ""),
            str(item.get("suggested_action") or item.get("recommendation") or ""),
        )
    return ("medium", "", str(item), "")


def build_review_summary(
    *,
    diff: str,
    check_results: list[CheckResult],
    sensor_report: HarnessSensorReport | None = None,
    changed_files: list[str] | None = None,
    semantic_review: dict | None = None,
) -> ReviewSummary:
    risk_level, risks = score_risk(diff, changed_files=changed_files)
    findings: list[ReviewFinding] = []

    for risk in risks:
        findings.append(
            ReviewFinding(
                source="rules",
                severity=_severity_from_risk(risk_level),  # type: ignore[arg-type]
                category="risk_pattern",
                message=risk,
                recommendation="Review the changed files for behavioral impact.",
            )
        )

    if sensor_report:
        for result in sensor_report.results:
            if result.passed and result.severity not in {"medium", "high"}:
                continue
            findings.append(
                ReviewFinding(
                    source="sensor",
                    severity=result.severity,
                    category=result.name,
                    file=_first_path(result.details),
                    message=result.message,
                    recommendation=(
                        "Resolve this blocking sensor before commit."
                        if not result.passed
                        else "Review this warning before commit."
                    ),
                )
            )
        if SEVERITY_ORDER[sensor_report.max_severity] > SEVERITY_ORDER[risk_level]:
            risk_level = sensor_report.max_severity

    semantic_risk = str((semantic_review or {}).get("risk_level") or "")
    if semantic_risk in SEVERITY_ORDER and SEVERITY_ORDER[semantic_risk] > SEVERITY_ORDER[risk_level]:
        risk_level = semantic_risk
    if semantic_review:
        if semantic_review.get("status") != "completed":
            findings.append(
                ReviewFinding(
                    source="semantic",
                    severity=_severity_from_risk(str(semantic_review.get("risk_level") or "medium")),  # type: ignore[arg-type]
                    category=str(semantic_review.get("reason") or "semantic_unavailable"),
                    message=str(semantic_review.get("message") or semantic_review.get("summary") or ""),
                    recommendation=str(semantic_review.get("recommendation") or "manual_review"),
                )
            )
        for item in semantic_review.get("findings", []) or []:
            severity, file, message, recommendation = _semantic_finding_message(item)
            if not message:
                continue
            findings.append(
                ReviewFinding(
                    source="semantic",
                    severity=severity,  # type: ignore[arg-type]
                    category="semantic_review",
                    file=file or None,
                    message=message,
                    recommendation=recommendation,
                )
            )

    if not findings:
        findings.append(
            ReviewFinding(
                source="rules",
                severity="low",
                category="risk_pattern",
                message="No obvious high-risk pattern detected.",
                recommendation="Proceed with normal review.",
            )
        )

    recommendation = (
        "Commit is allowed after human review."
        if all(result.success for result in check_results)
        and (sensor_report is None or sensor_report.overall_passed)
        and str((semantic_review or {}).get("recommendation") or "").lower() != "block"
        else "Do not commit until validation passes."
    )
    if str((semantic_review or {}).get("recommendation") or "").lower() in {
        "manual_review",
        "review",
    }:
        recommendation = "Manual review is required before commit."
    if str((semantic_review or {}).get("recommendation") or "").lower() == "block":
        recommendation = "Do not commit until semantic review findings are resolved."

    return ReviewSummary(
        risk_level=risk_level,  # type: ignore[arg-type]
        findings=findings,
        recommendation=recommendation,
    )


def _spec_section(task: str, spec: Spec | None) -> list[str]:
    if not spec:
        return [
            "## 1. Task Summary",
            "",
            f"Task: {task}",
        ]
    return [
        "## 1. Task Summary",
        "",
        f"Task: {task}",
        "",
        f"Spec goal: {spec.goal}",
        "",
        "Acceptance criteria:",
        _list_or_none(spec.acceptance_criteria),
        "",
        "Constraints:",
        _list_or_none(spec.constraints),
    ]


def _checks_section(check_results: list[CheckResult]) -> list[str]:
    lines = [
        "## 3. Validation Results",
        "",
        "| Command | Result | Return Code |",
        "| --- | --- | ---: |",
    ]
    if not check_results:
        lines.append("| no checks configured | PASS | 0 |")
        return lines
    for result in check_results:
        lines.append(
            f"| {_escape_table(result.command)} | {_check_status(result)} | {result.returncode} |"
        )
    return lines


def _sensors_section(sensor_report: HarnessSensorReport | None) -> list[str]:
    lines = [
        "## 4. Sensor Report",
        "",
        "| Sensor | Status | Severity | Message |",
        "| --- | --- | --- | --- |",
    ]
    if not sensor_report:
        lines.append("| no sensor report | PASS | info | - |")
        return lines
    for result in sensor_report.results:
        lines.append(
            "| {name} | {status} | {severity} | {message} |".format(
                name=_escape_table(result.name),
                status=_sensor_status(result.passed, result.severity),
                severity=_escape_table(result.severity),
                message=_escape_table(result.message),
            )
        )
    return lines


def _changed_files_section(changed_files: list[str]) -> list[str]:
    lines = ["## 5. Changed Files", ""]
    groups = _changed_file_groups(changed_files)
    for group, files in groups.items():
        lines.append(f"{group}:")
        lines.append(_list_or_none(files))
        lines.append("")
    return lines


def _repair_section(repair_history: list[dict[str, str | int]] | None) -> list[str]:
    lines = [
        "## 7. Repair History",
        "",
        "| Round | Reason | Result |",
        "| ---: | --- | --- |",
    ]
    if not repair_history:
        lines.append("| 0 | none | no repair needed |")
        return lines
    for item in repair_history:
        lines.append(
            "| {round} | {reason} | {result} |".format(
                round=_escape_table(item.get("round", "")),
                reason=_escape_table(item.get("reason", "")),
                result=_escape_table(item.get("result", "")),
            )
        )
    return lines


def _semantic_section(semantic_review: dict | None) -> list[str]:
    lines = ["## 8. Semantic Review", ""]
    if not semantic_review:
        lines.append("- not run")
        return lines
    lines.extend(
        [
            f"- Status: {_escape_table(semantic_review.get('status', 'unknown'))}",
            f"- Risk Level: {_escape_table(semantic_review.get('risk_level', 'unknown'))}",
            f"- Summary: {_escape_table(semantic_review.get('summary', ''))}",
            f"- Task Alignment: {_escape_table(semantic_review.get('task_alignment', ''))}",
            f"- Test Coverage: {_escape_table(semantic_review.get('test_coverage_notes', ''))}",
            f"- Recommendation: {_escape_table(semantic_review.get('recommendation', ''))}",
            f"- Reason: {_escape_table(semantic_review.get('reason', ''))}",
            f"- Message: {_escape_table(semantic_review.get('message', ''))}",
            "- Findings:",
            _list_or_none(
                [
                    str(item.get("reason") or item.get("message") or item)
                    if isinstance(item, dict)
                    else str(item)
                    for item in semantic_review.get("findings", [])
                ]
            ),
        ]
    )
    return lines


def _structured_findings_section(review_summary: ReviewSummary) -> list[str]:
    lines = [
        "- Structured Findings:",
        "",
        "| Source | Severity | Category | File | Message | Recommendation |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for finding in review_summary.findings:
        lines.append(
            "| {source} | {severity} | {category} | {file} | {message} | {recommendation} |".format(
                source=_escape_table(finding.source),
                severity=_escape_table(finding.severity),
                category=_escape_table(finding.category),
                file=_escape_table(finding.file or ""),
                message=_escape_table(finding.message),
                recommendation=_escape_table(finding.recommendation),
            )
        )
    return lines


def _checklist(sensor_report: HarnessSensorReport | None) -> list[str]:
    items = [
        "- [ ] 任务目标是否已满足？",
        "- [ ] 是否新增或更新了必要测试？",
        "- [ ] required checks 是否全部通过？",
        "- [ ] 是否没有删除已有测试？",
        "- [ ] 是否没有修改敏感路径？",
        "- [ ] 是否没有引入不必要依赖？",
        "- [ ] diff 范围是否足够小？",
        "- [ ] 是否需要人工补充边界测试？",
    ]
    if not sensor_report:
        return items
    sensor_names = {
        result.name
        for result in sensor_report.results
        if not result.passed or result.severity in {"medium", "high"}
    }
    if "dependency_change" in sensor_names:
        items.append("- [ ] 检查依赖变更是否必要。")
    if "high_risk_path" in sensor_names:
        items.append("- [ ] 检查高风险路径变更是否合理。")
    if "missing_test_change" in sensor_names:
        items.append("- [ ] 检查测试覆盖不足问题。")
    return items


def build_review_report(
    task: str,
    branch: str,
    diff: str,
    check_results: list[CheckResult],
    sensor_report: HarnessSensorReport | None = None,
    *,
    spec: Spec | None = None,
    status: str = "",
    repair_round: int = 0,
    mini_runs: list[str] | None = None,
    run_dir: str | None = None,
    changed_files: list[str] | None = None,
    repair_history: list[dict[str, str | int]] | None = None,
    semantic_review: dict | None = None,
    review_summary: ReviewSummary | None = None,
) -> str:
    review_summary = review_summary or build_review_summary(
        diff=diff,
        check_results=check_results,
        sensor_report=sensor_report,
        changed_files=changed_files,
        semantic_review=semantic_review,
    )
    risk_level = review_summary.risk_level
    risks = [
        finding.message
        for finding in review_summary.findings
        if finding.source == "rules" and finding.category == "risk_pattern"
    ]
    changed_lines = len(diff.splitlines())
    risk_text = "\n".join(f"- {item}" for item in risks) or "- none"
    blocking_text = "- none"
    if sensor_report:
        blocking_text = "\n".join(f"- {reason}" for reason in sensor_report.blocking_reasons) or "- none"
    recommendation = review_summary.recommendation

    lines = [
        "# CodeFlow Review Report",
        "",
        *_spec_section(task, spec),
        "",
        "## 2. Execution Summary",
        "",
        f"- Branch: {branch}",
        f"- Status: {status or 'unknown'}",
        f"- Repair rounds: {repair_round}",
        f"- Mini runs: {len(mini_runs or [])}",
        f"- Run directory: {run_dir or '(not recorded)'}",
        "",
        *_checks_section(check_results),
        "",
        *_sensors_section(sensor_report),
        "",
        *_changed_files_section(changed_files or []),
        "## 6. Risk Assessment",
        "",
        f"- Risk Level: {risk_level}",
        "- Risk Notes:",
        risk_text,
        "- Blocking Reasons:",
        blocking_text,
        f"- Diff Size: {changed_lines} diff lines",
        "",
        *_structured_findings_section(review_summary),
        "",
        *_repair_section(repair_history),
        "",
        *_semantic_section(semantic_review),
        "",
        "## 9. Manual Review Checklist",
        "",
        *_checklist(sensor_report),
        "",
        "## 10. Recommendation",
        "",
        recommendation,
    ]
    return "\n".join(lines).strip()
