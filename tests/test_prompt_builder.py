from __future__ import annotations

from codeflow.models import CheckResult
from codeflow.prompt_builder import build_initial_prompt, build_repair_prompt
from codeflow.spec_builder import build_spec


def test_initial_prompt_contains_required_context() -> None:
    spec = build_spec("add priority")
    prompt = build_initial_prompt("add priority", spec, "Keep changes small.", ["pytest -q"])

    assert "add priority" in prompt
    assert "Keep changes small." in prompt
    assert "pytest -q" in prompt


def test_repair_prompt_contains_failure_logs() -> None:
    spec = build_spec("fix tests")
    result = CheckResult(
        command="pytest -q",
        success=False,
        returncode=1,
        stdout="failed",
        stderr="traceback",
    )

    prompt = build_repair_prompt("fix tests", spec, "rules", [result], ["pytest -q"])

    assert "pytest -q" in prompt
    assert "failed" in prompt
    assert "traceback" in prompt
