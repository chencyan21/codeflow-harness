# CodeFlow 非 Benchmark 改进项完成记录

本文档原本记录当前项目中仍可继续改进的非 benchmark 项。当前这些条目已按顺序落地到代码、测试和文档中。已按要求排除 BugsInPy、SWE-bench、真实 benchmark 长期回归、benchmark artifact 归档等内容；外部环境导致的 skipped 测试也不作为代码问题记录。

## 完成摘要

- 第 1 项已完成：语义 Spec / Diff Review 增加超时、diff 长度、fail-open/fail-closed、路径强制审查、扩展 schema 和结构化失败原因。
- 第 2 项已完成：Diff Review 新增 `ReviewSummary` / `ReviewFinding`，runner 写入 `review_summary.json`，report 展示结构化 findings。
- 第 3 项已完成：Observability 新增 `.git/codeflow/index.jsonl`、dashboard 前端筛选、`serve` 本地 HTTP API 和 `cleanup`。
- 第 4 项已完成：mini runner 新增 executor 抽象、`MiniExecutionError` 错误分类和 `MiniRunResult.status/error_type`。
- 第 5 项已完成：shell check 新增风险扫描，doctor 和 `shell_check_risk` sensor 会提示高风险 shell 片段。

## 1. 语义 Spec / Diff Review 仍是可选能力

状态：已完成。

### 当前状态

CodeFlow 已有 `codeflow/semantic.py`，可以在 `semantic_spec: true` 时对规则版 Spec 做 LLM 语义增强，也可以在 `semantic_review: true` 或 `require_semantic_review: true` 时对 diff 做 LLM 语义审查。

当前语义能力依赖 OpenAI-compatible 配置，例如：

- `CODEFLOW_SEMANTIC_MODEL`
- `MSWEA_MODEL_NAME`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `.env` 中的 `semantic_model`、`model_id`、`api_key`、`base_url`

如果没有模型配置，语义增强和语义审查会跳过；只有设置 `require_semantic_review: true` 时才会强制进入 `review_required` 并拒绝提交。

### 问题

- 默认情况下，语义能力不是强制链路，很多项目仍会只使用规则版 Spec 和规则版 diff reviewer。
- 语义审查返回的 JSON schema 还比较简单，主要包含风险等级、summary、findings、recommendation、task alignment 和 test coverage notes。
- 语义审查失败时目前只返回 `None` 或生成 unavailable 状态，缺少更细的失败原因，例如配置缺失、网络失败、模型返回非 JSON、超时、rate limit。
- 当前没有针对语义审查结果的历史对比，例如同类任务反复被判高风险时的趋势或模式。

### 改进目标

- 让语义审查可以成为更稳定、更可审计的 policy 能力。
- 增加更精细的 schema，减少规则误判和漏判。
- 将语义审查失败原因结构化写入 artifact，便于排查。
- 支持按项目选择不同语义模型、超时和失败策略。

### 建议改动文件

- `codeflow/semantic.py`
- `codeflow/models.py`
- `codeflow/harness/policy.py`
- `codeflow/runner.py`
- `codeflow/diff_reviewer.py`
- `codeflow/init_project.py`
- `tests/test_semantic.py`
- `tests/test_runner.py`
- `docs/CODEFLOW_IMPLEMENTATION.md`
- `docs/PROJECT_OVERVIEW.md`
- `README.md`

### 大致改动内容

1. 扩展 `HarnessPolicy`

   在 `codeflow/models.py` 的 `HarnessPolicy` 中增加语义审查相关字段：

   ```python
   semantic_timeout_seconds: float = 60
   semantic_max_diff_chars: int = 20000
   semantic_fail_open: bool = True
   semantic_required_for_paths: list[str] = Field(default_factory=list)
   ```

   含义：

   - `semantic_timeout_seconds`：语义 LLM 调用超时时间。
   - `semantic_max_diff_chars`：传给模型的 diff 最大字符数。
   - `semantic_fail_open`：语义审查失败时是否允许继续；如果为 false，则进入 `review_required`。
   - `semantic_required_for_paths`：命中特定路径时强制要求语义审查，例如 `app/auth/`、`migrations/`。

2. 扩展语义审查 JSON schema

   在 `codeflow/semantic.py` 中把 review schema 从当前简版扩展为：

   ```json
   {
     "risk_level": "low|medium|high",
     "summary": "short summary",
     "findings": [
       {
         "severity": "low|medium|high",
         "file": "path or empty",
         "reason": "specific issue",
         "suggested_action": "what to inspect or change"
       }
     ],
     "task_alignment": "aligned|partial|not_aligned|unknown",
     "test_coverage": {
       "level": "none|weak|adequate|strong",
       "notes": "coverage assessment"
     },
     "behavioral_risks": ["risk"],
     "security_risks": ["risk"],
     "data_migration_risks": ["risk"],
     "recommendation": "commit|manual_review|block"
   }
   ```

