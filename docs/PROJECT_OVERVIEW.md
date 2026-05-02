# CodeFlow Harness 项目说明

本文档汇总当前仓库的项目定位、已完成功能、核心实现、benchmark 体系、测试覆盖和当前边界。它面向后续开发者快速接手项目，不替代接口级文档和源码注释。

## 1. 项目定位

CodeFlow Harness 是一个面向 Python 项目的 AI Coding Agent 可信执行与验证 Harness。它不重新实现 coding agent，而是把已集成到仓库中的 `mini-swe-agent v2` 作为代码执行器，然后在外层提供工程化控制能力：

- 把用户自然语言任务转换为结构化 Spec 和执行约束。
- 按 policy 可调用 OpenAI-compatible LLM 做语义 Spec 增强和 Diff 审查。
- 注入项目规则和 Harness Policy。
- 在干净 Git 仓库中创建隔离分支执行任务。
- 调用 mini-swe-agent 修改代码。
- 运行测试、ruff 等 required checks。
- 运行一组风险 sensors。
- 根据失败结果构造 repair prompt 并再次调用 agent。
- 生成 Markdown 审查报告。
- 对 prompt、日志、diff、state 和 check 输出中的常见 secret-like 内容做脱敏。
- 提供 commit / rollback / keep 人工治理流程。
- 提供 benchmark 数据准备、运行和汇总能力。

当前项目的核心分工是：

```text
mini-swe-agent v2 = Executor
CodeFlow Harness = Guidance + Sensors + Control Loop + Governance + Observability + Evaluation
```

## 2. 仓库结构

主要目录如下：

```text
.
├── codeflow/                 # CodeFlow Harness 主实现
├── codeflow/harness/         # Harness Policy、Guidance 和 Sensors
├── benchmark/                # benchmark 任务、脚本、报告
├── docs/                     # 设计和实现说明文档
├── examples/                 # 小型示例项目和对应 codeflow.yaml
├── minisweagent/             # 已整合的 mini-swe-agent 执行器源码
├── tests/                    # CodeFlow 自身测试
├── pyproject.toml            # 顶层包配置，统一安装 codeflow 与 minisweagent
├── README.md                 # 用户入口说明
└── benchmark.md              # benchmark 设计草案和任务规划记录
```

生成物默认不入库：

- `benchmark/generated/`
- `benchmark/workspaces/`
- `benchmark/results/`
- `benchmark/datasets/`
- `.venv/`
- cache、coverage、egg-info 等本地构建产物

## 3. 安装与入口

顶层 `pyproject.toml` 定义包名为 `codeflow-agent`，Python 版本要求为 `>=3.10`。依赖包括 `pydantic`、`typer`、`rich`、`pyyaml`、`python-dotenv`、`datasets`、`litellm`、`openai` 等。

项目脚本入口：

- `codeflow = codeflow.cli:app`
- `mini = minisweagent.run.mini:app`
- `mini-swe-agent = minisweagent.run.mini:app`
- `mini-extra = minisweagent.run.utilities.mini_extra:main`
- `mini-e = minisweagent.run.utilities.mini_extra:main`

`setuptools` 从根目录统一发现包：

```toml
where = ["."]
include = ["codeflow*", "minisweagent*"]
```

这意味着外层 `uv sync` 或 `pip install -e .` 会同时安装 CodeFlow 和本仓库根目录下的 `minisweagent/` 源码。

## 4. 用户使用流程

典型命令：

```bash
codeflow run \
  --repo ./examples/todo_api \
  --task "给 Todo 增加 due_date 字段，并补充测试" \
  --checks "pytest -q" \
  --no-commit
```

常用参数：

- `--repo`：目标 Git 仓库路径。
- `--task`：自然语言任务。
- `--checks`：required checks，可重复传入。
- `--max-repair-rounds`：最大 repair 轮数，当前上限为 3。
- `--model`：传给 mini-swe-agent 的模型名。
- `--mini-config`：传给 mini-swe-agent 的配置文件或配置 spec。
- `--dry-run`：只生成 prompt，不创建分支、不调用 agent。
- `--no-commit`：跳过人工 commit / rollback / keep 交互。
- `--allow-high-risk-commit`：在启用高风险阻断时允许提交。

目标项目必须是干净的 Git worktree。CodeFlow 会拒绝在脏工作区运行，以避免覆盖用户未保存的工作。

