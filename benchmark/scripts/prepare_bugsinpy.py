from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from _harness_bench_common import (
    ROOT,
    benchmark_env,
    project_path,
    run_command,
    write_benchmark_git_exclude,
)


DEFAULT_SOURCE = ROOT / "benchmark" / "datasets" / "bugsinpy"
DEFAULT_OUT = ROOT / "benchmark" / "generated" / "bugsinpy"
DEFAULT_TASKS_OUT = ROOT / "benchmark" / "tasks" / "bugsinpy_subset.yaml"
IGNORE_PATTERNS = (".git", "__pycache__", ".pytest_cache", ".ruff_cache", "*.pyc", "*.egg-info")


@dataclass(frozen=True)
class BugsInPyCandidate:
    project: str
    bug_id: str
    bug_dir: Path
    info: dict[str, Any]

    @property
    def task_id(self) -> str:
        return f"bugsinpy_{_safe_id(self.project)}_{_safe_id(self.bug_id)}"


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value).strip("_").lower()


def _split_values(value: str) -> list[str]:
    parts = []
    for chunk in value.replace(",", " ").split():
        stripped = chunk.strip().strip("'\"")
        if stripped:
            parts.append(stripped)
    return parts


def parse_bug_info(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    info: dict[str, Any] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        separator = ":" if ":" in line else "=" if "=" in line else None
        if separator is None:
            continue
        key, value = line.split(separator, 1)
        key = key.strip().lower().replace("-", "_")
        value = value.strip().strip("'\"")
        if key in {"test_file", "test_files", "test_function", "test_functions"}:
            info[key] = _split_values(value)
        else:
            info[key] = value
    return info


def discover_candidates(source: Path) -> list[BugsInPyCandidate]:
    projects_dir = source / "projects"
    if not projects_dir.exists():
        raise RuntimeError(f"BugsInPy projects directory not found: {projects_dir}")

    candidates = []
    for project_dir in sorted(path for path in projects_dir.iterdir() if path.is_dir()):
        bugs_dir = project_dir / "bugs"
        if not bugs_dir.exists():
            continue
        for bug_dir in sorted((path for path in bugs_dir.iterdir() if path.is_dir()), key=lambda item: item.name):
            candidates.append(
                BugsInPyCandidate(
                    project=project_dir.name,
                    bug_id=bug_dir.name,
                    bug_dir=bug_dir,
                    info=parse_bug_info(bug_dir / "bug.info"),
                )
            )
    return candidates


def _test_targets(info: dict[str, Any]) -> list[str]:
    files = info.get("test_file") or info.get("test_files") or []
    functions = info.get("test_function") or info.get("test_functions") or []
    if isinstance(files, str):
        files = [files]
    if isinstance(functions, str):
        functions = [functions]

    if files and functions and len(files) == len(functions):
        return [f"{file}::{function}" for file, function in zip(files, functions)]
    if files and functions and len(files) == 1:
        return [f"{files[0]}::{function}" for function in functions]
    if files:
        return list(files)
    return []


def _run_test_commands(candidate: BugsInPyCandidate) -> list[str]:
    run_test = candidate.bug_dir / "run_test.sh"
    if not run_test.exists():
        return []
    commands = []
    for raw_line in run_test.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            commands.append(line)
    return commands


def _python_major_minor(value: Any) -> str | None:
    if not value:
        return None
    parts = str(value).strip().split(".")
    if len(parts) < 2:
        return None
    major, minor = parts[0], parts[1]
    if not (major.isdigit() and minor.isdigit()):
        return None
    return f"{major}.{minor}"


def _uv_wrapped_check(
    command: str,
    *,
    python_version: str | None,
    uv_with: list[str],
) -> str:
    if not python_version:
        return command
    packages = list(uv_with)
    if command.startswith("pytest ") or command == "pytest":
        packages.insert(0, "pytest<8")
    with_args = " ".join(f"--with {shlex.quote(package)}" for package in packages)
    pieces = ["uv run --no-project", f"--python {shlex.quote(python_version)}"]
    if with_args:
        pieces.append(with_args)
    pieces.append(command)
    return " ".join(pieces)


def checks_for_candidate(
    candidate: BugsInPyCandidate,
    *,
    uv_python_checks: bool = False,
    python_version_override: str | None = None,
    uv_with: list[str] | None = None,
) -> list[str]:
    checks = _run_test_commands(candidate)
    if not checks:
        targets = _test_targets(candidate.info)
        if not targets:
            checks = ["pytest -q"]
        else:
            checks = ["pytest " + " ".join(targets) + " -q"]

    if not uv_python_checks:
        return checks

    python_version = python_version_override or _python_major_minor(candidate.info.get("python_version"))
    return [
        _uv_wrapped_check(command, python_version=python_version, uv_with=uv_with or [])
        for command in checks
    ]


def task_from_candidate(
    candidate: BugsInPyCandidate,
    workspace_root: Path,
    *,
    uv_python_checks: bool = False,
    python_version_override: str | None = None,
    uv_with: list[str] | None = None,
) -> dict[str, Any]:
    workspace = workspace_root / candidate.task_id
    return {
        "id": candidate.task_id,
        "dataset": "bugsinpy",
        "source_repo": _task_source_repo(workspace),
        "task": "修复当前仓库中的 bug，使指定测试通过。不要删除测试，不要跳过测试。",
        "checks": checks_for_candidate(
            candidate,
            uv_python_checks=uv_python_checks,
            python_version_override=python_version_override,
            uv_with=uv_with,
        ),
        "expected_type": "bugfix",
        "risk_tags": ["normal"],
        "metadata": {
            "project": candidate.project,
            "bug_id": candidate.bug_id,
            "python_version": candidate.info.get("python_version"),
            "bug_dir": str(candidate.bug_dir),
            "bug_info": candidate.info,
        },
    }


def _task_source_repo(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _checkout_command(source: Path, command_override: str | None = None) -> list[str]:
    if command_override:
        return command_override.split()
    local = source / "framework" / "bin" / "bugsinpy-checkout"
    if local.exists():
        return [str(local)]
    return ["bugsinpy-checkout"]


def _checkout_candidate(
    candidate: BugsInPyCandidate,
    *,
    source: Path,
    target: Path,
    command_override: str | None,
    env: dict[str, str],
) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"{candidate.task_id}-") as temp:
        temp_dir = Path(temp)
        command = _checkout_command(source, command_override)
        env = dict(env)
        framework_bin = source / "framework" / "bin"
        if framework_bin.exists():
            env["PATH"] = f"{framework_bin}{os.pathsep}{env.get('PATH', '')}"
        subprocess.run(
            command
            + [
                "-p",
                candidate.project,
                "-v",
                "0",
                "-i",
                candidate.bug_id,
                "-w",
                str(temp_dir),
            ],
            text=True,
            check=True,
            env=env,
        )
        checkout = _locate_checkout(temp_dir, candidate.project)
        shutil.copytree(checkout, target, ignore=shutil.ignore_patterns(*IGNORE_PATTERNS))

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
            "baseline-bugsinpy",
        ],
        target,
    )
    write_benchmark_git_exclude(target)


