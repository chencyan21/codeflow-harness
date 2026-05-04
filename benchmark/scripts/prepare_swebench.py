from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from _harness_bench_common import (
    BENCHMARK_META_DIR,
    ROOT,
    benchmark_env,
    mark_setup_done,
    portable_path,
    project_path,
    run_command,
    run_shell_command,
    utc_now_iso,
    write_benchmark_git_exclude,
    write_workspace_manifest,
)


DEFAULT_LITE_DATASET = "princeton-nlp/SWE-bench_Lite"
DEFAULT_VERIFIED_DATASET = "SWE-bench/SWE-bench_Verified"
DEFAULT_OUT = ROOT / "benchmark" / "generated" / "swebench_lite"
DEFAULT_TASKS_OUT = ROOT / "benchmark" / "tasks" / "swebench_lite_subset.jsonl"
ASTROPY_SETUP_COMPAT_SNIPPET = (
    "import collections, collections.abc, runpy, sys; "
    "aliases = ('Callable', 'Iterable', 'Iterator', 'Mapping', "
    "'MutableMapping', 'MutableSequence', 'Sequence'); "
    "[setattr(collections, name, getattr(collections.abc, name)) "
    "for name in aliases if not hasattr(collections, name)]; "
    "sys.argv = ['setup.py', 'build_ext', '--inplace']; "
    "runpy.run_path('setup.py', run_name='__main__')"
)
ASTROPY_BUILD_EXT_COMMAND = (
    "uv run --no-project --python 3.11 "
    '--with "setuptools<70" --with setuptools-scm --with extension-helpers '
    '--with cython --with "numpy<2" --with jinja2 '
    f"python -c {shlex.quote(ASTROPY_SETUP_COMPAT_SNIPPET)}"
)
SETUP_RECIPES = {
    "astropy/astropy": [ASTROPY_BUILD_EXT_COMMAND],
}


def configure_proxy(proxy: str | None) -> dict[str, str]:
    return benchmark_env(proxy=proxy)


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value).strip("_").lower()


def _jsonish_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        return [str(parsed)]
    return [str(value)]


def _dataset_label(dataset: str) -> str:
    lowered = dataset.lower()
    if "verified" in lowered:
        return "swebench_verified"
    if "lite" in lowered:
        return "swebench_lite"
    return "swebench"


def _django_unittest_targets(fail_to_pass: list[str]) -> list[str] | None:
    converted = []
    for target in fail_to_pass:
        match = re.fullmatch(r"(?P<method>[\w_]+) \((?P<class_path>[\w.]+)\)", target.strip())
        if not match:
            return None
        converted.append(f"{match.group('class_path')}.{match.group('method')}")
    return converted


def _checks_for_fail_to_pass(
    fail_to_pass: list[str],
    *,
    repo: str | None = None,
    check_prefix: str | None = None,
) -> list[str]:
    if not fail_to_pass:
        command = "python -m pytest -q"
        return [f"{check_prefix} {command}" if check_prefix else command]
    if repo == "django/django":
        django_targets = _django_unittest_targets(fail_to_pass)
        if django_targets:
            tests = " ".join(shlex.quote(test) for test in django_targets)
            command = f"python tests/runtests.py {tests} --verbosity 0"
            return [f"{check_prefix} {command}" if check_prefix else command]
    tests = " ".join(shlex.quote(test) for test in fail_to_pass)
    command = f"python -m pytest {tests} -q"
    return [f"{check_prefix} {command}" if check_prefix else command]


def setup_commands_for_record(
    record: dict[str, Any],
    *,
    setup_recipe: str,
    extra_setup_commands: list[str] | None = None,
) -> list[str]:
    commands: list[str] = []
    repo = str(record.get("repo", ""))
    if setup_recipe == "auto":
        commands.extend(SETUP_RECIPES.get(repo, []))
    elif setup_recipe == "astropy":
        commands.extend(SETUP_RECIPES["astropy/astropy"])
    elif setup_recipe != "none":
        raise RuntimeError(f"Unknown setup recipe: {setup_recipe}")
    commands.extend(extra_setup_commands or [])
    return commands