## 5. 主执行流程

主流程位于 `codeflow/runner.py`，`codeflow run` 会执行以下步骤：

1. 将 `repo` 解析为绝对路径。
2. 校验目标目录是 Git worktree。
3. 校验工作区干净。
4. 读取 `.codeflow/project_rules.md`，不存在时使用默认项目规则。
5. 读取 `.codeflow/codeflow.yaml`，并应用 CLI checks / repair rounds 覆盖。
6. 使用规则生成结构化 `Spec`，可选调用 LLM 做语义增强。
7. 构造初始 prompt，注入 Spec、项目规则、Harness Policy 和 required checks。
8. `--dry-run` 时直接返回 prompt。
9. 创建 `ai/{task_slug}-{timestamp}` 分支。
10. 调用 mini-swe-agent 执行代码修改。
11. 运行 required checks。
12. 读取 Git diff 和 changed files。
13. 运行 built-in sensors。
14. 如果 checks 和 sensors 都通过，状态为 `checks_passed`。
15. 如果存在可修复失败，构造 repair prompt 并再次调用 mini-swe-agent。
16. 如果存在不可盲目修复的风险 sensor，状态进入 `review_required`。
17. 可选调用 LLM 做语义 diff review，并生成 Markdown Review Report。
18. `--no-commit` 时保留修改并结束。
19. 否则要求人工选择 `commit` / `rollback` / `keep`。
20. commit 前按 policy 可再次运行 checks 和 sensors。

## 6. 核心数据模型

数据结构定义在 `codeflow/models.py`：

- `CodeFlowConfig`：CLI 参数到 runner 的配置对象。
- `HarnessPolicy`：结构化 policy，包括 checks、路径约束、diff 限制、治理策略等。
- `Spec`：任务类型、目标、验收标准和约束。
- `CheckResult`：单条校验命令的执行结果。
- `SensorContext`：sensor 运行所需上下文。
- `SensorResult`：单个 sensor 的结果。
- `HarnessSensorReport`：sensor 汇总结果。
- `RunState`：一次运行的完整状态。

主要运行状态包括：

- `initialized`
- `dry_run`
- `checks_passed`
- `checks_failed`
- `sensor_failed`
- `review_required`
- `commit_refused_checks_failed`
- `commit_refused_sensor_failed`
- `commit_refused_high_risk`
- `committed`
- `rolled_back`
- `kept_uncommitted`

`RunState.commit_action` 单独记录提交动作，例如 `skipped`、`committed`、`rolled_back`、`kept`、`refused`，避免 `--no-commit` 覆盖验证状态。

## 7. Git 保护层

Git 保护逻辑在 `codeflow/git_guard.py`：

- `ensure_git_repo()`：确认目标目录是 Git worktree。
- `ensure_clean_worktree()`：拒绝脏工作区。
- `slugify()`：生成分支名片段，支持中文字符并限制长度。
- `create_ai_branch()`：创建隔离分支。
- `get_diff()`：获取 tracked diff，同时为未跟踪文件生成 no-index diff。
- `get_changed_files()`：合并 tracked changed files 和 untracked files。
- `commit_changes()`：执行 `git add .` 和 `git commit -m`。
- `rollback()`：执行 `git restore .`，可选删除 Git 认为未跟踪且未忽略的文件。

rollback 删除未跟踪文件时会做路径边界检查，拒绝删除仓库根目录外的路径。

## 8. Spec 和 Prompt

`codeflow/spec_builder.py` 当前使用规则生成基础 Spec。`semantic_spec: true` 且模型配置可用时，
`codeflow/semantic.py` 会在基础 Spec 上补充语义验收条件、约束和备注。默认验收标准包括：

- 实现满足用户任务。
- 现有测试通过。
- 必要时新增或更新测试。
- 不修改无关文件。

默认约束包括：

- 不删除现有测试。
- 不绕过失败测试。
- 不修改环境密钥。
- 保持修改最小且相关。

`codeflow/prompt_builder.py` 生成两类 prompt：

- `build_initial_prompt()`：初始执行 prompt。
- `build_repair_prompt()`：修复 prompt，包含失败命令、return code、stdout、stderr、sensor report 和 blocking reasons。

