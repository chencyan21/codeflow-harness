# CodeFlow Harness 项目介绍报告

## 1. 一句话定位

CodeFlow Harness 是一个面向 Python 项目的 AI Coding Agent 可信执行与验证外层系统。它不从零实现 coding agent，而是把仓库内集成的 `mini-swe-agent v2` 作为执行器，在外层补齐工程化能力：任务结构化、策略注入、Git 隔离、测试门禁、风险传感器、失败修复循环、人工治理、审计日志、可视化和 benchmark。

项目的核心分工可以记成：

```text
mini-swe-agent v2 = Executor，负责探索仓库、执行 shell、修改代码、提交完成信号
CodeFlow Harness = 外层工程控制，负责约束、验证、修复、审查、留痕、评测
```

换句话说，mini-swe-agent 解决“让模型能改代码”，CodeFlow 解决“模型改完以后能不能被信任、复盘、阻断、修复和量化”。

## 2. 项目要解决的问题

普通 AI coding agent 的输出有几个典型风险：

- 只看见测试通过，但其实没有改代码，属于 no-change false success。
- 为了让测试通过，删除失败测试或降低断言强度。
- 修改 `.env`、密钥、证书、部署脚本等敏感路径。
- 引入大范围 diff 或无关重构，增加 review 成本。
- 修改代码后没有跑指定测试，或者测试失败后没有有效修复。
- 执行过程没有稳定 artifact，出了问题难以复盘。
- 评测只看 pass rate，无法区分 agent 失败、环境失败、模型 API 失败、policy 阻断。

CodeFlow 的思路是把 agent 执行放进一个 Harness：

```text
自然语言任务
  -> 结构化 Spec 和项目规则
  -> mini-swe-agent 执行
  -> checks + sensors 验证
  -> repair prompt 修复
  -> diff review 和语义审查
  -> commit / rollback / keep 人工治理
  -> artifacts / index / dashboard / benchmark
```

## 3. 仓库结构

主要目录如下：

```text
.
├── codeflow/                  # CodeFlow Harness 主实现
├── codeflow/harness/          # policy、sensors、governance、observability
├── codeflow/storage/          # JSONL / SQLite run store
├── codeflow/server/           # dashboard 与 /api/* 服务
├── minisweagent/              # 已集成的 mini-swe-agent v2 源码
├── benchmark/                 # benchmark 任务、准备脚本、评测脚本、报告
├── examples/                  # todo_api / file_utils / student_manager 示例项目
├── tests/                     # CodeFlow 和 mini-swe-agent 的测试
├── docs/                      # 设计与实现文档
├── pyproject.toml             # 统一安装 codeflow 与 minisweagent
└── README.md                  # 用户入口
```

顶层 `pyproject.toml` 暴露了这些命令：

```text
codeflow        -> codeflow.cli:app
mini            -> minisweagent.run.mini:app
mini-swe-agent  -> minisweagent.run.mini:app
mini-extra      -> minisweagent.run.utilities.mini_extra:main
mini-e          -> minisweagent.run.utilities.mini_extra:main
```

因此一次 `uv sync` 或 `pip install -e .` 会同时安装外层 CodeFlow 和内层 mini-swe-agent。

## 4. 核心输入与输出

### 4.1 用户输入

最典型输入是一个干净 Git 仓库、一个自然语言任务、一个或多个验证命令：

```bash
codeflow run \
  --repo ./examples/todo_api \
  --task "给 Todo 增加 due_date 字段，允许为空，并补充测试。" \
  --checks "pytest -q" \
  --no-commit
```

输入含义：

| 字段 | 示例 | 作用 |
| --- | --- | --- |
| `repo` | `./examples/todo_api` | 被修改的目标仓库，必须是 Git worktree |
| `task` | `给 Todo 增加 due_date 字段...` | 交给 agent 的自然语言需求 |
| `checks` | `pytest -q` | 修改完成后必须通过的验证命令 |
| `.codeflow/codeflow.yaml` | allowed paths / forbidden paths / repair rounds | 项目可执行策略 |
| `.codeflow/project_rules.md` | 不删除测试、不改密钥等 | 注入给模型的文本规则 |
| `.env` 或标准环境变量 | `model_id`、`api_key`、`base_url` | mini 和语义审查的模型配置 |

