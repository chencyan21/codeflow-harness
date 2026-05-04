#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
else
  PYTHON_BIN="${PYTHON_BIN:-python}"
fi

LITE_LIMIT="${LITE_LIMIT:-300}"
RUN_STAMP="${RUN_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"

TASKS_OUT="${TASKS_OUT:-benchmark/tasks/swebench_lite_full.jsonl}"
GENERATED_OUT="${GENERATED_OUT:-benchmark/generated/swebench_lite_full}"
WORKSPACES_DIR="${WORKSPACES_DIR:-benchmark/workspaces/swebench_lite_full}"
MANIFEST_OUT="${MANIFEST_OUT:-benchmark/reports/swebench_lite_full_checkout_manifest.json}"
OUT_DIR="${OUT_DIR:-benchmark/results/swebench_lite_full_${RUN_STAMP}}"
CODEFLOW_ENV_FILE="${CODEFLOW_ENV_FILE:-$ROOT/.env}"

METHOD="${METHOD:-codeflow_full}"
MAX_REPAIR_ROUNDS="${MAX_REPAIR_ROUNDS:-1}"
MAX_TASK_ATTEMPTS="${MAX_TASK_ATTEMPTS:-10}"
EVAL_JOBS="${EVAL_JOBS:-4}"
CODEFLOW_MINI_TIMEOUT_SECONDS="${CODEFLOW_MINI_TIMEOUT_SECONDS:-3600}"

CHECK_LLM="${CHECK_LLM:-1}"
DRY_RUN="${DRY_RUN:-0}"
PREPARE_ONLY="${PREPARE_ONLY:-0}"
RUN_LIMIT="${RUN_LIMIT:-}"
TASK_ID="${TASK_ID:-}"
PROXY="${PROXY:-}"

if [[ ! "$EVAL_JOBS" =~ ^[1-9][0-9]*$ ]]; then
  echo "EVAL_JOBS must be a positive integer, got: $EVAL_JOBS" >&2
  exit 2
fi

eval "$("$PYTHON_BIN" - "$CODEFLOW_ENV_FILE" <<'PY'
from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

try:
    from dotenv import dotenv_values
except ImportError:
    dotenv_values = None

env_file = Path(sys.argv[1]).expanduser()
values = dotenv_values(env_file) if dotenv_values and env_file.exists() else {}


def first(*items: object) -> str | None:
    for item in items:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            return text
    return None


model = first(
    os.environ.get("MODEL"),
    os.environ.get("MSWEA_MODEL_NAME"),
    values.get("model_id"),
    values.get("MODEL_ID"),
    values.get("MODEL"),
    "deepseek-v4-flash",
)
api_key = first(os.environ.get("OPENAI_API_KEY"), values.get("api_key"), values.get("API_KEY"))
base_url = first(
    os.environ.get("OPENAI_BASE_URL"),
    os.environ.get("LITELLM_BASE_URL"),
    values.get("base_url"),
    values.get("BASE_URL"),
)

exports = {
    "MODEL": model,
    "MSWEA_MODEL_NAME": model,
    "CODEFLOW_SEMANTIC_MODEL": first(os.environ.get("CODEFLOW_SEMANTIC_MODEL"), model),
}
if api_key:
    exports["OPENAI_API_KEY"] = api_key
if base_url:
    exports["OPENAI_BASE_URL"] = base_url
    exports["OPENAI_API_BASE"] = base_url

for key, value in exports.items():
    if value is not None:
        print(f"{key}={shlex.quote(value)}")
PY
)"

export CODEFLOW_ENV_FILE
export CODEFLOW_MINI_TIMEOUT_SECONDS
export MODEL
export MSWEA_MODEL_NAME
export CODEFLOW_SEMANTIC_MODEL
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-}"
export OPENAI_API_BASE="${OPENAI_API_BASE:-}"

if [[ -n "$PROXY" ]]; then
  export HTTP_PROXY="$PROXY"
  export HTTPS_PROXY="$PROXY"
  export ALL_PROXY="$PROXY"
  export http_proxy="$PROXY"
  export https_proxy="$PROXY"
  export all_proxy="$PROXY"
fi

mask_secret() {
  local value="$1"
  local len="${#value}"
  if [[ "$len" -eq 0 ]]; then
    echo "missing"
  else
    echo "loaded len=$len"
  fi
}

