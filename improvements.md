# CodeFlow 当前非 Benchmark 后续改进项

本文档记录当前仍值得继续推进的非 benchmark 改进点。已排除 benchmark 覆盖规模、SWE-bench / BugsInPy runnable workspace、长期 benchmark 回归和外部环境 skipped 测试。

## 1. 补充真实 LLM 回归验证

### 当前状态

当前代码已经有较完整的单元测试和本地集成测试，最近一次验证包括：

- `ruff check .`
- `mypy codeflow`
- CI 同款稳定测试子集和 coverage 门槛
- 全量 pytest

这些验证覆盖了 CodeFlow 的主要逻辑，但多数验证仍使用 fake mini、mock semantic client 或本地确定性测试。

用户已明确要求：后续验证均调用真实 LLM。因此，下一步需要补充一套真实 LLM 回归验证流程，覆盖 mini-swe-agent 调用链路、CodeFlow repair loop、semantic review 和 artifact 输出。

### 为什么需要改进

fake mini 和 mock semantic client 能验证控制流、policy、artifact 和错误处理，但不能验证真实模型下的行为质量，例如：

- prompt 是否足够清晰。
- semantic review JSON 是否稳定返回。
- mini-swe-agent 在真实模型下是否能正确执行任务。
- repair prompt 是否能引导模型修复失败 checks。
- 真实模型输出是否触发脱敏、sensor、review summary 和 governance 路径。

这不是代码失败，而是验证层面还缺少真实模型覆盖。

### 改进目标

- 建立可重复执行的真实 LLM smoke / regression 验证命令。
- 每次涉及 agent、prompt、semantic review、runner、observability 的改动后，都能跑真实模型验证。
- 将真实 LLM 验证结果写入可审计 artifact，但默认不提交敏感日志。
- 在 CI 中保留 mock/fake 稳定测试，在本地或手动 workflow 中运行真实 LLM 验证。

### 需要改动的文件

- `codeflow/cli.py`
- `codeflow/runner.py`
- `codeflow/semantic.py`
- `examples/todo_api/.codeflow/codeflow.yaml`
- `tests/` 或新增 `tests_real/`
- 新增 `scripts/run_real_llm_smoke.py`
- 新增 `docs/REAL_LLM_VALIDATION.md`
- `README.md`
- `.github/workflows/ci.yml` 或新增手动 workflow

### 大致实现内容

1. 新增真实 LLM smoke 脚本

   新增：

   ```text
   scripts/run_real_llm_smoke.py
   ```

   该脚本执行一个小型真实任务，例如：

   - 在临时 workspace 中复制 `examples/todo_api`。
   - 初始化 Git。
   - 配置 `.codeflow/codeflow.yaml`，开启 `semantic_spec` 和 `semantic_review`。
   - 调用真实 `codeflow run --no-commit`。
   - 检查：
     - `state.status` 是否是 `checks_passed` 或合理的 `review_required`。
     - `semantic_review.json` 是否存在且结构合法。
     - `review_summary.json` 是否存在。
     - `review_report.md` 是否存在。
     - `diff.patch` 中没有未脱敏 secret-like 内容。

2. 增加真实 semantic review 验证

   新增一个只调用 semantic review 的小测试或脚本路径：

   - 构造一段小 diff。
   - 调用真实 `review_diff_with_semantics()`。
   - 验证返回 JSON 中包含：
     - `status`
     - `risk_level`
     - `summary`
     - `findings`
     - `recommendation`
     - `test_coverage`

   如果模型返回 invalid JSON，要记录原始失败原因和 redacted prompt 摘要。

3. 增加手动 GitHub Actions workflow

   新增可手动触发的 workflow，例如：

   ```text
   .github/workflows/real-llm-smoke.yml
   ```

   使用 `workflow_dispatch`，读取 repository secrets：

   - `OPENAI_API_KEY`
   - `OPENAI_BASE_URL`
   - `MSWEA_MODEL_NAME` 或 `CODEFLOW_SEMANTIC_MODEL`

   默认不在普通 push / PR 中运行，避免成本和外部服务不稳定影响 CI。

4. 代理支持

   文档中说明如果网络不通，可以设置：

   ```bash
   export HTTP_PROXY=http://127.0.0.1:10087
   export HTTPS_PROXY=http://127.0.0.1:10087
   ```

5. 文档说明

   新增 `docs/REAL_LLM_VALIDATION.md`，写明：

   - 需要的环境变量。
   - 如何运行 smoke。
   - 如何判断通过。
   - 哪些 artifact 会生成。
   - 哪些日志默认不提交。

