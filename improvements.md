# CodeFlow Benchmark 完整改进计划

本文档只讨论 benchmark 体系，不包含 mini-swe-agent、Observability、CLI、CI 基础测试等其他改进点。

目标是把当前已经能跑通的 benchmark smoke，升级成一个可以长期复现、横向对比、支撑项目展示的评估体系。这里的重点不是单纯追求 pass rate，而是证明 CodeFlow 相比直接调用 agent 的价值：更稳定的任务执行、更可靠的 repair loop、更严格的安全/质量 sensor、更清楚的失败归因，以及可复现的真实 LLM 评估结果。

## 0. 2026-05-03 落地状态

本轮已经完成 benchmark 基础设施的主体改造：

- 已新增 `benchmark/schemas/task.schema.json` 和 `benchmark/schemas/result.schema.json`。
- 已为 workspace 准备流程写入 `.codeflow-benchmark/workspace_manifest.json`。
- 已为 `run_eval.py` 增加 `run_manifest.json`、`run_id`、`model/provider`、`error_category`、`patch_stats`、`artifact_paths`、attempt artifact 和最多 10 次 task retry 限制。
- 已扩展 `summarize_results.py`，新增 expected type、risk tag、retry analysis、failure taxonomy、runtime 和 artifact index。
- 已新增 `prepare_all_benchmark_data.py`、`archive_run.py`、`compare_runs.py`、`build_trend_report.py`、`inspect_artifact.py`。
- 已新增 benchmark smoke CI 和手动真实 LLM benchmark workflow。
- 已新增 `BENCHMARK_RUNBOOK.md`、`DATASET_STATUS.md`、`FAILURE_TAXONOMY.md`。
- 已生成 `quixbugs_full.yaml`，当前本地 QuixBugs Python 可转换任务为 31 个，并写入 `quixbugs_excluded_manifest.json` 说明 discovered/selected/generated。
- 已生成 `bugsinpy_stable_20.yaml` 和 `bugsinpy_stable_50.yaml` 作为 metadata 候选集；真实 checkout/eval 仍通过 manifest 单独记录，不把环境失败混入 agent 指标。
- 已生成 SWE-bench Lite / Verified 5 和 10 条 metadata 子集；真实 workspace checkout 仍是显式 opt-in。
- 已用 fake mini 跑通 benchmark infra smoke，并用真实 LLM 跑通 1 个 Harness-Bench 任务，验证真实模型路径下的 run manifest、result record 和 attempt artifact。

仍然属于长期扩展而不是本轮基础设施缺口的内容：

- Harness-Bench 从 12 扩到 30/60 个真实设计任务。
- BugsInPy stable 20/50 的逐个真实 checkout、依赖修复和真实 LLM eval。
- SWE-bench Lite / Verified 5/10/25 的真实 workspace checkout、setup 和真实 LLM eval。
- 多模型成本统计；当前 result schema 已预留 token/cost 字段，但底层 mini provider usage 还未统一回填。

## 1. 当前状态

### 1.1 已完成的能力

当前仓库已经具备一套基础 benchmark 闭环：

- `benchmark/scripts/run_eval.py` 可以读取 YAML / JSONL task file。
- 每个任务会复制 `source_repo` 到独立 workspace。
- workspace 会初始化 Git baseline。
- 支持执行 `setup_commands`。
- 支持写入 benchmark 专用 `.git/info/exclude`，避免 `__pycache__`、`.pytest_cache`、`uv.lock` 等生成物污染 diff。
- 支持 4 种 method：
  - `checks_only`
  - `raw_mini`
  - `codeflow_basic`
  - `codeflow_full`
- 支持真实 mini / 真实 LLM。
- 支持 `--fake-mini` 做确定性 harness smoke。
- 支持 `--max-task-attempts` 对真实 agent 任务做重试。
- 支持 `--proxy`，可以用 `http://127.0.0.1:10087` 处理下载数据集或依赖时的网络问题。
- 每个任务会输出：
  - JSON result record
  - Markdown review
  - 合并 Markdown report
  - retry manifest
- `benchmark/scripts/summarize_results.py` 可以合并多个结果 JSON 并生成报告。
- `benchmark/scripts/check_llm_env.py` 可以检查 `.env` 和最小真实 LLM 调用。

### 1.2 已接入的数据集

当前已经有这些任务文件：

- `benchmark/tasks/harness_bench.yaml`
- `benchmark/tasks/quixbugs.yaml`
- `benchmark/tasks/quixbugs_extended.yaml`
- `benchmark/tasks/bugsinpy_subset.yaml`
- `benchmark/tasks/bugsinpy_youtubedl_subset.yaml`
- `benchmark/tasks/bugsinpy_youtubedl_extra.yaml`
- `benchmark/tasks/bugsinpy_youtubedl_5.yaml`
- `benchmark/tasks/swebench_lite_subset.jsonl`
- `benchmark/tasks/swebench_lite_2_subset.jsonl`
- `benchmark/tasks/swebench_verified_subset.jsonl`
- `benchmark/tasks/swebench_verified_2_subset.jsonl`

当前重点可复核子集：

- QuixBugs extended：31 个任务。
- BugsInPy youtube-dl：5 个任务。
- SWE-bench Lite：2 个 Astropy 任务。
- SWE-bench Verified：2 个 Astropy 任务。

### 1.3 当前真实结果

当前合并报告位于：

- `benchmark/reports/current_real_results.md`
- `benchmark/reports/current_real_results.json`

报告包含 80 条记录：

- `checks_only` baseline：40 个任务，0 个通过。
- `codeflow_full`：40 个任务，40 个通过。
- unsafe diff：0。
- high risk review：0。
- no-change / test-deletion / forbidden-path / secret-like 等风险项：0。

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

### 1.4 当前结论边界

这些结果已经能证明 CodeFlow 的 benchmark runner、真实 LLM 调用、workspace 准备、checks 执行、repair loop 和 sensor 采集可以形成闭环。

但这些结果还不能直接证明：

- CodeFlow 在完整 SWE-bench Lite / Verified 上有稳定高通过率。
- CodeFlow 在 BugsInPy 多项目、多 Python 版本、多依赖组合下已经稳定。
- 当前 40 个任务的结果可以代表真实工业项目泛化能力。
- 当前 ignored 的 workspace / generated 数据能从 fresh clone 立即复现。
- 当前报告已经足够支撑长期趋势分析、成本分析和失败统计。

所以当前 benchmark 更接近“真实 LLM smoke + 小规模对比评估”，还不是完整 benchmark 产品。

## 2. Benchmark 的最终目标

### 2.1 核心问题

Benchmark 最终要回答这些问题：

- 直接跑 mini-swe-agent 和跑 CodeFlow Harness 相比，成功率差多少？
- `codeflow_basic` 和 `codeflow_full` 相比，sensor / policy / review 额外带来了多少质量收益？
- CodeFlow 的 repair loop 能把多少初次失败任务修好？
- CodeFlow 是否能拦截危险修改，例如删除测试、写 `.env`、修改 forbidden path、引入 secret-like 内容？
- CodeFlow 是否会出现 no-change false success，也就是没有做有效改动但被误判成功？
- CodeFlow 是否会为了通过测试牺牲任务语义？
- 不同数据集、任务类型、模型、重试次数下，结果是否稳定？
- 失败时能否快速区分是模型失败、网络失败、依赖失败、测试失败、sensor 阻断还是框架 bug？

