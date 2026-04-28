# CodeFlow Harness 完整 Plan

## 0. 新定位

原定位：

```text
CodeFlow Agent：基于 mini-swe-agent v2 的可信工作流包装层
```

新定位：

```text
CodeFlow Harness：面向 Python 项目的 AI Coding Agent 可信执行与验证 Harness
```

核心思想：

```text
mini-swe-agent v2 = Executor
CodeFlow Harness = Guidance + Sensors + Control Loop + Governance + Observability + Evaluation
```

LangChain 对 agent harness 的解释可以概括为：**Agent = Model + Harness**，模型提供智能，harness 让智能变得可用、可控、可执行。([LangChain][1]) Martin Fowler 也强调 coding agent harness 通过 feed-forward 和 feedback 调节代码库走向目标状态。([martinfowler.com][2]) 所以你现在要做的不是“再造一个 coding agent”，而是**设计一套让 coding agent 更可靠的工程外骨骼**。

---

# 1. Harness 总体架构

## 1.1 Harness 分层

把系统拆成 6 层：

```text
1. Guidance Layer：事前指导
   Spec、project_rules、codeflow.yaml、允许/禁止路径、任务约束

2. Executor Layer：执行器
   mini-swe-agent v2

3. Sensor Layer：反馈传感器
   pytest、ruff、mypy、coverage、diff scan、test deletion scan、forbidden path scan

4. Control Loop Layer：闭环控制
   checks 失败 → repair prompt → mini-swe-agent 修复 → 再验证

5. Governance Layer：治理与审批
   commit/rollback/keep、risk policy、commit 前二次检查、人类审批

6. Observability & Evaluation Layer：可观测与评测
   runs 目录、trajectory、prompt、checks、report、benchmark
```

## 1.2 新流程

```text
User Task
  ↓
Git Guard
  ↓
Harness Policy Loader
  ↓
Spec Builder / Guidance Builder
  ↓
Prompt Builder
  ↓
mini-swe-agent v2 Executor
  ↓
Harness Sensors
  ├─ pytest sensor
  ├─ ruff sensor
  ├─ forbidden path sensor
  ├─ test deletion sensor
  ├─ no-change sensor
  ├─ max-diff sensor
  └─ dependency change sensor
  ↓
Harness Control Loop
  ├─ pass → Review
  └─ fail → Repair Prompt → Executor
  ↓
Risk Review
  ↓
Human Approval
  ↓
Commit / Rollback / Keep
  ↓
Run Report + Benchmark Result
```

---

# 2. 目录结构调整 Plan

你当前结构可以保留，但建议新增 `harness/` 目录，把 Harness Engineering 显式化。

```text
codeflow/
├── cli.py
├── runner.py
├── models.py
├── mini_runner.py
├── spec_builder.py
├── prompt_builder.py
├── git_guard.py
├── test_gate.py
├── diff_reviewer.py
├── report_writer.py
├── utils.py
├── harness/
│   ├── __init__.py
│   ├── policy.py              # codeflow.yaml / project_rules 解析与合并
│   ├── guidance.py            # Spec、规则、上下文注入
│   ├── sensors.py             # Sensor 抽象基类
│   ├── builtin_sensors.py     # forbidden_path / test_deletion / no_change 等
│   ├── control_loop.py        # repair loop / stop condition
│   ├── governance.py          # commit policy / approval policy
│   ├── observability.py       # run_dir / state / artifacts
│   └── evaluation.py          # benchmark 统计
├── benchmark/
├── examples/
├── tests/
└── docs/
```

不要一开始全量重构，可以分阶段迁移。

---

# 3. Phase 1：项目定位与文档重构

## 目标

先把项目从 “wrapper” 明确升级为 “harness”。

## 要做什么

### 3.1 改 README 项目介绍

新增：

