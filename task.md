# CodeFlow Harness 功能扩展计划书

## 1. 计划目标

当前 CodeFlow Harness 已经完成主执行链路：用户输入任务后，系统能够完成 Git 校验、Policy 加载、Spec/Prompt 构造、调用 mini-swe-agent、执行 checks、运行 sensors、失败 repair、生成 review report，并进入 commit / rollback / keep 人工治理流程。项目当前定位是：

```text
mini-swe-agent v2 = Executor
CodeFlow Harness = Guidance + Sensors + Control Loop + Governance + Observability + Evaluation
```

后续暂时不扩展 benchmark，先聚焦功能层，把 CodeFlow 从“能跑通的 Harness”提升为：

> 一个可初始化、可诊断、可观测、可审计、可交互治理的 AI Coding Agent Harness 工具。

本阶段核心目标：

```text
1. 增强 Observability：统一运行记录、可查看、可导出
2. 增强 Usability：项目初始化、环境检查、CLI 体验优化
3. 增强 Governance：人工审批时可看 diff/checks/sensors/report
4. 增强 Review：报告更结构化，支持人工审查清单
5. 保持现有核心链路稳定，不大改 mini-swe-agent 执行器
```

---

## 2. 当前基础

当前已完成能力包括：

```text
1. 顶层 pyproject.toml 同时安装 CodeFlow 和 mini-swe-agent
2. codeflow / mini / mini-swe-agent CLI 入口
3. Git 仓库校验、干净工作区校验、隔离分支
4. project_rules.md 和 codeflow.yaml 读取
5. HarnessPolicy 加载、governance flatten、CLI 覆盖
6. 规则版 Spec 生成
7. initial prompt / repair prompt 构造
8. mini-swe-agent 非交互调用
9. .env 到 OpenAI-compatible 环境变量映射
10. required checks 执行
11. built-in sensors
12. repair loop
13. Markdown review report
14. commit / rollback / keep 人工治理
15. commit 前二次验证
16. fake mini 离线验证能力
17. QuixBugs、BugsInPy、SWE-bench mini subset 的 benchmark 基础能力
```

这些能力已经在项目说明中明确记录。

---

# 3. 总体建设路线

本阶段分为 5 个阶段：

```text
Phase 1：Observability 基础设施
Phase 2：Run 查看与导出命令
Phase 3：Project Init 与 Doctor
Phase 4：Governance 交互增强
Phase 5：Review Report 增强
```

推荐顺序：

```text
1. 统一 run artifact 目录
2. 保存完整运行状态
3. 增加 inspect / report / export
4. 增加 init / doctor
5. 增强 human approval
6. 增强 review report
```

---

# Phase 1：Observability 基础设施

## 1.1 目标

当前日志、trajectory、review report 已经存在，但组织方式还不够统一。下一步要把每次 `codeflow run` 的所有运行产物统一保存到独立目录中，形成可审计的 run artifact。

目标目录：

```text
.git/codeflow/
└── runs/
    └── {run_id}/
        ├── state.json
        ├── policy.json
        ├── spec.json
        ├── initial_prompt.md
        ├── mini_run_0.log
        ├── mini_run_0.trajectory.json
        ├── checks_round_0.json
        ├── sensor_report_round_0.json
        ├── repair_prompt_1.md
        ├── mini_run_1.log
        ├── mini_run_1.trajectory.json
        ├── checks_round_1.json
        ├── sensor_report_round_1.json
        ├── diff.patch
        └── review_report.md
```

`run_id` 建议格式：

```text
YYYYMMDD-HHMMSS-{task_slug}
```

示例：

```text
20260502-163012-add-priority
```

---

## 1.2 新增模块

新增文件：

```text
codeflow/harness/observability.py
```

核心职责：

```text
1. 创建 run_dir
2. 写入 JSON / Markdown / text 文件
3. 获取 latest run
4. 列出历史 runs
5. 导出 run artifact
```

