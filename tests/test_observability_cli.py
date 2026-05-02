from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codeflow.cli import app
from codeflow.harness.observability import create_run_dir, export_run_dir, write_json, write_text


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, text=True, capture_output=True, check=True)


def _write_run(repo: Path, task: str = "task") -> Path:
    run_dir = create_run_dir(str(repo), task)
    state = {
        "run_id": run_dir.name,
        "task": task,
        "branch": "ai/task",
        "status": "checks_passed",
        "commit_action": "skipped",
        "repair_round": 0,
        "risk_level": "low",
        "checks_passed": True,
        "sensor_passed": True,
    }
    write_json(run_dir / "state.json", state)
    write_text(run_dir / "review_report.md", "# Report\n")
    write_text(run_dir / "diff.patch", "+ changed\n")
    write_text(run_dir / "initial_prompt.md", "prompt\n")
    write_json(run_dir / "checks_round_0.json", [])
    write_json(run_dir / "sensor_report_round_0.json", {})
    write_text(run_dir / "mini_run_0.log", "log\n")
    write_text(run_dir / "mini_run_0.trajectory.json", "{}\n")
    return run_dir


def test_observability_creates_and_exports_run(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    run_dir = _write_run(tmp_path)
    out = tmp_path / "run.zip"

    exported = export_run_dir(run_dir, out)

    assert exported == out
    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())
    assert "state.json" in names
    assert "review_report.md" in names
    assert "mini_run_0.log" not in names
    assert "mini_run_0.trajectory.json" not in names


def test_export_rejects_output_inside_run_dir(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    run_dir = _write_run(tmp_path)

    with pytest.raises(RuntimeError, match="outside the run directory"):
        export_run_dir(run_dir, run_dir / "run.zip")


def test_inspect_report_export_cli(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    run_dir = _write_run(tmp_path, task="inspect task")
    runner = CliRunner()

    inspected = runner.invoke(app, ["inspect", "--repo", str(tmp_path), "--json"])
    assert inspected.exit_code == 0, inspected.output
    data = json.loads(inspected.output)
    assert data["run_id"] == run_dir.name

    reported = runner.invoke(app, ["report", "--repo", str(tmp_path), "--latest"])
    assert reported.exit_code == 0, reported.output
    assert "# Report" in reported.output

    out = tmp_path / "artifact.zip"
    exported = runner.invoke(
        app,
        ["export", "--repo", str(tmp_path), "--latest", "--out", str(out)],
    )
    assert exported.exit_code == 0, exported.output
    assert out.exists()


def test_inspect_no_run_is_clear(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["inspect", "--repo", str(tmp_path)])

    assert result.exit_code == 1
    assert "No CodeFlow runs found" in result.output