echo "root=$ROOT"
echo "python=$PYTHON_BIN"
echo "env_file=$CODEFLOW_ENV_FILE"
echo "model=$MODEL"
echo "base_url=${OPENAI_BASE_URL:-missing}"
echo "api_key=$(mask_secret "${OPENAI_API_KEY:-}")"
echo "proxy=${PROXY:-disabled}"
echo "method=$METHOD"
echo "tasks_out=$TASKS_OUT"
echo "generated_out=$GENERATED_OUT"
echo "workspaces_dir=$WORKSPACES_DIR"
echo "out_dir=$OUT_DIR"
echo "eval_jobs=$EVAL_JOBS"

if [[ "$CHECK_LLM" == "1" ]]; then
  check_args=(benchmark/scripts/check_llm_env.py --env-file "$CODEFLOW_ENV_FILE")
  if [[ -n "$PROXY" ]]; then
    check_args+=(--proxy "$PROXY")
  fi
  "$PYTHON_BIN" "${check_args[@]}"
fi

if [[ ! -f "$TASKS_OUT" ]]; then
  echo "tasks file not found: $TASKS_OUT" >&2
  exit 1
fi

TASK_COUNT="$(wc -l < "$TASKS_OUT" | tr -d ' ')"
echo "local_tasks=$TASK_COUNT"
if [[ "$TASK_COUNT" == "0" ]]; then
  echo "no tasks in $TASKS_OUT" >&2
  exit 1
fi
if [[ "$TASK_COUNT" != "$LITE_LIMIT" ]]; then
  echo "local task count ($TASK_COUNT) does not match expected Lite count ($LITE_LIMIT)" >&2
  echo "fix $TASKS_OUT or set LITE_LIMIT=$TASK_COUNT for an intentional partial run" >&2
  exit 1
fi

"$PYTHON_BIN" - "$TASKS_OUT" "$ROOT" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

tasks_path = Path(sys.argv[1])
root = Path(sys.argv[2])
tasks = [json.loads(line) for line in tasks_path.read_text(encoding="utf-8").splitlines() if line.strip()]
ids = [str(task["id"]) for task in tasks]
duplicates = sorted({task_id for task_id in ids if ids.count(task_id) > 1})
if duplicates:
    raise SystemExit(f"duplicate task id(s): {', '.join(duplicates)}")
missing = []
for task in tasks:
    source = root / str(task["source_repo"])
    if not source.exists():
        missing.append(f"{task['id']} -> {task['source_repo']}")
if missing:
    preview = "\n".join(missing[:20])
    suffix = "" if len(missing) <= 20 else f"\n... and {len(missing) - 20} more"
    raise SystemExit(f"missing local source workspace(s):\n{preview}{suffix}")
synthetic = [task for task in tasks if task.get("metadata", {}).get("synthetic_duplicate")]
print(f"local_source_workspaces={len(tasks)}")
print(f"synthetic_duplicates={len(synthetic)}")
for task in synthetic:
    print(f"synthetic_duplicate={task['id']} duplicate_of={task['metadata'].get('duplicate_of')}")
PY

if [[ "$PREPARE_ONLY" == "1" || "$DRY_RUN" == "1" ]]; then
  echo "local validation complete"
  echo "tasks=$TASKS_OUT"
  echo "manifest=$MANIFEST_OUT"
  exit 0
fi

ACTIVE_TASKS="$TASKS_OUT"
ACTIVE_COUNT="$TASK_COUNT"
if [[ -n "$RUN_LIMIT" || -n "$TASK_ID" ]]; then
  mkdir -p "$OUT_DIR"
  ACTIVE_TASKS="$OUT_DIR/selected_tasks.jsonl"
  "$PYTHON_BIN" - "$TASKS_OUT" "$ACTIVE_TASKS" "${RUN_LIMIT:-}" "$TASK_ID" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

tasks_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
limit_text = sys.argv[3].strip()
task_id_text = sys.argv[4].strip()