### 2.2 对外展示目标

最终 benchmark 应该可以对外表达为：

```text
CodeFlow includes a reproducible benchmark harness across synthetic harness tasks,
QuixBugs, BugsInPy and SWE-bench mini subsets. The benchmark compares direct agent
execution against CodeFlow's policy/sensor/repair loop and reports pass rate,
repair success, unsafe diff rate, regression checks, retry behavior, runtime and
failure taxonomy.
```

更适合简历或项目 README 的表述应该是：

```text
构建真实 LLM 驱动的 Agent Benchmark 平台，接入 QuixBugs、BugsInPy、SWE-bench Lite/Verified
子集和自建 Harness-Bench，支持 baseline / raw agent / full harness 对比，自动采集 pass rate、
repair success、unsafe diff、test deletion、forbidden path、retry manifest 和失败归因报告。
```

### 2.3 不应该追求的目标

短期不应该把目标设为：

- 一次性跑完整 SWE-bench Verified。
- 把所有第三方数据集和 workspace 全部提交进 Git。
- 让真实 LLM benchmark 作为普通 PR CI 的强制门禁。
- 只展示总通过率，而不拆 method、dataset、任务类型和失败原因。
- 用一个模型的一次结果宣称系统已经全面领先。

## 3. 当前缺口总览

下面是 benchmark 部分还缺少或需要改进的内容。

### 3.1 Fresh clone 复现不足

当前 `benchmark/results/`、`benchmark/generated/`、`benchmark/workspaces/`、`benchmark/datasets/` 默认被 `.gitignore` 忽略。

这本身是合理的，因为这些目录包含大量生成物和第三方源码。但代价是：fresh clone 后只能看到 task metadata、脚本和最终合并报告，不能直接复核当时的完整 workspace 状态。

需要补齐：

- 一键准备所有当前 benchmark 数据的脚本。
- 每次准备 workspace 的 manifest。
- 每次运行 benchmark 的 run manifest。
- 清楚说明哪些 artifact 入库，哪些不入库，哪些上传到外部 artifact store。

### 3.2 数据集规模还偏小

当前真实汇总是 40 个任务：

- QuixBugs 31。
- BugsInPy 5。
- SWE-bench Lite 2。
- SWE-bench Verified 2。

这个规模能支撑工程闭环展示，但还不足以支撑泛化结论。特别是 SWE-bench 和 BugsInPy 还需要扩大。

需要补齐：

- Harness-Bench 从 12 扩到 30，再扩到 60。
- QuixBugs 从 31 尽量补齐到完整 40。
- BugsInPy 从 youtube-dl 5 扩到多项目 20，再到 50。
- SWE-bench Lite / Verified 从 Astropy 2+2 扩到稳定可运行的 5、10、25 任务子集。

### 3.3 BugsInPy 覆盖不足

当前 BugsInPy 主要是 youtube-dl 小子集。BugsInPy 的真实价值在于多项目、多依赖、多 Python 版本、多测试命令。

需要补齐：

- 真实 checkout 多项目。
- 记录每个项目的 Python 版本、依赖安装方式、失败原因。
- 标记不可运行任务，而不是把环境失败混入 agent 失败。
- 建立稳定子集，例如 `bugsinpy_stable_20.yaml`。

### 3.4 SWE-bench 覆盖不足

当前 SWE-bench Lite / Verified 主要是 Astropy 小子集。它已经能验证脚本链路，但不能代表 SWE-bench 的真实复杂度。

需要补齐：

- 更多 repo 类型，例如 Astropy、Django、Pylint、Requests、Matplotlib、Scikit-learn 等。
- 更严格使用 SWE-bench 的 `FAIL_TO_PASS` 和 `PASS_TO_PASS`。
- 明确区分：
  - metadata only task
  - workspace prepared task
  - setup passed task
  - checks runnable task
  - real LLM evaluated task
- 记录 base commit、test patch、setup recipe、依赖缓存和失败日志。

### 3.5 Artifact 归档不足

当前报告记录了结构化字段，但长期复盘还需要完整 artifact。

需要补齐：

- 每次 run 的 manifest。
- 每个 attempt 的 stdout / stderr 摘要。
- mini trajectory。
- mini events。
- diff patch。
- checks log。
- sensor report。
- semantic review。
- retry manifest。
- workspace manifest。
- artifact checksum。
- redaction 状态。

这些 artifact 不一定全部提交到 Git，但必须有清楚的归档策略。

### 3.6 统计维度不足

当前报告已经有 method summary、dataset summary 和任务明细，但还缺少更强的分析维度。

需要补齐：

- 按 expected_type 统计。
- 按 risk_tags 统计。
- 按模型统计。
- 按 attempt 数统计。
- 按首次成功 / 重试成功统计。
- 按 repair rounds 统计。
- 按错误类型统计。
- 按运行时耗时统计。
- 按 token / 成本统计。
- 按 patch size / changed files 统计。
- 按 flaky / environment failure 统计。

### 3.7 失败归因不足

当前结果有 `error_type` 和 `error`，但还不够系统。

需要建立统一 failure taxonomy：

- `agent_no_change`
- `agent_wrong_fix`
- `checks_failed`
- `repair_failed`
- `sensor_blocked`
- `semantic_review_blocked`
- `policy_blocked`
- `setup_failed`
- `dependency_failed`
- `checkout_failed`
- `network_failed`
- `llm_api_failed`
- `llm_timeout`
- `invalid_model_output`
- `workspace_dirty`
- `benchmark_runner_error`
- `unknown`

报告中应显示这些类型的分布，并明确哪些算 agent failure，哪些算 environment failure。

### 3.8 成本与稳定性记录不足

真实 LLM benchmark 必须记录成本和稳定性，否则长期不可控。

需要补齐：

- model name。
- provider / base_url。
- temperature 等关键模型参数。
- prompt token。
- completion token。
- total token。
- estimated cost。
- wall time。
- API retry 次数。
- API error code。
- rate limit 情况。

如果底层 mini / model client 暂时拿不到 token usage，也要在 result schema 中预留字段。

### 3.9 对比矩阵不完整

当前合并报告主要比较了 `checks_only` 和 `codeflow_full`。

完整 benchmark 应该包含：

- `checks_only`
- `raw_mini`
- `codeflow_basic`
- `codeflow_full`

其中：

- `checks_only` 用于证明原始 bug 状态确实失败。
- `raw_mini` 用于证明直接调用 agent 的表现。
- `codeflow_basic` 用于证明 prompt + checks + repair loop 的收益。
- `codeflow_full` 用于证明 policy + sensors + review 的收益。

只有四个 method 都跑，才能说清楚 CodeFlow 的增量价值来自哪里。

### 3.10 CI 和周期运行不足

当前 benchmark 不适合直接放进普通 CI，因为真实 LLM 和第三方数据集受网络、成本、API key、依赖环境影响。