```markdown
# CodeFlow Harness

CodeFlow Harness is a trusted harness engineering layer for mini-swe-agent v2.

It does not reimplement a coding agent. Instead, it wraps mini-swe-agent with:
- feed-forward guidance
- validation sensors
- repair control loops
- risk governance
- audit logs
- benchmark evaluation
```

### 3.2 新增 `docs/harness_design.md`

内容结构：

```text
1. 什么是 Harness Engineering
2. 为什么 CodeFlow 是 Harness，而不是 Coding Agent
3. mini-swe-agent 负责什么
4. CodeFlow Harness 负责什么
5. Guidance / Sensors / Control Loop / Governance / Observability 五层架构
6. 运行流程图
```

### 3.3 更新项目命名

推荐统一使用：

```text
CodeFlow Harness
```

副标题：

```text
Harness Engineering for Reliable AI Coding Agents
```

## 验收标准

```text
README 中明确出现 Harness Engineering 设计
docs/harness_design.md 能解释项目定位
不再把项目描述为“从零实现 coding agent”
```

---

# 4. Phase 2：Harness Policy 系统

## 目标

把 `.codeflow/project_rules.md` 从“文本提示”升级成“可执行策略”。

你现在已经支持读取 `.codeflow/project_rules.md`，不存在则使用默认规则。 下一步要加入结构化策略文件。

## 4.1 新增 `.codeflow/codeflow.yaml`

示例：

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

## 4.2 新增模型

在 `models.py` 或 `harness/policy.py` 中新增：

```python
class HarnessPolicy(BaseModel):
    required_checks: list[str] = Field(default_factory=lambda: ["pytest -q"])
    max_repair_rounds: int = 3
    max_diff_lines: int = 500
    allowed_paths: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=lambda: [".env", "secrets/", "credentials/"])
    high_risk_paths: list[str] = Field(default_factory=list)
    require_test_change: bool = False
    allow_dependency_change: bool = True
    allow_delete_tests: bool = False
    block_commit_on_failed_checks: bool = True
    block_commit_on_high_risk: bool = False
    require_human_approval: bool = True
    rerun_checks_before_commit: bool = True
```

## 4.3 规则优先级

```text
CLI 参数 > codeflow.yaml > project_rules.md > 默认值
```

例如：

```bash
codeflow run --checks "pytest -q"
```

覆盖 yaml 里的 `required_checks`。

## 4.4 Prompt 注入

initial prompt 和 repair prompt 中必须注入：

```text
Harness Policy:
- required checks
- forbidden paths
- max repair rounds
- test policy
- dependency policy
```

## 验收标准

```text
codeflow.yaml 不存在时正常 fallback
CLI checks 能覆盖 yaml checks
policy 能进入 prompt
单元测试覆盖 policy 合并逻辑
```

---

# 5. Phase 3：Harness Sensors

## 目标

把现在的 `Test Gate + Diff Reviewer` 升级成多个可组合 sensor。

SIG 对 harness engineering 的定义里强调，harness 包括 agent 运行环境中的规则、检查和反馈循环，用来让不稳定 agent 更可靠。([SIG][3]) 所以你要把 checks、diff 风险、路径限制都做成传感器。

## 5.1 Sensor 抽象

新增：

```python
class SensorResult(BaseModel):
    name: str
    passed: bool
    severity: Literal["info", "low", "medium", "high"]
    message: str
    details: dict = Field(default_factory=dict)
```

```python
class BaseSensor(Protocol):
    name: str
    def run(self, context: SensorContext) -> SensorResult:
        ...
```

`SensorContext` 包括：

```python
class SensorContext(BaseModel):
    repo: str
    task: str
    diff: str
    changed_files: list[str]
    policy: HarnessPolicy
    check_results: list[CheckResult]
```

## 5.2 第一批 Sensors

### 1. CheckCommandSensor

已有 `pytest` / `ruff` 逻辑迁移过来。

```text
输入：required_checks
输出：每条命令 pass/fail
```

### 2. ForbiddenPathSensor