`codeflow/harness/guidance.py` 负责把 Spec、project rules 和 policy 格式化为 Guidance Context。

## 9. Harness Policy

Policy 读取逻辑在 `codeflow/harness/policy.py`。目标仓库可配置 `.codeflow/codeflow.yaml`：

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
    - .env.*
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
  governance:
    block_commit_on_failed_checks: true
    block_commit_on_high_risk: false
    require_human_approval: true
    rerun_checks_before_commit: true
```

加载规则：

- 顶层可以是 `harness:` 包裹，也可以直接是 policy 字段。
- `governance` 子字段会 flatten 到 `HarnessPolicy`。
- CLI `--checks` 覆盖 YAML 中的 `required_checks`。
- CLI `--max-repair-rounds` 覆盖 YAML 中的 `max_repair_rounds`。

默认值来自 `codeflow/config.py` 和 `HarnessPolicy`：

- 默认 checks：`pytest -q`
- 默认最大 repair 轮数：3
- 默认 forbidden paths：`.env`、`.env.*`、`secrets/`、`credentials/`、`*.pem`、`*.key`
- 默认允许依赖变更，但示例项目均配置为不允许
- 默认不允许 shell checks；需要时显式设置 `allow_shell_checks: true`
- 默认模型类字段不强制语义审查；`codeflow init` 模板会开启可选 `semantic_spec` 和 `semantic_review`
- 默认 commit 前重新验证

## 10. mini-swe-agent 集成

`codeflow/mini_runner.py` 通过 subprocess 调用 mini-swe-agent：

```bash
mini --task "<prompt>" --yolo --exit-immediately --output <trajectory.json>
```

实现细节：

- 每次调用生成一个短 UUID run id。
- prompt、日志和 trajectory 写入目标仓库的 `.git/codeflow/` 下，避免污染工作区 diff，并会做常见 secret-like 内容脱敏。
- 支持 `CODEFLOW_MINI_COMMAND` 覆盖 mini 命令，benchmark 的 fake mini 也通过这个变量接入。
- 如果 PATH 中有 `mini`，优先使用它。
- 如果没有 `mini`，回退到当前环境中的 `python -m minisweagent.run.mini`。
- mini 返回非零时抛出 `RuntimeError`，日志路径会写入错误信息。
- prompt 文件保留在 run artifact 目录中用于审计；`codeflow export` 默认排除 prompt，需要时可显式包含。
- mini 子进程默认 3600 秒超时，可通过 `CODEFLOW_MINI_TIMEOUT_SECONDS` 覆盖；超时时会终止子进程组并写入 log 后失败。

模型和 API 配置：

- 默认读取启动目录下 `.env`。
- 可用 `CODEFLOW_ENV_FILE` 指向其他 env 文件。
- 支持字段 `model_id`、`api_key`、`base_url`。
- `model_id` 会映射为 `MSWEA_MODEL_NAME` 或 `--model openai/{model_id}`。
- `api_key` 映射为 `OPENAI_API_KEY`。
- `base_url` 映射为 `OPENAI_BASE_URL` 和 `OPENAI_API_BASE`。
- 自动设置 `MSWEA_CONFIGURED=true`，跳过 mini 的首次交互式配置。
- 使用 OpenAI-compatible base URL 时设置 `MSWEA_COST_TRACKING=ignore_errors`。
- 如果用户已经设置标准环境变量，CodeFlow 不覆盖。
- 语义 Spec / Diff 审查复用同一套 OpenAI-compatible 配置，也可用 `CODEFLOW_SEMANTIC_MODEL` 指定单独模型。

## 11. Checks 和 Sensors

### Checks

`codeflow/test_gate.py` 在目标仓库内逐条执行 checks：

- 捕获 return code、stdout、stderr。
- stdout/stderr 最多保留末尾 8000 字符。
- stdout/stderr 会在写入 artifact、repair prompt 和 report 前脱敏。
- `all_checks_passed()` 判断全部通过。
- `failed_checks()` 为 repair prompt 提取失败项。
- 默认使用 `shlex.split` 后直接执行，不经 shell 解释。
- 需要管道、重定向或 `&&` 时必须设置 `allow_shell_checks: true` 并显式使用 `shell:` 前缀，且应只来自可信配置。

### Sensors

内置 sensors 在 `codeflow/harness/builtin_sensors.py`：

| Sensor | 作用 | 失败/警告行为 |
| --- | --- | --- |
| `check_commands` | 汇总 required checks | checks 失败时 high |
| `forbidden_path` | 检测禁改路径变更 | high blocking |
| `forbidden_path_write` | 检测新增代码对禁改路径的写入能力 | high blocking |
| `allowed_path` | 限制只能修改 allowed paths | high blocking |
| `high_risk_path` | 标记配置的高风险路径 | 默认 medium；启用 high-risk block 时 high |
| `test_deletion` | 检测删除测试函数、断言、`pytest.raises` | high blocking |
| `missing_test_change` | 业务代码变更但没有测试变更 | medium warning |
| `dependency_change` | 检测依赖文件变更 | policy 禁止时 high，否则 medium |
| `secret_like_content` | 检测新增 secret-like 内容 | high blocking |
| `max_diff` | 限制 diff 行数 | 超限 high blocking |
| `no_change` | 防止无修改被误判为成功 | medium failure |

当前可自动 repair 的 sensor 失败：

- `check_commands`
- `dependency_change`
- `missing_test_change`
- `no_change`

以下风险不会盲目 repair，会进入审查或阻断路径：

- forbidden path
- forbidden path write
- secret-like content
- test deletion
- max diff
- allowed path 越界

近期已修正的误报：

- parser 变量名 `token` 不再触发 high-risk diff reviewer；只检测更具体的 `access_token`、`api_token`、`auth_token`、`refresh_token`。
- `test_deletion` 只检查测试文件 hunk，且测试断言等价改写不再被误判为删除测试。

## 12. Diff Reviewer 和报告

`codeflow/diff_reviewer.py` 生成 Markdown 审查报告，包含：

- 任务
- 分支
- 验证结果
- 风险等级
- 风险说明
- Sensor Report
- Blocking Reasons
- Semantic Review
- Diff 大小
- 建议

风险评分是规则版：

- high：`auth`、`permission`、`migration`、`.env`、`secret`、`password`、具体 token 名、`delete`、`drop`
- medium：`api`、`schema`、`model`、`database`、`config`
- low：没有明显高风险关键词

如果 sensor report 的最高 severity 高于 diff reviewer 评分，会以 sensor severity 作为最终风险等级。
如果 `semantic_review: true` 或 `require_semantic_review: true` 且模型配置可用，
`codeflow/semantic.py` 会把脱敏 diff、changed files、checks 和 sensor report 发送给
OpenAI-compatible 模型，返回的风险等级、发现和建议会并入报告。语义审查 high risk 且
`block_commit_on_high_risk: true` 时会阻断提交；强制语义审查不可用时会进入 `review_required`。

## 13. 示例项目

`examples/` 下有三个小型 Python 项目，用于本地演示和 benchmark：

- `examples/todo_api`：Todo 数据模型和测试。
- `examples/file_utils`：文本工具库。
- `examples/student_manager`：学生信息管理库。

每个示例项目都有 `.codeflow/codeflow.yaml`，配置：

- required checks：`pytest -q`、`ruff check .`
- allowed paths：业务目录和 `tests/`
- forbidden paths：env、secret、credential、key 等
- high risk paths：配置、迁移、认证或部署目录
- `require_test_change: true`
- `allow_dependency_change: false`
- `allow_delete_tests: false`
- commit 前重新验证

## 14. Benchmark 体系

Benchmark 代码集中在 `benchmark/scripts/`。

### 通用运行器

`benchmark/scripts/run_eval.py` 支持四种 method：

- `checks_only`：只运行原始仓库 checks，作为 baseline。
- `raw_mini`：直接把任务交给 mini-swe-agent，随后采集 checks 和 diff review。
- `codeflow_basic`：使用 CodeFlow 初始 prompt、checks 和 repair loop，但不跑 sensors。
- `codeflow_full`：完整运行 CodeFlow Harness，包括 policy、sensors、repair loop 和 review。

每个任务会生成独立 workspace：

1. 从 `source_repo` 复制任务仓库。
2. 执行可选 `setup_commands`。
3. 初始化 Git 仓库并提交 baseline。
4. 写入 benchmark 专用 `.git/info/exclude`。
5. 运行指定 method。
6. 输出 JSON 结果、任务 review 和 Markdown 汇总。

结果字段包括：

- `id`
- `dataset`
- `method`
- `status`
- `checks_passed`
- `repair_rounds`
- `risk_level`
- `review_risk_level`
- `unsafe_diff`
- `test_deleted`
- `forbidden_path_modified`
- `forbidden_path_write`
- `secret_like_content`
- `missing_test_warning`
- `no_change`
- `runtime_seconds`
- `changed_files`
- `sensor_results`
- `check_results`

### 数据准备脚本

- `prepare_harness_bench.py`：为自建 Harness-Bench 准备 workspace。
- `prepare_quixbugs.py`：从 QuixBugs Python 程序和 JSON testcases 生成 pytest 项目。
- `prepare_bugsinpy.py`：解析 BugsInPy metadata，可只生成 task YAML，也可通过 `bugsinpy-checkout` 准备真实 workspace。
- `prepare_swebench.py`：下载 SWE-bench Lite / Verified metadata，可 clone GitHub repo、checkout base commit、应用 test patch、执行 setup recipe。
- `summarize_results.py`：合并多个 `*_results.json` 并生成 Markdown 报告。
- `check_llm_env.py`：验证 `.env` 中 LLM API 配置，并做一次最小 chat completions 请求。
- `fake_mini.py`：确定性 fake mini，用于不调用真实 LLM 的 harness 逻辑测试。

### 已接入数据集

- 自建 Harness-Bench v0：12 个任务，覆盖正常开发和风险场景。
- QuixBugs：已有 `quixbugs.yaml` smoke 子集和 `quixbugs_extended.yaml` 31 任务扩展子集。
- BugsInPy：已有 youtube-dl 子集，当前重点是 `bugsinpy_youtubedl_5.yaml`。
- SWE-bench Lite / Verified：已有 1-task 和 2-task mini subset JSONL，当前真实 runnable 子集主要是 Astropy 任务。

## 15. 当前 benchmark 结果

最新提交中已更新 `benchmark/reports/current_real_results.md`。当前汇总为 80 条结果记录，
报告按 method 单独展示 baseline 与 agent 通过率：

- baseline `checks_only`：40 个任务全部失败，符合原始 bug 对照预期，method pass rate 为 0/40。
- `codeflow_full`：40 个任务全部通过，method pass rate 为 40/40。
- unsafe diff：0。
- review high risk：0。
- no-change/test-deletion/forbidden/secret 等风险检测误报：0。

按数据集拆分：

| Dataset | Method | Tasks | Passed |
| --- | --- | ---: | ---: |
| QuixBugs extended | checks_only | 31 | 0 |
| QuixBugs extended | codeflow_full | 31 | 31 |
| BugsInPy youtube-dl 5 | checks_only | 5 | 0 |
| BugsInPy youtube-dl 5 | codeflow_full | 5 | 5 |
| SWE-bench Lite 2 | checks_only | 2 | 0 |
| SWE-bench Lite 2 | codeflow_full | 2 | 2 |
| SWE-bench Verified 2 | checks_only | 2 | 0 |
| SWE-bench Verified 2 | codeflow_full | 2 | 2 |

注意：`benchmark/results/`、`benchmark/generated/` 和 workspace 仍是忽略目录。当前入库的是任务文件、
脚本、汇总报告和合并后的 `benchmark/reports/current_real_results.json`；如果需要复核完整 workspace
状态，仍需要在本机保留生成目录或重新运行 benchmark。

## 16. 测试覆盖

CodeFlow 自身测试在 `tests/`，当前覆盖：

- Spec 生成。
- prompt 和 repair prompt 构造。
- diff reviewer 风险评分和语义审查报告合并。
- Git guard：分支、diff、rollback、脏工作区拒绝。
- Test gate：checks 运行、失败提取、shell policy 和输出脱敏。
- Runner：dry-run、no-commit 状态语义、人工审批路径、commit 拒绝、强制语义审查阻断、diff 脱敏。
- mini runner：`.env` 映射、显式 model 覆盖、标准 OpenAI env 保留、超时和日志脱敏。
- Harness policy：默认值、YAML 解析、governance flatten、CLI 覆盖。
- Sensors：forbidden path、allowed path、forbidden write、test deletion、missing test、no change、max diff、dependency、secret-like、high risk path。
- Semantic：语义 Spec 增强和 Diff 审查 JSON 适配。
- Observability CLI：inspect、report、export、search、summary、dashboard。
- Benchmark 准备和汇总：QuixBugs、BugsInPy、SWE-bench JSONL、checks-only、workspace artifact 排除、多结果汇总。

最近一次完整验证通过：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/uv-cache uv run mypy codeflow
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
git diff --check
```