建议实现函数：

```python
def create_run_dir(repo: str, task: str) -> Path:
    ...

def get_codeflow_dir(repo: str) -> Path:
    ...

def get_runs_dir(repo: str) -> Path:
    ...

def get_latest_run_dir(repo: str) -> Path | None:
    ...

def list_run_dirs(repo: str) -> list[Path]:
    ...

def write_json(path: Path, data: Any) -> None:
    ...

def write_text(path: Path, content: str) -> None:
    ...

def export_run_dir(run_dir: Path, out_path: Path) -> Path:
    ...
```

---

## 1.3 需要保存的运行文件

### 1.3.1 state.json

保存 `RunState` 的最终状态。

内容示例：

```json
{
  "repo": "/abs/path/to/repo",
  "task": "给 Todo 增加 priority 字段",
  "branch": "ai/add-priority-0502-163012",
  "status": "checks_passed",
  "commit_action": "skipped",
  "repair_round": 1,
  "risk_level": "low",
  "checks_passed": true,
  "run_dir": ".git/codeflow/runs/20260502-163012-add-priority"
}
```

### 1.3.2 policy.json

保存合并后的 Harness Policy。

```json
{
  "required_checks": ["pytest -q", "ruff check ."],
  "max_repair_rounds": 3,
  "max_diff_lines": 500,
  "forbidden_paths": [".env", ".env.*", "secrets/", "credentials/"],
  "allow_delete_tests": false,
  "require_test_change": true
}
```

### 1.3.3 spec.json

保存当前任务的结构化 Spec。

### 1.3.4 initial_prompt.md

保存交给 mini-swe-agent 的初始 prompt。

### 1.3.5 repair_prompt_N.md

保存每轮修复 prompt。

### 1.3.6 mini_run_N.log

保存 mini-swe-agent 的 stdout / stderr / command。

### 1.3.7 mini_run_N.trajectory.json

保存 mini-swe-agent 的 trajectory。

### 1.3.8 checks_round_N.json

保存 required checks 结果。

### 1.3.9 sensor_report_round_N.json

保存 sensors 结果。

### 1.3.10 diff.patch

保存最终 `git diff`。

### 1.3.11 review_report.md

保存最终 Markdown 审查报告。

---

## 1.4 Runner 集成点

在 `codeflow/runner.py` 中：

```text
1. 创建 run_dir
2. dry-run 时保存 prompt
3. 每次调用 mini 前保存 prompt
4. 每次 mini 后保存 log / trajectory
5. 每轮 checks 后保存 checks_round_N.json
6. 每轮 sensors 后保存 sensor_report_round_N.json
7. 最后保存 diff.patch
8. 最后保存 review_report.md
9. 最后保存 state.json
```

建议 `RunState` 新增字段：

```python
run_id: str | None = None
run_dir: str | None = None
artifacts: dict[str, str] = Field(default_factory=dict)
```

---

## 1.5 mini_runner 调整

当前 `mini_runner.py` 已经会写日志和 trajectory 到 `.git/codeflow/`。后续改为由 runner 传入 run_dir：

```python
def run_mini_agent(
    repo: str,
    prompt: str,
    run_dir: Path,
    run_index: int,
    model: str | None = None,
    mini_config: str | None = None,
) -> MiniRunResult:
    ...
```

返回：

```python
class MiniRunResult(BaseModel):
    log_path: str
    trajectory_path: str
    returncode: int
```

---

## 1.6 验收标准

```text
1. 每次 codeflow run 都生成唯一 run_dir
2. run_dir 位于 .git/codeflow/runs/{run_id}/
3. run_dir 下至少包含 state.json、initial_prompt.md、diff.patch、review_report.md
4. 如果发生 repair，保存 repair_prompt_N.md
5. 如果调用 mini，保存 mini_run_N.log 和 trajectory
6. 如果运行 checks，保存 checks_round_N.json
7. 如果运行 sensors，保存 sensor_report_round_N.json
8. 不污染 git diff
9. pytest 和 ruff 全部通过
```

