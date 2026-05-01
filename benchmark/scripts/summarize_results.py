from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _percent(value: int, total: int) -> str:
    if total == 0:
        return "0.0%"
    return f"{value / total:.1%}"


def _yes(value: bool) -> str:
    return "yes" if value else "no"


def build_markdown_report(results: list[dict[str, Any]]) -> str:
    total = len(results)
    status_counts = Counter(str(item.get("status", "unknown")) for item in results)
    dataset_method_counts = Counter(
        (str(item.get("dataset", "unknown")), str(item.get("method", "unknown"))) for item in results
    )
    checks_passed = sum(1 for item in results if item.get("checks_passed"))
    unsafe = sum(1 for item in results if item.get("unsafe_diff"))
    no_change = sum(1 for item in results if item.get("no_change"))
    test_deleted = sum(1 for item in results if item.get("test_deleted"))
    forbidden = sum(1 for item in results if item.get("forbidden_path_modified"))
    forbidden_write = sum(1 for item in results if item.get("forbidden_path_write"))
    secret_like = sum(1 for item in results if item.get("secret_like_content"))
    review_high = sum(1 for item in results if item.get("review_risk_level") == "high")
    missing_test = sum(1 for item in results if item.get("missing_test_warning"))
    repair_rounds = [int(item.get("repair_rounds", 0)) for item in results]
    avg_repair = sum(repair_rounds) / total if total else 0.0

    lines = [
        "# CodeFlow-Harness-Bench 报告",
        "",
        "## 汇总",
        "",
        f"- 任务数：{total}",
        f"- Checks Pass Rate：{checks_passed}/{total} ({_percent(checks_passed, total)})",
        f"- Unsafe Diff Rate：{unsafe}/{total} ({_percent(unsafe, total)})",
        f"- No-change Detection：{no_change}/{total} ({_percent(no_change, total)})",
        f"- Test Deletion Detection：{test_deleted}/{total} ({_percent(test_deleted, total)})",
        f"- Forbidden Path Detection：{forbidden}/{total} ({_percent(forbidden, total)})",
        f"- Forbidden Path Write Detection：{forbidden_write}/{total} ({_percent(forbidden_write, total)})",
        f"- Secret-like Content Detection：{secret_like}/{total} ({_percent(secret_like, total)})",
        f"- Review High Risk Detection：{review_high}/{total} ({_percent(review_high, total)})",
        f"- Missing Test Warning：{missing_test}/{total} ({_percent(missing_test, total)})",
        f"- Average Repair Rounds：{avg_repair:.2f}",
        "",
        "## 状态分布",
        "",
    ]
    for status, count in sorted(status_counts.items()):
        lines.append(f"- {status}: {count}")

    lines.extend(
        [
            "",
            "## Dataset / Method",
            "",
            "| dataset | method | tasks | checks_passed | unsafe | avg_repair |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for dataset, method in sorted(dataset_method_counts):
        group = [
            item
            for item in results
            if str(item.get("dataset", "unknown")) == dataset
            and str(item.get("method", "unknown")) == method
        ]
        group_total = len(group)
        group_passed = sum(1 for item in group if item.get("checks_passed"))
        group_unsafe = sum(1 for item in group if item.get("unsafe_diff"))
        group_repairs = [int(item.get("repair_rounds", 0)) for item in group]
        group_avg_repair = sum(group_repairs) / group_total if group_total else 0.0
        lines.append(
            f"| {dataset} | {method} | {group_total} | {group_passed} | "
            f"{group_unsafe} | {group_avg_repair:.2f} |"
        )

    lines.extend(
        [
            "",
            "## 任务明细",
            "",
            "| dataset | method | id | status | checks | risk | review | repair | unsafe | no_change | test_deleted | forbidden | forbidden_write | secret |",
            "| --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in results:
        lines.append(
            "| {dataset} | {method} | {id} | {status} | {checks} | {risk} | {review} | {repair} | {unsafe} | "
            "{no_change} | {test_deleted} | {forbidden} | {forbidden_write} | {secret} |".format(
                dataset=item.get("dataset", ""),
                method=item.get("method", ""),
                id=item.get("id", ""),
                status=item.get("status", ""),
                checks=_yes(bool(item.get("checks_passed"))),
                risk=item.get("risk_level", ""),
                review=item.get("review_risk_level", ""),
                repair=item.get("repair_rounds", 0),
                unsafe=_yes(bool(item.get("unsafe_diff"))),
                no_change=_yes(bool(item.get("no_change"))),
                test_deleted=_yes(bool(item.get("test_deleted"))),
                forbidden=_yes(bool(item.get("forbidden_path_modified"))),
                forbidden_write=_yes(bool(item.get("forbidden_path_write"))),
                secret=_yes(bool(item.get("secret_like_content"))),
            )
        )

    return "\n".join(lines) + "\n"


def load_result_files(paths: list[Path]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in paths:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, list):
            raise RuntimeError(f"Result file must contain a JSON list: {path}")
        for item in loaded:
            if not isinstance(item, dict):
                raise RuntimeError(f"Result item must be a JSON object in {path}")
            enriched = dict(item)
            enriched.setdefault("source_result_file", str(path))
            results.append(enriched)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize CodeFlow-Harness-Bench results.")
    parser.add_argument("results_json", nargs="+", help="Path(s) to *_results.json")
    parser.add_argument("--out", help="Markdown output path")
    args = parser.parse_args()

    result_paths = [Path(path) for path in args.results_json]
    results = load_result_files(result_paths)
    report = build_markdown_report(results)
    out_path = Path(args.out) if args.out else result_paths[0].with_suffix(".md")
    out_path.write_text(report, encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
