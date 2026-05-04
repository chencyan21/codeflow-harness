from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "benchmark" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from prepare_quixbugs import prepare_quixbugs  # noqa: E402
from prepare_swebench import ASTROPY_BUILD_EXT_COMMAND, task_from_record, write_jsonl  # noqa: E402
from prepare_bugsinpy import discover_candidates, prepare_bugsinpy  # noqa: E402
from _harness_bench_common import load_tasks, prepare_workspace  # noqa: E402
from summarize_results import build_markdown_report, load_result_files, make_portable_records  # noqa: E402
from prepare_all_benchmark_data import build_status_markdown  # noqa: E402
from compare_runs import build_comparison  # noqa: E402
from build_trend_report import build_trend_report  # noqa: E402
from archive_run import archive_run  # noqa: E402
from codeflow.git_guard import get_changed_files  # noqa: E402
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


def test_swebench_astropy_task_includes_setup_recipe(tmp_path: Path) -> None:
    record = {
        "instance_id": "astropy__astropy-12907",
        "repo": "astropy/astropy",
        "base_commit": "abc123",
        "problem_statement": "Fix the regression.",
        "FAIL_TO_PASS": [],
        "PASS_TO_PASS": [],
    }

    task = task_from_record(
        record,
        dataset="princeton-nlp/SWE-bench_Lite",
        workspace_root=tmp_path / "workspaces",
    )

    assert task["setup_commands"] == [ASTROPY_BUILD_EXT_COMMAND]
    assert task["metadata"]["setup_recipe"] == "auto"


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
    manifest = workspace / ".codeflow-benchmark" / "workspace_manifest.json"
    assert manifest.exists()
    loaded_manifest = json.loads(manifest.read_text(encoding="utf-8"))
    assert loaded_manifest["task_id"] == "checks_only_sample"
    assert loaded_manifest["setup_status"] == "not_required"


