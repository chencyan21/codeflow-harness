from __future__ import annotations

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
            "findings": ["Authentication path changed."],
            "recommendation": "block",
            "task_alignment": "unclear",
            "test_coverage_notes": "missing auth regression test",
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
    assert review["findings"] == ["Authentication path changed."]
