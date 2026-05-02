from __future__ import annotations

import json
from html import escape
from typing import Any


def build_service_dashboard_html(
    *,
    repos: list[str],
    runs: list[dict[str, Any]],
    summary: dict[str, Any],
) -> str:
    rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(item.get('repo', '')))}</td>"
        f"<td>{escape(str(item.get('run_id', '')))}</td>"
        f"<td>{escape(str(item.get('status', '')))}</td>"
        f"<td>{escape(str(item.get('risk_level', '')))}</td>"
        f"<td>{escape(str(item.get('task', '')))}</td>"
        f"<td>{escape(str(item.get('run_dir', '')))}</td>"
        "</tr>"
        for item in runs
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>CodeFlow Observability</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 24px; color: #1f2937; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #d1d5db; padding: 6px 8px; text-align: left; }}
    th {{ background: #f3f4f6; }}
    code, pre {{ background: #f3f4f6; padding: 2px 4px; }}
  </style>
</head>
<body>
  <h1>CodeFlow Observability</h1>
  <p>Repositories: {escape(", ".join(repos))}</p>
  <p>Total runs: {summary.get("total_runs", 0)}</p>
  <h2>Summary</h2>
  <pre>{escape(json.dumps(summary, ensure_ascii=False, indent=2))}</pre>
  <h2>Runs</h2>
  <table>
    <thead><tr><th>Repo</th><th>Run ID</th><th>Status</th><th>Risk</th><th>Task</th><th>Run Dir</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</body>
</html>
"""
