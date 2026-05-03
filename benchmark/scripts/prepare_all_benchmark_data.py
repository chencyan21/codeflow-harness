from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from _harness_bench_common import (
    DEFAULT_TASKS_PATH,
    DEFAULT_WORKSPACES_DIR,
    ROOT,
    benchmark_env,
    load_tasks,
    portable_path,
    prepare_workspace,
    project_path,
    select_tasks,
    utc_now_iso,
)
from prepare_bugsinpy import DEFAULT_SOURCE as BUGSINPY_SOURCE
from prepare_bugsinpy import prepare_bugsinpy
from prepare_quixbugs import DEFAULT_SOURCE as QUIXBUGS_SOURCE
from prepare_quixbugs import prepare_quixbugs
from prepare_swebench import DEFAULT_LITE_DATASET, prepare_swebench


DEFAULT_MANIFEST_OUT = ROOT / "benchmark" / "generated" / "prepare_manifest.json"
DEFAULT_STATUS_OUT = ROOT / "benchmark" / "generated" / "dataset_status.md"


def _record(
    *,
    dataset: str,
    status: str,
    tasks: int = 0,
    path: Path | None = None,
    reason: str | None = None,
    runtime_seconds: float = 0.0,
) -> dict[str, Any]:
    return {
        "dataset": dataset,
        "status": status,
        "tasks": tasks,
        "path": portable_path(path) if path else None,
        "reason": reason,
        "runtime_seconds": round(runtime_seconds, 3),
    }


def _prepare_harness(*, clean: bool, limit: int | None, dry_run: bool) -> dict[str, Any]:
    start = time.perf_counter()
    tasks = select_tasks(load_tasks(DEFAULT_TASKS_PATH), limit=limit)
    if dry_run:
        return _record(
            dataset="harness_bench",
            status="planned",
            tasks=len(tasks),
            path=DEFAULT_WORKSPACES_DIR,
            runtime_seconds=time.perf_counter() - start,
        )
    for task in tasks:
        prepare_workspace(task, workspaces_dir=DEFAULT_WORKSPACES_DIR, clean=clean)
    return _record(
        dataset="harness_bench",
        status="prepared",
        tasks=len(tasks),
        path=DEFAULT_WORKSPACES_DIR,
        runtime_seconds=time.perf_counter() - start,
    )


def _prepare_quixbugs(*, suite: str, clean: bool, dry_run: bool) -> dict[str, Any]:
    start = time.perf_counter()
    if not QUIXBUGS_SOURCE.exists():
        return _record(
            dataset="quixbugs",
            status="missing_source",
            reason=f"Clone https://github.com/jkoppel/QuixBugs to {portable_path(QUIXBUGS_SOURCE)}",
            runtime_seconds=time.perf_counter() - start,
        )
    tasks_out = ROOT / "benchmark" / "tasks" / ("quixbugs.yaml" if suite == "smoke" else "quixbugs_full.yaml")
    out = ROOT / "benchmark" / "generated" / ("quixbugs_smoke" if suite == "smoke" else "quixbugs_full")
    limit = 2 if suite == "smoke" else None
    if dry_run:
        return _record(dataset="quixbugs", status="planned", path=tasks_out)
    tasks = prepare_quixbugs(
        source=QUIXBUGS_SOURCE,
        out=out,
        tasks_out=tasks_out,
        limit=limit,
        clean=clean,
        excluded_out=ROOT / "benchmark" / "reports" / "quixbugs_excluded_manifest.json",
    )
    return _record(
        dataset="quixbugs",
        status="prepared",
        tasks=len(tasks),
        path=tasks_out,
        runtime_seconds=time.perf_counter() - start,
    )


def _prepare_bugsinpy(
    *,
    suite: str,
    clean: bool,
    dry_run: bool,
    proxy: str | None,
    prepare_workspaces: bool,
) -> dict[str, Any]:
    start = time.perf_counter()
    if not BUGSINPY_SOURCE.exists():
        return _record(
            dataset="bugsinpy",
            status="missing_source",
            reason=f"Clone https://github.com/soarsmu/BugsInPy to {portable_path(BUGSINPY_SOURCE)}",
            runtime_seconds=time.perf_counter() - start,
        )
    bug_ids = ["1", "10", "11", "12", "13"] if suite in {"current", "stable"} else ["1"]
    tasks_out = ROOT / "benchmark" / "tasks" / (
        "bugsinpy_youtubedl_subset.yaml" if suite == "smoke" else "bugsinpy_stable_20.yaml"
    )
    out = ROOT / "benchmark" / "generated" / ("bugsinpy_smoke" if suite == "smoke" else "bugsinpy_stable_20")
    if dry_run:
        return _record(dataset="bugsinpy", status="planned", tasks=len(bug_ids), path=tasks_out)
    tasks = prepare_bugsinpy(
        source=BUGSINPY_SOURCE,
        out=out,
        tasks_out=tasks_out,
        project="youtube-dl",
        bug_id=bug_ids,
        limit=None,
        prepare_workspaces=prepare_workspaces,
        checkout_command=None,
        clean=clean,
        uv_python_checks=True,
        python_version_override="3.8",
        uv_with=None,
        proxy=proxy,
        manifest_out=ROOT / "benchmark" / "reports" / "bugsinpy_candidate_manifest.json",
        continue_on_error=True,
    )
    return _record(
        dataset="bugsinpy",
        status="prepared",
        tasks=len(tasks),
        path=tasks_out,
        runtime_seconds=time.perf_counter() - start,
    )


