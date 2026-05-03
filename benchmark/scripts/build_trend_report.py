from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"Result file must contain a JSON list: {path}")
    return [dict(item) for item in data]


def build_trend_report(paths: list[Path]) -> str:
    lines = [
        "# Benchmark Trend Report",
        "",
        "| run | records | checks_passed | pass_rate | unsafe | avg_runtime |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for path in paths:
        results = _load(path)
        total = len(results)
        passed = sum(1 for item in results if item.get("checks_passed"))
        unsafe = sum(1 for item in results if item.get("unsafe_diff"))
        runtime = sum(float(item.get("runtime_seconds", 0) or 0) for item in results) / total if total else 0.0
        pass_rate = f"{passed / total:.1%}" if total else "0.0%"
        run = next((item.get("run_id") for item in results if item.get("run_id")), path.stem)
        lines.append(f"| {run} | {total} | {passed}/{total} | {pass_rate} | {unsafe} | {runtime:.2f}s |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a benchmark trend report from result JSON files.")
    parser.add_argument("results_json", nargs="+")
    parser.add_argument("--out", default="benchmark/reports/trends.md")
    args = parser.parse_args()

    report = build_trend_report([Path(path) for path in args.results_json])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
