from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from codeflow.models import CodeFlowConfig
from codeflow.runner import run_codeflow


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


def _head(path: Path) -> str:
    return _run(["git", "rev-parse", "HEAD"], path).stdout.strip()


def _branch(path: Path) -> str:
    return _run(["git", "branch", "--show-current"], path).stdout.strip()


def _status(path: Path) -> str:
    return _run(["git", "status", "--short"], path).stdout.strip()


def test_dry_run_does_not_create_branch_or_call_mini(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_repo(tmp_path)
    original_branch = _branch(tmp_path)

    def fail_mini(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("mini should not be called during dry-run")

    monkeypatch.setattr("codeflow.runner.run_mini_agent", fail_mini)

    state = run_codeflow(CodeFlowConfig(repo=str(tmp_path), task="dry run", dry_run=True))

    assert state.status == "dry_run"
    assert state.commit_action == "not_requested"
    assert state.branch == ""
    assert _branch(tmp_path) == original_branch
    assert "dry run" in state.report


def test_no_commit_preserves_failed_check_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_repo(tmp_path)
    calls: list[str] = []

    def fake_mini(repo: str, prompt: str, **_kwargs: object) -> str:
        calls.append(prompt)
        return str(Path(repo) / ".git" / "fake.log")

    monkeypatch.setattr("codeflow.runner.run_mini_agent", fake_mini)

    state = run_codeflow(
        CodeFlowConfig(
            repo=str(tmp_path),
            task="fail checks",
            checks=[f'{sys.executable} -c "raise SystemExit(7)"'],
            max_repair_rounds=1,
            no_commit=True,
        )
    )

    assert state.status == "checks_failed"
    assert state.commit_action == "skipped"
    assert state.repair_round == 1
    assert len(calls) == 2
    assert state.check_results[0].returncode == 7
    assert state.run_dir is not None
    assert (Path(state.run_dir) / "state.json").exists()
    assert (Path(state.run_dir) / "repair_prompt_1.md").exists()


@pytest.mark.parametrize(
    ("decision", "expected_status", "expected_action", "dirty", "readme_changed", "new_file_exists"),
    [
        ("keep", "kept_uncommitted", "kept", True, True, True),
        ("rollback", "rolled_back", "rolled_back", False, False, False),
        ("commit", "committed", "committed", False, True, True),
    ],
)
def test_human_approval_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
    expected_status: str,
    expected_action: str,
    dirty: bool,
    readme_changed: bool,
    new_file_exists: bool,
) -> None:
    _init_repo(tmp_path)

    def fake_mini(repo: str, prompt: str, **_kwargs: object) -> str:
        root = Path(repo)
        (root / "README.md").write_text("hello\nchanged\n", encoding="utf-8")
        (root / "new_file.txt").write_text("new\n", encoding="utf-8")
        return str(root / ".git" / "fake.log")

    monkeypatch.setattr("codeflow.runner.run_mini_agent", fake_mini)
    monkeypatch.setattr("codeflow.runner.Prompt.ask", lambda *_args, **_kwargs: decision)

    state = run_codeflow(
        CodeFlowConfig(
            repo=str(tmp_path),
            task=f"human {decision}",
            checks=[f'{sys.executable} -c "print(1)"'],
        )
    )

    assert state.status == expected_status
    assert state.commit_action == expected_action
    assert bool(_status(tmp_path)) is dirty
    assert ("changed" in (tmp_path / "README.md").read_text(encoding="utf-8")) is readme_changed
    assert (tmp_path / "new_file.txt").exists() is new_file_exists


def test_commit_is_refused_when_checks_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_repo(tmp_path)
    before = _head(tmp_path)

    def fake_mini(repo: str, prompt: str, **_kwargs: object) -> str:
        Path(repo, "README.md").write_text("changed\n", encoding="utf-8")
        return str(Path(repo) / ".git" / "fake.log")

    monkeypatch.setattr("codeflow.runner.run_mini_agent", fake_mini)
    monkeypatch.setattr("codeflow.runner.Prompt.ask", lambda *_args, **_kwargs: "commit")

    state = run_codeflow(
        CodeFlowConfig(
            repo=str(tmp_path),
            task="refuse commit",
            checks=[f'{sys.executable} -c "raise SystemExit(9)"'],
            max_repair_rounds=0,
        )
    )

    assert state.status == "commit_refused_checks_failed"
    assert state.commit_action == "refused"
    assert _head(tmp_path) == before
    assert bool(_status(tmp_path)) is True


def test_governance_show_actions_then_keep(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_repo(tmp_path)
    actions = iter(["show-diff", "show-checks", "show-sensors", "show-files", "show-report", "keep"])

    def fake_mini(repo: str, prompt: str, **_kwargs: object) -> str:
        Path(repo, "README.md").write_text("changed\n", encoding="utf-8")
        return str(Path(repo) / ".git" / "fake.log")

    monkeypatch.setattr("codeflow.runner.run_mini_agent", fake_mini)
    monkeypatch.setattr("codeflow.runner.Prompt.ask", lambda *_args, **_kwargs: next(actions))

    state = run_codeflow(
        CodeFlowConfig(
            repo=str(tmp_path),
            task="show governance",
            checks=[f'{sys.executable} -c "print(1)"'],
        )
    )

    assert state.status == "kept_uncommitted"
    assert state.commit_action == "kept"


def test_high_risk_commit_requires_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_repo(tmp_path)
    policy_dir = tmp_path / ".codeflow"
    policy_dir.mkdir()
    (policy_dir / "codeflow.yaml").write_text(
        f"""
harness:
  required_checks:
    - {sys.executable} -c "print(1)"
  max_repair_rounds: 0
  high_risk_paths:
    - app/auth/
  governance:
    block_commit_on_high_risk: true
""",
        encoding="utf-8",
    )
    _run(["git", "add", ".codeflow/codeflow.yaml"], tmp_path)
    _run(
        [
            "git",
            "-c",
            "user.email=test@example.local",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "policy",
        ],
        tmp_path,
    )
    before = _head(tmp_path)

    def fake_mini(repo: str, prompt: str, **_kwargs: object) -> str:
        auth_dir = Path(repo) / "app" / "auth"
        auth_dir.mkdir(parents=True)
        (auth_dir / "service.py").write_text("TOKEN = 'placeholder'\n", encoding="utf-8")
        return str(Path(repo) / ".git" / "fake.log")

    monkeypatch.setattr("codeflow.runner.run_mini_agent", fake_mini)
    monkeypatch.setattr("codeflow.runner.Prompt.ask", lambda *_args, **_kwargs: "commit")

    state = run_codeflow(CodeFlowConfig(repo=str(tmp_path), task="touch auth"))

    assert state.status == "commit_refused_high_risk"
    assert state.commit_action == "refused"
    assert _head(tmp_path) == before
    assert bool(_status(tmp_path)) is True