需要补齐两层自动化：

- 普通 CI：只跑 fake mini benchmark smoke，验证脚本、schema、报告生成。
- 手动 / 定时 CI：跑真实 LLM 小子集，上传 artifact，不阻塞普通 PR。

## 4. 统一数据模型改进

### 4.1 Task schema

当前 task 已经有基本字段：

- `id`
- `dataset`
- `source_repo`
- `task`
- `checks`
- `expected_type`
- `risk_tags`
- `setup_commands`

建议标准化为：

```yaml
- id: quixbugs_bitcount
  dataset: quixbugs
  source_repo: benchmark/generated/quixbugs/bitcount
  task: "修复 bitcount 实现，使其通过现有 pytest 测试。"
  checks:
    - "pytest -q"
  expected_type: bugfix
  risk_tags:
    - normal
  difficulty: small
  language: python
  framework: pytest
  source:
    kind: generated
    upstream: https://github.com/jkoppel/QuixBugs
    upstream_ref: null
    base_commit: null
  oracle:
    type: tests
    fail_to_pass:
      - "pytest -q"
    pass_to_pass: []
  environment:
    python: "3.11"
    install:
      - "uv pip install -e ."
  benchmark:
    stable: true
    runnable: true
    expected_baseline_status: checks_failed
```

必须补齐的字段：

- `difficulty`：`small`、`medium`、`large`。
- `language`：当前主要是 `python`。
- `framework`：`pytest`、`unittest`、`custom`。
- `source.kind`：`toy`、`generated`、`third_party_checkout`、`swebench`。
- `source.upstream`：第三方项目地址或数据集地址。
- `source.base_commit`：真实 repo 的 baseline commit。
- `oracle.fail_to_pass`：修复前失败、修复后应通过的测试。
- `oracle.pass_to_pass`：修复前后都应通过的回归测试。
- `benchmark.stable`：是否进入稳定评估集。
- `benchmark.runnable`：本机是否已验证可运行。
- `benchmark.expected_baseline_status`：通常为 `checks_failed`。

需要新增：

- `benchmark/schemas/task.schema.json`
- `tests/benchmark/test_task_schema.py`

### 4.2 Workspace manifest

每次生成 workspace 时写入：

```text
benchmark/workspaces/{task_id}/.codeflow-benchmark/workspace_manifest.json
```

字段建议：

```json
{
  "task_id": "swebench_lite_astropy__astropy_12907",
  "dataset": "swebench_lite",
  "source_repo": "benchmark/generated/swebench_lite/astropy__astropy_12907",
  "workspace": "benchmark/workspaces/swebench_lite_astropy__astropy_12907",
  "created_at": "2026-05-03T00:00:00Z",
  "source_kind": "swebench",
  "upstream_repo": "https://github.com/astropy/astropy",
  "base_commit": "...",
  "test_patch_applied": true,
  "setup_commands": ["..."],
  "setup_status": "passed",
  "setup_runtime_seconds": 12.3,
  "python_version": "3.11",
  "git_head": "...",
  "baseline_commit": "...",
  "files_hash": "sha256:..."
}
```

需要改动：

- `benchmark/scripts/_harness_bench_common.py`
- `benchmark/scripts/prepare_harness_bench.py`
- `benchmark/scripts/prepare_quixbugs.py`
- `benchmark/scripts/prepare_bugsinpy.py`
- `benchmark/scripts/prepare_swebench.py`

### 4.3 Run manifest

每次执行 `run_eval.py` 都写入：

```text
benchmark/results/{run_id}/run_manifest.json
```

字段建议：

```json
{
  "run_id": "20260503_120000_deepseekv4_codeflow_full",
  "created_at": "2026-05-03T12:00:00Z",
  "git_commit": "...",
  "git_dirty": true,
  "tasks_file": "benchmark/tasks/quixbugs_extended.yaml",
  "task_count": 31,
  "method": "codeflow_full",
  "model": "deepseekv4",
  "max_repair_rounds": 3,
  "max_task_attempts": 10,
  "proxy_enabled": true,
  "python": "3.13.0",
  "platform": "...",
  "env_redacted": {
    "OPENAI_BASE_URL": "https://...",
    "OPENAI_API_KEY": "***"
  }
}
```

需要改动：

- `benchmark/scripts/run_eval.py`
- `benchmark/scripts/summarize_results.py`

### 4.4 Result record

当前 result record 已经有不少字段。建议继续扩展为：

```json
{
  "id": "quixbugs_bitcount",
  "dataset": "quixbugs",
  "method": "codeflow_full",
  "run_id": "...",
  "attempts": 1,
  "status": "checks_passed",
  "checks_passed": true,
  "repair_rounds": 0,
  "risk_level": "low",
  "review_risk_level": "low",
  "unsafe_diff": false,
  "test_deleted": false,
  "forbidden_path_modified": false,
  "forbidden_path_write": false,
  "secret_like_content": false,
  "missing_test_warning": false,
  "no_change": false,
  "runtime_seconds": 31.2,
  "error_type": null,
  "error_category": null,
  "error": null,
  "model": "deepseekv4",
  "provider": "openai-compatible",
  "prompt_tokens": null,
  "completion_tokens": null,
  "total_tokens": null,
  "estimated_cost_usd": null,
  "changed_files": ["..."],
  "patch_stats": {
    "files": 1,
    "additions": 3,
    "deletions": 1
  },
  "artifact_paths": {
    "review": "...",
    "diff": "...",
    "checks_log": "...",
    "mini_trajectory": "...",
    "mini_events": "..."
  }
}
```

需要新增：

- `benchmark/schemas/result.schema.json`
- `tests/benchmark/test_result_schema.py`

## 5. 数据集建设路线

### 5.1 自建 Harness-Bench

当前状态：

- v0 有 12 个任务。
- 覆盖 feature、bugfix、quality、refactor 和风险场景。
- 可以验证 no-change、test deletion、forbidden path 等 harness sensor。

目标：

- 第一阶段扩到 30 个任务。
- 第二阶段扩到 60 个任务。
- 让它成为最能体现 CodeFlow Harness Engineering 的主评估集。

建议 30 任务分布：

| 类型 | 数量 | 目的 |
| --- | ---: | --- |
| feature | 8 | 验证正常功能实现 |
| bugfix | 8 | 验证失败测试驱动修复 |
| test_only | 4 | 验证测试补充能力 |
| refactor | 4 | 验证保持行为不变 |
| quality | 3 | 验证代码质量和边界处理 |
| risk_case | 3 | 验证 sensor 阻断 |

建议 60 任务扩展分布：

| 类型 | 数量 | 目的 |
| --- | ---: | --- |
| feature | 15 | 多文件功能修改 |
| bugfix | 15 | 多种失败类型 |
| test_only | 8 | 测试设计能力 |
| refactor | 8 | 非功能性修改 |
| quality | 6 | 类型、异常、边界条件 |
| risk_case | 8 | 安全策略和反作弊 |

需要新增的任务类型：

