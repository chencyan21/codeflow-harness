from __future__ import annotations

from codeflow.harness.builtin_sensors import run_builtin_sensors, should_attempt_repair
from codeflow.models import CheckResult, HarnessPolicy, SensorContext


def _context(
    *,
    diff: str = "",
    changed_files: list[str] | None = None,
    policy: HarnessPolicy | None = None,
    checks: list[CheckResult] | None = None,
) -> SensorContext:
    return SensorContext(
        repo="/repo",
        task="task",
        diff=diff,
        changed_files=changed_files or [],
        policy=policy or HarnessPolicy(),
        check_results=checks or [],
    )


def test_forbidden_path_is_blocking_high() -> None:
    report = run_builtin_sensors(_context(changed_files=[".env"]))

    result = next(item for item in report.results if item.name == "forbidden_path")
    assert result.passed is False
    assert result.severity == "high"
    assert report.overall_passed is False


def test_allowed_path_blocks_changes_outside_allowlist() -> None:
    report = run_builtin_sensors(
        _context(
            diff="+ changed",
            changed_files=["app/service.py", "docs/notes.md"],
            policy=HarnessPolicy(allowed_paths=["app/", "tests/"]),
        )
    )

    result = next(item for item in report.results if item.name == "allowed_path")
    assert result.passed is False
    assert result.severity == "high"
    assert "docs/notes.md" in result.message


def test_forbidden_path_write_is_blocking_high() -> None:
    report = run_builtin_sensors(
        _context(
            diff="""
diff --git a/app/config.py b/app/config.py
--- /dev/null
+++ b/app/config.py
@@ -0,0 +1,4 @@
+ENV_FILE = ".env"
+
+def write_demo_api_key_to_env() -> None:
+    Path(ENV_FILE).write_text("DEMO_API_KEY=demo-key-12345\\n")
""",
            changed_files=["app/config.py"],
        )
    )

    result = next(item for item in report.results if item.name == "forbidden_path_write")
    assert result.passed is False
    assert result.severity == "high"
    assert ".env" in result.message
    assert should_attempt_repair(report) is False


def test_forbidden_path_read_reference_is_not_blocked_without_write() -> None:
    report = run_builtin_sensors(
        _context(
            diff="""
diff --git a/app/config.py b/app/config.py
--- /dev/null
+++ b/app/config.py
@@ -0,0 +1,4 @@
+ENV_FILE = ".env"
+
+def env_file_name() -> str:
+    return ENV_FILE
""",
            changed_files=["app/config.py"],
        )
    )

    result = next(item for item in report.results if item.name == "forbidden_path_write")
    assert result.passed is True
    assert result.severity == "info"


def test_test_deletion_is_blocking_high() -> None:
    report = run_builtin_sensors(
        _context(
            diff="""diff --git a/tests/test_app.py b/tests/test_app.py
--- a/tests/test_app.py
+++ b/tests/test_app.py
@@ -1,3 +1,1 @@
-def test_old():
-    assert True
""",
            changed_files=["tests/test_app.py"],
        )
    )

    result = next(item for item in report.results if item.name == "test_deletion")
    assert result.passed is False
    assert result.severity == "high"
    assert should_attempt_repair(report) is False


def test_test_assertion_rewrite_is_not_test_deletion() -> None:
    report = run_builtin_sensors(
        _context(
            diff="""diff --git a/test_buggy.py b/test_buggy.py
--- a/test_buggy.py
+++ b/test_buggy.py
@@ -1,2 +1,2 @@
 def test_flatten():
-    assert buggy.flatten([1]) == [1]
+    assert list(buggy.flatten([1])) == [1]
""",
            changed_files=["test_buggy.py"],
        )
    )

    result = next(item for item in report.results if item.name == "test_deletion")
    assert result.passed is True
    assert result.severity == "info"


def test_source_assert_removal_is_not_test_deletion() -> None:
    report = run_builtin_sensors(
        _context(
            diff="""diff --git a/app/service.py b/app/service.py
--- a/app/service.py
+++ b/app/service.py
@@ -1,2 +1 @@
-assert DEBUG
 print("ok")
""",
            changed_files=["app/service.py"],
        )
    )

    result = next(item for item in report.results if item.name == "test_deletion")
    assert result.passed is True


def test_missing_test_change_is_warning_when_required() -> None:
    report = run_builtin_sensors(
        _context(
            diff="+print('changed')",
            changed_files=["app/service.py"],
            policy=HarnessPolicy(require_test_change=True),
        )
    )

    result = next(item for item in report.results if item.name == "missing_test_change")
    assert result.passed is True
    assert result.severity == "medium"
    assert report.overall_passed is True


def test_no_change_is_repairable_failure() -> None:
    report = run_builtin_sensors(_context())

    result = next(item for item in report.results if item.name == "no_change")
    assert result.passed is False
    assert result.severity == "medium"
    assert should_attempt_repair(report) is True


def test_max_diff_over_limit_is_high_and_not_repaired() -> None:
    report = run_builtin_sensors(
        _context(
            diff="\n".join(f"+ line {idx}" for idx in range(5)),
            changed_files=["app/service.py"],
            policy=HarnessPolicy(max_diff_lines=2),
        )
    )

    result = next(item for item in report.results if item.name == "max_diff")
    assert result.passed is False
    assert result.severity == "high"
    assert should_attempt_repair(report) is False


def test_dependency_change_can_be_blocked_by_policy() -> None:
    report = run_builtin_sensors(
        _context(
            diff="+ dependency",
            changed_files=["pyproject.toml"],
            policy=HarnessPolicy(allow_dependency_change=False),
        )
    )

    result = next(item for item in report.results if item.name == "dependency_change")
    assert result.passed is False
    assert result.severity == "high"
    assert should_attempt_repair(report) is True


def test_secret_like_content_is_blocking_high() -> None:
    report = run_builtin_sensors(
        _context(
            diff='+DEMO_API_KEY = "sk-demo-1234567890"',
            changed_files=["app/env_utils.py"],
        )
    )

    result = next(item for item in report.results if item.name == "secret_like_content")
    assert result.passed is False
    assert result.severity == "high"
    assert result.details["matches"] == ['DEMO_API_KEY = "sk-***"']
    assert should_attempt_repair(report) is False


def test_failed_check_is_high_and_repairable() -> None:
    check = CheckResult(command="pytest -q", success=False, returncode=1, stdout="", stderr="x")
    report = run_builtin_sensors(
        _context(
            diff="+ changed",
            changed_files=["app/service.py"],
            checks=[check],
        )
    )

    result = next(item for item in report.results if item.name == "check_commands")
    assert result.passed is False
    assert result.severity == "high"
    assert should_attempt_repair(report) is True


def test_high_risk_path_becomes_high_when_commit_block_enabled() -> None:
    report = run_builtin_sensors(
        _context(
            diff="+ auth change",
            changed_files=["app/auth/service.py"],
            policy=HarnessPolicy(
                high_risk_paths=["app/auth/"],
                block_commit_on_high_risk=True,
            ),
        )
    )

    result = next(item for item in report.results if item.name == "high_risk_path")
    assert result.passed is True
    assert result.severity == "high"
    assert report.max_severity == "high"