def _locate_checkout(temp_dir: Path, project: str) -> Path:
    direct = temp_dir / project
    if direct.exists():
        return direct
    children = [path for path in temp_dir.iterdir() if path.is_dir()]
    if len(children) == 1:
        return children[0]
    if (temp_dir / ".git").exists() or any(temp_dir.iterdir()):
        return temp_dir
    raise RuntimeError(f"Could not locate BugsInPy checkout under {temp_dir}")


def _select_candidates(
    candidates: list[BugsInPyCandidate],
    *,
    project: str | None,
    bug_id: list[str] | None,
    limit: int | None,
) -> list[BugsInPyCandidate]:
    selected = candidates
    if project:
        selected = [candidate for candidate in selected if candidate.project == project]
    if bug_id:
        wanted = set(bug_id)
        selected = [candidate for candidate in selected if candidate.bug_id in wanted]
        missing = wanted - {candidate.bug_id for candidate in selected}
        if missing:
            raise RuntimeError(f"Unknown BugsInPy bug id(s): {', '.join(sorted(missing))}")
    if limit is not None:
        selected = selected[:limit]
    return selected


def write_tasks(path: Path, tasks: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(tasks, allow_unicode=True, sort_keys=False), encoding="utf-8")


def prepare_bugsinpy(
    *,
    source: Path,
    out: Path,
    tasks_out: Path,
    project: str | None,
    bug_id: list[str] | None,
    limit: int | None,
    prepare_workspaces: bool,
    checkout_command: str | None,
    clean: bool,
    uv_python_checks: bool = False,
    python_version_override: str | None = None,
    uv_with: list[str] | None = None,
    proxy: str | None = None,
) -> list[dict[str, Any]]:
    candidates = _select_candidates(discover_candidates(source), project=project, bug_id=bug_id, limit=limit)
    tasks = [
        task_from_candidate(
            candidate,
            out,
            uv_python_checks=uv_python_checks,
            python_version_override=python_version_override,
            uv_with=uv_with,
        )
        for candidate in candidates
    ]

    if prepare_workspaces:
        env = benchmark_env(proxy=proxy)
        for candidate, task in zip(candidates, tasks):
            target = project_path(task["source_repo"])
            if target.exists() and not clean:
                print(f"reuse {task['id']}: {target}")
                continue
            print(f"prepare {task['id']}: {candidate.project} bug {candidate.bug_id}")
            _checkout_candidate(
                candidate,
                source=source,
                target=target,
                command_override=checkout_command,
                env=env,
            )

    write_tasks(tasks_out, tasks)
    return tasks