3. 结构化失败原因

   将 `_semantic_json()` 失败时的原因保留下来，不要只返回 `None`。可以增加 `SemanticResult` 或返回结构：

   ```python
   {
       "status": "unavailable",
       "reason": "missing_config|timeout|api_error|invalid_json",
       "message": "...",
   }
   ```

   然后在 `runner.py` 中写入 `semantic_review.json`，并在 `review_report.md` 中显示失败原因。

4. 基于路径强制语义审查

   在 `runner.py` 中根据 `policy.semantic_required_for_paths` 和 `changed_files` 判断是否强制语义审查：

   - 如果命中强制路径但语义审查不可用，则 `state.status = "review_required"`。
   - 如果命中强制路径且语义审查返回 high risk，则在 `block_commit_on_high_risk` 时拒绝提交。

5. 测试补充

   在 `tests/test_semantic.py` 中增加：

   - 模型返回扩展 schema 时能被规范化。
   - 模型返回 invalid JSON 时记录 `invalid_json`。
   - 模型调用异常时记录 `api_error`。

   在 `tests/test_runner.py` 中增加：

   - 命中 `semantic_required_for_paths` 且无模型配置时进入 `review_required`。
   - `semantic_fail_open: false` 时语义调用失败会阻断。

## 2. Diff Review 仍需要人工兜底

状态：已完成。

### 当前状态

`codeflow/diff_reviewer.py` 已经结合以下信号生成 Markdown 审查报告：

- changed files
- diff 行数
- required checks 结果
- sensor report
- 高风险路径
- 规则关键词
- 破坏性新增代码模式
- 可选 semantic review

报告会生成风险等级和 recommendation，并在高风险条件下配合 governance 阻断提交。

### 问题

- 规则审查仍无法真正理解业务语义，例如权限绕过、边界条件遗漏、兼容性变化。
- 当前风险说明主要是 report 文本，不够适合机器消费和后续聚合。
- Review report 中的 findings 没有统一结构，后续做搜索、趋势或 UI 时会比较困难。
- 高风险变更仍主要依赖人工审查兜底。

### 改进目标

- 让 diff review 的输出同时适合人读和机器读。
- 将规则 reviewer、sensor report、semantic review 的 findings 统一成结构化 review model。
- 让高风险项可以按文件、类型、严重程度聚合。

### 建议改动文件

- `codeflow/diff_reviewer.py`
- `codeflow/models.py`
- `codeflow/runner.py`
- `codeflow/harness/observability.py`
- `tests/test_diff_reviewer.py`
- `tests/test_observability_cli.py`
- `docs/CODEFLOW_IMPLEMENTATION.md`

### 大致改动内容

1. 新增结构化 review model

   在 `codeflow/models.py` 中增加：

   ```python
   class ReviewFinding(BaseModel):
       source: Literal["rules", "sensor", "semantic"]
       severity: Literal["info", "low", "medium", "high"]
       category: str
       file: str | None = None
       message: str
       recommendation: str = ""

   class ReviewSummary(BaseModel):
       risk_level: Literal["info", "low", "medium", "high"]
       findings: list[ReviewFinding] = Field(default_factory=list)
       recommendation: str
   ```

2. 让 diff reviewer 返回结构化对象

   将当前 `build_review_report()` 拆成两层：

   - `build_review_summary()`：返回 `ReviewSummary`。
   - `render_review_report()`：把 `ReviewSummary` 渲染成 Markdown。

   这样可以同时写入：

   - `review_summary.json`
   - `review_report.md`

3. 将 sensors 和 semantic review 合并进统一 findings

   在 `runner.py` 中把 sensor failures、semantic findings、规则风险全部转换成 `ReviewFinding`。

4. Observability 使用结构化 review

   在 `codeflow/harness/observability.py` 中读取 `review_summary.json`，让 `summary` 和 `dashboard` 可以展示：

   - high risk finding 数量
   - 常见 finding category
   - 最近 high risk 文件

5. 测试补充

   - `tests/test_diff_reviewer.py` 验证结构化 findings。
   - `tests/test_observability_cli.py` 验证 dashboard 能显示 finding category。
   - `tests/test_runner.py` 验证 `review_summary.json` 被写入 artifact。

## 3. Observability 还不是服务化平台

状态：已完成。

### 当前状态

CodeFlow 已有 run artifact 目录：

```text
.git/codeflow/runs/{run_id}/
```

并支持以下 CLI：

