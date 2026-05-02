from __future__ import annotations

from pathlib import Path

from codeflow.harness.policy import format_policy_for_prompt, load_harness_policy


def test_policy_falls_back_when_yaml_missing(tmp_path: Path) -> None:
    policy = load_harness_policy(str(tmp_path))

    assert policy.required_checks == ["pytest -q"]
    assert ".env" in policy.forbidden_paths
    assert policy.max_repair_rounds == 3
    assert policy.semantic_spec is False
    assert policy.semantic_review is False


def test_policy_loads_yaml_and_flattens_governance(tmp_path: Path) -> None:
    policy_dir = tmp_path / ".codeflow"
    policy_dir.mkdir()
    (policy_dir / "codeflow.yaml").write_text(
        """
harness:
  required_checks:
    - pytest -q
    - ruff check .
  max_repair_rounds: 1
  max_diff_lines: 42
  allowed_paths:
    - app/
  forbidden_paths:
    - secrets/
  high_risk_paths:
    - app/auth/
  require_test_change: true
  allow_dependency_change: false
  allow_delete_tests: false
  allow_shell_checks: true
  semantic_spec: false
  semantic_review: false
  require_semantic_review: true
  semantic_timeout_seconds: 12
  semantic_max_diff_chars: 1234
  semantic_fail_open: false
  semantic_required_for_paths:
    - app/auth/
  governance:
    block_commit_on_failed_checks: true
    block_commit_on_high_risk: true
    require_human_approval: true
    rerun_checks_before_commit: false
""",
        encoding="utf-8",
    )

    policy = load_harness_policy(str(tmp_path))

    assert policy.required_checks == ["pytest -q", "ruff check ."]
    assert policy.max_repair_rounds == 1
    assert policy.max_diff_lines == 42
    assert policy.allowed_paths == ["app/"]
    assert policy.forbidden_paths == ["secrets/"]
    assert policy.high_risk_paths == ["app/auth/"]
    assert policy.require_test_change is True
    assert policy.allow_dependency_change is False
    assert policy.allow_shell_checks is True
    assert policy.semantic_spec is False
    assert policy.semantic_review is False
    assert policy.require_semantic_review is True
    assert policy.semantic_timeout_seconds == 12
    assert policy.semantic_max_diff_chars == 1234
    assert policy.semantic_fail_open is False
    assert policy.semantic_required_for_paths == ["app/auth/"]
    assert policy.block_commit_on_high_risk is True
    assert policy.rerun_checks_before_commit is False


def test_cli_checks_and_repair_rounds_override_yaml(tmp_path: Path) -> None:
    policy_dir = tmp_path / ".codeflow"
    policy_dir.mkdir()
    (policy_dir / "codeflow.yaml").write_text(
        """
harness:
  required_checks:
    - pytest -q
  max_repair_rounds: 1
""",
        encoding="utf-8",
    )

    policy = load_harness_policy(
        str(tmp_path),
        cli_checks=["ruff check ."],
        cli_max_repair_rounds=2,
    )

    assert policy.required_checks == ["ruff check ."]
    assert policy.max_repair_rounds == 2


def test_policy_prompt_contains_harness_settings(tmp_path: Path) -> None:
    policy = load_harness_policy(str(tmp_path), cli_checks=["pytest -q", "ruff check ."])

    text = format_policy_for_prompt(policy)

    assert "Harness Policy:" in text
    assert "pytest -q" in text
    assert "ruff check ." in text
    assert "forbidden paths" in text
    assert "allow shell checks" in text
    assert "semantic review" in text
