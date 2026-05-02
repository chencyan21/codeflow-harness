from __future__ import annotations

from codeflow.diff_reviewer import build_review_report, score_risk
from codeflow.models import CheckResult


def test_score_risk_detects_high_risk_keywords() -> None:
    level, risks = score_risk("+ password = 'x'")

    assert level == "high"
    assert any("password" in risk for risk in risks)


def test_score_risk_detects_specific_token_names() -> None:
    level, risks = score_risk("+ access_token = 'x'")

    assert level == "high"
    assert any("access_token" in risk for risk in risks)


def test_score_risk_matches_keywords_on_token_boundaries() -> None:
    level, risks = score_risk("+ heapq.heapify(heap)\n+ value = api_key")

    assert level == "medium"
    assert risks == ["Medium-risk keyword found in diff: api"]


def test_score_risk_does_not_match_keyword_inside_identifier() -> None:
    level, risks = score_risk("+ heapq.heapify(heap)\n+ heapq.heappushpop(heap, x)")

    assert level == "low"
    assert risks == ["No obvious high-risk pattern detected."]


def test_score_risk_does_not_treat_parser_token_as_secret() -> None:
    level, risks = score_risk("+ opstack.append(token)\n+ token = tokens.pop()")

    assert level == "low"
    assert risks == ["No obvious high-risk pattern detected."]


def test_score_risk_uses_changed_file_paths() -> None:
    level, risks = score_risk("+ return True", changed_files=["app/auth/session.py"])

    assert level == "high"
    assert "High-risk path changed: app/auth/session.py" in risks


def test_score_risk_detects_destructive_added_behavior() -> None:
    level, risks = score_risk("+ shutil.rmtree(workspace)")

    assert level == "high"
    assert "recursive deletion call added: shutil.rmtree" in risks


def test_score_risk_marks_ci_workflow_changes_medium() -> None:
    level, risks = score_risk("+ run: pytest -q", changed_files=[".github/workflows/ci.yml"])

    assert level == "medium"
    assert "Medium-risk path changed: .github/workflows/ci.yml" in risks


def test_build_review_report_mentions_validation() -> None:
    result = CheckResult(command="pytest -q", success=True, returncode=0, stdout="", stderr="")

    report = build_review_report("task", "ai/task", "+ change", [result])

    assert "# CodeFlow Review Report" in report
    assert "| pytest -q | PASS | 0 |" in report
    assert "ai/task" in report
    assert "## 8. Manual Review Checklist" in report
