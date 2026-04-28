from __future__ import annotations

from pathlib import Path

from codeflow.test_gate import all_checks_passed, failed_checks, run_checks


def test_run_checks_collects_success_and_failure(tmp_path: Path) -> None:
    results = run_checks(str(tmp_path), ["python -c 'print(123)'", "python -c 'raise SystemExit(2)'"])

    assert results[0].success is True
    assert results[0].stdout.strip() == "123"
    assert results[1].success is False
    assert results[1].returncode == 2
    assert all_checks_passed(results) is False
    assert failed_checks(results) == [results[1]]
