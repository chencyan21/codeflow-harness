from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from codeflow.cli import app
from codeflow.doctor import run_doctor
from codeflow.init_project import init_project


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr or result.stdout
    return result


def _init_repo(path: Path) -> None:
    _run(["git", "init"], path)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _run(["git", "add", "."], path)
    _run(
        [
            "git",
            "-c",
            "user.email=test@example.local",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "init",
        ],
        path,
    )


def test_init_project_writes_defaults_and_refuses_overwrite(tmp_path: Path) -> None:
    written = init_project(str(tmp_path))

    assert tmp_path / ".codeflow" / "project_rules.md" in written
    assert (tmp_path / ".codeflow" / "codeflow.yaml").exists()

    try:
        init_project(str(tmp_path))
    except RuntimeError as exc:
        assert "--force" in str(exc)
    else:
        raise AssertionError("expected init_project to refuse overwrite")


def test_init_cli_force(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["init", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.output

    forced = runner.invoke(app, ["init", "--repo", str(tmp_path), "--force"])
    assert forced.exit_code == 0, forced.output


def test_doctor_reports_structured_results(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    init_project(str(tmp_path))
    _run(["git", "add", ".codeflow"], tmp_path)
    _run(
        [
            "git",
            "-c",
            "user.email=test@example.local",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "codeflow config",
        ],
        tmp_path,
    )

    results = run_doctor(str(tmp_path), skip_checks=True, skip_llm=True)

    assert any(item["name"] == "Git repository" and item["ok"] for item in results)
    assert any(item["name"] == "Policy file" and item["ok"] for item in results)


def test_doctor_rejects_missing_python_script_command(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    monkeypatch.setenv("CODEFLOW_MINI_COMMAND", "python missing_mini.py")

    results = run_doctor(str(tmp_path), skip_checks=True, skip_llm=True)

    mini = next(item for item in results if item["name"] == "mini CLI")
    assert not mini["ok"]
    assert "Python script not found" in str(mini["message"])


def test_doctor_probes_configured_mini_command(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    script = tmp_path / "mini_probe.py"
    script.write_text("import sys\nraise SystemExit(3 if '--help' in sys.argv else 0)\n", encoding="utf-8")
    monkeypatch.setenv("CODEFLOW_MINI_COMMAND", f"{sys.executable} {script}")

    results = run_doctor(str(tmp_path), skip_checks=True, skip_llm=True)

    mini = next(item for item in results if item["name"] == "mini CLI")
    assert not mini["ok"]
    assert "exit code 3" in str(mini["message"])


def test_doctor_probes_env_wrapped_mini_command(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    script = tmp_path / "mini_probe.py"
    script.write_text(
        "import os, sys\n"
        "ok = '--help' in sys.argv and os.environ.get('MINI_PROBE') == '1'\n"
        "raise SystemExit(0 if ok else 5)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEFLOW_MINI_COMMAND", f"env MINI_PROBE=1 {sys.executable} {script}")

    results = run_doctor(str(tmp_path), skip_checks=True, skip_llm=True)

    mini = next(item for item in results if item["name"] == "mini CLI")
    assert mini["ok"]
    assert "command probe passed" in str(mini["message"])


def test_doctor_reports_shell_checks_disabled_by_policy(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    init_project(str(tmp_path))
    policy_path = tmp_path / ".codeflow" / "codeflow.yaml"
    policy_path.write_text(
        """
harness:
  required_checks:
    - "shell: echo ok"
  allow_shell_checks: false
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEFLOW_MINI_COMMAND", f"{sys.executable} -m minisweagent.run.mini")

    results = run_doctor(str(tmp_path), skip_checks=True, skip_llm=True)

    shell_check = next(item for item in results if str(item["name"]).startswith("Required check:"))
    assert not shell_check["ok"]
    assert "shell check disabled" in str(shell_check["message"])


def test_doctor_cli_json(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    init_project(str(tmp_path))
    _run(["git", "add", ".codeflow"], tmp_path)
    _run(
        [
            "git",
            "-c",
            "user.email=test@example.local",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "codeflow config",
        ],
        tmp_path,
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["doctor", "--repo", str(tmp_path), "--json", "--skip-checks", "--skip-llm"],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert any(item["name"] == "Git repository" for item in data)