## 2. mini 已接入第一阶段 in-process executor

### 本轮完成状态

已完成第一阶段落地：

- 新增 `MiniRunRequest` 和 `MiniExecutor` 协议。
- 保留 `SubprocessMiniExecutor` 默认路径。
- 新增 `InProcessMiniExecutor`，通过 `CODEFLOW_MINI_EXECUTOR=inprocess` 调用
  `minisweagent.run.mini.run_mini_in_process()`。
- `minisweagent/run/mini.py` 已把 CLI 主流程抽成可导入的 `run_mini_in_process()`。
- 每次 mini 调用都会写入 `mini_run_N.events.jsonl`，记录 prompt/log 写入和 executor command 前后事件。
- `runner` 会把 events artifact 写入 `RunState.artifacts`。
- 已新增 subprocess events、in-process adapter 和非法 executor 配置测试。

后续仍可继续增强：把 mini 内部每一次工具调用、文件写入前后、模型 step 前后事件进一步接到
`ExecutorHook`，用于实时 policy 拦截。目前已不再只是 subprocess 调用边界。

### 当前状态

当前 `codeflow/mini_runner.py` 已经有：

- `SubprocessMiniExecutor`
- `ExecutorHook` 协议预留
- `MiniExecutionError`
- `MiniRunResult.status`
- `MiniRunResult.error_type`

默认执行方式仍然是通过 subprocess 调用本地 mini CLI：

```bash
mini --task-file <prompt> --yolo --exit-immediately --output <trajectory.json>
```

### 为什么需要改进

subprocess 是稳定、兼容、简单的执行边界，但它也带来限制：

- CodeFlow 不能实时观察 mini 内部每一次工具调用。
- 不能在文件写入前做实时 policy 拦截。
- 不能在 shell 命令执行前做实时风险判断。
- 错误分类仍主要依赖进程退出码、stdout/stderr 和 trajectory。
- hook 已预留，但 subprocess 路径无法充分利用 hook。

当前这不是 bug，而是执行器控制粒度的边界。

### 改进目标

- 保留 subprocess 默认实现，避免破坏稳定路径。
- 阅读并评估 `minisweagent/` 内部 API，确认是否可以稳定 in-process 调用。
- 如果可行，新增 `InProcessMiniExecutor`。
- 如果内部 API 不稳定，至少建立 adapter 层和测试，等 mini API 稳定后再接入。
- 让 `ExecutorHook` 能真正接收到命令执行、文件写入、工具调用等事件。

### 需要改动的文件

- `codeflow/mini_runner.py`
- `codeflow/models.py`
- `codeflow/runner.py`
- `minisweagent/run/mini.py`
- `minisweagent/` 下的 agent / tool / environment 相关模块
- `tests/test_mini_runner.py`
- `tests/test_runner.py`
- `docs/CODEFLOW_IMPLEMENTATION.md`
- `docs/harness_design.md`

### 大致实现内容

1. 阅读 mini 内部执行入口

   重点阅读：

   ```text
   minisweagent/run/mini.py
   minisweagent/agents/
   minisweagent/environments/
   minisweagent/tools/
   ```

   目标是找到 CLI 下真正执行任务的核心函数，确认是否可以传入：

   - task text / task file
   - model config
   - working directory
   - output trajectory path
   - non-interactive / yolo / exit-immediately 参数

2. 新增 executor interface

   将当前 executor 约定整理成明确接口：

   ```python
   class MiniExecutor(Protocol):
       def run(self, request: MiniRunRequest) -> MiniRunResult:
           ...
   ```

   新增模型：

   ```python
   class MiniRunRequest(BaseModel):
       repo: str
       prompt_path: str
       trajectory_path: str
       model: str | None
       mini_config: str | None
       env: dict[str, str]
       timeout_seconds: float
   ```

3. 实现 `InProcessMiniExecutor`

   如果 mini 内部 API 可用：

   - 直接在当前进程调用 mini 核心执行函数。
   - 捕获结构化事件。
   - 写入 trajectory。
   - 将异常映射到 `MiniExecutionError.error_type`。

   如果 API 不稳定：

   - 先实现 skeleton。
   - 默认不可启用。
   - 在文档中注明 blocked by internal API stability。