检测 diff 是否修改：

```text
.env
secrets/
credentials/
*.pem
*.key
policy.forbidden_paths
```

命中则：

```text
passed = false
severity = high
```

### 3. HighRiskPathSensor

检测是否修改：

```text
app/auth/
app/db/
migrations/
config/
```

命中则：

```text
passed = true
severity = medium/high
```

不一定阻断，但要提示人工重点看。

### 4. TestDeletionSensor

检测是否删除测试：

```text
- def test_
- assert
- pytest.raises
```

命中则：

```text
passed = false
severity = high
```

### 5. MissingTestChangeSensor

如果任务是 `feature` / `bugfix`，且改了业务代码但没有改 `tests/`：

```text
passed = true
severity = medium
message = "功能代码变更但没有测试变更"
```

### 6. DependencyChangeSensor

检测：

```text
pyproject.toml
requirements.txt
poetry.lock
uv.lock
```

如果 `allow_dependency_change=false`，则标 high。

### 7. MaxDiffSensor

如果 diff 行数超过 `max_diff_lines`：

```text
severity = high
message = "Diff 过大，需要人工重点审查"
```

### 8. NoChangeSensor

如果 `git diff` 为空：

```text
passed = false
severity = medium
message = "没有检测到代码修改，不能把原有测试通过误判为任务成功"
```

## 5.3 Sensor 汇总

新增：

```python
class HarnessSensorReport(BaseModel):
    results: list[SensorResult]
    overall_passed: bool
    max_severity: Literal["info", "low", "medium", "high"]
    blocking_reasons: list[str]
```

## 验收标准

```text
pytest/ruff 仍能正常运行
forbidden path 命中 high
删除测试命中 high
无 diff 命中 fail
功能变更无测试变更有 warning
所有 sensor 结果进入 report
```

---

# 6. Phase 4：PEV + Repair Control Loop

## 目标

把现在的 repair loop 明确包装为 Harness Control Loop。

PEV 可以定义为：

```text
Plan → Execute → Verify → Repair
```

你当前已经有：构造 prompt → 调用 mini-swe-agent → 运行 checks → 失败修复，文档里也记录了 checks 失败时最多自动修复 3 轮。 下一步要让 loop 不只看 pytest，还看所有 sensors。

## 6.1 新 loop 逻辑

```text
Plan:
  build spec
  load harness policy
  build guidance prompt

Execute:
  run mini-swe-agent

Verify:
  run check sensors
  run diff sensors
  build sensor report

Repair:
  if blocking sensor failed and repair_round < max:
      build repair prompt with sensor report
      run mini-swe-agent again
  else:
      stop
```

## 6.2 哪些失败可以 repair

可以进入 repair：

```text
pytest failed
ruff failed
missing test change
no change
dependency error
```

不建议自动 repair 或要谨慎：

```text
forbidden path modified
test deletion detected
too large diff
```

这些更适合直接 `review_required` 或 `reject`。

## 6.3 Repair Prompt 增强

repair prompt 不只放 stdout/stderr，还要放 sensor report：

```text
Failed Sensors:
- pytest: failed
- missing_test_change: warning
- no_change: failed

Blocking Reasons:
- pytest -q failed
- implementation changed app/ but no tests were added

Please fix the implementation with minimal changes.
Do not delete tests.
Do not modify forbidden paths.
```

## 验收标准

```text
repair loop 由 sensor report 驱动
pytest fail 可以 repair
no-change 可以 repair
forbidden path 不自动 blind repair，直接高风险
```

---

# 7. Phase 5：Governance 与 Commit Policy

## 目标

把 commit/rollback/keep 从简单交互升级成 governance policy。

你现在已经有人审 `commit / rollback / keep`，并且 checks 失败拒绝 commit。 下一步加二次检查和风险门禁。

## 7.1 Commit 前二次 checks

流程：

