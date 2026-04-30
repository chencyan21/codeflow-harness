from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from _harness_bench_common import ROOT, project_path, run_command


DEFAULT_LITE_DATASET = "princeton-nlp/SWE-bench_Lite"
DEFAULT_VERIFIED_DATASET = "SWE-bench/SWE-bench_Verified"
DEFAULT_OUT = ROOT / "benchmark" / "generated" / "swebench_lite"
DEFAULT_TASKS_OUT = ROOT / "benchmark" / "tasks" / "swebench_lite_subset.jsonl"
PROXY_ENV_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


def configure_proxy(proxy: str | None) -> dict[str, str]:
    env = os.environ.copy()
    if proxy:
        for key in PROXY_ENV_KEYS:
            env[key] = proxy
    return env


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


def _checks_for_fail_to_pass(fail_to_pass: list[str], *, check_prefix: str | None = None) -> list[str]:
    if not fail_to_pass:
        command = "python -m pytest -q"
        return [f"{check_prefix} {command}" if check_prefix else command]
    tests = " ".join(shlex.quote(test) for test in fail_to_pass)
    command = f"python -m pytest {tests} -q"
    return [f"{check_prefix} {command}" if check_prefix else command]


def task_from_record(
    record: dict[str, Any],
    *,
    dataset: str,
    workspace_root: Path,
    check_prefix: str | None = None,
) -> dict[str, Any]:
    instance_id = str(record["instance_id"])
    task_id = f"{_dataset_label(dataset)}_{_safe_id(instance_id)}"
    fail_to_pass = _jsonish_list(record.get("FAIL_TO_PASS") or record.get("fail_to_pass"))
    pass_to_pass = _jsonish_list(record.get("PASS_TO_PASS") or record.get("pass_to_pass"))
    workspace = workspace_root / task_id

    return {
        "id": task_id,
        "dataset": _dataset_label(dataset),
        "source_repo": _task_source_repo(workspace),
        "task": str(record.get("problem_statement", "")).strip(),
        "checks": _checks_for_fail_to_pass(fail_to_pass, check_prefix=check_prefix),
        "expected_type": "bugfix",
        "risk_tags": ["normal"],
        "metadata": {
            "instance_id": instance_id,
            "repo": record.get("repo"),
            "base_commit": record.get("base_commit"),
            "fail_to_pass": fail_to_pass,
            "pass_to_pass": pass_to_pass,
        },
    }


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


def _clone_workspace(record: dict[str, Any], target: Path, *, env: dict[str, str], apply_test_patch: bool) -> None:
    repo = str(record["repo"])
    base_commit = str(record["base_commit"])
    clone_url = f"https://github.com/{repo}.git"

    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--filter=blob:none", clone_url, str(target)],
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
) -> list[dict[str, Any]]:
    env = configure_proxy(proxy)
    old_env = os.environ.copy()
    os.environ.update(env)
    try:
        records = _load_hf_records(dataset, split, limit)
    finally:
        os.environ.clear()
        os.environ.update(old_env)

    tasks = [
        task_from_record(record, dataset=dataset, workspace_root=out, check_prefix=check_prefix)
        for record in records
    ]
    if prepare_workspaces:
        for record, task in zip(records, tasks):
            target = project_path(task["source_repo"])
            if target.exists() and not clean:
                print(f"reuse {task['id']}: {target}")
                continue
            print(f"prepare {task['id']}: {record['repo']}@{record['base_commit']}")
            _clone_workspace(record, target, env=env, apply_test_patch=apply_test_patch)

    write_jsonl(tasks_out, tasks)
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
    )
    print(f"wrote {len(tasks)} tasks to {project_path(args.tasks_out)}")


if __name__ == "__main__":
    main()