4. 连接 hook

   让 `ExecutorHook` 可以接收：

   - before command
   - after command
   - before file write
   - after file write
   - model step started / finished

   初期 hook 可以只记录 events：

   ```text
   mini_run_0.events.jsonl
   ```

5. 配置开关

   增加环境变量或 policy 字段：

   ```bash
   CODEFLOW_MINI_EXECUTOR=subprocess
   CODEFLOW_MINI_EXECUTOR=inprocess
   ```

   默认仍为 `subprocess`。

6. 测试

   - subprocess executor 行为保持不变。
   - in-process executor smoke。
   - executor hook 能记录事件。
   - in-process 不可用时给出清晰错误。
   - runner 对两种 executor 都能正常处理 result。

## 3. Observability 已具备第一阶段服务化能力

### 本轮完成状态

已完成第一阶段服务化：

- 新增 `codeflow/storage/`：
  - `JsonlRunStore` 读取多仓库 `.git/codeflow/index.jsonl` 和 run artifact。
  - `SQLiteRunStore` 将多仓库 run / finding 同步到 SQLite。
  - `RunFilters` / `FindingFilters` / `RunStore` 协议统一查询接口。
- 新增 `codeflow/server/`：
  - `ObservabilityServerConfig`
  - `handle_server_request()`
  - `serve_codeflow()`
  - bearer token / `X-CodeFlow-Token` 鉴权
  - 多仓库 dashboard
- `codeflow serve` 已支持重复 `--repo`、`--token` 和 `--sqlite-db`。
- 单仓库和多仓库 API 均支持：
  - `/api/runs`
  - `/api/findings`
  - `/api/trends`
  - `/api/failures`
  - `/api/summary`
- 已新增多仓库鉴权、findings/trends/failures 和 SQLite store 测试。

后续仍可继续增强：独立用户体系、RBAC、后台同步 worker、长期部署配置、分页游标、
审计日志和更完整的前端交互。目前已不再只是单用户本地 dashboard。

### 当前状态

当前 Observability 已经支持：

- `.git/codeflow/runs/{run_id}/`
- `.git/codeflow/index.jsonl`
- `codeflow inspect`
- `codeflow search`
- `codeflow summary`
- `codeflow dashboard`
- `codeflow serve`
- `codeflow cleanup`
- `codeflow report`
- `codeflow export`

`serve` 是基于标准库 HTTP server 的本地轻量服务，适合本机调试和单用户查看。

### 为什么需要改进

当前 observability 不是多用户长期平台：

- 没有认证和权限控制。
- 没有数据库。
- 没有后台任务或长期运行进程管理。
- 多个仓库、多用户、多 agent run 的聚合能力有限。
- `index.jsonl` 适合轻量场景，但不适合大量历史数据和复杂查询。
- retention 策略还比较简单。

这不是当前单机 harness 的 bug，而是产品化平台能力尚未扩展。

### 改进目标

- 保留当前轻量本地模式。
- 增加可选长期服务模式。
- 支持多仓库、多用户、多 run 聚合。
- 增加认证、权限和更强查询能力。
- 支持趋势图和失败聚合。

### 需要改动的文件

- `codeflow/harness/observability.py`
- `codeflow/cli.py`
- `codeflow/models.py`
- 新增 `codeflow/server/`
- 新增 `codeflow/storage/`
- `pyproject.toml`
- `tests/test_observability_cli.py`
- 新增 server/storage 测试
- `docs/CODEFLOW_IMPLEMENTATION.md`
- `README.md`

### 大致实现内容

1. 增加存储抽象

   新增：

   ```text
   codeflow/storage/base.py
   codeflow/storage/jsonl_store.py
   codeflow/storage/sqlite_store.py
   ```

   接口示例：

   ```python
   class RunStore(Protocol):
       def add_run(self, run: RunIndexEntry) -> None: ...
       def list_runs(self, filters: RunFilters) -> list[RunIndexEntry]: ...
       def summarize(self, filters: RunFilters) -> RunSummary: ...
   ```

2. 增加 SQLite 后端

   使用标准库 `sqlite3`，避免引入重依赖。

   表结构：

   - `runs`
   - `findings`
   - `artifacts`
   - `checks`
   - `sensors`

3. 增加服务端模块

   新增：

   ```text
   codeflow/server/app.py
   codeflow/server/auth.py
   codeflow/server/views.py
   ```

   初期可以继续使用标准库 HTTP server，也可以评估是否引入 `fastapi` / `uvicorn`。

