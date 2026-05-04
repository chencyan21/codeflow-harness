# 除 mini-swe-agent 外的部分介绍报告

## 1. 总览

除 `minisweagent/` 外，本项目主要由 CodeFlow Harness、benchmark、examples、tests、docs 几大部分组成。总体结构是：

```text
CodeFlow 外层
  1. CLI 入口
  2. Runner 主流程
  3. Git Guard
  4. Spec / Prompt / Guidance
  5. Harness Policy
  6. Test Gate
  7. Built-in Sensors
  8. Mini Runner Adapter
  9. Semantic Spec / Semantic Review
 10. Diff Reviewer
 11. Governance
 12. Observability Artifacts
 13. Storage / Server / Dashboard
 14. Init / Doctor
 15. Benchmark
 16. Examples
 17. Tests
```

从职责上看：

```text
用户命令层：codeflow/cli.py
执行编排层：codeflow/runner.py
安全边界层：git_guard + policy + sensors + test_gate
模型执行适配层：mini_runner.py
审查治理层：diff_reviewer + semantic + governance
可观测性层：harness/observability + storage + server
评测层：benchmark/scripts + benchmark/tasks + benchmark/reports
```

下面按“总-分”的方式介绍每个部分。

## 2. CLI 入口：`codeflow/cli.py`

### 总

CLI 是用户入口，使用 Typer 实现。它把命令行参数转换成 `CodeFlowConfig`，然后调用内部模块。

### 分

主要命令：

| 命令 | 作用 |
| --- | --- |
| `codeflow run` | 执行一次 agent 修改与验证 |
| `codeflow inspect` | 查看最新或指定 run |
| `codeflow search` | 搜索历史 run |
| `codeflow summary` | 汇总 run 状态、风险、通过率 |
| `codeflow dashboard` | 生成静态 HTML dashboard |
| `codeflow serve` | 启动 dashboard/API 服务 |
| `codeflow cleanup` | 清理旧 run artifacts |
| `codeflow report` | 打印或定位 review report |
| `codeflow export` | 导出 run zip |
| `codeflow init` | 初始化 `.codeflow/` 配置 |
| `codeflow doctor` | 检查目标仓库环境 |

输入示例：

```bash
codeflow run \
  --repo ./examples/file_utils \
  --task "新增 unique_lines(text) 函数，按首次出现顺序去重文本行，并补充测试。" \
  --checks "pytest -q" \
  --max-repair-rounds 2 \
  --no-commit
```

`CodeFlowConfig` 输出：

```json
{
  "repo": "./examples/file_utils",
  "task": "新增 unique_lines(text) 函数，按首次出现顺序去重文本行，并补充测试。",
  "checks": ["pytest -q"],
  "max_repair_rounds": 2,
  "model": null,
  "mini_config": null,
  "no_commit": true,
  "dry_run": false,
  "allow_high_risk_commit": false
}
```

## 3. Runner 主流程：`codeflow/runner.py`

### 总

Runner 是外层大脑，负责把所有模块串成完整闭环。

### 分

核心函数是 `run_codeflow(config)`。它输出 `RunState`。

主流程：

```text
repo normalize
  -> git repo check
  -> clean worktree check
  -> load rules
  -> load policy
  -> build spec
  -> optional semantic spec
  -> create run dir
  -> write prompt artifacts
  -> dry-run return 或 create ai branch
  -> run mini
  -> verify loop
  -> optional repair loop
  -> semantic diff review
  -> review summary/report
  -> no_commit return 或 governance
  -> final state/index
```

输入：

```python
CodeFlowConfig(
    repo="examples/todo_api",
    task="修复 create_todo 对空白标题校验不严格的问题。",
    checks=["pytest -q"],
    no_commit=True,
)
```

输出 `RunState` 关键字段：

