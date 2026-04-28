from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass

from codeflow.harness.sensors import build_sensor_report
from codeflow.models import HarnessSensorReport, SensorContext, SensorResult

DEPENDENCY_FILES = {
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "poetry.lock",
    "uv.lock",
}

TEST_DELETE_PATTERNS = ("def test_", "assert", "pytest.raises")
SECRET_NAME_PATTERN = re.compile(r"(api[_-]?key|secret|token|password|credential)", re.IGNORECASE)
SECRET_VALUE_PATTERN = re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{6,}\b")
FORBIDDEN_PATH_WRITE_PATTERN = re.compile(
    r"\b(write|write_text|writelines|open|append|touch|set_key|dump|dumps)\b",
    re.IGNORECASE,
)

REPAIRABLE_SENSOR_NAMES = {
    "check_commands",
    "dependency_change",
    "missing_test_change",
    "no_change",
}


def _matches_path(path: str, pattern: str) -> bool:
    normalized = path.strip("/")
    normalized_pattern = pattern.strip("/")
    if pattern.endswith("/"):
        return normalized == normalized_pattern or normalized.startswith(f"{normalized_pattern}/")
    return normalized == normalized_pattern or fnmatch.fnmatch(normalized, normalized_pattern)


def _matching_paths(paths: list[str], patterns: list[str]) -> list[str]:
    return sorted({path for path in paths for pattern in patterns if _matches_path(path, pattern)})


def _tests_changed(paths: list[str]) -> bool:
    return any(path.startswith("tests/") or "/tests/" in path or path.endswith("_test.py") for path in paths)


def _business_code_changed(paths: list[str]) -> bool:
    return any(
        path.endswith(".py")
        and not path.startswith("tests/")
        and "/tests/" not in path
        and not path.endswith("_test.py")
        for path in paths
    )


def _added_diff_lines(diff: str) -> list[str]:
    return [
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]


def _forbidden_path_references(line: str, patterns: list[str]) -> list[str]:
    lower = line.lower()
    matches = []
    for pattern in patterns:
        normalized = pattern.strip("/").lower()
        if not normalized:
            continue
        candidates = [normalized]
        if "*" in normalized:
            candidates.append(normalized.replace("*", ""))
        if pattern.endswith("/"):
            candidates.append(f"{normalized}/")
        if any(candidate and candidate in lower for candidate in candidates):
            matches.append(pattern)
    return matches


def _redact_secret_line(line: str) -> str:
    return SECRET_VALUE_PATTERN.sub("sk-***", line)


@dataclass
class CheckCommandSensor:
    name: str = "check_commands"

    def run(self, context: SensorContext) -> SensorResult:
        failed = [result.command for result in context.check_results if not result.success]
        if failed:
            return SensorResult(
                name=self.name,
                passed=False,
                severity="high",
                message=f"Validation checks failed: {', '.join(failed)}",
                details={"failed_commands": failed},
            )
        return SensorResult(
            name=self.name,
            passed=True,
            severity="info",
            message="All validation checks passed.",
            details={"commands": [result.command for result in context.check_results]},
        )


@dataclass
class ForbiddenPathSensor:
    name: str = "forbidden_path"

    def run(self, context: SensorContext) -> SensorResult:
        matches = _matching_paths(context.changed_files, context.policy.forbidden_paths)
        if matches:
            return SensorResult(
                name=self.name,
                passed=False,
                severity="high",
                message=f"Forbidden paths modified: {', '.join(matches)}",
                details={"paths": matches},
            )
        return SensorResult(
            name=self.name,
            passed=True,
            severity="info",
            message="No forbidden path modifications detected.",
        )


@dataclass
class ForbiddenPathWriteSensor:
    name: str = "forbidden_path_write"

    def run(self, context: SensorContext) -> SensorResult:
        added_lines = _added_diff_lines(context.diff)
        forbidden_references = []
        write_references = []
        for line in added_lines:
            matches = _forbidden_path_references(line, context.policy.forbidden_paths)
            if matches:
                forbidden_references.append(
                    {"line": _redact_secret_line(line.strip()), "patterns": matches}
                )
            if FORBIDDEN_PATH_WRITE_PATTERN.search(line):
                write_references.append(_redact_secret_line(line.strip()))

        if forbidden_references and write_references:
            matched_patterns = sorted(
                {
                    pattern
                    for reference in forbidden_references
                    for pattern in reference["patterns"]
                }
            )
            return SensorResult(
                name=self.name,
                passed=False,
                severity="high",
                message=(
                    "Code added write-capable behavior targeting forbidden paths: "
                    f"{', '.join(matched_patterns)}"
                ),
                details={
                    "forbidden_references": forbidden_references[:20],
                    "write_references": write_references[:20],
                },
            )

        return SensorResult(
            name=self.name,
            passed=True,
            severity="info",
            message="No write-capable forbidden path behavior detected.",
        )


@dataclass
class AllowedPathSensor:
    name: str = "allowed_path"

    def run(self, context: SensorContext) -> SensorResult:
        if not context.policy.allowed_paths:
            return SensorResult(
                name=self.name,
                passed=True,
                severity="info",
                message="No allowed path restriction configured.",
            )

        outside = sorted(
            path
            for path in context.changed_files
            if not any(_matches_path(path, pattern) for pattern in context.policy.allowed_paths)
        )
        if outside:
            return SensorResult(
                name=self.name,
                passed=False,
                severity="high",
                message=f"Changes outside allowed paths: {', '.join(outside)}",
                details={"paths": outside, "allowed_paths": context.policy.allowed_paths},
            )
        return SensorResult(
            name=self.name,
            passed=True,
            severity="info",
            message="All changed files are within allowed paths.",
        )


