from __future__ import annotations

import json
import subprocess
from pathlib import Path

from codeflow.harness.observability import create_run_dir, update_run_index, write_json, write_text
from codeflow.server import ObservabilityServerConfig, handle_server_request
from codeflow.storage import FindingFilters, RunFilters, SQLiteRunStore


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, text=True, capture_output=True, check=True)


def _write_run(
    repo: Path,
    task: str,
    *,
    status: str = "checks_passed",
    risk_level: str = "low",
) -> Path:
    run_dir = create_run_dir(str(repo), task)
    write_json(
        run_dir / "state.json",
        {
            "run_id": run_dir.name,
            "task": task,
            "branch": f"ai/{task}",
            "status": status,
            "repair_round": 1 if status != "checks_passed" else 0,
            "risk_level": risk_level,
            "checks_passed": status == "checks_passed",
            "sensor_passed": status == "checks_passed",
        },
    )
    write_json(
        run_dir / "review_summary.json",
        {
            "risk_level": risk_level,
            "recommendation": "review",
            "findings": [
                {
                    "source": "rules",
                    "severity": risk_level,
                    "category": "risk_pattern",
                    "file": "app/auth.py",
                    "message": f"{risk_level} finding",
                    "recommendation": "review",
                }
            ],
        },
    )
    write_text(run_dir / "review_report.md", "# Report\n")
    update_run_index(str(repo), run_dir)
    return run_dir


def test_multi_repo_service_requires_token_and_filters_runs(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    _init_repo(repo_a)
    _init_repo(repo_b)
    _write_run(repo_a, "fix auth", status="checks_failed", risk_level="high")
    _write_run(repo_b, "fix docs", status="checks_passed", risk_level="low")
    config = ObservabilityServerConfig(repos=[str(repo_a), str(repo_b)], token="secret")

    status, _content_type, body = handle_server_request(config, "/api/runs")
    assert status == 401
    assert json.loads(body)["error"] == "unauthorized"

    status, _content_type, body = handle_server_request(
        config,
        "/api/runs?repo=repo-a&status=checks_failed",
        headers={"Authorization": "Bearer secret"},
    )

    assert status == 200
    runs = json.loads(body)
    assert len(runs) == 1
    assert runs[0]["repo"] == "repo-a"
    assert runs[0]["task"] == "fix auth"


def test_service_exposes_findings_trends_and_failures(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _write_run(repo, "fix auth", status="checks_failed", risk_level="high")
    config = ObservabilityServerConfig(repos=[str(repo)])

    status, _content_type, findings_body = handle_server_request(
        config,
        "/api/findings?severity=high",
    )
    assert status == 200
    findings = json.loads(findings_body)
    assert findings[0]["category"] == "risk_pattern"

    status, _content_type, trends_body = handle_server_request(config, "/api/trends")
    assert status == 200
    assert json.loads(trends_body)["daily"][0]["total_runs"] == 1

    status, _content_type, failures_body = handle_server_request(config, "/api/failures")
    assert status == 200
    assert json.loads(failures_body)[0]["status"] == "checks_failed"


def test_sqlite_store_syncs_jsonl_runs_and_findings(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _write_run(repo, "fix auth", status="checks_failed", risk_level="high")
    store = SQLiteRunStore(tmp_path / "codeflow.db")

    store.sync_from_repos([str(repo)])

    runs = store.list_runs(RunFilters(repo="repo", status="checks_failed"))
    assert len(runs) == 1
    assert runs[0]["task"] == "fix auth"
    assert store.summarize(RunFilters(repo="repo"))["failed_runs"][0]["task"] == "fix auth"
    findings = store.list_findings(FindingFilters(repo="repo", severity="high"))
    assert findings[0]["file"] == "app/auth.py"