def _prepare_swebench(
    *,
    suite: str,
    clean: bool,
    dry_run: bool,
    proxy: str | None,
    prepare_workspaces: bool,
) -> list[dict[str, Any]]:
    start = time.perf_counter()
    if dry_run:
        limit = 1 if suite == "smoke" else 5
        return [
            _record(dataset="swebench_lite", status="planned", tasks=limit),
            _record(dataset="swebench_verified", status="planned", tasks=limit),
        ]

    limit = 1 if suite == "smoke" else 5
    lite_tasks_out = ROOT / "benchmark" / "tasks" / f"swebench_lite_{limit}_subset.jsonl"
    verified_tasks_out = ROOT / "benchmark" / "tasks" / f"swebench_verified_{limit}_subset.jsonl"
    records: list[dict[str, Any]] = []
    try:
        lite_tasks = prepare_swebench(
            dataset=DEFAULT_LITE_DATASET,
            split="test",
            out=ROOT / "benchmark" / "generated" / f"swebench_lite_{limit}",
            tasks_out=lite_tasks_out,
            limit=limit,
            proxy=proxy,
            prepare_workspaces=prepare_workspaces,
            apply_test_patch=True,
            clean=clean,
            manifest_out=ROOT / "benchmark" / "reports" / "swebench_lite_candidate_manifest.json",
            continue_on_error=True,
        )
        records.append(
            _record(
                dataset="swebench_lite",
                status="prepared",
                tasks=len(lite_tasks),
                path=lite_tasks_out,
                runtime_seconds=time.perf_counter() - start,
            )
        )
    except Exception as exc:
        records.append(_record(dataset="swebench_lite", status="prepare_failed", reason=str(exc)))

    verified_start = time.perf_counter()
    try:
        verified_tasks = prepare_swebench(
            dataset="SWE-bench/SWE-bench_Verified",
            split="test",
            out=ROOT / "benchmark" / "generated" / f"swebench_verified_{limit}",
            tasks_out=verified_tasks_out,
            limit=limit,
            proxy=proxy,
            prepare_workspaces=prepare_workspaces,
            apply_test_patch=True,
            clean=clean,
            manifest_out=ROOT / "benchmark" / "reports" / "swebench_verified_candidate_manifest.json",
            continue_on_error=True,
        )
        records.append(
            _record(
                dataset="swebench_verified",
                status="prepared",
                tasks=len(verified_tasks),
                path=verified_tasks_out,
                runtime_seconds=time.perf_counter() - verified_start,
            )
        )
    except Exception as exc:
        records.append(_record(dataset="swebench_verified", status="prepare_failed", reason=str(exc)))
    return records


def build_status_markdown(manifest: dict[str, Any]) -> str:
    lines = [
        "# Benchmark Dataset Status",
        "",
        f"- Suite: `{manifest['suite']}`",
        f"- Created at: `{manifest['created_at']}`",
        f"- Proxy enabled: `{manifest['proxy_enabled']}`",
        f"- Dry run: `{manifest['dry_run']}`",
        "",
        "| dataset | status | tasks | path | reason |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for record in manifest["records"]:
        lines.append(
            "| {dataset} | {status} | {tasks} | {path} | {reason} |".format(
                dataset=record["dataset"],
                status=record["status"],
                tasks=record["tasks"],
                path=record["path"] or "",
                reason=str(record["reason"] or "").replace("\n", " "),
            )
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare CodeFlow benchmark datasets and manifests.")
    parser.add_argument("--suite", choices=("smoke", "current", "stable"), default="current")
    parser.add_argument("--proxy", help="Proxy URL, for example http://127.0.0.1:10087")
    parser.add_argument("--clean", action="store_true", help="Recreate generated workspaces")
    parser.add_argument("--dry-run", action="store_true", help="Only write a plan manifest")
    parser.add_argument(
        "--prepare-external-workspaces",
        action="store_true",
        help="Clone/checkout external BugsInPy and SWE-bench workspaces instead of metadata-only tasks",
    )
    parser.add_argument("--manifest-out", default=str(DEFAULT_MANIFEST_OUT))
    parser.add_argument("--status-out", default=str(DEFAULT_STATUS_OUT))
    args = parser.parse_args()

    if args.proxy:
        benchmark_env(proxy=args.proxy)

    records = [
        _prepare_harness(clean=args.clean, limit=3 if args.suite == "smoke" else None, dry_run=args.dry_run),
        _prepare_quixbugs(suite=args.suite, clean=args.clean, dry_run=args.dry_run),
        _prepare_bugsinpy(
            suite=args.suite,
            clean=args.clean,
            dry_run=args.dry_run,
            proxy=args.proxy,
            prepare_workspaces=args.prepare_external_workspaces,
        ),
    ]
    records.extend(
        _prepare_swebench(
            suite=args.suite,
            clean=args.clean,
            dry_run=args.dry_run,
            proxy=args.proxy,
            prepare_workspaces=args.prepare_external_workspaces,
        )
    )

    manifest = {
        "schema_version": 1,
        "suite": args.suite,
        "created_at": utc_now_iso(),
        "proxy_enabled": bool(args.proxy),
        "dry_run": args.dry_run,
        "prepare_external_workspaces": args.prepare_external_workspaces,
        "records": records,
    }
    manifest_out = project_path(args.manifest_out)
    status_out = project_path(args.status_out)
    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    status_out.parent.mkdir(parents=True, exist_ok=True)
    manifest_out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    status_out.write_text(build_status_markdown(manifest), encoding="utf-8")
    print(f"wrote {manifest_out}")
    print(f"wrote {status_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
