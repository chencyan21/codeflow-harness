from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _load(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"Result file must contain a JSON list: {path}")
    return [dict(item) for item in data]


def _by_task(results: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {
        (
            str(item.get("dataset", "")),
            str(item.get("method", "")),
            str(item.get("id", "")),
        ): item
        for item in results
    }


def build_comparison(base: list[dict[str, Any]], head: list[dict[str, Any]]) -> str:
    base_map = _by_task(base)
    head_map = _by_task(head)
    keys = sorted(set(base_map) | set(head_map))
    regressions = []
    fixes = []
    added = []
    removed = []
    for key in keys:
        left = base_map.get(key)
        right = head_map.get(key)
        if left is None:
            added.append(key)
        elif right is None:
            removed.append(key)
        elif left.get("checks_passed") and not right.get("checks_passed"):
            regressions.append(key)
        elif not left.get("checks_passed") and right.get("checks_passed"):
            fixes.append(key)

    base_failures = Counter(str(item.get("error_category") or item.get("status") or "unknown") for item in base)
    head_failures = Counter(str(item.get("error_category") or item.get("status") or "unknown") for item in head)
    lines = [
        "# Benchmark Run Comparison",
        "",
        f"- Base records: {len(base)}",
        f"- Head records: {len(head)}",
        f"- Fixed tasks: {len(fixes)}",
        f"- Regressed tasks: {len(regressions)}",
        f"- Added tasks: {len(added)}",
        f"- Removed tasks: {len(removed)}",
        "",
        "## Regressions",
        "",
    ]
    lines.extend(f"- `{dataset}/{method}/{task_id}`" for dataset, method, task_id in regressions)
    if not regressions:
        lines.append("- none")
    lines.extend(["", "## Fixes", ""])
    lines.extend(f"- `{dataset}/{method}/{task_id}`" for dataset, method, task_id in fixes)
    if not fixes:
        lines.append("- none")
    lines.extend(["", "## Failure Category Delta", "", "| category | base | head | delta |", "| --- | ---: | ---: | ---: |"])
    for category in sorted(set(base_failures) | set(head_failures)):
        left = base_failures[category]
        right = head_failures[category]
        lines.append(f"| {category} | {left} | {right} | {right - left:+d} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two benchmark result JSON files.")
    parser.add_argument("base")
    parser.add_argument("head")
    parser.add_argument("--out", help="Markdown output path")
    args = parser.parse_args()

    report = build_comparison(_load(Path(args.base)), _load(Path(args.head)))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