- 修改业务代码但不加测试，应触发 `missing_test_warning`。
- 删除测试后通过，应触发 `test_deletion`。
- 尝试写 `.env`，应触发 `forbidden_path_write`。
- 修改 lockfile 或 dependency file，应触发 dependency sensor。
- 大 diff 重写，应触发 `max_diff`。
- 无任何有效修改，应触发 `no_change`。
- 只修改 README 但任务要求代码，应失败或触发语义风险。
- 引入 secret-like token，应触发 `secret_like_content`。
- 修改 `.github/workflows`，应根据 policy 判定高风险。

需要改动：

- `benchmark/tasks/harness_bench.yaml`
- `benchmark/scripts/prepare_harness_bench.py`
- `examples/todo_api/`
- `examples/file_utils/`
- `examples/student_manager/`
- 新增 `examples/config_loader/`
- 新增 `examples/inventory_api/`
- 新增 `examples/text_analyzer/`

验收标准：

- `checks_only` 对正常 bugfix/feature 任务应失败或保持 baseline 状态。
- `codeflow_full` 对正常任务应通过。
- 风险任务不要求通过，而要求被 sensor 正确标记。
- 所有任务都必须有明确 expected outcome。
- fake mini 可以覆盖至少 1 个正例和 1 个风险例。

### 5.2 QuixBugs

当前状态：

- 已有 smoke 子集。
- 已有 31 个可转换任务的 `quixbugs_extended.yaml`。
- 当前真实结果中 31 个 `checks_only` 全失败，31 个 `codeflow_full` 全通过。

目标：

- 尽量补齐完整 40 个 Python 任务。
- 为每个任务记录算法类别和缺陷类型。
- 形成稳定的快速 bugfix 基准。

需要做：

- 检查剩余 9 个任务为什么没有进入 extended。
- 区分是无法转换、测试缺失、Python 版本问题，还是脚本过滤问题。
- 给每个任务增加 metadata：
  - algorithm category
  - single_file / multi_file
  - expected patch size
  - known fixed implementation reference
- 增加 `quixbugs_full.yaml`。
- 增加生成脚本的校验输出，例如 `benchmark/generated/quixbugs_manifest.json`。

需要改动：

- `benchmark/scripts/prepare_quixbugs.py`
- `benchmark/tasks/quixbugs_extended.yaml`
- 新增 `benchmark/tasks/quixbugs_full.yaml`
- 新增 `tests/benchmark/test_prepare_quixbugs_full.py`

运行矩阵：

```bash
uv run python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/quixbugs_full.yaml \
  --method checks_only \
  --out-dir benchmark/results/quixbugs_full_checks_only

uv run python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/quixbugs_full.yaml \
  --method raw_mini \
  --model deepseekv4 \
  --max-task-attempts 10 \
  --out-dir benchmark/results/quixbugs_full_raw_mini

uv run python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/quixbugs_full.yaml \
  --method codeflow_basic \
  --model deepseekv4 \
  --max-repair-rounds 3 \
  --max-task-attempts 10 \
  --out-dir benchmark/results/quixbugs_full_basic

uv run python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/quixbugs_full.yaml \
  --method codeflow_full \
  --model deepseekv4 \
  --max-repair-rounds 3 \
  --max-task-attempts 10 \
  --out-dir benchmark/results/quixbugs_full_full
```

验收标准：

- 完整可运行任务数达到 40；如果达不到，必须有 manifest 说明排除原因。
- `checks_only` 失败率应接近 100%。
- `raw_mini`、`codeflow_basic`、`codeflow_full` 都有结果。
- 报告能展示 CodeFlow 相比 raw mini 的差异。

### 5.3 BugsInPy

当前状态：

- 已 clone / 支持 BugsInPy metadata。
- `prepare_bugsinpy.py` 可以只生成 task YAML，也可以调用 `bugsinpy-checkout` 准备 workspace。
- 当前真实 runnable 子集主要是 youtube-dl 5 个任务。

目标：

- 从 youtube-dl 单项目扩展到多项目稳定子集。
- 第一阶段：`bugsinpy_stable_20.yaml`。
- 第二阶段：`bugsinpy_stable_50.yaml`。
- 明确标记 checkout、setup、checks、real eval 每一步状态。

建议优先项目：

- youtube-dl：当前已有基础，继续保留。
- PySnooper：小项目，适合快速扩展。
- fastapi / sanic / tornado 类项目：如果 BugsInPy 中可用，优先选择依赖可控的 bug。
- pandas / matplotlib / scipy 类大型项目：后置处理，因为依赖和运行时间更复杂。

需要做：

- 用 `--list` 生成候选清单。
- 每个候选先做 metadata manifest。
- 对候选逐个 checkout。
- 记录 checkout 成败。
- 运行 baseline checks。
- 只把 baseline 确认失败、依赖可安装、测试可运行的任务放进 stable subset。
- 将环境失败单独归档，不混入 agent pass rate。

准备命令：

```bash
uv run python benchmark/scripts/prepare_bugsinpy.py \
  --source benchmark/datasets/bugsinpy \
  --list \
  --limit 100
```

网络不通时：

```bash
uv run python benchmark/scripts/prepare_bugsinpy.py \
  --source benchmark/datasets/bugsinpy \
  --out benchmark/generated/bugsinpy_stable_20 \
  --tasks-out benchmark/tasks/bugsinpy_stable_20.yaml \
  --limit 20 \
  --prepare-workspaces \
  --proxy http://127.0.0.1:10087 \
  --clean
```

如果 Python 版本过旧：

```bash
uv run python benchmark/scripts/prepare_bugsinpy.py \
  --source benchmark/datasets/bugsinpy \
  --out benchmark/generated/bugsinpy_youtubedl \
  --tasks-out benchmark/tasks/bugsinpy_youtubedl_compat.yaml \
  --project youtube-dl \
  --prepare-workspaces \
  --uv-python-checks \
  --python-version-override 3.8 \
  --proxy http://127.0.0.1:10087 \
  --clean
```

运行矩阵：

```bash
uv run python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/bugsinpy_stable_20.yaml \
  --method checks_only \
  --proxy http://127.0.0.1:10087 \
  --out-dir benchmark/results/bugsinpy_stable_20_checks_only

uv run python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/bugsinpy_stable_20.yaml \
  --method codeflow_full \
  --model deepseekv4 \
  --max-repair-rounds 3 \
  --max-task-attempts 10 \
  --proxy http://127.0.0.1:10087 \
  --out-dir benchmark/results/bugsinpy_stable_20_full
```

需要改动：

- `benchmark/scripts/prepare_bugsinpy.py`
- `benchmark/scripts/_harness_bench_common.py`
- 新增 `benchmark/tasks/bugsinpy_stable_20.yaml`
- 新增 `benchmark/tasks/bugsinpy_stable_50.yaml`
- 新增 `benchmark/reports/bugsinpy_candidate_manifest.md`
- 新增 `tests/benchmark/test_prepare_bugsinpy_manifest.py`

验收标准：

- `bugsinpy_stable_20.yaml` 至少包含 20 个真实 checkout 且 baseline checks 可运行的任务。
- 每个排除任务都有原因：checkout 失败、依赖失败、测试不可运行、Python 版本不可用、网络失败、数据缺失。
- 报告按项目拆分 pass rate，而不是只给总数。
- `checks_only` 与 `codeflow_full` 都有结果。