---

# Phase 2：Run 查看与导出命令

## 2.1 目标

新增用户可直接使用的运行记录查看能力。

新增命令：

```bash
codeflow inspect --repo <repo>
codeflow report --repo <repo> --latest
codeflow export --repo <repo> --latest --out run.zip
```

---

## 2.2 `codeflow inspect`

### 命令

```bash
codeflow inspect --repo ./examples/todo_api
```

可选参数：

```bash
--latest
--run-id <run_id>
--limit 10
--json
```

### 默认行为

不传 `run-id` 时显示最近一次运行摘要。

输出示例：

```text
Latest CodeFlow Run

Run ID: 20260502-163012-add-priority
Task: 给 Todo 增加 priority 字段，默认值为 medium，并补充测试
Branch: ai/add-priority-0502-163012
Status: checks_passed
Commit Action: skipped
Repair Rounds: 1
Risk Level: low
Checks: PASS
Sensors: PASS
Report: .git/codeflow/runs/.../review_report.md
Trajectory: .git/codeflow/runs/.../mini_run_0.trajectory.json
```

如果 `--limit 10`：

```text
Recent Runs

1. 20260502-163012-add-priority   checks_passed   low
2. 20260502-155022-fix-empty-file  review_required high
3. 20260502-150111-add-due-date    checks_failed  medium
```

如果 `--json`，输出 JSON。

---

## 2.3 `codeflow report`

### 命令

```bash
codeflow report --repo ./examples/todo_api --latest
```

可选参数：

```bash
--run-id <run_id>
--path-only
```

### 行为

默认打印 `review_report.md` 内容。

`--path-only` 输出文件路径：

```text
.git/codeflow/runs/20260502-163012-add-priority/review_report.md
```

---

## 2.4 `codeflow export`

### 命令

```bash
codeflow export \
  --repo ./examples/todo_api \
  --latest \
  --out ./artifacts/codeflow-run.zip
```

可选参数：

```bash
--run-id <run_id>
--include-trajectory
--include-logs
```

默认导出：

```text
state.json
policy.json
spec.json
initial_prompt.md
checks_round_*.json
sensor_report_round_*.json
diff.patch
review_report.md
```

可选导出：

```text
mini_run_*.log
mini_run_*.trajectory.json
```

---

## 2.5 CLI 修改

在 `codeflow/cli.py` 增加命令：

```python
@app.command()
def inspect(...):
    ...

@app.command()
def report(...):
    ...

@app.command()
def export(...):
    ...
```

---

## 2.6 验收标准

```text
1. codeflow inspect 能显示 latest run
2. codeflow inspect --limit 10 能显示最近多个 runs
3. codeflow inspect --json 能输出机器可读 JSON
4. codeflow report --latest 能打印最新 review_report.md
5. codeflow export --latest --out run.zip 能生成 zip
6. repo 下没有 run 时输出清晰错误
7. 单元测试覆盖 latest / run-id / no-run 场景
```

---

# Phase 3：Project Init 与 Doctor

## 3.1 目标

降低新项目接入成本，减少环境配置问题。

新增命令：

```bash
codeflow init --repo <repo>
codeflow doctor --repo <repo>
```

---

## 3.2 `codeflow init`

### 命令

```bash
codeflow init --repo ./my_project
```

可选参数：

```bash
--force
--template python
```

### 行为

在目标仓库生成：

```text
.codeflow/
├── project_rules.md
└── codeflow.yaml
```

### `project_rules.md` 默认内容

```markdown
# Project Rules

- Keep changes minimal and relevant.
- Do not delete existing tests.
- Do not bypass failing tests.
- Do not modify secrets, credentials, or environment files.
- Add or update tests for new behavior.
- Prefer small patches over broad rewrites.
```

### `codeflow.yaml` 默认内容