- `codeflow inspect`
- `codeflow search`
- `codeflow summary`
- `codeflow dashboard`
- `codeflow report`
- `codeflow export`

其中 `dashboard` 会生成本地静态 HTML。

### 问题

- dashboard 是静态 HTML，不是长期运行的 Web 服务。
- 当前数据来源主要是文件系统扫描，没有索引，run 多了之后搜索和汇总会变慢。
- dashboard 不能交互式筛选 status、risk、task、branch、日期范围。
- 没有趋势图、失败类别聚合、repair round 趋势、模型表现对比。
- 没有统一的 artifact retention 策略，例如保留最近 N 次、压缩历史、删除敏感大文件。

### 改进目标

- 提供轻量本地 Web UI，方便浏览历史 run。
- 增加本地索引，提高搜索和趋势统计效率。
- 支持按 status、risk、日期、task、branch、finding category 筛选。
- 支持 artifact retention 策略，避免 `.git/codeflow` 无限增长。

### 建议改动文件

- `codeflow/cli.py`
- `codeflow/harness/observability.py`
- `codeflow/models.py`
- `pyproject.toml`
- `tests/test_observability_cli.py`
- `docs/CODEFLOW_IMPLEMENTATION.md`
- `README.md`

### 大致改动内容

1. 增加 run index

   在 `.git/codeflow/index.jsonl` 中追加每次 run 的摘要：

   ```json
   {
     "run_id": "20260502-...",
     "created_at": "2026-05-02T...",
     "task": "...",
     "branch": "ai/...",
     "status": "checks_passed",
     "risk_level": "low",
     "checks_passed": true,
     "sensor_passed": true,
     "repair_round": 0,
     "finding_counts": {"high": 0, "medium": 1}
   }
   ```

   在 `runner.py` 的 `_write_final_state()` 或 observability helper 中更新索引。

2. 增加 Web 服务命令

   在 `codeflow/cli.py` 中新增：

   ```bash
   codeflow serve --repo ./target --host 127.0.0.1 --port 8765
   ```

   可选实现方式：

   - 使用标准库 `http.server` 提供最小本地服务。
   - 或增加轻量依赖，例如 `fastapi` / `uvicorn`，但需要评估依赖重量。

3. 增加 API endpoint

   如果使用 Web 服务，可以提供：

   - `GET /api/runs`
   - `GET /api/runs/{run_id}`
   - `GET /api/summary`
   - `GET /api/report/{run_id}`
   - `GET /api/artifacts/{run_id}`

4. 改造 dashboard

   让 `build_runs_dashboard_html()` 支持前端筛选：

   - status filter
   - risk filter
   - task 搜索
   - 日期范围
   - 失败 run only

   如果不引入前端框架，可以用原生 HTML + JavaScript 完成。

5. 增加 retention 策略

   新增 CLI：

   ```bash
   codeflow cleanup --repo ./target --keep 100 --dry-run
   ```

   支持：

   - 保留最近 N 个 run。
   - 删除或压缩旧 run。
   - 默认不删除 `review_report.md`、`state.json`、`review_summary.json`。

6. 测试补充

   - `tests/test_observability_cli.py` 增加 `serve` 的 endpoint 单元测试。
   - 增加 index 写入和读取测试。
   - 增加 cleanup dry-run 和实际清理测试。

## 4. mini-swe-agent 仍通过 subprocess 调用

状态：已完成。

### 当前状态

`codeflow/mini_runner.py` 通过 subprocess 调用 mini-swe-agent CLI：

```bash
mini --task-file <prompt_path> --yolo --exit-immediately --output <trajectory.json>
```

当前已经具备：

- `CODEFLOW_MINI_COMMAND` 覆盖命令。
- `.env` 到 OpenAI-compatible 环境变量映射。
- prompt 文件方式传参。
- mini 日志和 trajectory artifact。
- `CODEFLOW_MINI_TIMEOUT_SECONDS` 超时控制。
- 超时后终止子进程组。
- prompt、日志、trajectory 脱敏。

### 问题

- CodeFlow 无法直接控制 mini 内部的每一步工具调用。
- 只能通过 prompt、环境变量、超时、Git 隔离和事后 sensors 约束行为。
- 无法在 mini 执行中途对具体文件写入、命令执行、网络访问做实时拦截。
- subprocess 边界使错误分类比较粗，例如模型错误、工具错误、用户代码错误可能都表现为 mini 非零退出。

### 改进目标

- 保留 CLI subprocess 兼容模式，同时增加更强的内部执行器适配层。
- 尽可能捕获 mini 的结构化事件，而不是只看最终日志和 trajectory。
- 为未来实时 policy enforcement 留出接口。

### 建议改动文件

