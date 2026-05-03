from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return data


def build_summary(path: Path) -> str:
    data = _load_json(path)
    lines = ["# Benchmark Artifact", ""]
    for key in ("run_id", "created_at", "result_dir", "archive", "redacted"):
        if key in data:
            lines.append(f"- {key}: `{data[key]}`")
    files = data.get("files")
    if isinstance(files, list):
        lines.extend(["", "## Files", ""])
        lines.extend(f"- `{item}`" for item in files[:200])
        if len(files) > 200:
            lines.append(f"- ... {len(files) - 200} more")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a benchmark artifact manifest.")
    parser.add_argument("manifest")
    parser.add_argument("--out", help="Optional Markdown output path")
    args = parser.parse_args()

    summary = build_summary(Path(args.manifest))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(summary, encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