def task_from_record(
    record: dict[str, Any],
    *,
    dataset: str,
    workspace_root: Path,
    check_prefix: str | None = None,
    setup_recipe: str = "auto",
    extra_setup_commands: list[str] | None = None,
) -> dict[str, Any]:
    instance_id = str(record["instance_id"])
    task_id = f"{_dataset_label(dataset)}_{_safe_id(instance_id)}"
    fail_to_pass = _jsonish_list(record.get("FAIL_TO_PASS") or record.get("fail_to_pass"))
    pass_to_pass = _jsonish_list(record.get("PASS_TO_PASS") or record.get("pass_to_pass"))
    workspace = workspace_root / task_id
    setup_commands = setup_commands_for_record(
        record,
        setup_recipe=setup_recipe,
        extra_setup_commands=extra_setup_commands,
    )

    task = {
        "id": task_id,
        "dataset": _dataset_label(dataset),
        "source_repo": _task_source_repo(workspace),
        "task": str(record.get("problem_statement", "")).strip(),
        "checks": _checks_for_fail_to_pass(
            fail_to_pass,
            repo=str(record.get("repo") or ""),
            check_prefix=check_prefix,
        ),
        "expected_type": "bugfix",
        "risk_tags": ["normal"],
        "metadata": {
            "instance_id": instance_id,
            "repo": record.get("repo"),
            "base_commit": record.get("base_commit"),
            "fail_to_pass": fail_to_pass,
            "pass_to_pass": pass_to_pass,
            "setup_recipe": setup_recipe,
        },
    }
    if setup_commands:
        task["setup_commands"] = setup_commands
    return task


def _task_source_repo(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _load_hf_records(dataset: str, split: str, limit: int | None) -> list[dict[str, Any]]:
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise RuntimeError("Install the `datasets` package to download SWE-bench metadata") from exc

    data = load_dataset(dataset, split=split)
    records = []
    for index, item in enumerate(data):
        if limit is not None and index >= limit:
            break
        records.append(dict(item))
    return records


def _filter_records(records: list[dict[str, Any]], instance_ids: list[str] | None) -> list[dict[str, Any]]:
    if not instance_ids:
        return records
    wanted = set(instance_ids)
    selected = [record for record in records if str(record.get("instance_id")) in wanted]
    missing = wanted - {str(record.get("instance_id")) for record in selected}
    if missing:
        raise RuntimeError(f"Unknown SWE-bench instance id(s): {', '.join(sorted(missing))}")
    return selected


def _repo_cache_path(repo: str, repo_cache_dir: Path) -> Path:
    return repo_cache_dir / _safe_id(repo)


def _is_partial_clone(repo: Path) -> bool:
    result = subprocess.run(
        ["git", "config", "--get", "remote.origin.promisor"],
        cwd=repo,
        text=True,
        capture_output=True,
    )
    if result.returncode == 0 and result.stdout.strip().lower() == "true":
        return True
    result = subprocess.run(
        ["git", "config", "--get", "extensions.partialclone"],
        cwd=repo,
        text=True,
        capture_output=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _ensure_repo_cache(repo: str, *, repo_cache_dir: Path, env: dict[str, str]) -> Path:
    cache_path = _repo_cache_path(repo, repo_cache_dir)
    clone_url = f"https://github.com/{repo}.git"
    if cache_path.exists():
        if _is_partial_clone(cache_path):
            shutil.rmtree(cache_path)
        else:
            subprocess.run(["git", "fetch", "--all", "--prune"], cwd=cache_path, text=True, check=True, env=env)
            return cache_path
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", clone_url, str(cache_path)],
        text=True,
        check=True,
        env=env,
    )
    return cache_path


def _clone_workspace(
    record: dict[str, Any],
    target: Path,
    *,
    env: dict[str, str],
    apply_test_patch: bool,
    setup_commands: list[str],
    repo_cache_dir: Path | None = None,
) -> None:
    repo = str(record["repo"])
    base_commit = str(record["base_commit"])
    clone_source = (
        str(_ensure_repo_cache(repo, repo_cache_dir=repo_cache_dir, env=env))
        if repo_cache_dir
        else f"https://github.com/{repo}.git"
    )

    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", clone_source, str(target)],
        text=True,
        check=True,
        env=env,
    )
    run_command(["git", "checkout", base_commit], target)

    test_patch = str(record.get("test_patch") or "")
    if apply_test_patch and test_patch.strip():
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as patch_file:
            patch_file.write(test_patch)
            patch_path = Path(patch_file.name)
        try:
            run_command(["git", "apply", str(patch_path)], target)
        finally:
            patch_path.unlink(missing_ok=True)

    for command in setup_commands:
        print(f"setup {target.name}: {command}")
        run_shell_command(command, target, env=env)
    mark_setup_done(target, setup_commands)

    shutil.rmtree(target / ".git", ignore_errors=True)
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
            "baseline-swebench",
        ],
        target,
    )
    write_benchmark_git_exclude(target)
    write_workspace_manifest(
        target,
        {
            "id": target.name,
            "dataset": _dataset_label(str(record.get("dataset", ""))),
            "source_repo": _task_source_repo(target),
            "metadata": {
                "source_kind": "swebench",
                "repo": f"https://github.com/{repo}",
                "base_commit": base_commit,
            },
        },
        source_repo=Path(clone_source),
        setup_commands=setup_commands,
        setup_status="passed" if setup_commands else "not_required",
        setup_runtime_seconds=0.0,
        source_kind="swebench",
        upstream_repo=f"https://github.com/{repo}",
        base_commit=base_commit,
        test_patch_applied=apply_test_patch and bool(str(record.get("test_patch") or "").strip()),
    )