```yaml
harness:
  required_checks:
    - pytest -q
    - ruff check .

  max_repair_rounds: 3
  max_diff_lines: 500

  allowed_paths: []

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

  governance:
    block_commit_on_failed_checks: true
    block_commit_on_high_risk: false
    require_human_approval: true
    rerun_checks_before_commit: true
```

### 覆盖逻辑

如果 `.codeflow/` 已存在：

```text
默认不覆盖
--force 时覆盖
```

---

## 3.3 `codeflow doctor`

### 命令

```bash
codeflow doctor --repo ./examples/todo_api
```

### 检查内容

```text
Git repo
Clean worktree
.codeflow/project_rules.md
.codeflow/codeflow.yaml
required checks 是否存在
pytest 是否可运行
ruff 是否可运行
mini CLI 是否可运行
.env / OpenAI-compatible 环境变量
CODEFLOW_MINI_COMMAND 是否有效
```

### 输出示例

```text
CodeFlow Doctor

Git repository: OK
Clean worktree: OK
Policy file: OK (.codeflow/codeflow.yaml)
Project rules: OK (.codeflow/project_rules.md)
pytest: OK
ruff: OK
mini CLI: OK
LLM environment: OK
Required checks:
- pytest -q: OK
- ruff check .: OK
```

如果失败：

```text
mini CLI: FAILED
Reason: mini command not found
Suggestion: run `pip install -e .` or set CODEFLOW_MINI_COMMAND
```

### 可选参数

```bash
--json
--skip-checks
--skip-llm
```

---

## 3.4 新增模块

```text
codeflow/init_project.py
codeflow/doctor.py
```

---

## 3.5 验收标准

```text
1. codeflow init 能生成 .codeflow/project_rules.md 和 codeflow.yaml
2. 已存在配置时默认拒绝覆盖
3. --force 可覆盖
4. codeflow doctor 能检查 Git、policy、checks、mini、env
5. doctor 对失败项给出 suggestion
6. doctor --json 输出结构化结果
7. 单元测试覆盖 init / doctor
```

---

# Phase 4：Governance 交互增强

## 4.1 目标

增强人工审批体验，使用户在 commit / rollback / keep 前可以查看更多信息。

当前已有人审流程，但选项比较简单。后续扩展为：

```text
commit
rollback
keep
show-diff
show-report
show-checks
show-sensors
show-files
```

---

## 4.2 新审批界面

运行结束后显示：

```text
CodeFlow Governance

Task: 给 Todo 增加 priority 字段
Branch: ai/add-priority-0502-163012
Status: checks_passed
Risk Level: medium
Checks: PASS
Sensors: PASS with 2 warnings
Repair Rounds: 1

Changed Files:
- app/todo.py
- tests/test_todo.py

Options:
[c] commit
[r] rollback
[k] keep
[d] show diff
[p] show report
[t] show checks
[s] show sensors
[f] show changed files
[q] quit
```

---

## 4.3 show-diff

执行：

```bash
git diff
```

或读取 `diff.patch`。

---

## 4.4 show-report

打印 `review_report.md`。

---

## 4.5 show-checks

打印 checks summary：

```text
pytest -q: PASS
ruff check .: PASS
```

如果失败，显示失败摘要。

---

## 4.6 show-sensors

显示 sensor report：

```text
forbidden_path: PASS
test_deletion: PASS
missing_test_change: WARNING
max_diff: PASS
```

---

## 4.7 high-risk 提交确认

如果风险等级为 high，要求输入：

```text
CONFIRM HIGH RISK
```

否则拒绝提交。

如果 policy 设置 `block_commit_on_high_risk=true`，则即使确认也不能提交，除非 CLI 传入：

```bash
--allow-high-risk-commit
```

---

## 4.8 新增模块

```text
codeflow/governance_ui.py
```

或者放入：

```text
codeflow/harness/governance.py
```

---

## 4.9 验收标准

