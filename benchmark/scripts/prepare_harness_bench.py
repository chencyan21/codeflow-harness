from __future__ import annotations

import argparse
import json

from _harness_bench_common import (
    DEFAULT_TASKS_PATH,
    DEFAULT_WORKSPACES_DIR,
    load_tasks,
    prepare_workspace,
    project_path,
    select_tasks,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare CodeFlow-Harness-Bench workspaces.")
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS_PATH), help="Harness bench task YAML")
    parser.add_argument(
        "--workspaces-dir",
        default=str(DEFAULT_WORKSPACES_DIR),
        help="Directory for prepared task repositories",
    )
    parser.add_argument("--task-id", action="append", help="Prepare only this task id")
    parser.add_argument("--limit", type=int, help="Prepare only the first N selected tasks")
    parser.add_argument("--clean", action="store_true", help="Recreate existing workspaces")
    args = parser.parse_args()

    tasks_path = project_path(args.tasks)
    workspaces_dir = project_path(args.workspaces_dir)
    tasks = select_tasks(load_tasks(tasks_path), task_ids=args.task_id, limit=args.limit)

    manifest = []
    for task in tasks:
        workspace = prepare_workspace(task, workspaces_dir=workspaces_dir, clean=args.clean)
        manifest.append({"id": task["id"], "workspace": str(workspace)})
        print(f"prepared {task['id']}: {workspace}")

    manifest_path = workspaces_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {manifest_path}")


if __name__ == "__main__":
    main()
