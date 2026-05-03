# CodeFlow Harness 当前实现说明

本文档记录当前仓库中 CodeFlow Harness 的具体实现。项目定位是基于 `mini-swe-agent v2` 的可信执行与验证 Harness，不重新实现 coding agent。

## 总体流程

`codeflow run` 的主流程位于 `codeflow/runner.py`：

1. 校验目标目录是 Git 仓库。
2. 校验目标工作区干净。
3. 读取项目规则 `.codeflow/project_rules.md`，不存在则使用默认规则。
4. 读取 `.codeflow/codeflow.yaml` 并合并 CLI 覆盖项。
5. 根据自然语言任务生成结构化 `Spec`，按 policy 可调用 LLM 做语义增强。
6. 构造传给 mini-swe-agent 的初始 prompt，注入 Spec、project rules 和 Harness Policy。
7. 如果是 `--dry-run`，只返回 prompt，不创建分支、不调用 mini。
8. 创建 `ai/{task_slug}-{timestamp}` 分支。
9. 调用 mini-swe-agent 执行代码修改。
10. 运行 required checks，例如 `pytest -q`、`ruff check .`。
11. 运行 Harness Sensors，生成 sensor report。
12. checks 或可修复 sensor 失败时构造 repair prompt，最多自动修复 3 轮。
13. 读取 `git diff`，按 policy 可调用 LLM 做语义 diff review，并生成 Markdown 风险审查报告。
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

`codeflow/spec_builder.py` 当前使用规则生成第一版稳定 Spec。默认验收标准包括：

- 实现满足用户任务。
- 现有测试通过。
- 适当新增或更新测试。
- 不修改无关文件。

`codeflow/prompt_builder.py` 生成两类 prompt：

- `build_initial_prompt()`：初次交给 mini-swe-agent 的任务 prompt。
- `build_repair_prompt()`：checks 失败后，把失败命令、stdout、stderr 和原任务一起交给 mini-swe-agent 修复。

prompt 中包含任务、结构化 Spec、项目规则和 required checks。

如果 `semantic_spec: true` 且存在 OpenAI-compatible 模型配置，`codeflow/semantic.py`
会在规则 Spec 基础上补充语义验收条件、约束和审查备注。语义增强失败或未配置模型时不会阻断默认流程。
语义 diff review 会记录 `missing_config`、`timeout`、`api_error`、`invalid_json` 等结构化失败原因。

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
  allow_shell_checks: false
  semantic_spec: true
  semantic_review: true
  require_semantic_review: false
  semantic_timeout_seconds: 60
  semantic_max_diff_chars: 20000
  semantic_fail_open: true
  semantic_required_for_paths:
    - app/auth/
    - migrations/
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
`allow_shell_checks` 默认关闭；`semantic_spec` / `semantic_review` 默认在新初始化项目中开启但不强制，
`require_semantic_review`、`semantic_fail_open: false` 或 `semantic_required_for_paths` 命中后，
如果语义审查没有完成，会进入 `review_required` 并拒绝提交。

## mini-swe-agent 调用

`codeflow/mini_runner.py` 通过 `MiniExecutor` 协议调用 mini-swe-agent。默认仍使用
`SubprocessMiniExecutor` 调用本地 `mini` CLI：

```bash
mini --task-file <prompt.txt> --yolo --exit-immediately --output <trajectory.json>
```

实现细节：

- 日志和 trajectory 写入目标仓库的 `.git/codeflow/` 下，避免污染工作区 diff。
- prompt、日志和 trajectory 写入前后会做常见 secret-like 内容脱敏。
- 支持 `CODEFLOW_MINI_COMMAND` 覆盖 mini 命令，便于测试或调试。
- 如果 PATH 中没有 `mini`，会回退到当前环境中的 `python -m minisweagent.run.mini`。
- 支持 `CODEFLOW_MINI_EXECUTOR=subprocess|inprocess`；in-process 路径直接调用
  `minisweagent.run.mini.run_mini_in_process()`，并把 `ExecutorHook` 传入 mini 内部。
- in-process hook 会记录 model step、shell command、prompt/log/trajectory 写入事件；命中
  `rm -rf`、`curl | sh`、`wget | sh`、写 `.env`、`sudo`、`chmod 777`、
  `docker run --privileged` 或 forbidden path 写入时，会以 `policy_blocked` 阻断。