```text
1. 人审阶段支持 show-diff
2. 支持 show-report
3. 支持 show-checks
4. 支持 show-sensors
5. high risk 需要二次确认
6. block_commit_on_high_risk 生效
7. checks failed 仍拒绝 commit
8. 单元测试覆盖 commit / rollback / keep / show-* 路径
```

---

# Phase 5：Review Report 增强

## 5.1 目标

让 Review Report 更适合人工审查和展示。

当前报告包含任务、分支、验证结果、风险等级、sensor report、blocking reasons、diff 大小和建议。 后续增强结构和可读性。

---

## 5.2 新报告结构

```markdown
# CodeFlow Review Report

## 1. Task Summary

## 2. Execution Summary

## 3. Validation Results

## 4. Sensor Report

## 5. Changed Files

## 6. Risk Assessment

## 7. Repair History

## 8. Manual Review Checklist

## 9. Recommendation
```

---

## 5.3 Task Summary

内容：

```text
Task
Spec goal
Acceptance criteria
Constraints
```

---

## 5.4 Execution Summary

内容：

```text
Branch
Status
Repair rounds
Mini runs
Run directory
```

---

## 5.5 Validation Results

表格：

```markdown
| Command | Result | Return Code |
| --- | --- | ---: |
| pytest -q | PASS | 0 |
| ruff check . | PASS | 0 |
```

---

## 5.6 Sensor Report

表格：

```markdown
| Sensor | Status | Severity | Message |
| --- | --- | --- | --- |
| forbidden_path | PASS | info | No forbidden path modified |
| missing_test_change | WARN | medium | Business code changed without test changes |
```

---

## 5.7 Changed Files

按类型分类：

```text
Source Files:
- app/todo.py

Test Files:
- tests/test_todo.py

Config Files:
- pyproject.toml

Unknown:
- ...
```

---

## 5.8 Risk Assessment

内容：

```text
Risk Level
Risk Notes
Blocking Reasons
Warnings
```

---

## 5.9 Repair History

如果 repair_round > 0：

```markdown
| Round | Reason | Result |
| --- | --- | --- |
| 1 | pytest failed | checks passed |
```

---

## 5.10 Manual Review Checklist

固定清单：

```markdown
- [ ] 任务目标是否已满足？
- [ ] 是否新增或更新了必要测试？
- [ ] required checks 是否全部通过？
- [ ] 是否没有删除已有测试？
- [ ] 是否没有修改敏感路径？
- [ ] 是否没有引入不必要依赖？
- [ ] diff 范围是否足够小？
- [ ] 是否需要人工补充边界测试？
```

根据 sensors 动态追加：

```markdown
- [ ] 检查依赖变更是否必要。
- [ ] 检查高风险路径变更是否合理。
- [ ] 检查测试覆盖不足问题。
```

---

## 5.11 验收标准

```text
1. review_report.md 使用新版结构
2. 包含 changed files 分类
3. 包含 checks 表格
4. 包含 sensors 表格
5. 包含 manual review checklist
6. repair 后包含 repair history
7. 风险 warning 能动态进入 checklist
8. 旧测试不破坏
```

---

# Phase 6：可选语义增强

此阶段不是当前最优先，但可以作为后续增强项。

## 6.1 LLM Spec Builder

当前 Spec 是规则生成。后续可新增：

```bash
codeflow run --spec-mode rule
codeflow run --spec-mode llm
codeflow run --spec-mode hybrid
```

默认先保持：

```text
rule
```

LLM Spec 输出：

```json
{
  "task_type": "feature",
  "goal": "...",
  "acceptance_criteria": ["..."],
  "constraints": ["..."],
  "expected_files": ["..."],
  "test_suggestions": ["..."],
  "risk_hints": ["..."]
}
```

要求：

```text
1. JSON parse 失败 fallback 到 rule spec
2. LLM spec 不能删除默认约束
3. LLM spec 只能增强，不可降低 safety
```

---

