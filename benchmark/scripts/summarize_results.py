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
            "## 任务明细",
            "",
            "| id | status | checks | risk | review | repair | unsafe | no_change | test_deleted | forbidden | forbidden_write | secret |",
            "| --- | --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in results:
        lines.append(
            "| {id} | {status} | {checks} | {risk} | {review} | {repair} | {unsafe} | "
            "{no_change} | {test_deleted} | {forbidden} | {forbidden_write} | {secret} |".format(
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize CodeFlow-Harness-Bench results.")
    parser.add_argument("results_json", help="Path to harness_bench_results.json")
    parser.add_argument("--out", help="Markdown output path")
    args = parser.parse_args()

    results_path = Path(args.results_json)
    results = json.loads(results_path.read_text(encoding="utf-8"))
    report = build_markdown_report(results)
    out_path = Path(args.out) if args.out else results_path.with_suffix(".md")
    out_path.write_text(report, encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
