from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codeflow.cli import app
from codeflow.harness.observability import (
    create_run_dir,
    export_run_dir,
    search_run_states,
    summarize_run_states,
    write_json,
    write_text,
)


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, text=True, capture_output=True, check=True)


def _write_run(
    repo: Path,
    task: str = "task",
    *,
    status: str = "checks_passed",
    risk_level: str = "low",
) -> Path:
    run_dir = create_run_dir(str(repo), task)
    state = {
        "run_id": run_dir.name,
        "task": task,
        "branch": "ai/task",
        "status": status,
        "commit_action": "skipped",
        "repair_round": 0,
        "risk_level": risk_level,
        "checks_passed": status == "checks_passed",
        "sensor_passed": status == "checks_passed",
    }
    write_json(run_dir / "state.json", state)
    write_text(run_dir / "review_report.md", "# Report\n")
    write_text(run_dir / "diff.patch", "+ changed\n")
    write_text(run_dir / "initial_prompt.md", "prompt\n")
    write_text(run_dir / "repair_prompt_1.md", "repair\n")
    write_text(run_dir / "prompt_0.txt", "mini prompt\n")
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
    assert "initial_prompt.md" not in names
    assert "repair_prompt_1.md" not in names
    assert "prompt_0.txt" not in names
    assert "mini_run_0.log" not in names
    assert "mini_run_0.trajectory.json" not in names

    with_prompts = export_run_dir(run_dir, tmp_path / "run-with-prompts.zip", include_prompts=True)
    with zipfile.ZipFile(with_prompts) as archive:
        prompt_names = set(archive.namelist())
    assert "initial_prompt.md" in prompt_names
    assert "repair_prompt_1.md" in prompt_names
    assert "prompt_0.txt" in prompt_names


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
    with zipfile.ZipFile(out) as archive:
        assert "initial_prompt.md" not in set(archive.namelist())

    out_with_prompts = tmp_path / "artifact-with-prompts.zip"
    exported_with_prompts = runner.invoke(
        app,
        [
            "export",
            "--repo",
            str(tmp_path),
            "--latest",
            "--out",
            str(out_with_prompts),
            "--include-prompts",
        ],
    )
    assert exported_with_prompts.exit_code == 0, exported_with_prompts.output
    with zipfile.ZipFile(out_with_prompts) as archive:
        assert "initial_prompt.md" in set(archive.namelist())

    summary = runner.invoke(app, ["summary", "--repo", str(tmp_path), "--json"])
    assert summary.exit_code == 0, summary.output
    summary_data = json.loads(summary.output)
    assert summary_data["total_runs"] == 1
    assert summary_data["daily_counts"]

    searched = runner.invoke(app, ["search", "--repo", str(tmp_path), "--query", "inspect", "--json"])
    assert searched.exit_code == 0, searched.output
    search_data = json.loads(searched.output)
    assert search_data[0]["run_id"] == run_dir.name

    dashboard = tmp_path / "dashboard.html"
    dashboard_result = runner.invoke(
        app,
        ["dashboard", "--repo", str(tmp_path), "--out", str(dashboard)],
    )
    assert dashboard_result.exit_code == 0, dashboard_result.output
    assert "CodeFlow Runs Dashboard" in dashboard.read_text(encoding="utf-8")


def test_search_and_summary_helpers_filter_runs(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write_run(tmp_path, task="first task", status="checks_failed", risk_level="high")
    _write_run(tmp_path, task="second task", status="checks_passed", risk_level="low")

    failed = search_run_states(str(tmp_path), status="checks_failed")
    summary = summarize_run_states(str(tmp_path))

    assert len(failed) == 1
    assert failed[0]["task"] == "first task"
    assert summary["total_runs"] == 2
    assert summary["status_counts"]["checks_failed"] == 1
    assert summary["status_counts"]["checks_passed"] == 1
    assert summary["failed_runs"][0]["task"] == "first task"
    assert summary["daily_counts"]


def test_inspect_no_run_is_clear(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["inspect", "--repo", str(tmp_path)])

    assert result.exit_code == 1
    assert "No CodeFlow runs found" in result.output