## 6.2 LLM Diff Reviewer

新增：

```bash
codeflow run --review-mode rule
codeflow run --review-mode llm
codeflow run --review-mode hybrid
```

默认建议：

```text
rule
```

后续成熟后再改为：

```text
hybrid
```

LLM Review 输入：

```text
task
spec
policy
git diff
checks
sensor report
```

输出：

```json
{
  "summary": "...",
  "task_alignment": "aligned",
  "changed_behavior": ["..."],
  "potential_breakages": ["..."],
  "test_coverage_gaps": ["..."],
  "manual_review_focus": ["..."],
  "risk_level": "medium",
  "recommendation": "review_required"
}
```

硬规则：

```text
1. LLM 不能降低 rule sensor 检出的 high risk
2. LLM JSON parse 失败 fallback 到 rule review
3. LLM review 不参与最终安全阻断，只提供语义审查建议
```

---

# 7. 开发排期建议

## 第 1 周：Observability

目标：

```text
完成统一 run_dir 和基础运行产物保存
```

任务：

```text
1. 新增 codeflow/harness/observability.py
2. RunState 增加 run_id / run_dir / artifacts
3. runner.py 创建 run_dir
4. mini_runner.py 接收 run_dir
5. 保存 state.json / policy.json / spec.json
6. 保存 prompt / checks / sensors / diff / report
7. 补测试
```

验收：

```bash
uv run pytest -q
uv run ruff check .
codeflow run --repo ./examples/todo_api --task "..." --no-commit
```

确认：

```text
.git/codeflow/runs/{run_id}/ 下有完整文件
```

---

## 第 2 周：inspect / report / export

目标：

```text
用户可以查看和导出历史运行
```

任务：

```text
1. codeflow inspect
2. codeflow report
3. codeflow export
4. 支持 --latest / --run-id / --json
5. zip 导出
6. 补测试
```

验收：

```bash
codeflow inspect --repo ./examples/todo_api
codeflow report --repo ./examples/todo_api --latest
codeflow export --repo ./examples/todo_api --latest --out /tmp/run.zip
```

---

## 第 3 周：init / doctor

目标：

```text
提升新项目接入体验
```

任务：

```text
1. codeflow init
2. 默认 project_rules.md
3. 默认 codeflow.yaml
4. --force 覆盖
5. codeflow doctor
6. 检查 git / policy / checks / mini / env
7. --json 输出
8. 补测试
```

验收：

```bash
codeflow init --repo ./tmp_project
codeflow doctor --repo ./tmp_project
```

---

## 第 4 周：Governance UI + Review Report

目标：

```text
提升人工审批和审查报告质量
```

任务：

```text
1. 人审选项增加 show-diff / show-report / show-checks / show-sensors
2. high risk 二次确认
3. 新版 review report 结构
4. changed files 分类
5. manual review checklist
6. repair history
7. 补测试
```

验收：

```text
完整 run 后，可以在审批阶段查看 diff/report/checks/sensors
review_report.md 结构清晰，可直接展示
```

---

# 8. 最终验收标准

完成本阶段后，项目应满足：

```text
1. codeflow run 仍然稳定运行
2. 每次 run 都有独立 run artifact 目录
3. 用户可 inspect 最近运行
4. 用户可 report 查看审查报告
5. 用户可 export 导出运行证据包
6. 用户可 init 快速接入新项目
7. 用户可 doctor 检查环境和配置
8. 人审阶段可查看 diff/report/checks/sensors
9. Review Report 具备完整人工审查清单
10. 所有新增功能有测试覆盖
11. uv run pytest -q 通过
12. uv run ruff check . 通过
13. git diff --check 通过
```

---

# 9. 推荐给 Codex 的执行任务描述

下面这段可以直接给 Codex 作为实现任务：

