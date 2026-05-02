from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from codeflow.models import HarnessPolicy


def _flatten_policy_data(data: dict[str, Any]) -> dict[str, Any]:
    harness = data.get("harness", data) or {}
    if not isinstance(harness, dict):
        return {}

    flattened = {key: value for key, value in harness.items() if key != "governance"}
    governance = harness.get("governance") or {}
    if isinstance(governance, dict):
        flattened.update(governance)
    return flattened


def load_harness_policy(
    repo: str,
    *,
    cli_checks: list[str] | None = None,
    cli_max_repair_rounds: int | None = None,
) -> HarnessPolicy:
    path = Path(repo) / ".codeflow" / "codeflow.yaml"
    data: dict[str, Any] = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise RuntimeError(f"Invalid harness policy file: {path}")
        data = _flatten_policy_data(loaded)

    policy = HarnessPolicy.model_validate(data)

    if cli_checks:
        policy.required_checks = cli_checks
    if cli_max_repair_rounds is not None:
        policy.max_repair_rounds = cli_max_repair_rounds

    return policy


def format_policy_for_prompt(policy: HarnessPolicy) -> str:
    return "\n".join(
        [
            "Harness Policy:",
            f"- required checks: {', '.join(policy.required_checks) or '(none)'}",
            f"- max repair rounds: {policy.max_repair_rounds}",
            f"- max diff lines: {policy.max_diff_lines}",
            f"- allowed paths: {', '.join(policy.allowed_paths) or '(not restricted)'}",
            f"- forbidden paths: {', '.join(policy.forbidden_paths) or '(none)'}",
            f"- high risk paths: {', '.join(policy.high_risk_paths) or '(none)'}",
            f"- require test change: {policy.require_test_change}",
            f"- allow dependency change: {policy.allow_dependency_change}",
            f"- allow delete tests: {policy.allow_delete_tests}",
            f"- allow shell checks: {policy.allow_shell_checks}",
            f"- semantic spec: {policy.semantic_spec}",
            f"- semantic review: {policy.semantic_review}",
            f"- require semantic review: {policy.require_semantic_review}",
            f"- semantic timeout seconds: {policy.semantic_timeout_seconds:g}",
            f"- semantic max diff chars: {policy.semantic_max_diff_chars}",
            f"- semantic fail open: {policy.semantic_fail_open}",
            f"- semantic required paths: {', '.join(policy.semantic_required_for_paths) or '(none)'}",
            f"- block commit on failed checks: {policy.block_commit_on_failed_checks}",
            f"- block commit on high risk: {policy.block_commit_on_high_risk}",
            f"- rerun checks before commit: {policy.rerun_checks_before_commit}",
        ]
    )
