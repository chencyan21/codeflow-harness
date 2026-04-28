from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from codeflow.models import CodeFlowConfig  # noqa: E402
from codeflow.runner import run_codeflow  # noqa: E402


def _run(cmd: list[str], cwd: Path) -> None:
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)


def _prepare_repo(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".ruff_cache"),
    )
    _run(["git", "init"], destination)
    _run(["git", "add", "."], destination)
    _run(
        [
            "git",
            "-c",
            "user.email=codeflow@example.local",
            "-c",
            "user.name=CodeFlow",
            "commit",
            "-m",
            "init",
        ],
        destination,
    )


def main() -> None:
    tasks = yaml.safe_load((ROOT / "benchmark" / "tasks.yaml").read_text(encoding="utf-8"))[
        "tasks"
    ]
    results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="codeflow-benchmark-") as tmp:
        tmp_root = Path(tmp)
        for index, item in enumerate(tasks, start=1):
            source_repo = ROOT / item["repo"]
            run_repo = tmp_root / f"task_{index}"
            try:
                _prepare_repo(source_repo, run_repo)
                config = CodeFlowConfig(
                    repo=str(run_repo),
                    task=item["task"],
                    checks=item.get("checks", ["pytest -q"]),
                    no_commit=True,
                    max_repair_rounds=3,
                )
                state = run_codeflow(config)
                results.append(
                    {
                        "task": item["task"],
                        "status": state.status,
                        "repair_round": state.repair_round,
                        "checks_passed": all(result.success for result in state.check_results),
                        "report": state.report,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "task": item["task"],
                        "status": "error",
                        "error": str(exc),
                    }
                )

    (ROOT / "benchmark" / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