### 4.2 输出物

一次运行会在目标仓库的 Git 目录下写入：

```text
.git/codeflow/runs/{run_id}/
├── policy.json
├── spec.json
├── initial_prompt.md
├── prompt_0.txt
├── mini_run_0.log
├── mini_run_0.trajectory.json
├── mini_run_0.events.jsonl
├── checks_round_0.json
├── sensor_report_round_0.json
├── diff.patch
├── review_summary.json
├── review_report.md
└── state.json
```

如果修复循环触发，还会出现：

```text
repair_prompt_1.md
mini_run_1.log
mini_run_1.trajectory.json
checks_round_1.json
sensor_report_round_1.json
```

这些输出让一次 agent 修改从“黑盒聊天”变成可审计的工程流程。

## 5. 主执行流程

主流程位于 `codeflow/runner.py`。从输入到输出的链路如下：

1. `ensure_git_repo()` 校验目标目录是 Git 仓库。
2. `ensure_clean_worktree()` 拒绝脏工作区，避免覆盖用户改动。
3. `read_project_rules()` 读取 `.codeflow/project_rules.md`，不存在时使用默认规则。
4. `load_harness_policy()` 读取 `.codeflow/codeflow.yaml` 并合并 CLI 覆盖项。
5. `build_spec()` 把自然语言任务包装成结构化 `Spec`。
6. `enhance_spec_with_semantics()` 可选调用 LLM 增强验收条件。
7. `build_initial_prompt()` 构造交给 mini-swe-agent 的 prompt。
8. `create_ai_branch()` 创建 `ai/{task_slug}-{timestamp}` 隔离分支。
9. `run_mini_agent()` 调用 mini-swe-agent 修改代码。
10. `run_checks()` 执行 `pytest`、`ruff` 等 required checks。
11. `run_builtin_sensors()` 执行风险传感器。
12. 如果 checks 或可修复 sensor 失败，`build_repair_prompt()` 生成修复 prompt 并再次调用 mini。
13. `review_diff_with_semantics()` 可选做语义 diff review。
14. `build_review_summary()` 和 `build_review_report()` 生成审查摘要与 Markdown 报告。
15. `--no-commit` 时保留状态；否则进入 commit / rollback / keep 人工治理。
16. `_write_final_state()` 写入 `state.json` 并更新 `.git/codeflow/index.jsonl`。

## 6. 结构化 Spec 示例

输入任务：

```text
给 Todo 增加 due_date 字段，允许为空，并补充测试。
```

规则版 `Spec` 输出大致为：

```json
{
  "task_type": "coding_task",
  "goal": "给 Todo 增加 due_date 字段，允许为空，并补充测试。",
  "acceptance_criteria": [
    "Implementation satisfies the user task.",
    "Existing tests pass.",
    "New or updated tests are added when appropriate.",
    "No unrelated files are modified."
  ],
  "constraints": [
    "Do not delete existing tests.",
    "Do not bypass failing tests.",
    "Do not modify environment secrets.",
    "Keep changes minimal and relevant."
  ],
  "semantic_notes": []
}
```

如果 policy 打开 `semantic_spec: true` 且模型配置可用，语义增强会尝试补充更具体的验收标准，例如“已有 Todo 创建逻辑不应破坏”“due_date 缺省值应为 None 或可选字段”等。

## 7. 初始 Prompt 示例

`codeflow/prompt_builder.py` 会把任务、Spec、项目规则和 policy 拼成初始 prompt。简化示例：