## 17. 当前已完成能力清单

已完成：

- 顶层 `pyproject.toml` 整合 CodeFlow 与 mini-swe-agent。
- `mini` / `mini-swe-agent` / `codeflow` CLI 入口。
- Git 仓库校验、干净工作区校验、隔离分支。
- 默认 project rules 和 `.codeflow/project_rules.md` 读取。
- `.codeflow/codeflow.yaml` policy 读取、governance flatten、CLI 覆盖。
- 规则版 Spec 生成。
- 可选 LLM 语义 Spec 增强和 Diff 审查，支持失败原因记录、路径强制审查和 fail-closed policy。
- 初始 prompt 与 repair prompt。
- mini-swe-agent 非交互调用。
- mini executor 抽象、错误分类和 trajectory missing 状态记录。
- `.env` 到 OpenAI-compatible 环境变量映射。
- mini 子进程超时和子进程组终止保护。
- checks 执行和失败日志裁剪。
- shell checks 默认禁用，需 policy 显式允许。
- shell checks 风险扫描，doctor 和 sensor report 会提示高风险 shell 片段。
- built-in sensors。
- repair loop。
- prompt、mini 日志、trajectory、diff、state 和 check 输出脱敏。
- Markdown review report 和结构化 `review_summary.json`。
- `codeflow inspect` / `search` / `summary` / `dashboard` / `serve` / `cleanup` / `report` / `export` 运行结果查看、汇总、本地服务、清理和导出。
- `.git/codeflow/index.jsonl` run 索引，支持 finding counts/category 聚合。
- commit / rollback / keep 人工治理。
- commit 前二次验证。
- GitHub Actions CI，覆盖 ruff、mypy、稳定单元测试子集和覆盖率门槛。
- Harness-Bench、自建示例项目、QuixBugs、BugsInPy、SWE-bench mini subset。
- fake mini 离线验证能力。
- 当前真实 LLM benchmark 汇总报告，报告已按 method 拆分 baseline 与 full run。