def test_prepare_workspace_excludes_generated_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "buggy.py").write_text("VALUE = 1\n", encoding="utf-8")
    docs = source / "docs"
    docs.mkdir()
    try:
        (docs / "missing_target.md").symlink_to("does-not-exist.md")
    except (NotImplementedError, OSError):
        pass
    task = {
        "id": "artifact_filter_sample",
        "source_repo": str(source),
        "task": "Run validation only.",
        "checks": [f"{sys.executable} -c \"print('ok')\""],
    }

    workspace = prepare_workspace(task, workspaces_dir=tmp_path / "workspaces", clean=True)
    pycache = workspace / "__pycache__"
    pycache.mkdir()
    (pycache / "buggy.cpython-313.pyc").write_bytes(b"pyc")
    (workspace / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    egg_info = workspace / "sample.egg-info"
    egg_info.mkdir()
    (egg_info / "PKG-INFO").write_text("Metadata-Version: 2.1\n", encoding="utf-8")
    (workspace / "Grammar3.13.9.final.0.pickle").write_bytes(b"cache")
    if (source / "docs" / "missing_target.md").is_symlink():
        assert (workspace / "docs" / "missing_target.md").is_symlink()

    assert get_changed_files(str(workspace)) == []


def test_summarize_results_can_merge_multiple_files(tmp_path: Path) -> None:
    first = tmp_path / "first_results.json"
    second = tmp_path / "second_results.json"
    first.write_text(
        '[{"id": "a", "dataset": "quixbugs", "method": "checks_only", '
        '"status": "checks_failed", "checks_passed": false}]',
        encoding="utf-8",
    )
    second.write_text(
        '[{"id": "b", "dataset": "quixbugs", "method": "codeflow_full", '
        '"status": "checks_passed", "checks_passed": true}]',
        encoding="utf-8",
    )

    results = load_result_files([first, second])
    report = build_markdown_report(results)

    assert "quixbugs | checks_only" in report
    assert "quixbugs | codeflow_full" in report
    assert "Overall Checks Pass Rate (all records)：1/2" in report
    assert "| checks_only | 1 | 0/1 | 0.0% | 0 | 0.00 |" in report
    assert "| codeflow_full | 1 | 1/1 | 100.0% | 0 | 0.00 |" in report


def test_summarize_results_can_make_raw_records_portable(tmp_path: Path) -> None:
    workspace = tmp_path / "benchmark" / "workspaces" / "task"
    records = [{"id": "task", "workspace": str(workspace)}]

    portable = make_portable_records(records, root=tmp_path)

    assert portable[0]["workspace"] == "benchmark/workspaces/task"


def test_retry_manifest_records_attempt_decisions(tmp_path: Path) -> None:
    task = {"id": "task-1", "dataset": "quixbugs"}
    failed_record = {
        "status": "checks_failed",
        "checks_passed": False,
        "runtime_seconds": 1.25,
        "error_type": None,
        "error": None,
    }

    assert (
        run_eval._should_retry_record(
            failed_record,
            method="codeflow_full",
            attempt=1,
            max_attempts=3,
        )
        is True
    )
    assert (
        run_eval._should_retry_record(
            failed_record,
            method="checks_only",
            attempt=1,
            max_attempts=3,
        )
        is False
    )
    assert (
        run_eval._should_retry_record(
            {"status": "review_required", "checks_passed": True, "unsafe_diff": True},
            method="codeflow_full",
            attempt=1,
            max_attempts=3,
        )
        is True
    )

    manifest = run_eval._retry_manifest_record(
        task=task,
        method="codeflow_full",
        attempt=1,
        max_attempts=3,
        record=failed_record,
        will_retry=True,
        model="deepseekv4",
        workspace=tmp_path,
    )

    assert manifest["id"] == "task-1"
    assert manifest["attempt"] == 1
    assert manifest["max_attempts"] == 3
    assert manifest["will_retry"] is True
    assert manifest["model"] == "deepseekv4"
    assert manifest["workspace"] == str(tmp_path)


def test_run_eval_classifies_errors_and_patch_stats() -> None:
    assert run_eval._classify_error("RuntimeError", "git clone failed") == "checkout_failed"
    assert run_eval._classify_error("TimeoutError", "mini model timed out") == "llm_timeout"
    assert run_eval._patch_stats(
        "diff --git a/a.py b/a.py\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "-old\n"
        "+new\n"
    ) == {"files": 1, "additions": 1, "deletions": 1}


def test_benchmark_schemas_cover_required_fields() -> None:
    task_schema = json.loads((ROOT / "benchmark" / "schemas" / "task.schema.json").read_text())
    result_schema = json.loads((ROOT / "benchmark" / "schemas" / "result.schema.json").read_text())

    assert {"id", "dataset", "source_repo", "task", "checks"} <= set(task_schema["required"])
    assert {"id", "dataset", "method", "status", "checks_passed"} <= set(result_schema["required"])

    for task_file in (ROOT / "benchmark" / "tasks").glob("*"):
        if task_file.suffix not in {".yaml", ".jsonl"}:
            continue
        for task in load_tasks(task_file):
            for field in task_schema["required"]:
                assert field in task, f"{task_file} missing {field} for {task.get('id')}"


def test_prepare_all_status_markdown() -> None:
    report = build_status_markdown(
        {
            "suite": "smoke",
            "created_at": "2026-05-03T00:00:00Z",
            "proxy_enabled": False,
            "dry_run": True,
            "records": [
                {
                    "dataset": "harness_bench",
                    "status": "planned",
                    "tasks": 3,
                    "path": "benchmark/workspaces",
                    "reason": None,
                }
            ],
        }
    )

    assert "Benchmark Dataset Status" in report
    assert "| harness_bench | planned | 3 | benchmark/workspaces |  |" in report


def test_compare_and_trend_reports(tmp_path: Path) -> None:
    base = [{"id": "a", "dataset": "d", "method": "codeflow_full", "checks_passed": False}]
    head = [{"id": "a", "dataset": "d", "method": "codeflow_full", "checks_passed": True}]

    comparison = build_comparison(base, head)

    assert "Fixed tasks: 1" in comparison
    assert "`d/codeflow_full/a`" in comparison

    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps(base), encoding="utf-8")
    second.write_text(json.dumps(head), encoding="utf-8")

    trend = build_trend_report([first, second])

    assert "Benchmark Trend Report" in trend
    assert "| first | 1 | 0/1 | 0.0% | 0 | 0.00s |" in trend
    assert "| second | 1 | 1/1 | 100.0% | 0 | 0.00s |" in trend


def test_archive_run_writes_redacted_archive_manifest(tmp_path: Path) -> None:
    result_dir = tmp_path / "results" / "run"
    result_dir.mkdir(parents=True)
    (result_dir / "run_manifest.json").write_text('{"run_id": "run-1"}', encoding="utf-8")
    (result_dir / "log.txt").write_text("api_key=secret-value\n", encoding="utf-8")

    manifest = archive_run(
        result_dir,
        archive_dir=tmp_path / "archives",
        manifest_dir=tmp_path / "manifests",
    )

    assert manifest["run_id"] == "run-1"
    assert manifest["redacted"] is True
    assert (tmp_path / "archives" / "run-1.tar.gz").exists()
    assert (tmp_path / "manifests" / "run-1.json").exists()
