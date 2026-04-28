# CodeFlow Harness 当前实现说明

本文档记录当前仓库中 CodeFlow Harness 的具体实现。项目定位是基于 `mini-swe-agent v2` 的可信执行与验证 Harness，不重新实现 coding agent。

## 总体流程

`codeflow run` 的主流程位于 `codeflow/runner.py`：

1. 校验目标目录是 Git 仓库。
2. 校验目标工作区干净。
3. 读取项目规则 `.codeflow/project_rules.md`，不存在则使用默认规则。
4. 读取 `.codeflow/codeflow.yaml` 并合并 CLI 覆盖项。
5. 根据自然语言任务生成结构化 `Spec`。
6. 构造传给 mini-swe-agent 的初始 prompt，注入 Spec、project rules 和 Harness Policy。
7. 如果是 `--dry-run`，只返回 prompt，不创建分支、不调用 mini。
8. 创建 `ai/{task_slug}-{timestamp}` 分支。
9. 调用 mini-swe-agent 执行代码修改。
10. 运行 required checks，例如 `pytest -q`、`ruff check .`。
11. 运行 Harness Sensors，生成 sensor report。
12. checks 或可修复 sensor 失败时构造 repair prompt，最多自动修复 3 轮。
13. 读取 `git diff` 并生成 Markdown 风险审查报告。
14. 如果 `--no-commit`，保留当前状态并跳过人工确认。
15. 否则要求人工选择 `commit` / `rollback` / `keep`，commit 前按 policy 二次验证。

## CLI

入口在 `codeflow/cli.py`，命令为：

```bash
codeflow run \
  --repo ./examples/todo_api \
  --task "给 Todo 增加 due_date 字段，并补充测试" \
  --checks "pytest -q" \
  --max-repair-rounds 3 \
  --no-commit
```

主要参数：

- `--repo`：目标 Git 仓库路径。
- `--task`：自然语言编程任务。
- `--checks`：可重复传入的校验命令。
- `--max-repair-rounds`：最多修复轮数，当前上限为 3。
- `--model`：传给 mini-swe-agent 的模型名。
- `--mini-config`：传给 mini-swe-agent 的配置路径或配置 spec。
- `--no-commit`：不进入 commit / rollback / keep 交互。
- `--dry-run`：只生成 prompt，不调用 mini，不切分支。
- `--allow-high-risk-commit`：允许高风险 sensor 存在时继续提交。

## 核心数据结构

`codeflow/models.py` 定义了：

- `CodeFlowConfig`：CLI 到 runner 的配置对象。
- `Spec`：任务规格，包括目标、验收标准和约束。
- `CheckResult`：单条校验命令的结构化结果。
- `RunState`：一次 CodeFlow 运行的状态。
- `HarnessPolicy`：结构化 Harness Policy。
- `SensorResult` / `HarnessSensorReport`：sensor 输出与汇总结果。

`RunState.status` 表示主状态，例如：

- `dry_run`
- `checks_passed`
- `checks_failed`
- `committed`
- `rolled_back`
- `kept_uncommitted`
- `commit_refused_checks_failed`
- `sensor_failed`
- `review_required`

`RunState.commit_action` 单独记录提交相关动作：

- `pending`
- `not_requested`
- `skipped`
- `kept`
- `rolled_back`
- `committed`
- `refused`

这样 `--no-commit` 不会覆盖 `checks_passed` / `checks_failed`，调用方可以可靠判断校验结果。

## Git Guard

`codeflow/git_guard.py` 负责 Git 保护层：

- `ensure_git_repo()`：确认目标目录在 Git worktree 内。
- `ensure_clean_worktree()`：拒绝在脏工作区运行。
- `create_ai_branch()`：创建隔离分支 `ai/{slug}-{timestamp}`。
- `get_diff()`：读取当前 diff。
- `commit_changes()`：执行 `git add .` 和 `git commit -m`。
- `rollback()`：默认执行 `git restore .`。