def _print_list(
    candidates: list[BugsInPyCandidate],
    *,
    uv_python_checks: bool,
    python_version_override: str | None,
    uv_with: list[str],
) -> None:
    rows = [
        {
            "project": candidate.project,
            "bug_id": candidate.bug_id,
            "checks": checks_for_candidate(
                candidate,
                uv_python_checks=uv_python_checks,
                python_version_override=python_version_override,
                uv_with=uv_with,
            ),
            "python_version": candidate.info.get("python_version"),
        }
        for candidate in candidates
    ]
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a BugsInPy mini-subset for CodeFlow eval.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="BugsInPy checkout path")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Generated workspace root")
    parser.add_argument("--tasks-out", default=str(DEFAULT_TASKS_OUT), help="Generated task YAML path")
    parser.add_argument("--project", help="Filter to one BugsInPy project")
    parser.add_argument("--bug-id", action="append", help="Filter to one or more bug ids")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of selected bugs")
    parser.add_argument("--list", action="store_true", help="List candidate bugs and exit")
    parser.add_argument(
        "--prepare-workspaces",
        action="store_true",
        help="Run bugsinpy-checkout and create independent Git workspaces",
    )
    parser.add_argument("--checkout-command", help="Override bugsinpy-checkout command")
    parser.add_argument(
        "--uv-python-checks",
        action="store_true",
        help="Wrap checks with `uv run --no-project --python <candidate python>`",
    )
    parser.add_argument(
        "--python-version-override",
        help="Use this Python version for --uv-python-checks, for example 3.8",
    )
    parser.add_argument("--uv-with", action="append", default=[], help="Extra package for uv-wrapped checks")
    parser.add_argument("--proxy", help="Proxy URL for checkout, for example http://127.0.0.1:10087")
    parser.add_argument("--clean", action="store_true", help="Recreate existing generated workspaces")
    args = parser.parse_args()

    source = project_path(args.source)
    candidates = _select_candidates(
        discover_candidates(source),
        project=args.project,
        bug_id=args.bug_id,
        limit=args.limit,
    )
    if args.list:
        _print_list(
            candidates,
            uv_python_checks=args.uv_python_checks,
            python_version_override=args.python_version_override,
            uv_with=args.uv_with,
        )
        return

    tasks = prepare_bugsinpy(
        source=source,
        out=project_path(args.out),
        tasks_out=project_path(args.tasks_out),
        project=args.project,
        bug_id=args.bug_id,
        limit=args.limit,
        prepare_workspaces=args.prepare_workspaces,
        checkout_command=args.checkout_command,
        clean=args.clean,
        uv_python_checks=args.uv_python_checks,
        python_version_override=args.python_version_override,
        uv_with=args.uv_with,
        proxy=args.proxy,
    )
    print(f"wrote {len(tasks)} tasks to {project_path(args.tasks_out)}")


if __name__ == "__main__":
    main()
