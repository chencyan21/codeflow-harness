from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from _harness_bench_common import ROOT, project_path, run_command


DEFAULT_SOURCE = ROOT / "benchmark" / "datasets" / "quixbugs"
DEFAULT_OUT = ROOT / "benchmark" / "generated" / "quixbugs"
DEFAULT_TASKS_OUT = ROOT / "benchmark" / "tasks" / "quixbugs.yaml"


def _name(path: Path) -> str:
    return path.stem.lower()


def _as_args(value: Any) -> tuple[Any, ...]:
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _case_to_tuple(case: Any) -> tuple[tuple[Any, ...], Any] | None:
    if isinstance(case, dict):
        input_value = None
        for key in ("input", "inputs", "args", "arguments"):
            if key in case:
                input_value = case[key]
                break
        expected = None
        for key in ("output", "expected", "result"):
            if key in case:
                expected = case[key]
                break
        if input_value is None or expected is None:
            return None
        return _as_args(input_value), expected

    if isinstance(case, list) and len(case) == 2:
        return _as_args(case[0]), case[1]

    return None


def _load_cases(path: Path) -> list[tuple[tuple[Any, ...], Any]]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(data, dict):
        if isinstance(data.get("testcases"), list):
            raw_cases = data["testcases"]
        elif isinstance(data.get("cases"), list):
            raw_cases = data["cases"]
        else:
            raw_cases = list(data.values())
    elif isinstance(data, list):
        raw_cases = data
    else:
        raw_cases = []

    cases = []
    for item in raw_cases:
        parsed = _case_to_tuple(item)
        if parsed is not None:
            cases.append(parsed)
    return cases


def _find_case_file(source: Path, program: Path) -> Path | None:
    cases_dir = source / "json_testcases"
    if not cases_dir.exists():
        return None

    candidates = [
        cases_dir / f"{program.stem}.json",
        cases_dir / f"{program.stem.lower()}.json",
        cases_dir / f"{program.stem.upper()}.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    wanted = _name(program)
    for candidate in cases_dir.glob("*.json"):
        if _name(candidate) == wanted:
            return candidate
    return None


def _discover_programs(source: Path) -> list[tuple[Path, Path]]:
    programs_dir = source / "python_programs"
    if not programs_dir.exists():
        raise RuntimeError(f"QuixBugs python_programs directory not found: {programs_dir}")

    pairs = []
    for program in sorted(programs_dir.glob("*.py")):
        if program.name == "__init__.py":
            continue
        case_file = _find_case_file(source, program)
        if case_file is not None:
            pairs.append((program, case_file))
    return pairs


def _write_test(target: Path, function_name: str, cases: list[tuple[tuple[Any, ...], Any]]) -> None:
    rendered_cases = ",\n    ".join(repr((args, expected)) for args, expected in cases)
    target.write_text(
        f"""from __future__ import annotations

import pytest

import buggy


CASES = [
    {rendered_cases}
]


@pytest.mark.parametrize(("args", "expected"), CASES)
def test_{function_name}(args, expected):
    assert buggy.{function_name}(*args) == expected
""",
        encoding="utf-8",
    )


def _write_project_files(target: Path, source_program: Path, cases: list[tuple[tuple[Any, ...], Any]]) -> None:
    function_name = source_program.stem
    shutil.copy2(source_program, target / "buggy.py")
    _write_test(target / "test_buggy.py", function_name, cases)
    (target / "README.md").write_text(
        f"# QuixBugs {function_name}\n\nFix `buggy.{function_name}` so the pytest suite passes.\n",
        encoding="utf-8",
    )
    (target / "pyproject.toml").write_text(
        """[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "quixbugs-task"
version = "0.0.0"
requires-python = ">=3.10"
dependencies = ["pytest>=8.0.0"]
""",
        encoding="utf-8",
    )


def _init_git(target: Path) -> None:
    run_command(["git", "init"], target)
    run_command(["git", "add", "."], target)
    run_command(
        [
            "git",
            "-c",
            "user.email=codeflow@example.local",
            "-c",
            "user.name=CodeFlow",
            "commit",
            "-m",
            "baseline-quixbugs",
        ],
        target,
    )


def _task_source_repo(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def prepare_quixbugs(
    *,
    source: Path,
    out: Path,
    tasks_out: Path,
    limit: int | None,
    clean: bool,
) -> list[dict[str, Any]]:
    pairs = _discover_programs(source)
    if limit is not None:
        pairs = pairs[:limit]

    tasks = []
    for program, case_file in pairs:
        cases = _load_cases(case_file)
        if not cases:
            print(f"skip {program.stem}: no convertible test cases in {case_file}")
            continue

        task_id = f"quixbugs_{program.stem.lower()}"
        target = out / program.stem.lower()
        if target.exists():
            if not clean:
                print(f"reuse {task_id}: {target}")
            else:
                shutil.rmtree(target)
        if not target.exists():
            target.mkdir(parents=True)
            _write_project_files(target, program, cases)
            _init_git(target)
            print(f"prepared {task_id}: {target}")

        tasks.append(
            {
                "id": task_id,
                "dataset": "quixbugs",
                "source_repo": _task_source_repo(target),
                "task": "修复该 Python 程序中的 bug，使所有测试通过。不要删除测试。",
                "checks": ["timeout 10s pytest -q"],
                "expected_type": "bugfix",
                "risk_tags": ["normal"],
                "metadata": {
                    "program": program.stem,
                    "case_file": str(case_file),
                    "case_count": len(cases),
                },
            }
        )

    tasks_out.parent.mkdir(parents=True, exist_ok=True)
    tasks_out.write_text(yaml.safe_dump(tasks, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return tasks


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a QuixBugs Python subset for CodeFlow eval.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="QuixBugs checkout path")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Generated workspace directory")
    parser.add_argument("--tasks-out", default=str(DEFAULT_TASKS_OUT), help="Generated task YAML path")
    parser.add_argument("--limit", type=int, default=10, help="Maximum number of convertible tasks")
    parser.add_argument("--clean", action="store_true", help="Recreate generated workspaces")
    args = parser.parse_args()

    tasks = prepare_quixbugs(
        source=project_path(args.source),
        out=project_path(args.out),
        tasks_out=project_path(args.tasks_out),
        limit=args.limit,
        clean=args.clean,
    )
    print(f"wrote {len(tasks)} tasks to {project_path(args.tasks_out)}")


if __name__ == "__main__":
    main()
