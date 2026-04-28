from __future__ import annotations

from codeflow.diff_reviewer import build_review_report, score_risk
from codeflow.models import CheckResult


def test_score_risk_detects_high_risk_keywords() -> None:
    level, risks = score_risk("+ password = 'x'")

    assert level == "high"
    assert any("password" in risk for risk in risks)


def test_build_review_report_mentions_validation() -> None:
    result = CheckResult(command="pytest -q", success=True, returncode=0, stdout="", stderr="")

    report = build_review_report("task", "ai/task", "+ change", [result])

    assert "# CodeFlow Review Report" in report
    assert "pytest -q: PASS" in report
    assert "ai/task" in report
