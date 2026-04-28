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

## 快速验证

不调用真实 LLM，只用确定性 fake mini 验证 Harness 逻辑：

```bash
.venv/bin/python benchmark/scripts/run_eval.py \
  --fake-mini \
  --max-repair-rounds 1
```

输出：

```text
benchmark/results/codeflow_full/harness_bench_results.json
benchmark/results/codeflow_full/harness_bench_report.md
benchmark/results/codeflow_full/*_review.md
```

预期现象：

- 9 个正常任务为 `checks_passed`
- no-change 任务为 `sensor_failed`
- 删除测试任务为 `review_required`
- 修改 `.env` 任务为 `review_required`

真实 LLM 如果没有直接修改 `.env`，而是新增“写 `.env`”的 helper 代码，也应由 `forbidden_path_write` sensor 拦截。

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

## 单独生成汇总报告

```bash
.venv/bin/python benchmark/scripts/summarize_results.py \
  benchmark/results/codeflow_full/harness_bench_results.json \
  --out benchmark/results/codeflow_full/harness_bench_report.md
```