- mini 返回非零退出码时抛出 `MiniExecutionError`，并在日志中记录 `ERROR_TYPE`。
- 默认 mini 子进程超时为 3600 秒，可用 `CODEFLOW_MINI_TIMEOUT_SECONDS` 覆盖；超时时会终止子进程组并写入 mini log。
- 每次 mini 调用都会写入 `mini_run_N.events.jsonl`，记录结构化 `MiniEvent`。
- `MiniRunRequest` 记录 repo、prompt path、trajectory path、model、mini config、env、timeout 和 command。
- `MiniRunResult` 记录 `status`、`error_type` 和 `events_path`，当前可区分 `timeout`、
  `command_not_found`、`nonzero_exit`、`invalid_timeout`、`policy_blocked` 和
  `trajectory_missing`。

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
语义 Spec / Diff 审查默认复用同一套 OpenAI-compatible 配置，也可用
`CODEFLOW_SEMANTIC_MODEL` 指定单独模型。

## Test Gate

`codeflow/test_gate.py` 在目标仓库内逐条运行 checks：

- 保存命令、return code、stdout、stderr。
- stdout/stderr 最多保留末尾 8000 字符。
- `all_checks_passed()` 判断全部通过。
- `failed_checks()` 提取失败项用于 repair prompt。
- 默认使用 `shlex.split` 后直接执行命令，不经 shell 解释。
- stdout/stderr 会裁剪并脱敏后进入 artifact、repair prompt 和 report。
- 如果必须使用管道、重定向、`&&` 等 shell 语法，需要同时设置
  `allow_shell_checks: true` 并显式写 `shell:` 前缀；这类配置应来自可信项目。
  允许 shell 后，CodeFlow 会扫描 `rm -rf`、`curl | sh`、`wget | sh`、写 `.env`、
  `chmod 777`、`sudo`、`docker run --privileged` 等高风险片段，并在 doctor 和 sensor report 中提示。

## Harness Sensors

`codeflow/harness/builtin_sensors.py` 提供第一批可组合 sensor：

- `check_commands`：汇总 required checks。
- `shell_check_risk`：允许 shell checks 时提示高风险 shell 片段。
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

`codeflow/diff_reviewer.py` 生成结构化 `ReviewSummary` 和 Markdown 审查报告，包含：

- Task
- Branch
- Validation
- Risk Level
- Risk Notes
- Diff Size
- Sensor Report
- Blocking Reasons
- Recommendation

Runner 会写入 `review_summary.json`，其中包含统一的 `ReviewFinding` 列表。每条 finding 记录
`source`、`severity`、`category`、`file`、`message` 和 `recommendation`，来源可以是
`rules`、`sensor` 或 `semantic`。

风险评分是规则版：

- high：命中 `auth`、`permission`、`migration`、`.env`、`secret`、`password`、`token`、`delete`、`drop`
- medium：命中 `api`、`schema`、`model`、`database`、`config`
- low：没有明显高风险关键词

评分还会结合 changed files 和新增代码行为：`auth/`、`migrations/`、`secrets/` 等路径会提高风险；
新增 `shutil.rmtree`、`rm -rf`、破坏性 SQL 或 `chmod 777` 会直接标记为 high。

如果 `semantic_review: true` 或 `require_semantic_review: true` 且模型配置可用，
`codeflow/semantic.py` 会把脱敏后的 diff、changed files、checks 和 sensor report 发送给
OpenAI-compatible 模型，要求返回严格 JSON。语义风险会并入 Markdown report，并可在
`block_commit_on_high_risk` 时阻断提交。强制语义审查、路径强制语义审查或 fail-closed 策略下，
模型不可用会生成 high-risk 的 `semantic_review.json` 并把状态置为 `review_required`。

## 示例项目

`examples/todo_api` 是最小 Python 示例项目，包含：

- `app/todo.py`
- `tests/test_todo.py`
- `pyproject.toml`
- `README.md`

它本身也是一个独立 Git 仓库，用于验证 CodeFlow 对目标仓库的 Git 保护、分支隔离和校验流程。

## Benchmark

`benchmark/tasks/harness_bench.yaml` 定义了 Harness-Bench v0 任务。`benchmark/run_benchmark.py`
是兼容入口，内部转调 `benchmark/scripts/run_eval.py`。新的 benchmark 流程会：

1. 为每个任务复制一份独立 workspace。
2. 初始化临时 Git 仓库并提交 baseline。
3. 按 method 运行 `checks_only`、`raw_mini`、`codeflow_basic` 或 `codeflow_full`。
4. 汇总 status、repair_round、checks_passed、sensors 和 risk review。
5. 输出 `benchmark/results/{method}/{task_file_stem}_results.json` 和 Markdown 报告。

真实 LLM 评测支持 `--max-task-attempts`。每个 attempt 会追加到
`{task_file_stem}_retry_manifest.json`，记录模型、workspace、状态、耗时、错误和是否继续重试。
汇总报告会按 method 拆分 pass rate，避免把 `checks_only` baseline 和 `codeflow_full` 混成一个结论。

## Observability