```text
You are working inside a local Git repository.

User task:
给 Todo 增加 due_date 字段，允许为空，并补充测试。

Structured spec:
Goal: 给 Todo 增加 due_date 字段，允许为空，并补充测试。

Project rules:
- Keep changes minimal and relevant.
- Do not delete existing tests.
- Add or update tests for new behavior.

Harness Policy:
- required checks: pytest -q, ruff check .
- max repair rounds: 3
- forbidden paths: .env, .env.*, secrets/, credentials/, *.pem, *.key
- require test change: True

Required validation commands:
- pytest -q
- ruff check .

Instructions:
1. Inspect the repository before editing.
2. Make the minimal necessary code changes.
3. Add or update tests when appropriate.
4. Do not claim success unless the required validation commands can pass.
5. Do not modify unrelated files.
```

这类 prompt 不是直接替模型写代码，而是给模型一个更稳定的任务边界。

## 8. Repair Prompt 示例

如果 mini 第一次修改后 `pytest -q` 失败，外层会把失败日志交回模型：

```text
The previous implementation did not pass validation.

Original task:
修复 create_todo 对空白标题校验不严格的问题：纯空白字符串也应报错，并补充测试。

Failed validation logs:
Command: pytest -q
Return code: 1
STDOUT:
tests/test_todo.py::test_blank_title_rejected FAILED

Sensor report:
Overall passed: True
Max severity: info

Required validation commands:
- pytest -q

Please fix the implementation with minimal changes.
Do not delete tests.
Do not bypass tests.
Do not modify unrelated files.
```

这就是 CodeFlow 的 control loop：模型第一次产出的 patch 不合格时，不直接失败，而是带着结构化反馈进入下一轮。

## 9. Harness Policy 示例

示例项目 `examples/todo_api/.codeflow/codeflow.yaml` 的核心策略：

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
  require_test_change: true
  allow_dependency_change: false
  allow_delete_tests: false
  governance:
    block_commit_on_failed_checks: true
    require_human_approval: true
    rerun_checks_before_commit: true
