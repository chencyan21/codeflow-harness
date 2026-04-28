from __future__ import annotations

from codeflow.spec_builder import build_spec


def test_build_spec_contains_task() -> None:
    spec = build_spec("add due_date")

    assert spec.task_type == "coding_task"
    assert spec.goal == "add due_date"
    assert spec.acceptance_criteria
    assert spec.constraints
