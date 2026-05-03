# CodeFlow Benchmark Runbook

This runbook describes the reproducible benchmark flow for CodeFlow. Generated datasets,
workspaces, raw result directories and artifact archives are intentionally ignored by Git.
Tracked files define the tasks, scripts, schemas and current summary reports.

## 1. Environment Check

Run this before any real LLM benchmark:

```bash
uv run python benchmark/scripts/check_llm_env.py \
  --proxy http://127.0.0.1:10087
```

If the network is already available without a proxy, omit `--proxy`.

## 2. Prepare Dataset Metadata and Workspaces

Smoke suite:

```bash
uv run python benchmark/scripts/prepare_all_benchmark_data.py \
  --suite smoke \
  --clean
```

Current suite:

```bash
uv run python benchmark/scripts/prepare_all_benchmark_data.py \
  --suite current \
  --proxy http://127.0.0.1:10087 \
  --clean
```

External workspaces for BugsInPy/SWE-bench are opt-in because they can require network,
large clones and project-specific dependencies:

```bash
uv run python benchmark/scripts/prepare_all_benchmark_data.py \
  --suite current \
  --prepare-external-workspaces \
  --proxy http://127.0.0.1:10087 \
  --clean
```

Outputs:

- `benchmark/generated/prepare_manifest.json`
- `benchmark/generated/dataset_status.md`
- per-workspace `.codeflow-benchmark/workspace_manifest.json`

## 3. Run Benchmark Methods

Each stable task file should eventually be run with:

- `checks_only`
- `raw_mini`
- `codeflow_basic`
- `codeflow_full`

Example:

```bash
uv run python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/quixbugs_extended.yaml \
  --method codeflow_full \
  --model openai/deepseek-v4-flash \
  --max-repair-rounds 3 \
  --max-task-attempts 10 \
  --proxy http://127.0.0.1:10087 \
  --out-dir benchmark/results/quixbugs_extended_full_current
```

Every run writes:

- `run_manifest.json`
- `{task_file_stem}_results.json`
- `{task_file_stem}_report.md`
- `{task_file_stem}_retry_manifest.json`
- `artifacts/{task_id}/attempt_{n}/`

## 4. Summarize Results

```bash
uv run python benchmark/scripts/summarize_results.py \
  benchmark/results/quixbugs_extended_checks_only_current/quixbugs_extended_results.json \
  benchmark/results/quixbugs_extended_full_current/quixbugs_extended_results.json \
  --out benchmark/reports/quixbugs_extended_matrix.md \
  --raw-out benchmark/reports/quixbugs_extended_matrix.json
```

The summary separates baseline and agent methods. Do not read the overall pass rate as
a single model score when it mixes `checks_only` with agent methods.

## 5. Archive Artifacts

```bash
uv run python benchmark/scripts/archive_run.py \
  benchmark/results/quixbugs_extended_full_current
```

This writes:

- `benchmark/artifact_archives/{run_id}.tar.gz`
- `benchmark/artifacts/manifests/{run_id}.json`

Large archives should be uploaded as CI artifacts or external storage, not committed.

## 6. Compare Runs

```bash
uv run python benchmark/scripts/compare_runs.py \
  benchmark/reports/previous.json \
  benchmark/reports/current.json \
  --out benchmark/reports/run_comparison.md
```

## 7. Build Trend Report

```bash
uv run python benchmark/scripts/build_trend_report.py \
  benchmark/reports/run_1.json \
  benchmark/reports/run_2.json \
  --out benchmark/reports/trends.md
```

## 8. Real LLM Rules

- Record the model name on every run.
- Do not use more than 10 attempts per task.
- Keep first-attempt success and final success separate.
- Separate setup/network/API failures from agent failures.
- Use `http://127.0.0.1:10087` when dataset downloads or dependency installs need the local proxy.
- Do not commit raw trajectories or unredacted logs.