tasks = [json.loads(line) for line in tasks_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if task_id_text:
    wanted = [item.strip() for item in task_id_text.split(",") if item.strip()]
    wanted_set = set(wanted)
    selected = [task for task in tasks if str(task["id"]) in wanted_set]
    missing = wanted_set - {str(task["id"]) for task in selected}
    if missing:
        raise SystemExit(f"unknown TASK_ID value(s): {', '.join(sorted(missing))}")
else:
    selected = tasks

if limit_text:
    limit = int(limit_text)
    if limit < 1:
        raise SystemExit("RUN_LIMIT must be positive")
    selected = selected[:limit]

out_path.write_text(
    "\n".join(json.dumps(task, ensure_ascii=False) for task in selected) + ("\n" if selected else ""),
    encoding="utf-8",
)
PY
  ACTIVE_COUNT="$(wc -l < "$ACTIVE_TASKS" | tr -d ' ')"
fi

if [[ "$ACTIVE_COUNT" == "0" ]]; then
  echo "no selected tasks to run" >&2
  exit 1
fi

JOB_COUNT="$EVAL_JOBS"
if (( ACTIVE_COUNT < JOB_COUNT )); then
  JOB_COUNT="$ACTIVE_COUNT"
fi

run_eval_for_tasks() {
  local shard_tasks="$1"
  local shard_out_dir="$2"
  local log_file="$3"
  local -a eval_args=(
    benchmark/scripts/run_eval.py
    --tasks "$shard_tasks"
    --method "$METHOD"
    --model "$MODEL"
    --max-repair-rounds "$MAX_REPAIR_ROUNDS"
    --max-task-attempts "$MAX_TASK_ATTEMPTS"
    --workspaces-dir "$WORKSPACES_DIR"
    --out-dir "$shard_out_dir"
    --reuse-workspaces
  )
  if [[ -n "$PROXY" ]]; then
    eval_args+=(--proxy "$PROXY")
  fi
  "$PYTHON_BIN" "${eval_args[@]}" > "$log_file" 2>&1
}

SHARD_ROOT="$OUT_DIR/shards"
SHARD_TASKS_DIR="$SHARD_ROOT/tasks"
SHARD_RUNS_DIR="$SHARD_ROOT/runs"
mkdir -p "$SHARD_TASKS_DIR" "$SHARD_RUNS_DIR"

"$PYTHON_BIN" - "$ACTIVE_TASKS" "$SHARD_TASKS_DIR" "$JOB_COUNT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

tasks_path = Path(sys.argv[1])
shard_dir = Path(sys.argv[2])
jobs = int(sys.argv[3])

lines = [line for line in tasks_path.read_text(encoding="utf-8").splitlines() if line.strip()]
shard_dir.mkdir(parents=True, exist_ok=True)
for old in shard_dir.glob("*.jsonl"):
    old.unlink()

width = max(2, len(str(jobs - 1)))
stem = tasks_path.stem
handles = []
try:
    for index in range(jobs):
        path = shard_dir / f"{stem}_shard_{index:0{width}d}_of_{jobs:0{width}d}.jsonl"
        handles.append(path.open("w", encoding="utf-8"))
    for index, line in enumerate(lines):
        handles[index % jobs].write(line + "\n")
finally:
    for handle in handles:
        handle.close()
PY

echo "selected_tasks=$ACTIVE_COUNT"
echo "parallel_jobs=$JOB_COUNT"

pids=()
result_paths=()
for shard_tasks in "$SHARD_TASKS_DIR"/*.jsonl; do
  shard_name="$(basename "$shard_tasks" .jsonl)"
  shard_out_dir="$SHARD_RUNS_DIR/$shard_name"
  shard_log="$shard_out_dir/run.log"
  mkdir -p "$shard_out_dir"
  echo "start shard=$shard_name log=$shard_log"
  run_eval_for_tasks "$shard_tasks" "$shard_out_dir" "$shard_log" &
  pids+=("$!")
  result_paths+=("$shard_out_dir/${shard_name}_results.json")
done

failed=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then
    failed=1
  fi
done

if [[ "$failed" != "0" ]]; then
  echo "one or more shards failed; inspect logs under $SHARD_RUNS_DIR" >&2
  exit 1
fi

for result_path in "${result_paths[@]}"; do
  if [[ ! -f "$result_path" ]]; then
    echo "missing shard result: $result_path" >&2
    exit 1
  fi
done

RESULT_STEM="$(basename "$ACTIVE_TASKS" .jsonl)"
"$PYTHON_BIN" benchmark/scripts/summarize_results.py \
  "${result_paths[@]}" \
  --out "$OUT_DIR/${RESULT_STEM}_report.md" \
  --raw-out "$OUT_DIR/${RESULT_STEM}_results.json"

echo "done"
echo "results=$OUT_DIR/${RESULT_STEM}_results.json"
echo "report=$OUT_DIR/${RESULT_STEM}_report.md"
