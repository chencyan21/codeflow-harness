# CodeFlow-Harness-Bench v0

这是第一个自建 CodeFlow-Harness-Bench，用来快速验证 CodeFlow Harness 的整体闭环：

- workspace 复制和 baseline Git 初始化
- mini-swe-agent 调用链路
- checks 执行
- repair loop
- no-change / test deletion / forbidden path / forbidden path write 等 Harness sensors
- JSON 结果和 Markdown 报告输出

## 目录

```text
benchmark/
├── tasks/harness_bench.yaml
├── scripts/prepare_harness_bench.py
├── scripts/run_eval.py
├── scripts/summarize_results.py
└── scripts/fake_mini.py
```

当前 v0 包含 12 个任务：

- 9 个正常任务：feature、bugfix、quality、refactor
- 3 个风险任务：no-change、删除测试、修改 `.env`

示例项目：

- `examples/todo_api`
- `examples/file_utils`
- `examples/student_manager`

`run_eval.py` 支持 4 种方法：

- `raw_mini`：直接把任务交给 mini-swe-agent，随后只采集 checks 结果。
- `checks_only`：只运行原始仓库的 validation checks，不调用 mini-swe-agent、repair 或 sensors。
- `codeflow_basic`：使用 CodeFlow 初始 prompt、checks 和 repair loop，不做 sensors。
- `codeflow_full`：完整 Harness Policy、Sensors、Repair Loop 和 Review。

## 快速验证

不调用真实 LLM，只用确定性 fake mini 验证 Harness 逻辑：

```bash
.venv/bin/python benchmark/scripts/run_eval.py \
  --fake-mini \
  --max-repair-rounds 1
```

输出：

```text
benchmark/results/codeflow_full/{task_file_stem}_results.json
benchmark/results/codeflow_full/{task_file_stem}_report.md
benchmark/results/codeflow_full/*_review.md
```

预期现象：

- 9 个正常任务为 `checks_passed`
- no-change 任务为 `sensor_failed`
- 删除测试任务为 `review_required`
- 修改 `.env` 任务为 `review_required`

真实 LLM 如果没有直接修改 `.env`，而是新增“写 `.env`”的 helper 代码，也应由 `forbidden_path_write` sensor 拦截。

## 方法对比

```bash
for method in raw_mini checks_only codeflow_basic codeflow_full; do
  .venv/bin/python benchmark/scripts/run_eval.py \
    --fake-mini \
    --method "$method" \
    --out-dir "benchmark/results/$method"
done
```

## 仅准备 workspace

```bash
.venv/bin/python benchmark/scripts/prepare_harness_bench.py --clean
```

准备后的仓库在：

```text
benchmark/workspaces/{task_id}
```

`benchmark/workspaces/` 和 `benchmark/results/` 是生成物，默认不纳入 Git。

## 使用真实 mini/LLM

去掉 `--fake-mini` 即可走真实 mini-swe-agent。模型、API key、base URL 继续复用 CodeFlow 当前环境约定：

```bash
.venv/bin/python benchmark/scripts/run_eval.py \
  --method codeflow_full \
  --model openai/your-model \
  --max-repair-rounds 3
```

如需要代理，可在命令前设置：

```bash
HTTPS_PROXY=http://127.0.0.1:10087 \
HTTP_PROXY=http://127.0.0.1:10087 \
ALL_PROXY=http://127.0.0.1:10087 \
.venv/bin/python benchmark/scripts/run_eval.py --model openai/your-model
```

也可以显式指定 mini 命令：

```bash
.venv/bin/python benchmark/scripts/run_eval.py \
  --mini-command ".venv/bin/mini" \
  --model openai/your-model
```

## 常用筛选

只跑前 N 个任务：

```bash
.venv/bin/python benchmark/scripts/run_eval.py --fake-mini --limit 3
```

只跑指定任务：

```bash
.venv/bin/python benchmark/scripts/run_eval.py \
  --fake-mini \
  --task-id harness_risk_test_deletion_001
```

## QuixBugs 子集

先把 QuixBugs clone 到默认目录：

```bash
git clone https://github.com/jkoppel/QuixBugs.git benchmark/datasets/quixbugs
```

生成前 10 个可转换的 Python 任务：

```bash
.venv/bin/python benchmark/scripts/prepare_quixbugs.py \
  --source benchmark/datasets/quixbugs \
  --out benchmark/generated/quixbugs \
  --tasks-out benchmark/tasks/quixbugs.yaml \
  --limit 10 \
  --clean
```

运行：

```bash
.venv/bin/python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/quixbugs.yaml \
  --method codeflow_full \
  --out-dir benchmark/results/quixbugs_codeflow_full
```

## BugsInPy 子集

先 clone BugsInPy：

```bash
git clone https://github.com/soarsmu/BugsInPy.git benchmark/datasets/bugsinpy
```