人工选择 `rollback` 时，runner 会调用 `rollback(remove_untracked=True)`，额外删除当前 worktree 中未跟踪文件。实现没有使用无差别 `git clean -fd`，而是通过 `git ls-files --others --exclude-standard` 获取 Git 认为未跟踪且未忽略的文件，再逐项删除，并做路径边界检查，避免越界删除。

## Spec 与 Prompt

`codeflow/spec_builder.py` 当前使用规则生成第一版稳定 Spec，不调用 LLM。默认验收标准包括：

- 实现满足用户任务。
- 现有测试通过。
- 适当新增或更新测试。
- 不修改无关文件。

`codeflow/prompt_builder.py` 生成两类 prompt：

- `build_initial_prompt()`：初次交给 mini-swe-agent 的任务 prompt。
- `build_repair_prompt()`：checks 失败后，把失败命令、stdout、stderr 和原任务一起交给 mini-swe-agent 修复。

prompt 中包含任务、结构化 Spec、项目规则和 required checks。

## Harness Policy

`codeflow/harness/policy.py` 负责读取 `.codeflow/codeflow.yaml`。支持结构：

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

当前实现中，`project_rules.md` 作为文本 guidance 注入 prompt；`codeflow.yaml` 作为可执行 policy 驱动 checks、sensors、repair loop 和 governance。

## mini-swe-agent 调用

`codeflow/mini_runner.py` 使用 subprocess 调用本地 `mini` CLI。当前本地 mini-swe-agent v2.2.8 使用参数：

```bash
mini --task "<prompt>" --yolo --exit-immediately --output <trajectory.json>
```

实现细节：

- 日志和 trajectory 写入目标仓库的 `.git/codeflow/` 下，避免污染工作区 diff。
- 支持 `CODEFLOW_MINI_COMMAND` 覆盖 mini 命令，便于测试或调试。
- 如果 PATH 中没有 `mini`，且当前仓库存在本地 `mini-swe-agent/src`，会回退到 `python -m minisweagent.run.mini`。
- mini 返回非零退出码时抛出 `RuntimeError`，并指向日志文件。

### 模型配置

为支持真实 LLM 非交互运行，`mini_runner` 会读取启动目录下的 `.env`，或 `CODEFLOW_ENV_FILE` 指定的文件：

```bash
model_id="deepseek-v4-flash"
api_key="sk-..."
base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
```

这些值只在 mini 子进程环境中映射：

- `model_id` -> `MSWEA_MODEL_NAME` / `--model openai/{model_id}`
- `api_key` -> `OPENAI_API_KEY`
- `base_url` -> `OPENAI_BASE_URL` 和 `OPENAI_API_BASE`
- 自动设置 `MSWEA_CONFIGURED=true`，跳过 mini 的首次交互式配置向导。
- 使用 OpenAI-compatible base URL 时设置 `MSWEA_COST_TRACKING=ignore_errors`，避免未知模型成本表阻断运行。

如果用户已经设置标准环境变量，CodeFlow 不会覆盖它们。

## Test Gate

`codeflow/test_gate.py` 使用 `subprocess.run(..., shell=True)` 在目标仓库内逐条运行 checks：

- 保存命令、return code、stdout、stderr。
- stdout/stderr 最多保留末尾 8000 字符。
- `all_checks_passed()` 判断全部通过。
- `failed_checks()` 提取失败项用于 repair prompt。

## Harness Sensors

`codeflow/harness/builtin_sensors.py` 提供第一批可组合 sensor：

- `check_commands`：汇总 required checks。
- `forbidden_path`：检测 `.env`、secret、key 等敏感路径修改，命中为 high 且 blocking。
- `forbidden_path_write`：检测新增代码中对 `.env`、secret、key 等禁改路径的写入能力，防止通过新增 helper 间接写 forbidden path。
- `allowed_path`：配置 `allowed_paths` 时检测越界文件修改，命中为 high 且 blocking。
- `high_risk_path`：检测 policy 配置的高风险路径；默认命中为 medium warning，启用 `block_commit_on_high_risk` 时升级为 high 并要求 `--allow-high-risk-commit` 才能提交。
- `test_deletion`：检测删除测试函数、断言或 `pytest.raises`，命中为 high 且 blocking。
- `missing_test_change`：`require_test_change=true` 时，业务代码变更但未改测试会标记 medium warning。
- `dependency_change`：检测 `pyproject.toml`、`requirements.txt`、`poetry.lock`、`uv.lock` 等依赖文件变更。
- `secret_like_content`：检测新增 API key、token、secret-like 字符串，命中为 high 且 blocking。
- `max_diff`：diff 行数超过 policy 限制时 high 且 blocking。
- `no_change`：没有 diff 且没有 changed files 时 fail，防止原测试通过被误判为成功。