一次运行的 artifact 写入目标仓库 `.git/codeflow/runs/{run_id}/`。CLI 支持：

- `codeflow inspect`：查看最新或指定 run 的状态摘要，支持 `--json` 和 recent list。
- `codeflow search`：按 run id、task、branch、status、risk level 搜索历史 run，支持 `--json`。
- `codeflow summary`：汇总 status、risk、每日 run 数、失败 run、checks/sensors pass rate 和平均 repair 轮数。
- `codeflow dashboard`：生成静态 HTML dashboard，展示汇总指标、每日趋势、finding category 和最近失败任务，并支持前端筛选。
- `codeflow serve`：用标准库 HTTP server 提供 dashboard 和 `/api/*` JSON endpoint；支持重复
  `--repo` 服务多个仓库、bearer token、可选 SQLite 索引，以及 `/api/runs`、`/api/findings`、
  `/api/trends`、`/api/failures` 等接口。
- `codeflow cleanup`：按 `--keep` 保留最近 run，支持 `--dry-run`。
- `codeflow report`：输出 `review_report.md` 或只打印路径。
- `codeflow export`：导出 zip。默认排除 prompt、mini 日志和 trajectory，避免无意泄露任务上下文；
  需要排查时可用 `--include-prompts`、`--include-logs`、`--include-trajectory` 显式包含。

写入 artifact 时会对 prompt、mini 日志、trajectory、diff、state 和 check 输出做常见
API key / token / private key 模式脱敏。脱敏是防护层，不替代 policy 中对 `.env`、secret path
和 secret-like content 的阻断。
每次 final state 写入后还会更新 `.git/codeflow/index.jsonl`，用于加速搜索、汇总和 dashboard。
服务化实现拆为 `codeflow/storage/` 和 `codeflow/server/`：

- `JsonlRunStore` 读取各仓库 `.git/codeflow/index.jsonl` 和 run artifact。
- `SQLiteRunStore` 可把多仓库 run / finding 同步到 SQLite，便于长期查询。
- `ObservabilityServerConfig` 组合 repos、token 和 sqlite db，并由 `handle_server_request()` 驱动可测试的 HTTP handler。

## 测试覆盖

当前测试包括：

- `tests/test_spec_builder.py`：Spec 生成。
- `tests/test_prompt_builder.py`：initial / repair prompt 内容。
- `tests/test_diff_reviewer.py`：风险评分、结构化 review summary 和报告。
- `tests/test_git_guard.py`：Git 仓库检查、干净工作区、分支、diff、rollback。
- `tests/test_test_gate.py`：checks 成功/失败结果收集、shell check policy、输出脱敏。
- `tests/test_runner.py`：dry-run 不切分支、no-commit 状态语义、人审 keep/rollback/commit、失败 commit 拒绝、语义审查强制阻断、diff 脱敏。
- `tests/test_mini_runner.py`：mini 调用环境映射、显式 model 优先级、已有标准环境变量保留、超时、错误分类和日志脱敏。
- `tests/test_harness_policy.py`：policy fallback、yaml 解析、CLI 覆盖、prompt 注入。
- `tests/test_harness_sensors.py`：forbidden path、删除测试、无测试变更、无 diff、大 diff、依赖变更、checks fail。
- `tests/test_semantic.py`：语义 Spec 增强、扩展 Diff 审查 schema 和失败原因记录。
- `tests/test_observability_cli.py`：inspect/report/export/search/summary/dashboard/serve response/cleanup。

已验证命令：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/uv-cache uv run mypy codeflow
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
git diff --check
```

还使用 fake mini 验证了完整 pass/fail/repair/human approval 流程，并使用真实 LLM 验证了 `.env` 自动映射后的 mini-swe-agent 调用链路。

## CI

`.github/workflows/ci.yml` 在 push / pull request 上运行 Python 3.11 和 3.12 矩阵：

- `uv sync --locked --group dev`
- `uv run ruff check .`
- `uv run mypy codeflow`
- `uv run pytest -q` 的稳定单元测试子集，并要求 `codeflow` 覆盖率不低于 70%

CI 默认排除 Docker/Podman、Singularity、SWE-bench container、extra environment 和真实 API fire tests。

## 当前注意事项

- 根仓库提交时不要纳入 `.env`、`.venv/`、缓存目录和 benchmark 结果；这些已在 `.gitignore` 中忽略。
- `examples/todo_api` 是嵌套 Git 仓库。根仓库如果直接 `git add .`，Git 会把它作为嵌入仓库处理；如需根仓库完整追踪示例项目源码，需要先决定是否移除示例项目内部 `.git`，或接受 gitlink 形式。
- 真实 LLM 调用依赖外部模型服务和网络代理；当前环境已通过 `127.0.0.1:10087` 验证可用。