@dataclass
class HighRiskPathSensor:
    name: str = "high_risk_path"

    def run(self, context: SensorContext) -> SensorResult:
        matches = _matching_paths(context.changed_files, context.policy.high_risk_paths)
        if matches:
            severity = "high" if context.policy.block_commit_on_high_risk else "medium"
            return SensorResult(
                name=self.name,
                passed=True,
                severity=severity,
                message=f"High-risk paths modified: {', '.join(matches)}",
                details={"paths": matches},
            )
        return SensorResult(
            name=self.name,
            passed=True,
            severity="info",
            message="No configured high-risk path modifications detected.",
        )


@dataclass
class TestDeletionSensor:
    name: str = "test_deletion"

    def run(self, context: SensorContext) -> SensorResult:
        if context.policy.allow_delete_tests:
            return SensorResult(
                name=self.name,
                passed=True,
                severity="info",
                message="Test deletion is allowed by policy.",
            )

        deleted_lines = []
        for line in context.diff.splitlines():
            if not line.startswith("-") or line.startswith("---"):
                continue
            if any(pattern in line for pattern in TEST_DELETE_PATTERNS):
                deleted_lines.append(line[1:].strip())

        if deleted_lines:
            return SensorResult(
                name=self.name,
                passed=False,
                severity="high",
                message="Test deletion detected in diff.",
                details={"deleted_lines": deleted_lines[:20]},
            )
        return SensorResult(
            name=self.name,
            passed=True,
            severity="info",
            message="No test deletion detected.",
        )


@dataclass
class MissingTestChangeSensor:
    name: str = "missing_test_change"

    def run(self, context: SensorContext) -> SensorResult:
        if (
            context.policy.require_test_change
            and _business_code_changed(context.changed_files)
            and not _tests_changed(context.changed_files)
        ):
            return SensorResult(
                name=self.name,
                passed=True,
                severity="medium",
                message="功能代码变更但没有测试变更。",
                details={"changed_files": context.changed_files},
            )
        return SensorResult(
            name=self.name,
            passed=True,
            severity="info",
            message="Test change policy satisfied.",
        )


@dataclass
class DependencyChangeSensor:
    name: str = "dependency_change"

    def run(self, context: SensorContext) -> SensorResult:
        dependency_files = sorted(path for path in context.changed_files if path in DEPENDENCY_FILES)
        if dependency_files and not context.policy.allow_dependency_change:
            return SensorResult(
                name=self.name,
                passed=False,
                severity="high",
                message=f"Dependency files modified but policy disallows it: {', '.join(dependency_files)}",
                details={"files": dependency_files},
            )
        if dependency_files:
            return SensorResult(
                name=self.name,
                passed=True,
                severity="medium",
                message=f"Dependency files modified: {', '.join(dependency_files)}",
                details={"files": dependency_files},
            )
        return SensorResult(
            name=self.name,
            passed=True,
            severity="info",
            message="No dependency file changes detected.",
        )


@dataclass
class SecretLikeContentSensor:
    name: str = "secret_like_content"

    def run(self, context: SensorContext) -> SensorResult:
        matches = []
        for line in context.diff.splitlines():
            if not line.startswith("+") or line.startswith("+++"):
                continue
            content = line[1:]
            if SECRET_VALUE_PATTERN.search(content) and SECRET_NAME_PATTERN.search(content):
                matches.append(_redact_secret_line(content.strip()))

        if matches:
            return SensorResult(
                name=self.name,
                passed=False,
                severity="high",
                message="Secret-like content was added to the diff.",
                details={"matches": matches[:20]},
            )
        return SensorResult(
            name=self.name,
            passed=True,
            severity="info",
            message="No secret-like content detected.",
        )


@dataclass
class MaxDiffSensor:
    name: str = "max_diff"

    def run(self, context: SensorContext) -> SensorResult:
        diff_lines = len(context.diff.splitlines())
        if diff_lines > context.policy.max_diff_lines:
            return SensorResult(
                name=self.name,
                passed=False,
                severity="high",
                message=f"Diff is too large: {diff_lines} lines > {context.policy.max_diff_lines}.",
                details={"diff_lines": diff_lines, "max_diff_lines": context.policy.max_diff_lines},
            )
        return SensorResult(
            name=self.name,
            passed=True,
            severity="info",
            message=f"Diff size is within policy: {diff_lines} lines.",
            details={"diff_lines": diff_lines, "max_diff_lines": context.policy.max_diff_lines},
        )


@dataclass
class NoChangeSensor:
    name: str = "no_change"

    def run(self, context: SensorContext) -> SensorResult:
        if not context.diff.strip() and not context.changed_files:
            return SensorResult(
                name=self.name,
                passed=False,
                severity="medium",
                message="没有检测到代码修改，不能把原有测试通过误判为任务成功。",
            )
        return SensorResult(
            name=self.name,
            passed=True,
            severity="info",
            message="Repository changes detected.",
            details={"changed_files": context.changed_files},
        )


BUILTIN_SENSORS = [
    CheckCommandSensor(),
    ForbiddenPathSensor(),
    ForbiddenPathWriteSensor(),
    AllowedPathSensor(),
    HighRiskPathSensor(),
    TestDeletionSensor(),
    MissingTestChangeSensor(),
    DependencyChangeSensor(),
    SecretLikeContentSensor(),
    MaxDiffSensor(),
    NoChangeSensor(),
]


def run_builtin_sensors(context: SensorContext) -> HarnessSensorReport:
    return build_sensor_report([sensor.run(context) for sensor in BUILTIN_SENSORS])


def should_attempt_repair(report: HarnessSensorReport) -> bool:
    failed = [result.name for result in report.results if not result.passed]
    return bool(failed) and all(name in REPAIRABLE_SENSOR_NAMES for name in failed)