sensor report 会进入 repair prompt 和最终 review report。当前可自动 repair 的失败包括 checks、no-change、missing-test warning 和 dependency policy；forbidden path、forbidden path write、secret-like content、test deletion、大 diff 不做盲目 repair，直接进入 review-required / blocked 状态。

## Diff Reviewer

`codeflow/diff_reviewer.py` 生成 Markdown 审查报告，包含：

- Task
- Branch
- Validation
- Risk Level
- Risk Notes
- Diff Size
- Sensor Report
- Blocking Reasons
- Recommendation

风险评分是规则版：

- high：命中 `auth`、`permission`、`migration`、`.env`、`secret`、`password`、`token`、`delete`、`drop`
- medium：命中 `api`、`schema`、`model`、`database`、`config`
- low：没有明显高风险关键词

## 示例项目

`examples/todo_api` 是最小 Python 示例项目，包含：

- `app/todo.py`
- `tests/test_todo.py`
- `pyproject.toml`
- `README.md`

它本身也是一个独立 Git 仓库，用于验证 CodeFlow 对目标仓库的 Git 保护、分支隔离和校验流程。

## Benchmark

`benchmark/tasks.yaml` 定义了 3 个 todo_api 任务。`benchmark/run_benchmark.py` 会：

1. 为每个任务复制一份临时 todo_api 仓库。
2. 初始化临时 Git 仓库并提交 baseline。
3. 用 `no_commit=True` 调用 `run_codeflow()`。
4. 汇总 status、repair_round、checks_passed 和 report。
5. 输出 `benchmark/results.json`。

## 测试覆盖

当前测试包括：

- `tests/test_spec_builder.py`：Spec 生成。
- `tests/test_prompt_builder.py`：initial / repair prompt 内容。
- `tests/test_diff_reviewer.py`：风险评分和报告。
- `tests/test_git_guard.py`：Git 仓库检查、干净工作区、分支、diff、rollback。
- `tests/test_test_gate.py`：checks 成功/失败结果收集。
- `tests/test_runner.py`：dry-run 不切分支、no-commit 状态语义、人审 keep/rollback/commit、失败 commit 拒绝。
- `tests/test_mini_runner.py`：mini 调用环境映射、显式 model 优先级、已有标准环境变量保留。
- `tests/test_harness_policy.py`：policy fallback、yaml 解析、CLI 覆盖、prompt 注入。
- `tests/test_harness_sensors.py`：forbidden path、删除测试、无测试变更、无 diff、大 diff、依赖变更、checks fail。

已验证命令：

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/codeflow --help
.venv/bin/codeflow run --help
cd examples/todo_api && pytest -q
```

还使用 fake mini 验证了完整 pass/fail/repair/human approval 流程，并使用真实 LLM 验证了 `.env` 自动映射后的 mini-swe-agent 调用链路。

## 当前注意事项

- 根仓库提交时不要纳入 `.env`、`.venv/`、`mini-swe-agent/`、缓存目录和 benchmark 结果；这些已在 `.gitignore` 中忽略。
- `examples/todo_api` 是嵌套 Git 仓库。根仓库如果直接 `git add .`，Git 会把它作为嵌入仓库处理；如需根仓库完整追踪示例项目源码，需要先决定是否移除示例项目内部 `.git`，或接受 gitlink 形式。
- 真实 LLM 调用依赖外部模型服务和网络代理；当前环境已通过 `127.0.0.1:10087` 验证可用。