### 5.4 SWE-bench Lite / Verified

当前状态：

- `prepare_swebench.py` 可以下载 SWE-bench Lite / Verified metadata。
- 可以 clone GitHub repo、checkout base commit、应用 test patch、执行 setup recipe。
- 当前已有 1-task 和 2-task mini subset JSONL。
- 当前真实结果主要是 Astropy 任务。

目标：

- 形成可稳定复现的小型 SWE-bench 子集。
- 不追求立即跑完整 SWE-bench。
- 第一阶段：Lite 5 + Verified 5。
- 第二阶段：Lite 10 + Verified 10。
- 第三阶段：Lite 25 + Verified 25。

任务状态分层：

| 状态 | 含义 |
| --- | --- |
| metadata_selected | 只选中了 SWE-bench instance |
| repo_cloned | 上游 repo 已 clone |
| base_checked_out | base commit 已 checkout |
| test_patch_applied | test patch 已应用 |
| setup_passed | setup recipe 已成功 |
| baseline_checked | baseline checks 已验证 |
| real_eval_done | 已用真实 LLM 跑 agent |
| stable | 可进入长期稳定 benchmark |

准备命令：

```bash
uv run python benchmark/scripts/prepare_swebench.py \
  --dataset princeton-nlp/SWE-bench_Lite \
  --split test \
  --limit 5 \
  --out benchmark/generated/swebench_lite_5 \
  --tasks-out benchmark/tasks/swebench_lite_5_subset.jsonl \
  --proxy http://127.0.0.1:10087 \
  --clean
```

Verified：

```bash
uv run python benchmark/scripts/prepare_swebench.py \
  --verified \
  --split test \
  --limit 5 \
  --out benchmark/generated/swebench_verified_5 \
  --tasks-out benchmark/tasks/swebench_verified_5_subset.jsonl \
  --proxy http://127.0.0.1:10087 \
  --clean
```

运行矩阵：

```bash
uv run python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/swebench_lite_5_subset.jsonl \
  --method checks_only \
  --proxy http://127.0.0.1:10087 \
  --out-dir benchmark/results/swebench_lite_5_checks_only

uv run python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/swebench_lite_5_subset.jsonl \
  --method codeflow_full \
  --model deepseekv4 \
  --max-repair-rounds 3 \
  --max-task-attempts 10 \
  --proxy http://127.0.0.1:10087 \
  --out-dir benchmark/results/swebench_lite_5_full
```

需要做：

- 明确 `FAIL_TO_PASS` 和 `PASS_TO_PASS` 映射到 `checks`。
- 将 setup 失败和 agent 失败分开统计。
- 对大 repo 增加 clone cache，避免每次重复下载。
- 增加 `--repo-cache-dir` 参数。
- 增加 `--instance-id` 参数，便于精确重跑某个 SWE-bench case。
- 保存每个 instance 的 `problem_statement`、`base_commit`、`test_patch`、`created_at`。
- 对每个 workspace 写入 `workspace_manifest.json`。

需要改动：

- `benchmark/scripts/prepare_swebench.py`
- `benchmark/scripts/run_eval.py`
- `benchmark/scripts/_harness_bench_common.py`
- 新增 `benchmark/tasks/swebench_lite_5_subset.jsonl`
- 新增 `benchmark/tasks/swebench_verified_5_subset.jsonl`
- 新增 `benchmark/tasks/swebench_lite_10_subset.jsonl`
- 新增 `benchmark/tasks/swebench_verified_10_subset.jsonl`
- 新增 `tests/benchmark/test_prepare_swebench_manifest.py`

验收标准：

- Lite 5 和 Verified 5 都能从 fresh clone 加网络准备出来。
- 每个任务的 base commit、test patch、checks 都可追踪。
- baseline checks 预期失败。
- `codeflow_full` 结果不把 setup failure 算成 agent failure。
- 报告单独展示 SWE-bench 子集规模和稳定性边界。

## 6. 运行矩阵设计

### 6.1 Method 矩阵

每个稳定任务集都应该跑：

| Method | 目的 |
| --- | --- |
| `checks_only` | baseline，对照原始 bug 是否失败 |
| `raw_mini` | 直接 agent 能力 |
| `codeflow_basic` | prompt + checks + repair loop |
| `codeflow_full` | 完整 policy + sensors + repair + review |

最小可接受矩阵：

- 所有稳定任务集必须跑 `checks_only`。
- 所有稳定任务集必须跑 `codeflow_full`。
- 至少主报告中的核心子集必须跑 `raw_mini` 和 `codeflow_basic`。

### 6.2 Model 矩阵

短期固定一个主模型，避免变量过多：

- 主模型：`deepseekv4`。
- 可选对照：另一个 OpenAI-compatible 模型。

长期再扩展：

- small / cheap model。
- strong model。
- local model。

报告必须记录 model name，不能把不同模型结果混在一个 pass rate 中。

### 6.3 Retry 策略

真实 LLM benchmark 必须允许重试，但不能无限重试后只报告最好结果。

建议策略：

- 默认 `--max-task-attempts 1`。
- 正式真实 LLM benchmark 使用 `--max-task-attempts 3`。
- 针对用户要求或强复核场景，最多 `--max-task-attempts 10`。
- 报告同时记录：
  - first attempt success
  - final success after retry
  - attempts used
  - retry reason

重要原则：

- 不能只报告最终成功率。
- 必须同时报告首轮成功率。
- 重试成功应归类为 repair/retry 能力的一部分。
- API/network/setup failure 的重试必须和 agent semantic failure 区分。

### 6.4 推荐标准命令

先检查真实 LLM：

```bash
uv run python benchmark/scripts/check_llm_env.py \
  --proxy http://127.0.0.1:10087
```

跑 QuixBugs 四方法：

```bash
uv run python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/quixbugs_extended.yaml \
  --method checks_only \
  --out-dir benchmark/results/quixbugs_extended_checks_only_current

uv run python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/quixbugs_extended.yaml \
  --method raw_mini \
  --model deepseekv4 \
  --max-task-attempts 10 \
  --out-dir benchmark/results/quixbugs_extended_raw_mini_current

uv run python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/quixbugs_extended.yaml \
  --method codeflow_basic \
  --model deepseekv4 \
  --max-repair-rounds 3 \
  --max-task-attempts 10 \
  --out-dir benchmark/results/quixbugs_extended_basic_current

uv run python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/quixbugs_extended.yaml \
  --method codeflow_full \
  --model deepseekv4 \
  --max-repair-rounds 3 \
  --max-task-attempts 10 \
  --out-dir benchmark/results/quixbugs_extended_full_current
```

合并报告：

```bash
uv run python benchmark/scripts/summarize_results.py \
  benchmark/results/quixbugs_extended_checks_only_current/quixbugs_extended_results.json \
  benchmark/results/quixbugs_extended_raw_mini_current/quixbugs_extended_results.json \
  benchmark/results/quixbugs_extended_basic_current/quixbugs_extended_results.json \
  benchmark/results/quixbugs_extended_full_current/quixbugs_extended_results.json \
  --out benchmark/reports/quixbugs_extended_matrix.md \
  --raw-out benchmark/reports/quixbugs_extended_matrix.json
```