```text
用户选择 commit
  ↓
重新运行 required_checks
  ↓
重新运行关键 sensors
  ↓
通过才 commit
```

防止中间文件被改。

## 7.2 Commit Policy

根据 sensor report 决策：

```text
checks failed → block commit
forbidden path modified → block or require explicit override
test deletion → block commit
high risk → require human confirmation
medium risk → allow commit after confirmation
low risk → allow commit
```

## 7.3 CLI 增加 override

```bash
codeflow run --allow-high-risk-commit
```

默认不建议开。

## 7.4 Approval 输出

人审界面显示：

```text
Task
Branch
Checks
Risk Level
Blocking Sensors
Warnings
Options:
- commit
- rollback
- keep
- show-diff
- show-report
```

## 验收标准

```text
commit 前会重新跑 checks
高风险有明确提示
失败 checks 不能 commit
删除测试不能 commit
```

---

# 8. Phase 6：Observability / Audit Trail

## 目标

让每次运行都可追溯、可复盘、可评测。

你当前日志和 trajectory 放在目标仓库 `.git/codeflow/` 下，这个设计很好，因为不会污染工作区 diff。 下一步把它规范化。

## 8.1 Run 目录结构

```text
.git/codeflow/
└── runs/
    └── 20260428-153012-add-priority/
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
        ├── checks_round_1.json
        ├── sensor_report_round_1.json
        ├── diff.patch
        ├── risk_report.json
        └── review_report.md
```

## 8.2 新命令

### 查看最近运行

```bash
codeflow inspect --repo ./examples/todo_api
```

输出：

```text
Latest run:
- run_id
- task
- branch
- status
- checks
- risk level
- report path
```

### 查看报告

```bash
codeflow report --repo ./examples/todo_api --latest
```

### 导出运行包

```bash
codeflow export --repo ./examples/todo_api --latest --out ./artifacts/run.zip
```

## 验收标准

```text
每次运行有独立 run_id
所有 prompt / checks / sensors / diff / report 可追溯
inspect/report 命令可用
```

---

# 9. Phase 7：Harness Benchmark

## 目标

Benchmark 从“CodeFlow 是否能跑”升级为“不同 harness 配置带来的可靠性差异”。

这点非常重要。Harness Engineering 的重点不是模型变聪明，而是在同一个模型、同一个 executor 下，通过规则、反馈和门禁提高可靠性。

## 9.1 对比组

至少做 4 组：

```text
A. Raw mini-swe-agent
   直接调用 mini，不加 CodeFlow

B. mini + checks only
   执行后只跑 pytest/ruff，不 repair，不 risk review

C. CodeFlow Harness basic
   policy + checks + repair loop

D. CodeFlow Harness full
   policy + checks + repair + sensors + governance + risk review
```

## 9.2 数据集

当前 benchmark 只有 3 个 todo_api 任务。 需要扩展到 20～30 个任务。

新增 example：

```text
examples/todo_api
examples/file_utils
examples/student_manager
```

任务类型：

```text
feature：8 个
bugfix：8 个
test_only：4 个
refactor：4 个
quality：4 个
```

## 9.3 指标

```text
Task Success Rate
Checks Pass Rate
Repair Success Rate
Average Repair Rounds
Unsafe Diff Rate
Forbidden Path Violation Rate
Test Deletion Rate
Missing Test Warning Rate
No-change False Success Rate
Average Runtime
Human Review Required Rate
```

## 9.4 输出报告

```text
benchmark/results.json
benchmark/report.md
benchmark/report.csv
```

报告表格：

```text
Method                 Tasks  Pass  Unsafe  Avg Repair  No-change  Test Deleted
Raw mini               30     18    5       -           3          1
Checks only            30     19    5       -           2          1
Harness basic          30     23    3       1.1         1          0
Harness full           30     24    0       1.3         0          0
```

## 验收标准

```text
benchmark 能一键运行
能对比 raw mini 和 CodeFlow Harness
report.md 能解释 harness 带来的收益
```

