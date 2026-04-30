from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "benchmark" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from prepare_quixbugs import prepare_quixbugs  # noqa: E402
from prepare_swebench import task_from_record, write_jsonl  # noqa: E402
from prepare_bugsinpy import discover_candidates, prepare_bugsinpy  # noqa: E402
from _harness_bench_common import load_tasks, prepare_workspace  # noqa: E402
import run_eval  # noqa: E402


def test_prepare_quixbugs_generates_pytest_workspace(tmp_path: Path) -> None:
    source = tmp_path / "quixbugs"
    programs = source / "python_programs"
    cases = source / "json_testcases"
    programs.mkdir(parents=True)
    cases.mkdir()
    (programs / "sample.py").write_text(
        "def sample(value):\n"
        "    return value + 1\n",
        encoding="utf-8",
    )
    (cases / "sample.json").write_text(
        "[[[1], 2], [[2], 3]]",
        encoding="utf-8",
    )

    out = tmp_path / "generated"
    tasks_out = tmp_path / "tasks.yaml"
    tasks = prepare_quixbugs(source=source, out=out, tasks_out=tasks_out, limit=None, clean=True)

    assert [task["id"] for task in tasks] == ["quixbugs_sample"]
    assert yaml.safe_load(tasks_out.read_text(encoding="utf-8")) == tasks

    workspace = out / "sample"
    assert (workspace / "buggy.py").exists()
    assert (workspace / "test_buggy.py").exists()
    assert (workspace / ".git").exists()

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=workspace,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_swebench_task_jsonl_can_be_loaded(tmp_path: Path) -> None:
    record = {
        "instance_id": "django__django-12345",
        "repo": "django/django",
        "base_commit": "abc123",
        "problem_statement": "Fix the regression.",
        "FAIL_TO_PASS": '["tests/test_regression.py::test_case"]',
        "PASS_TO_PASS": [],
    }
    task = task_from_record(
        record,
        dataset="princeton-nlp/SWE-bench_Lite",
        workspace_root=tmp_path / "workspaces",
    )
    tasks_path = tmp_path / "swebench_lite_subset.jsonl"
    write_jsonl(tasks_path, [task])

    loaded = load_tasks(tasks_path)

    assert loaded == [task]
    assert loaded[0]["dataset"] == "swebench_lite"
    assert loaded[0]["checks"] == ["python -m pytest tests/test_regression.py::test_case -q"]


def test_swebench_task_can_prefix_checks(tmp_path: Path) -> None:
    record = {
        "instance_id": "django__django-12345",
        "repo": "django/django",
        "base_commit": "abc123",
        "problem_statement": "Fix the regression.",
        "FAIL_TO_PASS": '["tests/test_regression.py::test_case"]',
        "PASS_TO_PASS": [],
    }

    task = task_from_record(
        record,
        dataset="princeton-nlp/SWE-bench_Lite",
        workspace_root=tmp_path / "workspaces",
        check_prefix="uv run --no-project --python 3.11 --with pytest",
    )

    assert task["checks"] == [
        "uv run --no-project --python 3.11 --with pytest "
        "python -m pytest tests/test_regression.py::test_case -q"
    ]


def test_prepare_bugsinpy_generates_task_yaml(tmp_path: Path) -> None:
    source = tmp_path / "bugsinpy"
    bug_dir = source / "projects" / "demo" / "bugs" / "1"
    bug_dir.mkdir(parents=True)
    (bug_dir / "bug.info").write_text(
        "python_version: 3.10\n"
        "test_file: tests/test_demo.py\n"
        "test_function: test_regression\n",
        encoding="utf-8",
    )

    candidates = discover_candidates(source)

    assert len(candidates) == 1
    assert candidates[0].project == "demo"
    assert candidates[0].bug_id == "1"

    tasks_out = tmp_path / "bugsinpy_subset.yaml"
    tasks = prepare_bugsinpy(
        source=source,
        out=tmp_path / "generated",
        tasks_out=tasks_out,
        project=None,
        bug_id=None,
        limit=None,
        prepare_workspaces=False,
        checkout_command=None,
        clean=True,
    )

    assert yaml.safe_load(tasks_out.read_text(encoding="utf-8")) == tasks
    assert tasks[0]["id"] == "bugsinpy_demo_1"
    assert tasks[0]["checks"] == ["pytest tests/test_demo.py::test_regression -q"]
    assert tasks[0]["metadata"]["python_version"] == "3.10"


def test_prepare_bugsinpy_prefers_run_test_and_can_wrap_uv_python(tmp_path: Path) -> None:
    source = tmp_path / "bugsinpy"
    bug_dir = source / "projects" / "demo" / "bugs" / "1"
    bug_dir.mkdir(parents=True)
    (bug_dir / "bug.info").write_text(
        "python_version: 3.7.4\n"
        "test_file: tests/test_demo.py\n",
        encoding="utf-8",
    )
    (bug_dir / "run_test.sh").write_text(
        "python -m unittest -q tests.test_demo.TestDemo.test_regression\n",
        encoding="utf-8",
    )

    tasks = prepare_bugsinpy(
        source=source,
        out=tmp_path / "generated",
        tasks_out=tmp_path / "bugsinpy_subset.yaml",
        project=None,
        bug_id=None,
        limit=None,
        prepare_workspaces=False,
        checkout_command=None,
        clean=True,
        uv_python_checks=True,
        python_version_override="3.8",
        uv_with=None,
    )

    assert tasks[0]["checks"] == [
        "uv run --no-project --python 3.8 "
        "python -m unittest -q tests.test_demo.TestDemo.test_regression"
    ]


def test_checks_only_does_not_call_mini_agent(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "buggy.py").write_text("VALUE = 1\n", encoding="utf-8")
    task = {
        "id": "checks_only_sample",
        "source_repo": str(source),
        "task": "Run validation only.",
        "checks": [f"{sys.executable} -c \"print('ok')\""],
    }
    workspace = prepare_workspace(task, workspaces_dir=tmp_path / "workspaces", clean=True)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("checks_only must not call mini-swe-agent")

    monkeypatch.setattr(run_eval, "run_mini_agent", fail_if_called)

    state = run_eval._run_task(
        task=task,
        workspace=workspace,
        method="checks_only",
        model=None,
        max_repair_rounds=None,
    )

    assert state.status == "checks_passed"
    assert state.mini_runs == []
    assert state.branch == "baseline"
    assert state.diff == ""