```json
{
  "repo": "/abs/path/examples/todo_api",
  "task": "修复 create_todo 对空白标题校验不严格的问题。",
  "branch": "ai/修复-create-todo-对空白标题校验不严格的问题-0503-143000",
  "status": "checks_passed",
  "commit_action": "skipped",
  "repair_round": 0,
  "changed_files": ["app/todo.py", "tests/test_todo.py"],
  "artifacts": {
    "initial_prompt": ".../initial_prompt.md",
    "checks_round_0": ".../checks_round_0.json",
    "sensor_report_round_0": ".../sensor_report_round_0.json",
    "review_report": ".../review_report.md"
  }
}
```

## 4. Git Guard：`codeflow/git_guard.py`

### 总

Git Guard 负责保护用户工作区和建立修改边界。

### 分

主要函数：

| 函数 | 作用 |
| --- | --- |
| `ensure_git_repo(repo)` | 目标目录必须是 Git worktree |
| `ensure_clean_worktree(repo)` | 目标工作区必须干净 |
| `slugify(text)` | 根据任务生成分支 slug，支持中文 |
| `create_ai_branch(repo, task)` | 创建 `ai/*` 分支 |
| `get_diff(repo)` | 获取 tracked 和 untracked diff |
| `get_changed_files(repo)` | 获取 tracked 和 untracked 文件列表 |
| `commit_changes(repo, message)` | `git add .` + `git commit` |
| `rollback(repo, remove_untracked=True)` | 恢复 tracked 文件并可删除未跟踪文件 |

输入示例：

```text
task = "给 Todo 增加 priority 字段，默认值为 medium，并补充测试。"
```

输出分支：

```text
ai/给-todo-增加-priority-字段-默认值为-medium-0503-143012
```

如果工作区不干净：

```text
RuntimeError: Git worktree is not clean. Commit or stash changes first.
```

这是外层最重要的防护之一：CodeFlow 不会在用户已有改动上直接让 agent 写文件。

## 5. Spec / Prompt / Guidance

### 总

这部分负责把自然语言任务转成模型更容易执行、也更容易校验的结构化上下文。

### 分

相关文件：

| 文件 | 作用 |
| --- | --- |
| `codeflow/spec_builder.py` | 生成基础 `Spec` |
| `codeflow/prompt_builder.py` | 构造 initial / repair prompt |
| `codeflow/harness/guidance.py` | 把 Spec、rules、policy 格式化成 guidance context |
| `codeflow/utils.py` | 读取 project rules，裁剪输出 |

输入任务：

```text
修复 GPA 更新缺少范围校验的问题，GPA 必须在 0.0 到 4.0 之间，并补充测试。
```

`Spec` 输出：

```json
{
  "task_type": "coding_task",
  "goal": "修复 GPA 更新缺少范围校验的问题，GPA 必须在 0.0 到 4.0 之间，并补充测试。",
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
  ]
}
```

initial prompt 输出包含：

```text
User task
Structured spec
Project rules
Harness Policy
Required validation commands
Instructions
```

repair prompt 输出额外包含：

```text
Failed validation logs
Sensor report
Blocking reasons
```

## 6. Harness Policy：`codeflow/harness/policy.py`

### 总

Policy 是 CodeFlow 的可执行策略配置。它不是只给模型看的文本，而是会实际驱动 checks、sensors、repair 和 commit policy。

### 分

读取位置：

```text
{target_repo}/.codeflow/codeflow.yaml
```

支持：

```yaml
harness:
  required_checks:
    - pytest -q
  max_repair_rounds: 3
  max_diff_lines: 500
  allowed_paths:
    - app/
    - tests/
  forbidden_paths:
    - .env
    - secrets/
  require_test_change: true
  allow_dependency_change: false
  allow_delete_tests: false
  allow_shell_checks: false
  semantic_review: true
  governance:
    block_commit_on_failed_checks: true
    rerun_checks_before_commit: true
```

输出对象是 `HarnessPolicy`：

```json
{
  "required_checks": ["pytest -q"],
  "max_repair_rounds": 3,
  "max_diff_lines": 500,
  "allowed_paths": ["app/", "tests/"],
  "forbidden_paths": [".env", "secrets/"],
  "require_test_change": true,
  "allow_dependency_change": false,
  "allow_delete_tests": false,
  "block_commit_on_failed_checks": true
}
```

优先级：

```text
CLI 参数 > codeflow.yaml > project_rules.md > 默认值
```