```text
请在当前 CodeFlow Harness 项目中扩展功能，不要改动 mini-swe-agent 执行器核心逻辑，不要引入 benchmark 新任务。目标是增强单次 codeflow run 的可观测性、可审计性、项目初始化、环境诊断和人工治理体验。

需要实现以下功能：

1. 统一 run artifact 目录
- 新增 codeflow/harness/observability.py
- 每次 codeflow run 在目标 repo 的 .git/codeflow/runs/{run_id}/ 下创建独立运行目录
- run_id 格式为 YYYYMMDD-HHMMSS-{task_slug}
- 保存 state.json、policy.json、spec.json、initial_prompt.md、checks_round_N.json、sensor_report_round_N.json、diff.patch、review_report.md
- 如果发生 repair，保存 repair_prompt_N.md
- mini_runner 调用时将 log 和 trajectory 保存到当前 run_dir 下
- 不污染 git diff

2. 新增 CLI 命令
- codeflow inspect --repo <repo> [--latest] [--run-id <id>] [--limit 10] [--json]
- codeflow report --repo <repo> [--latest] [--run-id <id>] [--path-only]
- codeflow export --repo <repo> [--latest] [--run-id <id>] --out <zip_path>

3. inspect 功能
- 默认显示最新 run 摘要
- 支持列出最近 N 个 runs
- 支持 JSON 输出
- repo 下没有 run 时给出清晰错误

4. report 功能
- 默认打印 review_report.md
- --path-only 时只输出 report 路径

5. export 功能
- 将指定 run_dir 打包为 zip
- 默认包含 state、policy、spec、prompt、checks、sensor report、diff、review report
- 可包含 logs 和 trajectory

6. 新增 codeflow init
- codeflow init --repo <repo> [--force]
- 生成 .codeflow/project_rules.md 和 .codeflow/codeflow.yaml
- 已存在时默认拒绝覆盖，--force 才覆盖

7. 新增 codeflow doctor
- codeflow doctor --repo <repo> [--json] [--skip-checks] [--skip-llm]
- 检查 Git repo、clean worktree、policy file、project rules、pytest、ruff、mini CLI、LLM env
- 对失败项给出 suggestion
- 支持 JSON 输出

8. 增强 Human Approval
- 原有 commit / rollback / keep 保留
- 增加 show-diff、show-report、show-checks、show-sensors、show-files
- high risk 时要求输入 CONFIRM HIGH RISK
- 如果 policy block_commit_on_high_risk=true，则 high risk 不允许 commit，除非 CLI 设置 allow_high_risk_commit

9. 增强 Review Report
- 新报告包含：
  1. Task Summary
  2. Execution Summary
  3. Validation Results
  4. Sensor Report
  5. Changed Files
  6. Risk Assessment
  7. Repair History
  8. Manual Review Checklist
  9. Recommendation
- Changed Files 按 source/test/config/unknown 分类
- Manual Review Checklist 固定包含任务目标、测试覆盖、checks、删除测试、敏感路径、依赖变更、diff 范围等项目
- 根据 sensor warning 动态追加 checklist

10. 测试要求
- 新增/更新单元测试，覆盖 observability、inspect、report、export、init、doctor、governance show-*、review report 新结构
- 保证 uv run pytest -q 通过
- 保证 uv run ruff check . 通过
- 保证 git diff --check 通过

注意：
- 不要新增 benchmark 数据集
- 不要重写 mini-swe-agent
- 不要引入 Web 前端
- 不要引入数据库
- 优先保持现有 codeflow run 主流程兼容
```

---

# 10. 结论

当前阶段最适合做的不是继续扩大 benchmark，也不是重写 agent，而是把 CodeFlow Harness 的**功能完整度**补齐：

```text
能初始化项目
能检查环境
能记录完整运行过程
能查看历史运行
能导出审计证据
能在人工审批时查看 diff/checks/sensors/report
能生成更专业的审查报告
```

这部分完成后，你的项目会更像一个真正的 **AI Coding Agent Harness 工具**，而不是一个只能跑实验的 wrapper。
