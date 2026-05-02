# CodeFlow Harness

Harness Engineering for Reliable AI Coding Agents.

CodeFlow Harness 是一个面向 Python 项目的 AI Coding Agent 可信执行与验证 Harness。它不重新实现 coding agent，而是把 `mini-swe-agent v2` 作为 Executor，并在外层提供：

- feed-forward guidance
- validation sensors
- repair control loops
- risk governance
- audit logs
- benchmark evaluation

换句话说，`mini-swe-agent v2` 负责执行代码修改，CodeFlow Harness 负责让执行过程可约束、可验证、可修复、可审查、可量化。

## 功能

- Git 分支隔离
- 结构化任务 Spec
- 项目规则注入
- pytest / ruff 校验门禁
- forbidden path / test deletion / no-change / max-diff sensors
- 结构化 `codeflow.yaml` Harness Policy
- 基于 mini-swe-agent 的失败修复循环
- Diff 风险审查报告
- run inspect / report / export
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
```

`mini-swe-agent` 源码已并入本仓库根目录的 `minisweagent/` 包，由外层 `pyproject.toml` 统一安装。

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

查看和导出运行结果：

```bash
codeflow inspect --repo ./examples/todo_api --latest
codeflow report --repo ./examples/todo_api --latest
codeflow export --repo ./examples/todo_api --latest --out ./codeflow-run.zip
```

`codeflow export` 默认不包含 prompt、mini 日志和 trajectory；需要排查时再显式加
`--include-prompts`、`--include-logs` 或 `--include-trajectory`。

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

## Harness Policy

在目标仓库中创建 `.codeflow/codeflow.yaml` 可以启用结构化策略：

```yaml
harness:
  required_checks:
    - pytest -q
    - ruff check .
  max_repair_rounds: 3
  max_diff_lines: 500
  allowed_paths:
    - app/
    - tests/
  forbidden_paths:
    - .env
    - secrets/
    - credentials/
    - "*.pem"
    - "*.key"
  high_risk_paths:
    - app/auth/
    - app/db/
    - migrations/
    - config/
  require_test_change: true
  allow_dependency_change: false
  allow_delete_tests: false
  governance:
    block_commit_on_failed_checks: true
    block_commit_on_high_risk: false
    require_human_approval: true
    rerun_checks_before_commit: true
```

优先级：

```text
CLI 参数 > codeflow.yaml > project_rules.md > 默认值
```

当前 `project_rules.md` 仍作为 prompt guidance 注入，`codeflow.yaml` 则作为可执行 Harness Policy 驱动 checks、sensors、repair 和 commit policy。

`required_checks` 默认不经 shell 解释，CodeFlow 会用 `shlex.split` 后直接执行命令。
确实需要 shell 语法时使用显式前缀，例如 `shell: cd app && pytest -q`；这类 check 应只来自可信配置。

## Sensors

当前内置 sensors：

- `check_commands`：汇总 pytest / ruff 等 required checks。
- `forbidden_path`：阻止 `.env`、secret、key 等敏感路径变更。
- `forbidden_path_write`：阻止新增代码绕过路径变更、间接写入 `.env` 等禁改路径。
- `allowed_path`：配置 `allowed_paths` 时阻止越界文件修改。
- `high_risk_path`：标记高风险路径，需要人工重点审查。
- `test_deletion`：检测删除测试断言或测试函数。
- `missing_test_change`：功能代码变更但没有测试变更时给出 warning。
- `dependency_change`：检测依赖文件变更，并可按 policy 阻断。
- `secret_like_content`：检测新增的 API key / token / secret-like 内容。
- `max_diff`：限制过大的 diff。
- `no_change`：防止“未修改代码但原有测试通过”被误判为成功。

## Benchmark

```bash
python benchmark/run_benchmark.py
```

这是兼容入口，内部调用 `benchmark/scripts/run_eval.py` 和 `benchmark/tasks/harness_bench.yaml`。
运行结果会写入 `benchmark/results/codeflow_full/`。每个任务会复制一份独立 workspace，
避免多个任务之间的 Git 状态互相污染。

完整测试中部分 mini-swe-agent 环境测试会按条件跳过，例如 Docker/Podman、Singularity、
Contree/Modal 依赖和真实 API key。Python 可选依赖可用 `uv sync --extra full` 安装；容器运行时和
provider API key 仍需要由本机环境提供。