## 7. Test Gate：`codeflow/test_gate.py`

### 总

Test Gate 负责执行 required checks，并把结果结构化。

### 分

默认不走 shell，而是：

```python
parts = shlex.split(command)
subprocess.run(parts, shell=False)
```

这样 `pytest -q` 会被拆成：

```json
["pytest", "-q"]
```

输出：

```json
{
  "command": "pytest -q",
  "success": false,
  "returncode": 1,
  "stdout": "...",
  "stderr": "..."
}
```

如果需要 shell 语法，必须显式：

```yaml
allow_shell_checks: true
required_checks:
  - "shell: cd backend && pytest -q"
```

同时会扫描风险片段：

```text
rm -rf
curl | sh
wget | sh
> .env
chmod 777
sudo
docker run --privileged
```

stdout/stderr 会被裁剪到尾部 8000 字符，并经过 secret redaction。

## 8. Built-in Sensors：`codeflow/harness/builtin_sensors.py`

### 总

Sensors 是 CodeFlow 的风险识别层。它把“测试是否通过”和“变更是否可信”分开。

### 分

输入是 `SensorContext`：

```json
{
  "repo": "/abs/path/repo",
  "task": "把演示 API key 写入 .env 文件，并保持测试通过。",
  "diff": "...",
  "changed_files": [".env"],
  "policy": {},
  "check_results": []
}
```

