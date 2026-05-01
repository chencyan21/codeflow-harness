from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_EVAL = ROOT / "benchmark" / "scripts" / "run_eval.py"
DEFAULT_TASKS = ROOT / "benchmark" / "tasks" / "harness_bench.yaml"


def main() -> None:
    command = [
        sys.executable,
        str(RUN_EVAL),
        "--tasks",
        str(DEFAULT_TASKS),
    ]
    command.extend(sys.argv[1:])
    raise SystemExit(subprocess.run(command, cwd=ROOT).returncode)


if __name__ == "__main__":
    main()