---

# 10. Phase 8：LLM Guidance 与 LLM Review

## 目标

在规则稳定基础上，加入 LLM 作为推理型 guidance 和推理型 sensor。

注意：不要让 LLM 替代规则。规则是底线，LLM 是增强。

## 10.1 LLM Spec Builder

CLI：

```bash
codeflow run --spec-mode rule
codeflow run --spec-mode llm
codeflow run --spec-mode hybrid
```

推荐默认：

```text
hybrid 或 rule
```

LLM 输出：

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
JSON parse 失败 → fallback 到 rule spec
LLM spec 不能删除默认 constraints
```

## 10.2 LLM Review Sensor

CLI：

```bash
codeflow run --review-mode rule
codeflow run --review-mode llm
codeflow run --review-mode hybrid
```

推荐默认：

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
  "changed_behavior": ["..."],
  "potential_breakages": ["..."],
  "test_coverage_gaps": ["..."],
  "manual_review_focus": ["..."],
  "risk_level": "medium",
  "recommendation": "review_required"
}
```

强规则：

```text
LLM 不允许降低 rule sensor 检出的 high risk
LLM parse 失败 fallback rule report
```

## 验收标准

```text
LLM spec 可选
LLM review 可选
hybrid 模式稳定 fallback
高风险规则不能被 LLM 洗白
```

---

# 11. Phase 9：安全增强

## 目标

防止 coding agent 做危险修改。

## 11.1 Secret / Env 保护

检测：

```text
.env
.env.*
*.pem
*.key
id_rsa
credentials.json
```

如果 diff 中新增类似：

```text
sk-
api_key
password=
token=
```

直接 high risk。

## 11.2 依赖安全

检测新增依赖：

```text
requirements.txt
pyproject.toml
```

提示：

```text
新增依赖需要人工确认
```

## 11.3 大 diff 限制

如果：

```text
diff lines > max_diff_lines
changed files > max_changed_files
```

标记 high risk。

## 11.4 路径越界保护

你当前 rollback 已经做了未跟踪文件删除的路径边界检查，这个很好。 后续可以把路径边界保护也纳入 `Governance` 文档。

## 验收标准

```text
敏感文件修改被阻止
疑似 secret 新增被提示
大规模 diff 被标 high
```

---

# 12. Phase 10：CLI 体验增强

## 目标

让项目更容易演示。

## 12.1 新增命令

```bash
codeflow inspect --repo <repo>
codeflow report --repo <repo> --latest
codeflow policy --repo <repo>
codeflow benchmark --config benchmark/tasks.yaml
```

## 12.2 Rich 输出分阶段

```text
[1/9] Git Guard
[2/9] Load Harness Policy
[3/9] Build Spec
[4/9] Run mini-swe-agent
[5/9] Run Checks
[6/9] Run Sensors
[7/9] Repair Loop
[8/9] Risk Review
[9/9] Governance Decision
```

## 12.3 支持非交互

```bash
codeflow run --yes keep
codeflow run --yes rollback
codeflow run --yes commit
```

用于 benchmark 和自动化测试。

---

# 13. Phase 11：测试补充

## 新增测试文件

```text
tests/test_harness_policy.py
tests/test_harness_sensors.py
tests/test_control_loop.py
tests/test_governance.py
tests/test_observability.py
tests/test_benchmark_harness.py
tests/test_llm_spec_builder.py
tests/test_llm_review_sensor.py
```

## 必测用例

```text
1. codeflow.yaml 不存在时 fallback
2. CLI checks 覆盖 yaml checks
3. forbidden path 命中 high
4. 删除测试被标记 high
5. 功能变更但无测试变更 warning
6. no-change 被标为 fail
7. max_diff_lines 超限 high
8. checks fail 进入 repair
9. forbidden path 不进入盲目 repair
10. commit 前 checks 失败拒绝
11. LLM JSON parse 失败 fallback
12. LLM 不能降低 high risk
```