## 7. 指标体系

### 7.1 必须统计的核心指标

- `checks_pass_rate`：checks 通过率。
- `first_attempt_pass_rate`：第一次尝试通过率。
- `final_pass_rate`：重试后的最终通过率。
- `repair_success_rate`：初次失败后 repair 成功比例。
- `avg_repair_rounds`：平均 repair 轮数。
- `unsafe_diff_rate`：unsafe diff 比例。
- `sensor_block_rate`：sensor 阻断比例。
- `test_deletion_detection_rate`：删除测试检测比例。
- `forbidden_path_detection_rate`：forbidden path 检测比例。
- `forbidden_path_write_detection_rate`：forbidden path write 检测比例。
- `secret_like_detection_rate`：secret-like 内容检测比例。
- `no_change_detection_rate`：无有效修改检测比例。
- `missing_test_warning_rate`：缺少测试修改提醒比例。
- `runtime_avg_seconds`：平均运行时间。
- `runtime_p50_seconds`：中位数运行时间。
- `runtime_p95_seconds`：P95 运行时间。
- `api_failure_rate`：LLM API 失败比例。
- `setup_failure_rate`：环境准备失败比例。

### 7.2 建议统计的质量指标

- `patch_files_avg`：平均修改文件数。
- `patch_additions_avg`：平均新增行数。
- `patch_deletions_avg`：平均删除行数。
- `test_files_changed_rate`：涉及测试文件修改比例。
- `source_files_changed_rate`：涉及源码文件修改比例。
- `docs_only_false_success_rate`：只改文档但任务要求代码的误成功比例。
- `pass_to_pass_regression_rate`：回归测试失败比例，主要用于 SWE-bench。
- `semantic_risk_rate`：语义审查中 medium/high 风险比例。

### 7.3 成本指标

如果 provider 返回 token usage，应统计：

- `prompt_tokens_avg`
- `completion_tokens_avg`
- `total_tokens_avg`
- `total_tokens_sum`
- `estimated_cost_usd`
- `cost_per_success`
- `cost_per_dataset`
- `cost_per_method`

如果暂时拿不到 usage，应在报告中显示 `unknown`，不要省略字段。

### 7.4 报告展示方式

最终报告至少包含：

- 总览。
- Method summary。
- Dataset / method summary。
- Expected type summary。
- Risk tag summary。
- Retry summary。
- Failure taxonomy。
- Cost summary。
- Runtime summary。
- Task detail table。
- Artifact index。
- Known caveats。

## 8. Artifact 策略

### 8.1 Git 中应该保留

建议提交到 Git：

- benchmark 脚本。
- task 文件。
- schema 文件。
- 当前稳定主报告：
  - `benchmark/reports/current_real_results.md`
  - `benchmark/reports/current_real_results.json`
- 小型、经过脱敏的 manifest。
- 文档和 runbook。

### 8.2 Git 中不应该保留

不建议提交：

- `benchmark/datasets/`
- `benchmark/generated/`
- `benchmark/workspaces/`
- `benchmark/results/`
- 第三方源码完整拷贝。
- 原始 LLM 日志。
- 可能含 API key 或路径隐私的 trajectory。
- 大型 dependency cache。

这些目录当前被 `.gitignore` 忽略是合理的。

### 8.3 需要新增的 artifact 归档方案

新增脚本：

- `benchmark/scripts/archive_run.py`
- `benchmark/scripts/inspect_artifact.py`

归档目录建议：

```text
benchmark/artifacts/
├── README.md
├── manifests/
│   └── 20260503_deepseekv4_codeflow_full.json
└── samples/
    └── redacted_failure_examples/
```

大型 artifact 不入 Git，可以压缩到：

```text
benchmark/artifact_archives/{run_id}.tar.zst
```

并默认被 ignore。归档 manifest 入 Git，压缩包可上传到 GitHub Actions artifact 或外部存储。

### 8.4 Redaction 要求

归档前必须脱敏：

- API key。
- Authorization header。
- Cookie。
- token-like 字符串。
- `.env` 内容。
- 本机用户名路径如果需要公开，也应替换为 `<workspace>`。

需要复用或扩展：

- `codeflow/redaction.py`
- `codeflow/test_gate.py` 中已有日志脱敏能力。
- `codeflow/mini_runner.py` 中 mini log 脱敏能力。

## 9. 自动化与 CI

### 9.1 普通 PR CI

普通 PR CI 不应该跑真实 LLM benchmark。

应该跑：

- benchmark task schema 校验。
- fake mini harness smoke。
- `summarize_results.py` 单元测试。
- `prepare_quixbugs.py` 小样本转换测试。
- `prepare_bugsinpy.py` metadata 解析测试。
- `prepare_swebench.py` JSONL metadata 解析测试。

建议新增 workflow：

- `.github/workflows/benchmark-smoke.yml`

示例步骤：

```bash
uv run python benchmark/scripts/run_eval.py \
  --fake-mini \
  --tasks benchmark/tasks/harness_bench.yaml \
  --limit 3 \
  --method codeflow_full \
  --out-dir benchmark/results/ci_fake_smoke

uv run python benchmark/scripts/summarize_results.py \
  benchmark/results/ci_fake_smoke/harness_bench_results.json \
  --out benchmark/results/ci_fake_smoke/report.md
```

### 9.2 手动真实 LLM workflow

真实 LLM benchmark 用 `workflow_dispatch`：

- 手动选择 tasks file。
- 手动选择 method。
- 手动选择 model。
- 手动选择 max attempts，最大 10。
- 上传 artifact。
- 不阻塞普通 PR。

建议新增：

- `.github/workflows/benchmark-real-llm.yml`

### 9.3 定时 benchmark

长期可以每周跑一次小型稳定集：

- QuixBugs full。
- BugsInPy stable 20。
- SWE-bench Lite 5。
- SWE-bench Verified 5。

定时 workflow 只在主分支运行，结果上传 artifact，同时更新趋势报告需要人工确认后再提交。

### 9.4 CI 验收标准

- fake mini benchmark smoke 必须稳定通过。
- schema 测试必须稳定通过。
- summarize 测试必须稳定通过。
- 真实 LLM workflow 允许失败，但必须生成失败归因和 artifact。

## 10. 需要新增或修改的文件

### 10.1 新增文件

建议新增：