4. 增加认证

   最小实现：

   - 环境变量 `CODEFLOW_DASHBOARD_TOKEN`
   - HTTP header `Authorization: Bearer ...`
   - 本地模式默认只绑定 `127.0.0.1`

5. 多仓库支持

   支持：

   ```bash
   codeflow serve --repo ./repo1 --repo ./repo2
   ```

   或：

   ```bash
   codeflow serve --workspace-index ~/.codeflow/workspaces.yaml
   ```

6. 查询和趋势

   增加 API：

   - `GET /api/runs?status=&risk=&repo=&from=&to=`
   - `GET /api/findings?category=&severity=`
   - `GET /api/trends`
   - `GET /api/failures`

7. 测试

   - SQLite store add/list/search。
   - token auth。
   - 多 repo 查询。
   - trend summary。
   - cleanup 与 store 一致性。

## 4. 高风险语义仍需人工确认

### 当前状态

CodeFlow 已经具备：

- 规则风险评分。
- sensors。
- semantic review。
- `ReviewSummary` / `ReviewFinding`。
- `block_commit_on_high_risk`。
- `require_semantic_review`。
- `semantic_required_for_paths`。
- 人工 `commit` / `rollback` / `keep` governance。

高风险变更仍需要人工确认，这是正确设计，不应被取消。

### 为什么仍可以改进

需要改进的不是“让高风险自动通过”，而是提升机器辅助审查质量：

- 更清楚说明为什么高风险。
- 更准确定位文件和代码区域。
- 给出更具体的验证建议。
- 降低误报和漏报。
- 保存更完整的审查记录。

最终目标仍然是：机器辅助判断，人工负责最终决策。

### 改进目标

- 保持高风险人工确认。
- 让 high-risk findings 更精确、更可执行。
- 支持文件级、行级、类别级审查提示。
- 根据 finding 自动生成验证建议。
- 记录人工确认原因，便于审计。

### 需要改动的文件

- `codeflow/diff_reviewer.py`
- `codeflow/semantic.py`
- `codeflow/models.py`
- `codeflow/harness/governance.py`
- `codeflow/runner.py`
- `codeflow/harness/observability.py`
- `tests/test_diff_reviewer.py`
- `tests/test_runner.py`
- `tests/test_observability_cli.py`
- `docs/CODEFLOW_IMPLEMENTATION.md`
- `README.md`

### 大致实现内容

1. 增加文件/行级 finding

   扩展 `ReviewFinding`：

   ```python
   class ReviewFinding(BaseModel):
       source: Literal["rules", "sensor", "semantic"]
       severity: Literal["info", "low", "medium", "high"]
       category: str
       file: str | None = None
       line: int | None = None
       diff_hunk: str | None = None
       message: str
       recommendation: str = ""
       verification: list[str] = Field(default_factory=list)
   ```

2. 从 diff 中提取 hunk 上下文

   在 `diff_reviewer.py` 中解析 unified diff：

   - 当前文件。
   - hunk 起始行。
   - 新增行号。
   - 命中风险规则时记录 file / line / hunk。

3. semantic review 输出 line hints

   扩展 semantic schema：

   ```json
   {
     "findings": [
       {
         "severity": "high",
         "file": "app/auth/login.py",
         "line": 42,
         "reason": "Authentication bypass risk",
         "suggested_action": "Add regression test for invalid credentials",
         "verification": ["pytest tests/test_auth.py -q"]
       }
     ]
   }
   ```

4. 自动生成验证建议

   根据 finding category 生成建议：

   - `auth`：建议运行 auth/security tests。
   - `migration`：建议检查 migration rollback/forward。
   - `dependency_change`：建议检查 lockfile 和 import。
   - `missing_test_change`：建议补测试。
   - `shell_check_risk`：建议人工确认命令必要性。

5. 人工确认原因记录

   在 governance commit 流程中，如果 high risk 仍选择 commit，要求输入确认理由：

   ```text
   Why is this high-risk change acceptable?
   ```

   写入：

   ```text
   governance_decision.json
   ```

   包含：

   - decision
   - high_risk_findings
   - approver_reason
   - timestamp

6. Observability 展示

   dashboard / summary 展示：

   - high risk accepted count
   - high risk rollback count
   - top high risk categories
   - recent approval reasons

7. 测试

   - risk finding 能定位 file/line。
   - semantic line hint 能进入 `ReviewFinding`。
   - high-risk commit 要求 reason。
   - `governance_decision.json` 写入。
   - dashboard 能显示 high-risk approval summary。