列出候选 bug：

```bash
.venv/bin/python benchmark/scripts/prepare_bugsinpy.py \
  --source benchmark/datasets/bugsinpy \
  --list \
  --limit 20
```

只生成任务 metadata，不 checkout 项目：

```bash
.venv/bin/python benchmark/scripts/prepare_bugsinpy.py \
  --source benchmark/datasets/bugsinpy \
  --tasks-out benchmark/tasks/bugsinpy_subset.yaml \
  --limit 20
```

如果需要让生成的 checks 使用 BugsInPy 标注的 Python 版本，可加 `--uv-python-checks`。本机没有
对应旧版本时，可以用 `--python-version-override` 指到可用兼容版本：

```bash
.venv/bin/python benchmark/scripts/prepare_bugsinpy.py \
  --source benchmark/datasets/bugsinpy \
  --out benchmark/generated/bugsinpy_youtubedl \
  --tasks-out benchmark/tasks/bugsinpy_youtubedl_subset.yaml \
  --project youtube-dl \
  --bug-id 1 \
  --prepare-workspaces \
  --uv-python-checks \
  --python-version-override 3.8
```

准备可运行 workspace：

```bash
.venv/bin/python benchmark/scripts/prepare_bugsinpy.py \
  --source benchmark/datasets/bugsinpy \
  --out benchmark/generated/bugsinpy \
  --tasks-out benchmark/tasks/bugsinpy_subset.yaml \
  --limit 5 \
  --prepare-workspaces \
  --clean
```

如果本机 `PATH` 没有 BugsInPy framework，也可以显式指定：

```bash
.venv/bin/python benchmark/scripts/prepare_bugsinpy.py \
  --checkout-command "benchmark/datasets/bugsinpy/framework/bin/bugsinpy-checkout" \
  --prepare-workspaces
```

运行：

```bash
.venv/bin/python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/bugsinpy_subset.yaml \
  --method codeflow_full \
  --out-dir benchmark/results/bugsinpy_codeflow_full
```

## SWE-bench Lite / Verified Mini-Subset

只生成 metadata 和任务 JSONL，不 clone 大仓库：

```bash
.venv/bin/python benchmark/scripts/prepare_swebench.py \
  --dataset princeton-nlp/SWE-bench_Lite \
  --limit 10 \
  --proxy http://127.0.0.1:10087 \
  --tasks-out benchmark/tasks/swebench_lite_subset.jsonl
```

Verified 子集：

```bash
.venv/bin/python benchmark/scripts/prepare_swebench.py \
  --verified \
  --limit 10 \
  --proxy http://127.0.0.1:10087 \
  --tasks-out benchmark/tasks/swebench_verified_subset.jsonl
```

如需准备可运行 workspace，再加 `--prepare-workspaces --clean`。这会 clone 对应 GitHub 仓库、checkout
`base_commit`、可选应用 `test_patch`，成本明显更高，建议先用很小的 `--limit` 试跑。

```bash
.venv/bin/python benchmark/scripts/prepare_swebench.py \
  --dataset princeton-nlp/SWE-bench_Lite \
  --limit 2 \
  --proxy http://127.0.0.1:10087 \
  --prepare-workspaces \
  --clean
```

对需要额外测试依赖的真实项目，可以用 `--check-prefix` 固定运行环境。例如当前 astropy
smoke task 使用：

```bash
.venv/bin/python benchmark/scripts/prepare_swebench.py \
  --dataset princeton-nlp/SWE-bench_Lite \
  --limit 1 \
  --proxy http://127.0.0.1:10087 \
  --out benchmark/generated/swebench_lite \
  --tasks-out benchmark/tasks/swebench_lite_subset.jsonl \
  --check-prefix "uv run --no-project --python 3.11 --with pytest --with pytest-doctestplus --with hypothesis --with 'numpy<2' --with setuptools-scm --with packaging --with pyerfa --with pyyaml"
```

Astropy 这类 source checkout 还需要先在生成的 workspace 中构建扩展：

```bash
cd benchmark/generated/swebench_lite/swebench_lite_astropy__astropy_12907
uv run --no-project --python 3.11 \
  --with 'setuptools<70' --with setuptools-scm --with extension-helpers \
  --with cython --with 'numpy<2' --with jinja2 \
  python setup.py build_ext --inplace
```

准备好 workspace 后即可运行：

```bash
.venv/bin/python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/swebench_lite_subset.jsonl \
  --method codeflow_full \
  --out-dir benchmark/results/swebench_lite_codeflow_full
```

## 单独生成汇总报告

```bash
.venv/bin/python benchmark/scripts/summarize_results.py \
  benchmark/results/codeflow_full/harness_bench_results.json \
  --out benchmark/results/codeflow_full/harness_bench_report.md
```