- `benchmark/schemas/task.schema.json`
- `benchmark/schemas/result.schema.json`
- `benchmark/scripts/prepare_all_benchmark_data.py`
- `benchmark/scripts/archive_run.py`
- `benchmark/scripts/compare_runs.py`
- `benchmark/scripts/build_trend_report.py`
- `benchmark/scripts/inspect_artifact.py`
- `benchmark/tasks/quixbugs_full.yaml`
- `benchmark/tasks/bugsinpy_stable_20.yaml`
- `benchmark/tasks/bugsinpy_stable_50.yaml`
- `benchmark/tasks/swebench_lite_5_subset.jsonl`
- `benchmark/tasks/swebench_verified_5_subset.jsonl`
- `benchmark/tasks/swebench_lite_10_subset.jsonl`
- `benchmark/tasks/swebench_verified_10_subset.jsonl`
- `benchmark/reports/BENCHMARK_RUNBOOK.md`
- `benchmark/reports/DATASET_STATUS.md`
- `benchmark/reports/FAILURE_TAXONOMY.md`
- `tests/benchmark/test_task_schema.py`
- `tests/benchmark/test_result_schema.py`
- `tests/benchmark/test_prepare_all_benchmark_data.py`
- `.github/workflows/benchmark-smoke.yml`
- `.github/workflows/benchmark-real-llm.yml`

### 10.2 修改现有文件

需要修改：

- `benchmark/scripts/_harness_bench_common.py`
  - 写 workspace manifest。
  - 更完整地记录 setup 状态。
  - 支持 repo cache / generated source metadata。
- `benchmark/scripts/run_eval.py`
  - 写 run manifest。
  - 增加 run id。
  - 增加 artifact paths。
  - 增加 failure category。
  - 增加 patch stats。
  - 增加 model/provider/cost 字段。
- `benchmark/scripts/summarize_results.py`
  - 增加 method matrix。
  - 增加 first/final attempt 对比。
  - 增加 failure taxonomy。
  - 增加 runtime/cost 统计。
  - 增加 artifact index。
- `benchmark/scripts/prepare_quixbugs.py`
  - 尽量补齐完整 40。
  - 输出 excluded reason manifest。
- `benchmark/scripts/prepare_bugsinpy.py`
  - 输出 candidate manifest。
  - 区分 checkout/setup/checks 状态。
  - 增加更清晰的 Python version strategy。
- `benchmark/scripts/prepare_swebench.py`
  - 增加 repo cache。
  - 增加 instance-id 精确选择。
  - 增加 workspace manifest。
  - 更严格记录 fail_to_pass/pass_to_pass。
- `benchmark/README.md`
  - 更新当前 benchmark 定位。
  - 增加 runbook 链接。
  - 增加 artifact 策略。
- `docs/PROJECT_OVERVIEW.md`
  - 更新 benchmark 边界和对外表述。
- `.gitignore`
  - 保持 datasets/generated/workspaces/results 默认忽略。
  - 视情况增加 artifact archive 忽略规则。

## 11. 分阶段执行计划

### Phase 1：文档、schema、manifest

目的：先把 benchmark 从“能跑”变成“可解释、可复现、可审计”。

任务：

- 新增 task schema。
- 新增 result schema。
- 为 `run_eval.py` 增加 run manifest。
- 为 workspace 生成增加 workspace manifest。
- 为 result record 增加 `run_id`、`model`、`error_category`、`artifact_paths`。
- 更新 summarize report 的 failure taxonomy。
- 新增 `BENCHMARK_RUNBOOK.md`。

验收：

- `uv run python benchmark/scripts/run_eval.py --fake-mini --limit 3` 可以生成 run manifest。
- schema 测试通过。
- Markdown report 中出现 run id、method、model、failure taxonomy。

### Phase 2：四方法对比矩阵

目的：证明 CodeFlow 的增量价值，而不是只证明 agent 能修 bug。

任务：

- 对 QuixBugs extended 跑：
  - `checks_only`
  - `raw_mini`
  - `codeflow_basic`
  - `codeflow_full`
- 对 Harness-Bench 跑四方法。
- 合并生成 matrix report。
- 报告展示 raw mini 与 full harness 的差距。

验收：

- 生成 `benchmark/reports/quixbugs_extended_matrix.md`。
- 生成 `benchmark/reports/harness_bench_matrix.md`。
- 报告中明确展示各 method 的 pass rate、unsafe diff、repair rounds。

### Phase 3：QuixBugs full

目的：把 QuixBugs 从 31 扩到尽可能完整的 40。

任务：

- 分析剩余 9 个未转换任务。
- 能转换的补进 `quixbugs_full.yaml`。
- 不能转换的写入 excluded manifest。
- 跑四方法真实 LLM 对比。

验收：

- `quixbugs_full.yaml` 包含 40 个任务，或 manifest 明确说明为什么少于 40。
- current report 更新 QuixBugs full 结果。

### Phase 4：BugsInPy stable 20

目的：让 BugsInPy 从 youtube-dl 单项目扩展到多项目真实子集。

任务：

- 列出 BugsInPy 候选。
- 批量 checkout。
- 过滤稳定可运行任务。
- 生成 `bugsinpy_stable_20.yaml`。
- 跑 `checks_only` 和 `codeflow_full`。
- 对核心子集补跑 `raw_mini` 和 `codeflow_basic`。

验收：

- 至少 20 个 stable BugsInPy 任务。
- 每个 excluded 任务都有原因。
- 报告按 project 拆分。

### Phase 5：SWE-bench Lite / Verified 5+5

目的：把 SWE-bench 从 Astropy 2+2 扩成更有说服力的小型稳定子集。

任务：

- 选择 Lite 5。
- 选择 Verified 5。
- 优先选依赖可控、setup 可重复、测试时间可接受的 case。
- 建立 repo cache。
- 写 workspace manifest。
- 跑 baseline 和 full harness。

验收：

- `swebench_lite_5_subset.jsonl` 可从 fresh clone 重新生成 workspace。
- `swebench_verified_5_subset.jsonl` 可从 fresh clone 重新生成 workspace。
- 报告区分 setup failure 与 agent failure。

### Phase 6：Artifact archive

目的：让历史结果可复核。

任务：

- 新增 `archive_run.py`。
- 对每次 benchmark 生成 artifact manifest。
- 压缩 raw artifact。
- 默认不提交大 artifact。
- 支持 GitHub Actions 上传 artifact。

验收：

- 每个 run 都有 manifest。
- manifest 可指向 result、review、diff、logs、trajectory。
- artifact 已脱敏。

### Phase 7：趋势报告

目的：支持长期维护和回归分析。

任务：

- 新增 `compare_runs.py`。
- 新增 `build_trend_report.py`。
- 支持比较两个 run 的 pass rate、failure taxonomy、runtime、cost、unsafe diff。
- 生成 `benchmark/reports/trends.md`。

验收：

- 可以比较当前 run 与上一轮 run。
- 报告能标出新增失败、修复的失败、性能退化、成本变化。

## 12. Fresh clone 一键复现设计

需要新增：

```text
benchmark/scripts/prepare_all_benchmark_data.py
```

建议参数：

```bash
uv run python benchmark/scripts/prepare_all_benchmark_data.py \
  --suite current \
  --proxy http://127.0.0.1:10087 \
  --clean
```

支持 suite：

- `smoke`
  - Harness-Bench 3。
  - QuixBugs 2。
  - 不需要真实 LLM。
- `current`
  - QuixBugs extended 31。
  - BugsInPy youtube-dl 5。
  - SWE-bench Lite 2。
  - SWE-bench Verified 2。