- `codeflow/mini_runner.py`
- `codeflow/models.py`
- `codeflow/runner.py`
- `minisweagent/`
- `tests/test_mini_runner.py`
- `tests/test_runner.py`
- `docs/CODEFLOW_IMPLEMENTATION.md`

### 大致改动内容

1. 引入 executor 抽象

   新增或扩展模型：

   ```python
   class ExecutorResult(BaseModel):
       log_path: str
       trajectory_path: str
       returncode: int
       status: str
       error_type: str | None = None
       events_path: str | None = None
   ```

   在 `mini_runner.py` 中提供：

   - `SubprocessMiniExecutor`
   - 未来可加 `InProcessMiniExecutor`

2. 保留默认 subprocess 模式

   继续支持当前稳定路径：

   ```python
   run_mini_agent(...)
   ```

   内部改为调用 executor：

   ```python
   executor = SubprocessMiniExecutor(...)
   result = executor.run(...)
   ```

3. 增加结构化错误分类

   在 `_run_mini_subprocess()` 和 `run_mini_agent()` 中区分：

   - `timeout`
   - `command_not_found`
   - `nonzero_exit`
   - `trajectory_missing`
   - `invalid_timeout`

   写入 `MiniRunResult` 或新的 `ExecutorResult`。

4. 尝试接入 mini 内部 API

   阅读 `minisweagent/run/mini.py` 和相关模块，确认是否可以在不经过 CLI 的情况下调用核心 run 函数。

   如果可行，新增 `InProcessMiniExecutor`：

   - 直接传入 task。
   - 捕获结构化 trajectory。
   - 更细粒度处理异常。

   如果 mini 内部 API 不稳定，则先只实现接口和 subprocess 默认实现，不强行改执行路径。

5. 为实时 policy enforcement 预留接口

   新增 hook 概念：

   ```python
   class ExecutorHook(Protocol):
       def before_command(self, command: str) -> None: ...
       def after_command(self, command: str, result: object) -> None: ...
       def before_file_write(self, path: str) -> None: ...
   ```

   初期可以不接入 mini 内部，只作为后续 in-process executor 的设计落点。

6. 测试补充

   - subprocess executor 正常成功。
   - command not found 分类。
   - timeout 分类。
   - nonzero exit 分类。
   - trajectory missing 分类。
   - runner 对新的 executor result 仍兼容。

## 5. Shell Check 可信配置边界仍需更强提示

状态：已完成。

### 当前状态

`test_gate.py` 默认不使用 shell 执行 checks。只有满足以下条件才允许 shell：

- check 使用 `shell:` 前缀。
- policy 设置 `allow_shell_checks: true`。

这已经避免了大多数误用 shell 的情况。

### 问题

- 一旦项目配置允许 shell，命令内容仍完全由项目配置决定。
- 当前 doctor 只提示 shell checks 被禁用或允许，没有对 shell 命令本身做风险分类。
- shell check 可能包含重定向、删除、网络访问、环境变量展开等风险。

### 改进目标

- 在允许 shell 的情况下，对 shell check 做静态风险提示。
- 将高风险 shell 片段写入 doctor 和 review report。
- 不阻断可信项目的合理用法，但让风险更可见。

### 建议改动文件

- `codeflow/test_gate.py`
- `codeflow/doctor.py`
- `codeflow/harness/builtin_sensors.py`
- `codeflow/diff_reviewer.py`
- `tests/test_test_gate.py`
- `tests/test_init_doctor.py`
- `tests/test_harness_sensors.py`

### 大致改动内容

1. 增加 shell command 风险扫描

   在 `test_gate.py` 或新文件中增加：

   ```python
   def scan_shell_check_risk(command: str) -> list[str]:
       ...
   ```

   初始检测：

   - `rm -rf`
   - `curl | sh`
   - `wget | sh`
   - 写入 `.env`
   - `chmod 777`
   - `sudo`
   - `docker run --privileged`

2. doctor 中展示风险

   在 `doctor.py` 的 checks 检查中，如果发现 shell 风险，输出：

   ```json
   {
     "name": "required_check: shell: ...",
     "status": "warning",
     "message": "Shell check contains high-risk pattern: rm -rf"
   }
   ```

3. sensors 中增加 shell check policy sensor

   新增 sensor：

   - `shell_check_risk`

   如果 policy 允许 shell 且命令命中高风险片段，标记 medium 或 high warning。

4. report 中展示

   在 review report 的 sensor section 中展示 shell check 风险。

5. 测试补充

   - shell check 默认禁用仍通过现有测试。
   - 允许 shell 时 `rm -rf` 被 doctor 标记 warning。
   - `shell_check_risk` sensor 能识别高风险命令。