```

这个配置的效果：

- mini 只能合理修改 `app/` 和 `tests/`。
- 修改 `.env`、密钥、证书会被 sensor 阻断。
- 业务代码变更但不改测试会被警告。
- 删除测试默认不允许。
- 提交前会再次验证 checks 和 sensors。

## 10. Built-in Sensors

当前内置 sensors 在 `codeflow/harness/builtin_sensors.py`：

| Sensor | 作用 | 示例输入 | 示例输出 |
| --- | --- | --- | --- |
| `check_commands` | 汇总 required checks 是否失败 | `pytest -q` return code 1 | high / blocking |
| `shell_check_risk` | 检查 shell checks 是否含高风险片段 | `shell: curl ... | sh` | medium/high warning |
| `forbidden_path` | 禁止修改 `.env`、secrets、key 文件 | changed files 包含 `.env` | high / blocking |
| `forbidden_path_write` | 禁止新增能写敏感路径的代码 | 新增 `open(".env", "w")` | high / blocking |
| `allowed_path` | 限制只能改允许目录 | allowed `app/`，实际改 `scripts/deploy.py` | high / blocking |
| `high_risk_path` | 标记高风险路径 | 改 `migrations/` | medium/high warning |
| `test_deletion` | 检测删除测试函数或断言 | diff 删除 `def test_` | high / blocking |
| `missing_test_change` | 业务代码变更但未改测试 | 改 `app/todo.py` 不改 `tests/` | medium warning |
| `dependency_change` | 检测依赖文件变更 | 改 `pyproject.toml` | policy 决定阻断或 warning |
| `secret_like_content` | 检测新增 token/key 字符串 | 新增 `api_key="sk-..."` | high / blocking |
| `max_diff` | 限制 diff 行数 | diff 800 行，限制 500 | high / blocking |
| `no_change` | 防止无修改误判成功 | checks 通过但无 diff | medium / blocking |

示例 sensor report：

```json
{
  "overall_passed": false,
  "max_severity": "high",
  "blocking_reasons": ["Forbidden paths modified: .env"],
  "results": [
    {
      "name": "forbidden_path",
      "passed": false,
      "severity": "high",
      "message": "Forbidden paths modified: .env",
      "details": {"paths": [".env"]}
    }
  ]
}
```

## 11. mini-swe-agent 集成方式

外层通过 `codeflow/mini_runner.py` 调用 mini。默认命令是：

```bash
mini --task-file <prompt.txt> --yolo --exit-immediately --output <trajectory.json>
```

可通过环境变量调整：

| 环境变量 | 作用 |
| --- | --- |
| `CODEFLOW_MINI_COMMAND` | 覆盖 mini 命令，比如 `python -m minisweagent.run.mini` |
| `CODEFLOW_MINI_EXECUTOR` | `subprocess` 或 `inprocess` |
| `CODEFLOW_MINI_TIMEOUT_SECONDS` | mini 最大运行时间，默认 3600 秒 |
| `CODEFLOW_ENV_FILE` | 指定 `.env` 路径 |

`.env` 示例：

```text
model_id="deepseek-v4-flash"
api_key="sk-..."
base_url="https://example.com/compatible/v1"
```

CodeFlow 会把它映射为 mini 可识别的 OpenAI-compatible 环境变量：

```text
model_id -> MSWEA_MODEL_NAME=openai/{model_id}
api_key  -> OPENAI_API_KEY
base_url -> OPENAI_BASE_URL / OPENAI_API_BASE
```

## 12. 运行状态与治理

`RunState.status` 表示执行结果：

| 状态 | 含义 |
| --- | --- |
| `dry_run` | 只生成 prompt，没有执行 mini |
| `checks_passed` | checks 和 sensors 均通过 |
| `checks_failed` | required checks 失败 |
| `sensor_failed` | checks 通过但可修复 sensor 失败 |
| `review_required` | 存在不可盲目修复的风险，需要人工审查 |
| `commit_refused_checks_failed` | checks 失败，拒绝提交 |
| `commit_refused_sensor_failed` | blocking sensor 失败，拒绝提交 |
| `commit_refused_high_risk` | 高风险未确认，拒绝提交 |
| `committed` | 已提交 |
| `rolled_back` | 已回滚 |
| `kept_uncommitted` | 保留未提交状态 |

`commit_action` 单独记录治理动作，避免 `--no-commit` 把验证状态覆盖掉。

## 13. Observability

CodeFlow 不只生成一次性报告，还提供历史运行查询能力：

```bash
codeflow inspect --repo ./examples/todo_api --latest
codeflow search --repo ./examples/todo_api --status checks_failed
codeflow summary --repo ./examples/todo_api
codeflow dashboard --repo ./examples/todo_api --out ./dashboard.html
codeflow serve --repo ./examples/todo_api --host 127.0.0.1 --port 8765
codeflow export --repo ./examples/todo_api --latest --out ./run.zip
```

输出示例：

```text
Latest CodeFlow Run
Run ID: 20260503-143012-给-todo-增加-due-date
Task: 给 Todo 增加 due_date 字段，允许为空，并补充测试。
Branch: ai/给-todo-增加-due-date-0503-143012
Status: checks_passed
Commit Action: skipped
Repair Rounds: 0
Risk Level: low
Checks: PASS
Sensors: PASS
Report: .git/codeflow/runs/.../review_report.md
```

服务端接口包括：

```text
/api/runs
/api/summary
/api/findings
/api/trends
/api/failures
```

可用 JSONL 索引，也可同步到 SQLite。

## 14. Benchmark 体系

benchmark 目录提供统一任务格式、workspace 准备和多方法对比：

```text
benchmark/tasks/*.yaml / *.jsonl
benchmark/scripts/prepare_*.py
benchmark/scripts/run_eval.py
benchmark/scripts/summarize_results.py
benchmark/results/
benchmark/reports/
```

评测方法：

| Method | 含义 |
| --- | --- |
| `checks_only` | 不调用 agent，只验证 baseline，确认任务初始应失败 |
| `raw_mini` | 只把任务交给 mini-swe-agent，随后采集 checks，不加外层 guidance/sensors/repair |
| `codeflow_basic` | 使用 CodeFlow prompt 和 repair loop，但不加 sensors |
| `codeflow_full` | 完整 Harness：policy、sensors、repair、review、artifacts |

已有结果显示，当前真实 `codeflow_full` 在 113 条记录上 checks pass 为 113/113，同时识别 6 条 unsafe diff，其中 1 条 Harness-Bench forbidden path 被置为 `review_required`。这说明“测试通过”与“允许提交”被明确拆开了。

## 15. 与普通 Agent 的差异

普通 mini-swe-agent 单独运行时的输出通常是：

```text
trajectory.json
最终 submission
目标仓库中的代码修改
```

CodeFlow 外层运行后会额外得到：

```text
结构化 spec
最终 prompt
每轮 mini log 和 trajectory
每轮 checks JSON
每轮 sensor report
diff.patch
review_summary.json
review_report.md
state.json
index.jsonl
可导出的 zip
dashboard/API 查询能力
```

所以项目价值不在“多包装一层命令”，而在把 agent 修改变成可验证的工程过程。

## 16. 当前边界

当前项目仍有一些边界：

- 主要面向 Python 项目，默认 checks 是 `pytest -q`。
- 真实 LLM 表现依赖模型、API、网络代理和目标仓库环境。
- `semantic_spec` / `semantic_review` 是可选能力，模型不可用时默认 fail-open，除非 policy 要求 fail-closed。
- 外部 benchmark，尤其 SWE-bench 和 BugsInPy，准备 workspace 的成本较高。
- raw mini 大规模对照结果在当前仓库中不如 `codeflow_full` 结果完整，报告解读时需要区分已有数据和方法设计。

## 17. 面试讲法

可以这样介绍项目：

```text
我做了一个 AI Coding Agent 的可信执行 Harness。底层复用 mini-swe-agent 作为代码执行器，
外层实现了结构化任务 Spec、项目策略注入、Git 分支隔离、pytest/ruff 校验门禁、
风险 sensors、失败修复循环、人工 commit/rollback 治理、运行 artifact、dashboard 和 benchmark。

这个项目的重点不是再造一个 agent，而是把不稳定的模型改代码过程工程化：
每次运行都有输入 prompt、trajectory、diff、checks、sensor report、review summary 和最终 state，
并且能对删除测试、修改 .env、无代码修改、大 diff、依赖变更等风险做自动阻断或提示。
```

如果面试官追问难点，可以展开：

- 如何把自然语言任务转换为稳定 Spec 和 prompt guidance。
- 如何设计 sensor，将“测试通过但风险不可接受”与“代码正确”拆开。
- 如何做 repair loop，避免第一次失败就终止。
- 如何用 Git 干净工作区和隔离分支保护用户代码。
- 如何保留 artifact，让 agent 运行可复盘。
- 如何构造 benchmark，把 baseline、raw mini、basic harness、full harness 分开评测。

## 18. 简历写法

偏工程平台方向：

```text
设计并实现 CodeFlow Harness，一个面向 Python 项目的 AI Coding Agent 可信执行平台；
集成 mini-swe-agent 作为执行器，在外层实现结构化 Spec、策略注入、Git 分支隔离、
pytest/ruff 校验门禁、风险传感器、失败修复循环、人工治理、运行审计和 dashboard/API。
```

偏 AI Agent 可靠性方向：

```text
围绕 mini-swe-agent 构建可靠性 Harness，将 agent 编码过程拆解为 guidance、execution、
validation、repair、risk review、governance 和 evaluation 七个阶段；
实现 forbidden path、test deletion、no-change、secret-like content、max diff 等 sensors，
降低测试通过但变更不可信的风险。
```

偏评测方向：

```text
搭建 CodeFlow-Harness-Bench 评测体系，统一 Harness-Bench、QuixBugs、BugsInPy、
SWE-bench Lite/Verified 任务格式；支持 checks_only、raw_mini、codeflow_basic、
codeflow_full 多方法对照，输出 JSON/Markdown 报告、失败分类、重试分析和 artifact 索引。
```

偏后端/可观测性方向：

```text
实现 AI Agent 运行可观测性模块，将每次运行的 state、review finding、checks、sensors、
diff 和 artifact 写入 JSONL/SQLite，并提供 inspect/search/summary/dashboard/serve/export 命令
以及 /api/runs、/api/findings、/api/trends、/api/failures 查询接口。
```