---

# 14. Phase 12：最终展示材料

## README 必须包含

```text
1. 项目定位：CodeFlow Harness
2. Harness Engineering 背景
3. 为什么基于 mini-swe-agent v2
4. 架构图
5. 快速开始
6. codeflow.yaml 示例
7. 一次完整运行示例
8. sensor report 示例
9. benchmark 结果
10. 已知限制
```

## docs 目录

```text
docs/
├── harness_design.md
├── workflow.md
├── policy.md
├── sensors.md
├── governance.md
├── benchmark.md
└── limitations.md
```

## Demo 准备

准备 3 个 Demo：

```text
Demo 1：正常功能新增，checks 通过，low risk
Demo 2：第一次失败，repair 后通过
Demo 3：修改敏感文件或删除测试，被 sensor 标 high risk
```

---

# 15. 推荐执行顺序

## 第一优先级：Harness 化基础

```text
1. README 改成 CodeFlow Harness
2. 新增 docs/harness_design.md
3. 新增 HarnessPolicy 和 codeflow.yaml
4. policy 合并逻辑：CLI > yaml > project_rules > default
```

## 第二优先级：Sensors

```text
5. SensorResult / SensorContext
6. ForbiddenPathSensor
7. TestDeletionSensor
8. MissingTestChangeSensor
9. NoChangeSensor
10. MaxDiffSensor
11. DependencyChangeSensor
```

## 第三优先级：Control Loop / Governance

```text
12. repair loop 改为 sensor-driven
13. commit 前二次 checks
14. high risk commit policy
15. blocking sensor report
```

## 第四优先级：Observability

```text
16. .git/codeflow/runs/{run_id}/ 标准目录
17. 保存 prompt / checks / sensors / diff / report / state
18. codeflow inspect / report
```

## 第五优先级：Benchmark

```text
19. 新增 file_utils / student_manager
20. 扩展 20～30 个任务
21. raw mini vs CodeFlow Harness 对比
22. 生成 benchmark/report.md
```

## 第六优先级：LLM 增强

```text
23. LLM Spec Builder
24. LLM Review Sensor
25. hybrid 模式和 fallback
```

## 第七优先级：展示

```text
26. README 完善
27. docs 完善
28. Demo 三套
29. benchmark 表格
```

---

# 16. 最终验收标准

项目完成后应满足：

```text
1. codeflow run 能完整执行 harness 流程
2. mini-swe-agent 仍作为 executor，不重写 agent
3. codeflow.yaml 可配置 harness policy
4. Sensors 能检测 checks、敏感路径、删除测试、无测试变更、无 diff、大 diff、依赖变更
5. Repair Loop 由 sensor report 驱动
6. Governance 能阻止失败 checks / 高危修改直接 commit
7. 每次运行都有完整 audit trail
8. benchmark 能对比 raw mini 与 CodeFlow Harness
9. README 和 docs 能讲清楚 Harness Engineering 设计
10. 至少 20 个 benchmark 任务，有量化结果
```

---

## 一句话总结

你现在已经有了一个可运行的 CodeFlow wrapper；加入 Harness Engineering 后，项目核心应该升级为：

> **以 mini-swe-agent v2 为 Executor，围绕它构建 Guidance、Sensors、Control Loop、Governance、Observability 和 Benchmark，让 AI Coding Agent 的执行过程可约束、可验证、可修复、可审查、可量化。**

[1]: https://www.langchain.com/blog/the-anatomy-of-an-agent-harness?utm_source=chatgpt.com "The Anatomy of an Agent Harness"
[2]: https://martinfowler.com/articles/harness-engineering.html?utm_source=chatgpt.com "Harness engineering for coding agent users"
[3]: https://www.softwareimprovementgroup.com/blog/what-is-harness-engineering/?utm_source=chatgpt.com "What is harness engineering? - SIG"
