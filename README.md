# CodeFlow Agent

CodeFlow Agent 是一个面向 Python 项目的可信 AI 编程工作流包装层。它不重新实现 coding agent，而是在 `mini-swe-agent v2` 外层增加 Git 分支隔离、任务规格化、项目规则注入、测试门禁、失败修复循环、Diff 风险审查和人工确认。

## 功能

- Git 分支隔离
- 结构化任务 Spec
- 项目规则注入
- pytest / ruff 校验门禁
- 基于 mini-swe-agent 的失败修复循环
- Diff 风险审查报告
- commit / rollback / keep 人工确认
- 小型 benchmark

## 安装

推荐使用当前目录下的 uv 环境：

```bash
uv sync
```

也可以使用 pip：

```bash
pip install -e .
pip install mini-swe-agent
```

本仓库的 `pyproject.toml` 已配置 uv 从本地 `mini-swe-agent/` 克隆安装依赖。

## 使用

目标项目必须是干净的本地 Git 仓库：

```bash
cd examples/todo_api
git init
git add .
git -c user.email=codeflow@example.local -c user.name=CodeFlow commit -m init
cd ../..
```

运行 CodeFlow：

```bash
codeflow run \
  --repo ./examples/todo_api \
  --task "给 Todo 增加 due_date 字段，并补充测试" \
  --checks "pytest -q" \
  --no-commit
```

只生成 prompt、不调用 mini-swe-agent：

```bash
codeflow run \
  --repo ./examples/todo_api \
  --task "给 Todo 增加 due_date 字段，并补充测试" \
  --checks "pytest -q" \
  --dry-run \
  --no-commit
```

如果本地 `mini` 不在 PATH 中，可以设置：

```bash
export CODEFLOW_MINI_COMMAND="python -m minisweagent.run.mini"
```

## 模型配置

CodeFlow 默认不会写入 mini-swe-agent 的全局配置。运行时会读取启动目录下的 `.env`，也可以用 `CODEFLOW_ENV_FILE` 指向其他文件：

```bash
model_id="deepseek-v4-flash"
api_key="sk-..."
base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
```

这些值会只在子进程中映射为 OpenAI-compatible 环境变量，并自动跳过 mini 的首次交互式配置向导。也可以直接使用标准环境变量：

```bash
export MSWEA_MODEL_NAME="openai/deepseek-v4-flash"
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
```

## 项目规则

在目标仓库中创建 `.codeflow/project_rules.md`：

```markdown
- Do not delete existing tests.
- Do not modify .env files.
- Keep changes minimal.
- Add tests for new behavior.
```

如果没有该文件，CodeFlow 会使用默认规则。

## Benchmark

```bash
python benchmark/run_benchmark.py
```

运行结果会写入 `benchmark/results.json`。每个任务会复制一份临时示例仓库，避免多个任务之间的 Git 状态互相污染。
