# Harness Design

## 1. 什么是 Harness Engineering

Harness Engineering 是围绕 AI coding agent 构建的工程外骨骼。模型负责智能决策和代码修改，harness 负责把这个过程放进可控的运行环境中：提供上下文、执行命令、收集反馈、触发修复、执行门禁、生成审计记录。

对 coding agent 来说，harness 的价值不是“替模型写代码”，而是把不稳定的模型行为接入工程化反馈循环，让一次任务执行更接近可复盘、可验证、可治理的交付流程。

## 2. 为什么 CodeFlow 是 Harness，而不是 Coding Agent

CodeFlow Harness 不从零实现 coding agent，也不替代 mini-swe-agent 的执行能力。它把 mini-swe-agent v2 作为 Executor，然后在外层实现：

- Guidance：Spec、project rules、Harness Policy 注入。
- Sensors：pytest、ruff、路径、测试删除、无变更、大 diff、依赖变更检测。
- Control Loop：失败后构造 repair prompt 并再次调用 Executor。
- Governance：commit / rollback / keep，commit 前二次检查和风险门禁。
- Observability：日志、trajectory、report、benchmark 结果。

所以 CodeFlow 的定位是：

```text
mini-swe-agent v2 = Executor
CodeFlow Harness = Guidance + Sensors + Control Loop + Governance + Observability + Evaluation
```

## 3. mini-swe-agent 负责什么

mini-swe-agent v2 负责：

- 读取任务 prompt。
- 探索目标仓库。
- 执行 shell 命令。
- 编辑代码。
- 根据 repair prompt 修复问题。
- 产出 trajectory。

CodeFlow 不重写这些能力，默认通过 `SubprocessMiniExecutor` 调用本地 `mini` CLI，并保留 executor 抽象以便后续接入更细粒度执行器。

## 4. CodeFlow Harness 负责什么

CodeFlow Harness 负责：

- 检查目标目录是干净 Git 仓库。
- 创建 `ai/*` 隔离分支。
- 读取 `.codeflow/project_rules.md`。
- 读取 `.codeflow/codeflow.yaml` 并合并 CLI 覆盖项。
- 生成结构化 Spec 和 Guidance Prompt。
- 运行 mini-swe-agent。
- 运行 required checks。
- 运行 built-in sensors。
- 根据 sensor report 决定是否 repair、review required 或允许进入 commit。
- 生成 Markdown Review Report。
- 执行人工审批后的 commit / rollback / keep。

## 5. 五层架构

```text
Guidance Layer
  Spec + project_rules + codeflow.yaml + Harness Policy

Executor Layer
  mini-swe-agent v2

Sensor Layer
  checks + forbidden path + test deletion + no-change + max-diff + dependency scan

Control Loop Layer
  verify failed -> repair prompt -> executor -> verify again

Governance Layer
  risk policy + human approval + rerun before commit + commit/rollback/keep

Observability & Evaluation Layer
  logs + trajectory + review report + benchmark
```

## 6. 运行流程图

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
  ├─ check command sensor
  ├─ forbidden path sensor
  ├─ forbidden path write sensor
  ├─ allowed path sensor
  ├─ test deletion sensor
  ├─ missing test change sensor
  ├─ dependency change sensor
  ├─ secret-like content sensor
  ├─ max diff sensor
  └─ no change sensor
  ↓
Harness Control Loop
  ├─ pass -> Review
  └─ repairable fail -> Repair Prompt -> Executor
  ↓
Risk Review
  ↓
Human Approval
  ↓
Commit / Rollback / Keep
  ↓
Run Report + Benchmark Result
```

## 7. 当前边界

当前实现已经覆盖 Harness 化基础、结构化 policy、第一批 sensors、commit 前二次检查、
可选 LLM Spec / Review、结构化 review summary、标准 run 目录、run index、
`inspect` / `search` / `summary` / `dashboard` / `serve` / `cleanup` / `report` / `export` 命令、
mini executor 抽象、子进程超时保护、GitHub Actions CI、raw mini 对比 benchmark
和真实 LLM 小子集评测。
仍属于后续阶段的是更大规模 benchmark 覆盖、可复现 raw artifact 归档、多用户服务化平台和 in-process executor。