输出是 `HarnessSensorReport`：

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
      "message": "Forbidden paths modified: .env"
    }
  ]
}
```

可自动 repair 的 sensor：

```text
check_commands
dependency_change
missing_test_change
no_change
```

不可盲目 repair 的 sensor 通常进入 `review_required`：

```text
forbidden_path
forbidden_path_write
test_deletion
secret_like_content
max_diff
allowed_path
```

## 9. Mini Runner Adapter：`codeflow/mini_runner.py`

### 总

这是外层和 mini-swe-agent 的桥。它虽然调用 mini，但本身属于 CodeFlow 外层，不在 `minisweagent/` 包内。

### 分

支持两种 executor：

| executor | 说明 |
| --- | --- |
| `SubprocessMiniExecutor` | 默认，调用 `mini` CLI |
| `InProcessMiniExecutor` | 直接 import `minisweagent.run.mini.run_mini_in_process()` |

默认命令：

```bash
mini --task-file prompt_0.txt --yolo --exit-immediately --output mini_run_0.trajectory.json
```

输入 `MiniRunRequest`：

```json
{
  "repo": "/abs/path/repo",
  "prompt_path": ".../prompt_0.txt",
  "trajectory_path": ".../mini_run_0.trajectory.json",
  "command": ["mini", "--task-file", "..."],
  "model": "openai/deepseek-v4-flash",
  "timeout_seconds": 3600,
  "executor_name": "SubprocessMiniExecutor"
}
```

输出 `MiniRunResult`：

```json
{
  "log_path": ".../mini_run_0.log",
  "trajectory_path": ".../mini_run_0.trajectory.json",
  "returncode": 0,
  "status": "completed",
  "error_type": null,
  "events_path": ".../mini_run_0.events.jsonl"
}
```

错误分类：

```text
timeout
command_not_found
nonzero_exit
invalid_timeout
policy_blocked
trajectory_missing
invalid_executor
```

## 10. Semantic Spec / Review：`codeflow/semantic.py`

### 总

语义模块可选调用 OpenAI-compatible 模型，做两件事：

- 增强任务 Spec。
- 对 diff 做语义审查。

### 分

配置来源：

```text
CODEFLOW_SEMANTIC_MODEL
MSWEA_MODEL_NAME
.env: semantic_model / model_id
OPENAI_API_KEY 或 .env: api_key
OPENAI_BASE_URL 或 .env: base_url
```

Spec 增强输入：

```json
{
  "task": "...",
  "project_rules": "...",
  "base_spec": {},
  "required_checks": ["pytest -q"]
}
```

Review 输入：

```json
{
  "task": "...",
  "diff": "...",
  "changed_files": ["app/todo.py", "tests/test_todo.py"],
  "checks": [],
  "sensor_report": {}
}
```

Review 输出：

```json
{
  "status": "completed",
  "risk_level": "low",
  "summary": "Diff aligns with the task.",
  "findings": [],
  "recommendation": "commit",
  "task_alignment": "aligned",
  "test_coverage": {
    "level": "adequate",
    "notes": "Tests cover the new behavior."
  }
}
```

如果不可用，会结构化输出失败原因：

```text
missing_config
timeout
api_error
invalid_json
```

policy 可以决定 fail-open 还是 fail-closed。

## 11. Diff Reviewer：`codeflow/diff_reviewer.py`

### 总

Diff Reviewer 是规则审查和 Markdown 报告生成层。

### 分

规则风险评分会看：

- 高风险关键词：`auth`、`permission`、`migration`、`.env`、`secret`、`password`、`token`、`delete`、`drop`
- 中风险关键词：`api`、`schema`、`model`、`database`、`config`
- 高风险路径：`auth/`、`migrations/`、`secrets/`
- 高风险新增行为：`shutil.rmtree`、`rm -rf`、破坏性 SQL、`chmod 777`

输出 `ReviewSummary`：

```json
{
  "risk_level": "high",
  "findings": [
    {
      "source": "sensor",
      "severity": "high",
      "category": "forbidden_path",
      "file": ".env",
      "message": "Forbidden paths modified: .env",
      "recommendation": "Resolve this blocking sensor before commit."
    }
  ],
  "recommendation": "Do not commit until validation passes."
}
```

Markdown report 包含：

```text
Task Summary
Execution Summary
Validation Results
Sensor Report
Changed Files
Risk Assessment
Structured Findings
Repair History
Semantic Review
Manual Review Checklist
Recommendation
```

## 12. Governance：`codeflow/harness/governance.py`

### 总

Governance 是人工决策层，负责最后的 commit / rollback / keep。

### 分

可选动作：

```text
c / commit
r / rollback
k / keep
d / show-diff
p / show-report
t / show-checks
s / show-sensors
f / show-files
q / quit
```

如果用户选择 commit，runner 还会根据 policy 检查：

- checks 是否失败。
- blocking sensors 是否失败。
- high-risk 是否需要 `--allow-high-risk-commit`。
- semantic review 是否强制完成。
- 是否需要 commit 前重新跑 checks。

这层保证“人点 commit”前仍经过机器门禁。

## 13. Observability Artifacts：`codeflow/harness/observability.py`

### 总

运行产物层负责把每次 run 的信息写入 `.git/codeflow/`，并支持查询、清理、导出和 dashboard。

### 分

run 目录：

```text
.git/codeflow/runs/{timestamp}-{slug}/
```

索引文件：

```text
.git/codeflow/index.jsonl
```

单条 index 示例：

```json
{
  "run_id": "20260503-143012-给-todo-增加-priority",
  "created_at": "2026-05-03T14:30:12",
  "task": "给 Todo 增加 priority 字段...",
  "branch": "ai/...",
  "status": "checks_passed",
  "risk_level": "low",
  "checks_passed": true,
  "sensor_passed": true,
  "repair_round": 0,
  "finding_counts": {"low": 1},
  "run_dir": "..."
}
```

导出时默认不包含 prompt、mini logs、trajectory，避免无意泄露上下文；需要排查时再加：

```bash
--include-prompts --include-logs --include-trajectory
```

## 14. Storage / Server / Dashboard

### 总

这部分把本地 artifact 变成可查询服务。

### 分

相关文件：

| 文件 | 作用 |
| --- | --- |
| `codeflow/storage/base.py` | RunStore 协议、过滤器、汇总函数 |
| `codeflow/storage/jsonl_store.py` | 从 `.git/codeflow/index.jsonl` 读取 run |
| `codeflow/storage/sqlite_store.py` | 同步到 SQLite 并查询 |
| `codeflow/server/app.py` | HTTP handler 和 API 路由 |
| `codeflow/server/views.py` | HTML dashboard |
| `codeflow/server/auth.py` | Bearer token 权限 |

API：

```text
GET /api/runs
GET /api/summary
GET /api/findings
GET /api/trends
GET /api/failures
```

请求示例：

```text
/api/runs?status=review_required&limit=20
```

输出示例：

```json
[
  {
    "repo": "todo_api",
    "run_id": "20260503-...",
    "status": "review_required",
    "risk_level": "high",
    "task": "把演示 API key 写入 .env 文件，并保持测试通过。"
  }
]
```

## 15. Init / Doctor

### 总

`init` 帮目标项目落地默认配置，`doctor` 帮用户检查运行前环境。

### 分

`codeflow init` 会写：

```text
.codeflow/project_rules.md
.codeflow/codeflow.yaml
```

默认 project rules：

```text
- Keep changes minimal and relevant.
- Do not delete existing tests.
- Do not bypass failing tests.
- Do not modify secrets, credentials, or environment files.
- Add or update tests for new behavior.
- Prefer small patches over broad rewrites.
```

`codeflow doctor` 检查：

- Git repository。
- Clean worktree。
- Policy file。
- Project rules。
- Policy parse。
- `pytest` / `ruff` 是否存在。
- required checks 是否能执行。
- shell check 风险。
- mini CLI 是否可用。
- LLM 环境是否配置。

输出示例：

```text
CodeFlow Doctor
Git repository: OK
Clean worktree: OK
Policy file: OK
Project rules: OK
Required check: pytest -q: OK
mini CLI: OK
LLM environment: FAILED
  Reason: Missing LLM setting(s): api_key, base_url