## 18. 当前边界和后续改进点

当前仍不是完整产品化平台。主要边界：

- 语义 Spec / Diff 审查依赖 OpenAI-compatible 模型配置；强制策略已能阻断不可用场景，但模型质量仍需要人工评估。
- diff review 已有结构化 findings、规则、sensors 和可选语义审查，但高风险变更仍需要人工确认业务语义。
- Observability 已有 run 索引、inspect、search、summary、dashboard、serve、cleanup、report 和 export；serve 是轻量本地 HTTP 服务，还不是多用户长期运行平台。
- `benchmark/generated/` 和 `benchmark/results/` 不入库，fresh clone 需要重新准备 runnable workspaces 才能跑 SWE-bench / BugsInPy 真实任务。
- SWE-bench 当前只验证了很小的 Astropy mini subset，还不是全量 SWE-bench 结论。
- BugsInPy 当前重点验证 youtube-dl 5 个任务，还没有大规模跨项目覆盖。
- benchmark 中真实 LLM 结果受模型、网络、代理和依赖缓存影响，长期回归仍需要把 raw artifact 按策略归档。
- `test_gate.py` 默认不经 shell 解释 checks；允许 shell 后已有风险扫描，但仍要求这类配置来自可信项目。
- `mini_runner.py` 已有 executor 抽象和错误分类，默认仍通过 subprocess 调 mini；还没有稳定接入 mini 内部 API 做实时拦截。
- 完整测试中会按条件跳过 Docker/Podman、Singularity、Contree/Modal 和真实 API provider 相关用例；这些依赖需要本机环境提供。

建议后续优先级：

1. 增加可选 raw JSON / workspace artifact 归档策略，至少归档关键 summary 和失败样本。
2. 扩大 BugsInPy 和 SWE-bench runnable 子集。
3. 为 real benchmark 增加长期回归脚本和趋势对比，基于现有 per-task retry manifest 做稳定性统计。
4. 在 mini 内部 API 稳定后，增加 in-process executor 和实时 policy hook。
