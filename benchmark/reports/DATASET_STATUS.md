# Benchmark Dataset Status

This document tracks the intended benchmark suites. The generated status for a concrete
machine/run is written to `benchmark/generated/dataset_status.md`.

## Current Tracked Inputs

| Dataset | Task File | Current Role | Status |
| --- | --- | --- | --- |
| Harness-Bench | `benchmark/tasks/harness_bench.yaml` | Harness sensor and repair smoke | tracked |
| QuixBugs | `benchmark/tasks/quixbugs.yaml` | small smoke subset | tracked |
| QuixBugs extended | `benchmark/tasks/quixbugs_extended.yaml` | current fast bugfix subset | tracked |
| BugsInPy youtube-dl | `benchmark/tasks/bugsinpy_youtubedl_5.yaml` | current real BugsInPy subset | tracked |
| SWE-bench Lite 2 | `benchmark/tasks/swebench_lite_2_subset.jsonl` | current Lite smoke subset | tracked |
| SWE-bench Verified 2 | `benchmark/tasks/swebench_verified_2_subset.jsonl` | current Verified smoke subset | tracked |
| QuixBugs full | `benchmark/tasks/quixbugs_full.yaml` | all currently convertible local QuixBugs Python tasks | tracked |
| BugsInPy stable 20 | `benchmark/tasks/bugsinpy_stable_20.yaml` | 20 BugsInPy metadata candidates; checkout/eval is manifest-driven | tracked |
| BugsInPy stable 50 | `benchmark/tasks/bugsinpy_stable_50.yaml` | 50 BugsInPy metadata candidates; checkout/eval is manifest-driven | tracked |
| SWE-bench Lite 5/10 | `benchmark/tasks/swebench_lite_5_subset.jsonl`, `benchmark/tasks/swebench_lite_10_subset.jsonl` | metadata candidates; workspace prep is opt-in | tracked |
| SWE-bench Verified 5/10 | `benchmark/tasks/swebench_verified_5_subset.jsonl`, `benchmark/tasks/swebench_verified_10_subset.jsonl` | metadata candidates; workspace prep is opt-in | tracked |

## Target Stable Suites

| Suite | Contents | Purpose |
| --- | --- | --- |
| `smoke` | Harness 3, QuixBugs 2, BugsInPy 1 metadata, SWE-bench 1+1 metadata | CI and local script validation |
| `current` | Harness v0, QuixBugs full/extended, BugsInPy youtube-dl, SWE-bench Lite/Verified mini subsets | current reproducible benchmark |
| `stable` | Harness 30, QuixBugs full, BugsInPy stable 20, SWE-bench Lite 5, SWE-bench Verified 5 | resume-project quality benchmark |

## External Source Policy

The following directories are generated or third-party sources and should stay ignored:

- `benchmark/datasets/`
- `benchmark/generated/`
- `benchmark/workspaces/`
- `benchmark/results/`
- `benchmark/artifact_archives/`

Use `benchmark/scripts/prepare_all_benchmark_data.py` to rebuild local generated state.