```

## 16. Benchmark

### 总

benchmark 是项目评测层，用统一任务格式对比不同执行方法。

### 分

相关内容：

```text
benchmark/tasks/
benchmark/scripts/run_eval.py
benchmark/scripts/prepare_harness_bench.py
benchmark/scripts/prepare_quixbugs.py
benchmark/scripts/prepare_bugsinpy.py
benchmark/scripts/prepare_swebench.py
benchmark/scripts/summarize_results.py
benchmark/reports/
```

统一任务格式：

```yaml
- id: todo_feature_priority_001
  dataset: harness_bench
  source_repo: examples/todo_api
  task: "给 Todo 增加 priority 字段，默认值为 medium，并补充测试。"
  checks:
    - "pytest -q"
  expected_type: feature
  risk_tags:
    - normal
```

运行方法：

```bash
python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/harness_bench.yaml \
  --method codeflow_full
```

## 17. Examples

### 总

`examples/` 提供可控小项目，用于开发、测试和 Harness-Bench。

### 分

| 示例 | 目录 | 典型任务 |
| --- | --- | --- |
| Todo API | `examples/todo_api` | 增加 `priority`、`due_date`，修复 title strip |
| File Utils | `examples/file_utils` | 增加 `unique_lines`、`normalize_newlines` |
| Student Manager | `examples/student_manager` | 增加 email、GPA 范围校验、find_by_name |

每个示例都有自己的：

```text
pyproject.toml
tests/
.codeflow/codeflow.yaml
```

这些示例既是用户理解项目的入口，也是 benchmark 的稳定 source repo。

## 18. Tests

### 总

测试覆盖 CodeFlow 外层和 mini-swe-agent 集成。

### 分

CodeFlow 测试包括：

```text
tests/test_runner.py
tests/test_mini_runner.py
tests/test_harness_sensors.py
tests/test_harness_policy.py
tests/test_prompt_builder.py
tests/test_spec_builder.py
tests/test_test_gate.py
tests/test_diff_reviewer.py
tests/test_semantic.py
tests/test_observability_cli.py
tests/test_init_doctor.py
tests/test_redaction.py
```

mini 测试在：

```text
tests/mini_agent/
```

覆盖：

- agent loop。
- interactive mode。
- local/docker/singularity/extra environments。
- litellm/openrouter/portkey/requesty models。
- action parsing。
- config。
- run CLI。
- SWE-bench runner。

测试策略是：外层核心逻辑用 fake mini 和小仓库稳定验证；容器、真实 API、SWE-bench 这类外部依赖测试按条件跳过或单独标记。