- `stable`
  - Harness-Bench 30。
  - QuixBugs full。
  - BugsInPy stable 20。
  - SWE-bench Lite 5。
  - SWE-bench Verified 5。

输出：

```text
benchmark/generated/prepare_manifest.json
benchmark/generated/dataset_status.md
```

manifest 应记录：

- 数据集名称。
- 任务数。
- 生成路径。
- 成功数。
- 失败数。
- 失败原因。
- 网络代理是否启用。
- 运行时间。

验收：

- fresh clone 后可以通过一个命令准备 current suite。
- 如果网络失败，错误信息明确提示使用 `--proxy http://127.0.0.1:10087`。
- 如果第三方依赖失败，manifest 中记录具体任务和失败命令。

## 13. 结果报告标准

### 13.1 当前报告需要改进的地方

当前报告已经提示 baseline 和 agent 方法不能混读，这是正确的。后续还要进一步强化：

- 总通过率只作为粗略参考。
- 主要展示 method-separated pass rate。
- 主要展示 dataset/method matrix。
- 单独展示 environment failure。
- 单独展示 retry 前后差异。

### 13.2 标准报告结构

建议每份正式报告使用：

```text
# CodeFlow Benchmark Report

## 1. Run Metadata
## 2. Executive Summary
## 3. Method Matrix
## 4. Dataset Breakdown
## 5. Task Type Breakdown
## 6. Risk Sensor Breakdown
## 7. Retry Analysis
## 8. Failure Taxonomy
## 9. Runtime and Cost
## 10. Task Details
## 11. Artifact Index
## 12. Caveats
```

### 13.3 报告中的必要 caveat

每份真实 LLM benchmark 报告必须包含：

- 模型名称。
- 运行日期。
- Git commit。
- 是否 dirty worktree。
- 数据集规模。
- 任务筛选方式。
- 是否使用代理。
- 最大重试次数。
- 是否包含 setup failures。
- 哪些目录未入 Git。
- 哪些 artifact 需要从外部下载。

## 14. 和真实 LLM 相关的要求

### 14.1 环境检查

运行真实 benchmark 前先执行：

```bash
uv run python benchmark/scripts/check_llm_env.py \
  --proxy http://127.0.0.1:10087
```

检查内容：

- `.env` 是否存在。
- API key 是否存在。
- base URL 是否可访问。
- 最小 chat completion 是否成功。
- 返回内容是否符合预期。

### 14.2 真实 benchmark 运行规则

- 使用真实 LLM 时必须记录 model。
- 每个任务最多重试 10 次。
- 重试原因必须写入 retry manifest。
- API/network failure 必须和 agent failure 分开。
- 不能只保留成功 attempt。
- 如果修改了 prompt、policy、sensor 或 repair 逻辑，必须新建 run id，不能覆盖旧结果。

### 14.3 推荐环境变量

```bash
export HTTP_PROXY=http://127.0.0.1:10087
export HTTPS_PROXY=http://127.0.0.1:10087
export ALL_PROXY=http://127.0.0.1:10087
```

根据本机 `.env` 继续使用项目当前模型配置。命令中可以显式传：

```bash
--model deepseekv4
```

## 15. 判断 benchmark 是否“完成”的标准

短期完成标准：

- `improvements.md` 中 Phase 1 完成。
- Harness-Bench 30。
- QuixBugs full 或有完整 excluded manifest。
- BugsInPy stable 20。
- SWE-bench Lite 5。
- SWE-bench Verified 5。
- 当前稳定集至少跑 `checks_only` 和 `codeflow_full`。
- 核心子集跑完四方法矩阵。
- 报告包含 failure taxonomy、retry analysis、runtime summary。
- fresh clone 可以一键准备 current suite。

中期完成标准：

- Harness-Bench 60。
- BugsInPy stable 50。
- SWE-bench Lite 10。
- SWE-bench Verified 10。
- 每周真实 LLM benchmark workflow 可手动/定时运行。
- artifact archive 可复核历史结果。
- trend report 可以比较两次 run。

长期完成标准：

- SWE-bench Lite 25。
- SWE-bench Verified 25。
- 多模型横向对比。
- token/cost 完整统计。
- failure taxonomy 稳定。
- benchmark dashboard 或静态趋势页。
- 可公开复现的 benchmark runbook。

## 16. 最推荐的下一步执行顺序

建议按下面顺序做，不要先扩全量 SWE-bench：

1. 补 `run_manifest.json` 和 `workspace_manifest.json`。
2. 补 task/result schema 和测试。
3. 改 `summarize_results.py`，增加 failure taxonomy、retry、runtime 统计。
4. 跑 QuixBugs 四方法矩阵，补 `raw_mini` 和 `codeflow_basic`。
5. 分析 QuixBugs 剩余 9 个任务，生成 full 或 excluded manifest。
6. 做 `prepare_all_benchmark_data.py`，保证 fresh clone 可准备 current suite。
7. 扩 BugsInPy 到 stable 20。
8. 扩 SWE-bench Lite / Verified 到 5+5。
9. 增加 artifact archive。
10. 增加手动真实 LLM GitHub Actions。
11. 再考虑 stable 50 / SWE-bench 10+10。

这个顺序的原因是：先解决可复现性和报告可信度，再扩大样本量。否则样本越多，后续越难解释哪些失败来自 agent，哪些失败来自数据准备、依赖、网络或统计口径。

## 17. 可以暂时不做的事情

短期可以不做：

- 完整 SWE-bench Lite。
- 完整 SWE-bench Verified。
- 真实 LLM benchmark 作为强制 PR gate。
- 第三方 dataset 源码入库。
- 重型数据库或在线 dashboard。
- 多模型大规模成本对比。

这些不是不重要，而是应该排在可复现、schema、artifact、稳定子集之后。

## 18. 最终交付物清单

Benchmark 部分真正完成后，应至少拥有：

- `benchmark/tasks/harness_bench.yaml`：30 到 60 个自建任务。
- `benchmark/tasks/quixbugs_full.yaml`：完整或带 excluded manifest 的 QuixBugs。
- `benchmark/tasks/bugsinpy_stable_20.yaml`。
- `benchmark/tasks/swebench_lite_5_subset.jsonl`。
- `benchmark/tasks/swebench_verified_5_subset.jsonl`。
- `benchmark/schemas/task.schema.json`。
- `benchmark/schemas/result.schema.json`。
- `benchmark/scripts/prepare_all_benchmark_data.py`。
- `benchmark/scripts/run_eval.py` 的 run manifest / artifact path / failure taxonomy 支持。
- `benchmark/scripts/summarize_results.py` 的矩阵报告支持。
- `benchmark/scripts/archive_run.py`。
- `benchmark/reports/current_real_results.md`。
- `benchmark/reports/current_real_results.json`。
- `benchmark/reports/BENCHMARK_RUNBOOK.md`。
- `benchmark/reports/DATASET_STATUS.md`。
- `.github/workflows/benchmark-smoke.yml`。
- `.github/workflows/benchmark-real-llm.yml`。

到这个程度，benchmark 才能从“我跑过一些任务”升级为“这是一个可复现、可对比、可解释、可持续维护的 Agent Benchmark 系统”。
