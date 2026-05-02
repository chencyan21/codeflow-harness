from __future__ import annotations

import json

from codeflow.models import CheckResult, HarnessPolicy
from codeflow.semantic import enhance_spec_with_semantics, review_diff_with_semantics
from codeflow.spec_builder import build_spec


def test_enhance_spec_with_semantics_merges_llm_fields() -> None:
    base = build_spec("add search")

    def fake_client(kind: str, _payload: dict):
        assert kind == "spec"
        return {
            "task_type": "coding_task",
            "goal": "add searchable index",
            "acceptance_criteria": ["Search handles empty queries."],
            "constraints": ["Do not change public API names."],
            "semantic_notes": ["LLM refined spec."],
        }

    spec, metadata = enhance_spec_with_semantics(
        task="add search",
        rules="",
        policy=HarnessPolicy(semantic_spec=True),
        base_spec=base,
        client=fake_client,
    )

    assert metadata and metadata["status"] == "completed"
    assert spec.goal == "add searchable index"
    assert "Search handles empty queries." in spec.acceptance_criteria
    assert "Do not change public API names." in spec.constraints
    assert spec.semantic_notes == ["LLM refined spec."]


def test_review_diff_with_semantics_normalizes_result() -> None:
    def fake_client(kind: str, _payload: dict):
        assert kind == "review"
        return {
            "risk_level": "HIGH",
            "summary": "Auth behavior changed.",
            "findings": [
                {
                    "severity": "high",
                    "file": "app/auth/login.py",
                    "reason": "Authentication path changed.",
                    "suggested_action": "Add an auth regression test.",
                }
            ],
            "recommendation": "block",
            "task_alignment": "partial",
            "test_coverage": {"level": "weak", "notes": "missing auth regression test"},
            "behavioral_risks": ["login flow changed"],
            "security_risks": ["auth bypass possible"],
            "data_migration_risks": [],
        }

    review = review_diff_with_semantics(
        task="change login",
        diff="+ return True",
        changed_files=["app/auth/login.py"],
        check_results=[CheckResult(command="pytest -q", success=True, returncode=0, stdout="", stderr="")],
        sensor_report=None,
        policy=HarnessPolicy(semantic_review=True),
        client=fake_client,
    )

    assert review
    assert review["status"] == "completed"
    assert review["risk_level"] == "high"
    assert review["findings"][0]["reason"] == "Authentication path changed."
    assert review["test_coverage"]["level"] == "weak"
    assert review["security_risks"] == ["auth bypass possible"]


def test_review_diff_with_semantics_records_invalid_json_from_client() -> None:
    def fake_client(_kind: str, _payload: dict):
        raise json.JSONDecodeError("bad json", "not-json", 0)

    review = review_diff_with_semantics(
        task="change login",
        diff="+ return True",
        changed_files=["app/auth/login.py"],
        check_results=[],
        sensor_report=None,
        policy=HarnessPolicy(semantic_review=True, semantic_fail_open=False),
        client=fake_client,
    )

    assert review
    assert review["status"] == "unavailable"
    assert review["reason"] == "invalid_json"
    assert review["risk_level"] == "high"


def test_review_diff_with_semantics_records_api_error_from_client() -> None:
    def fake_client(_kind: str, _payload: dict):
        raise RuntimeError("provider unavailable")

    review = review_diff_with_semantics(
        task="change login",
        diff="+ return True",
        changed_files=[],
        check_results=[],
        sensor_report=None,
        policy=HarnessPolicy(semantic_review=True),
        client=fake_client,
    )

    assert review
    assert review["status"] == "unavailable"
    assert review["reason"] == "api_error"
    assert review["risk_level"] == "medium"


def test_review_diff_with_semantics_runs_for_required_paths_without_global_review() -> None:
    def fake_client(kind: str, payload: dict):
        assert kind == "review"
        assert payload["changed_files"] == ["app/auth/login.py"]
        return {"risk_level": "low", "summary": "ok", "recommendation": "commit"}

    review = review_diff_with_semantics(
        task="change login",
        diff="+ return True",
        changed_files=["app/auth/login.py"],
        check_results=[],
        sensor_report=None,
        policy=HarnessPolicy(semantic_required_for_paths=["app/auth/"]),
        client=fake_client,
    )

    assert review
    assert review["status"] == "completed"
    assert review["required_by_path"] is True
