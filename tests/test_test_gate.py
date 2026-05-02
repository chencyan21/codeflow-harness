from __future__ import annotations

import shlex
import sys
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


def test_run_checks_does_not_use_shell_by_default(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    command = (
        f"{shlex.quote(sys.executable)} -c "
        f"'import pathlib, sys; pathlib.Path(sys.argv[1]).write_text(\"ok\")' "
        f"{shlex.quote(str(marker))} && {shlex.quote(sys.executable)} -c 'raise SystemExit(7)'"
    )

    result = run_checks(str(tmp_path), [command])[0]

    assert result.success is True
    assert marker.read_text(encoding="utf-8") == "ok"


def test_run_checks_requires_explicit_shell_prefix(tmp_path: Path) -> None:
    marker = tmp_path / "shell-marker.txt"

    result = run_checks(str(tmp_path), [f"shell: printf ok > {shlex.quote(str(marker))}"])[0]

    assert result.success is True
    assert marker.read_text(encoding="utf-8") == "ok"
