from __future__ import annotations

from codeflow.diff_reviewer import build_review_report, score_risk
from codeflow.models import CheckResult


def test_score_risk_detects_high_risk_keywords() -> None:
    level, risks = score_risk("+ password = 'x'")

    assert level == "high"
    assert any("password" in risk for risk in risks)


def test_score_risk_matches_keywords_on_token_boundaries() -> None:
    level, risks = score_risk("+ heapq.heapify(heap)\n+ value = api_key")

    assert level == "medium"
    assert risks == ["Medium-risk keyword found in diff: api"]


def test_score_risk_does_not_match_keyword_inside_identifier() -> None:
    level, risks = score_risk("+ heapq.heapify(heap)\n+ heapq.heappushpop(heap, x)")

    assert level == "low"
    assert risks == ["No obvious high-risk pattern detected."]


def test_build_review_report_mentions_validation() -> None:
    result = CheckResult(command="pytest -q", success=True, returncode=0, stdout="", stderr="")

    report = build_review_report("task", "ai/task", "+ change", [result])

    assert "# CodeFlow Review Report" in report
    assert "pytest -q: PASS" in report
    assert "ai/task" in report