def write_jsonl(path: Path, tasks: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(task, ensure_ascii=False) for task in tasks) + ("\n" if tasks else ""),
        encoding="utf-8",
    )


def prepare_swebench(
    *,
    dataset: str,
    split: str,
    out: Path,
    tasks_out: Path,
    limit: int | None,
    proxy: str | None,
    prepare_workspaces: bool,
    apply_test_patch: bool,
    clean: bool,
    check_prefix: str | None = None,
    setup_recipe: str = "auto",
    extra_setup_commands: list[str] | None = None,
    instance_ids: list[str] | None = None,
    repo_cache_dir: Path | None = None,
    manifest_out: Path | None = None,
    continue_on_error: bool = False,
) -> list[dict[str, Any]]:
    env = configure_proxy(proxy)
    old_env = os.environ.copy()
    os.environ.update(env)
    try:
        records = _filter_records(_load_hf_records(dataset, split, limit), instance_ids)
    finally:
        os.environ.clear()
        os.environ.update(old_env)

    tasks = [
        task_from_record(
            record,
            dataset=dataset,
            workspace_root=out,
            check_prefix=check_prefix,
            setup_recipe=setup_recipe,
            extra_setup_commands=extra_setup_commands,
        )
        for record in records
    ]
    manifest_rows: list[dict[str, Any]] = []
    prepared_task_ids: set[str] = set()
    if prepare_workspaces:
        for record, task in zip(records, tasks):
            target = project_path(task["source_repo"])
            if target.exists() and not clean:
                manifest_path = target / BENCHMARK_META_DIR / "workspace_manifest.json"
                if manifest_path.exists():
                    print(f"reuse {task['id']}: {target}")
                    prepared_task_ids.add(str(task["id"]))
                    manifest_rows.append(
                        {
                            "id": task["id"],
                            "instance_id": record.get("instance_id"),
                            "repo": record.get("repo"),
                            "status": "reused",
                            "workspace": portable_path(target),
                            "reason": None,
                        }
                    )
                    continue
                shutil.rmtree(target)
            print(f"prepare {task['id']}: {record['repo']}@{record['base_commit']}")
            try:
                _clone_workspace(
                    {**record, "dataset": dataset},
                    target,
                    env=env,
                    apply_test_patch=apply_test_patch,
                    setup_commands=[str(command) for command in task.get("setup_commands", [])],
                    repo_cache_dir=repo_cache_dir,
                )
                prepared_task_ids.add(str(task["id"]))
                manifest_rows.append(
                    {
                        "id": task["id"],
                        "instance_id": record.get("instance_id"),
                        "repo": record.get("repo"),
                        "status": "prepared",
                        "workspace": portable_path(target),
                        "reason": None,
                    }
                )
            except Exception as exc:
                manifest_rows.append(
                    {
                        "id": task["id"],
                        "instance_id": record.get("instance_id"),
                        "repo": record.get("repo"),
                        "status": "prepare_failed",
                        "workspace": portable_path(target),
                        "reason": str(exc),
                    }
                )
                if not continue_on_error:
                    raise

    if prepare_workspaces:
        tasks = [task for task in tasks if str(task["id"]) in prepared_task_ids]
    write_jsonl(tasks_out, tasks)
    if manifest_out:
        manifest_out.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": 1,
            "dataset": _dataset_label(dataset),
            "hf_dataset": dataset,
            "split": split,
            "created_at": utc_now_iso(),
            "selected": len(records),
            "tasks_out": portable_path(tasks_out),
            "prepare_workspaces": prepare_workspaces,
            "apply_test_patch": apply_test_patch,
            "proxy_enabled": bool(proxy),
            "repo_cache_dir": portable_path(repo_cache_dir) if repo_cache_dir else None,
            "records": manifest_rows
            or [
                {
                    "id": task["id"],
                    "instance_id": record.get("instance_id"),
                    "repo": record.get("repo"),
                    "status": "metadata_only",
                    "workspace": portable_path(project_path(task["source_repo"])),
                    "reason": None,
                }
                for record, task in zip(records, tasks)
            ],
        }
        manifest_out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return tasks


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a SWE-bench Lite/Verified mini-subset.")
    parser.add_argument("--dataset", default=DEFAULT_LITE_DATASET, help="Hugging Face dataset name")
    parser.add_argument("--verified", action="store_true", help="Use SWE-bench Verified preset")
    parser.add_argument("--split", default="test", help="Dataset split")
    parser.add_argument("--limit", type=int, default=10, help="Number of instances to select")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Workspace root")
    parser.add_argument("--tasks-out", default=str(DEFAULT_TASKS_OUT), help="Task JSONL output path")
    parser.add_argument("--proxy", help="Proxy URL, for example http://127.0.0.1:10087")
    parser.add_argument("--instance-id", action="append", help="Select a specific SWE-bench instance id")
    parser.add_argument("--repo-cache-dir", help="Optional shared Git clone cache directory")
    parser.add_argument(
        "--prepare-workspaces",
        action="store_true",
        help="Clone repositories and create runnable workspaces instead of metadata-only tasks",
    )
    parser.add_argument(
        "--no-apply-test-patch",
        action="store_true",
        help="Do not apply SWE-bench test_patch while preparing workspaces",
    )
    parser.add_argument(
        "--check-prefix",
        help="Prefix every generated validation command, for example a uv run environment wrapper",
    )
    parser.add_argument(
        "--setup-recipe",
        default="auto",
        choices=("auto", "none", "astropy"),
        help="Workspace setup recipe to run before the benchmark baseline commit",
    )
    parser.add_argument(
        "--setup-command",
        action="append",
        default=[],
        help="Extra shell command to run before the benchmark baseline commit",
    )
    parser.add_argument("--manifest-out", help="Optional dataset preparation manifest JSON path")
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue preparing other instances after clone/setup failures and record failures",
    )
    parser.add_argument("--clean", action="store_true", help="Recreate existing workspaces")
    args = parser.parse_args()

    dataset = DEFAULT_VERIFIED_DATASET if args.verified else args.dataset
    tasks = prepare_swebench(
        dataset=dataset,
        split=args.split,
        out=project_path(args.out),
        tasks_out=project_path(args.tasks_out),
        limit=args.limit,
        proxy=args.proxy,
        prepare_workspaces=args.prepare_workspaces,
        apply_test_patch=not args.no_apply_test_patch,
        clean=args.clean,
        check_prefix=args.check_prefix,
        setup_recipe=args.setup_recipe,
        extra_setup_commands=args.setup_command,
        instance_ids=args.instance_id,
        repo_cache_dir=project_path(args.repo_cache_dir) if args.repo_cache_dir else None,
        manifest_out=project_path(args.manifest_out) if args.manifest_out else None,
        continue_on_error=args.continue_on_error,
    )
    print(f"wrote {len(tasks)} tasks to {project_path(args.tasks_out)}")


if __name__ == "__main__":
    main()
