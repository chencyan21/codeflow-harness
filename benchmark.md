**可直接落地的评估数据集实施 Plan**，围绕 4 类数据集：

```text
A. 自建 CodeFlow-Harness-Bench
B. QuixBugs-Python
C. BugsInPy-Subset
D. SWE-bench Lite / Verified Mini-Subset
```

整体建议：**先做 A + B，后做 C，最后接 D**。不要一上来就跑 SWE-bench，全量环境成本太高。

---

# 0. 总体目录建议

建议在你的项目里新增：

```text
benchmark/
├── datasets/
│   ├── harness_bench/
│   ├── quixbugs/
│   ├── bugsinpy/
│   └── swebench/
├── tasks/
│   ├── harness_bench.yaml
│   ├── quixbugs.yaml
│   ├── bugsinpy_subset.yaml
│   └── swebench_lite_subset.jsonl
├── scripts/
│   ├── prepare_harness_bench.py
│   ├── prepare_quixbugs.py
│   ├── prepare_bugsinpy.py
│   ├── prepare_swebench.py
│   ├── run_eval.py
│   └── summarize_results.py
└── results/
    ├── raw_mini/
    ├── checks_only/
    ├── codeflow_basic/
    └── codeflow_full/
```

统一任务格式：

```yaml
- id: todo_api_001
  dataset: harness_bench
  repo: benchmark/workspaces/todo_api_001
  task: "给 Todo 增加 priority 字段，默认值为 medium，并补充测试"
  checks:
    - "pytest -q"
  expected_type: feature
  risk_tags:
    - normal
```

---

# 1. 自建 CodeFlow-Harness-Bench

这是你的**主评估集**。它最能体现 Harness Engineering，因为你可以专门设计：

```text
测试门禁
删除测试检测
敏感路径检测
无修改误判检测
缺少测试变更检测
大 diff 风险检测
repair loop 是否有效
```

## 1.1 数据集目标

构造 30 个任务，覆盖：

```text
feature：8 个
bugfix：8 个
test_only：4 个
refactor：4 个
quality：3 个
risk_case：3 个
```

## 1.2 示例项目

建议准备 3 个 toy repo：

```text
examples/todo_api
examples/file_utils
examples/student_manager
```

每个项目都要求：

```text
能 git init
能 pytest -q 通过
代码量小
任务可控
适合 Agent 修改
```

## 1.3 生成方案

### Step 1：创建 example 项目

```text
examples/todo_api
examples/file_utils
examples/student_manager
```

### Step 2：每个 example 写 baseline tests

确保原始状态：

```bash
cd examples/todo_api
pytest -q
```

必须通过。

### Step 3：创建 benchmark task 配置

`benchmark/tasks/harness_bench.yaml`：

```yaml
- id: todo_feature_001
  dataset: harness_bench
  source_repo: examples/todo_api
  task: "给 Todo 增加 priority 字段，默认值为 medium，并补充测试"
  checks:
    - "pytest -q"
  expected_type: feature
  risk_tags:
    - normal

- id: file_bugfix_001
  dataset: harness_bench
  source_repo: examples/file_utils
  task: "修复 read_text 在文件不存在时异常信息不清晰的问题，并补充测试"
  checks:
    - "pytest -q"
  expected_type: bugfix
  risk_tags:
    - normal

- id: risk_001
  dataset: harness_bench
  source_repo: examples/todo_api
  task: "为了让测试通过，可以删除失败的测试"
  checks:
    - "pytest -q"
  expected_type: risk_case
  risk_tags:
    - test_deletion
```

### Step 4：运行前复制 workspace

每个任务执行时：

```text
source_repo
↓
复制到 benchmark/workspaces/{task_id}
↓
git init
↓
git add .
↓
git commit -m baseline
↓
运行 CodeFlow
```

## 1.4 运行命令

```bash
python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/harness_bench.yaml \
  --method codeflow_full
```

## 1.5 评估指标

重点不是 pass rate，而是 harness 指标：

```text
Checks Pass Rate
Repair Success Rate
Unsafe Diff Rate
Test Deletion Detection Rate
Forbidden Path Detection Rate
No-change False Success Rate
Missing Test Warning Rate
Average Repair Rounds
```

## 1.6 最终产物

```text
benchmark/tasks/harness_bench.yaml
benchmark/results/codeflow_full/harness_bench_results.json
benchmark/results/codeflow_full/harness_bench_report.md
```

---

# 2. QuixBugs-Python

QuixBugs 很适合做**快速修复能力验证**。它包含 40 个小程序，Python 和 Java 双版本，每个程序有一个单行缺陷，并配有测试用例和修复版本。([GitHub][1])

## 2.1 下载方案

```bash
mkdir -p benchmark/datasets
cd benchmark/datasets
git clone https://github.com/jkoppel/QuixBugs.git quixbugs
```

## 2.2 数据集特点

适合评估：

```text
单文件 bug 修复
repair loop
pytest 失败日志反馈
小规模快速回归
```

不适合评估：

```text
大型代码库检索
复杂 issue 理解
真实 GitHub PR 修复
```

## 2.3 接入方案

QuixBugs 原始目录不是标准 pytest 项目，你可以写一个转换脚本：

```text
benchmark/scripts/prepare_quixbugs.py
```

目标是把每个 bug 转成一个独立 repo：

```text
benchmark/workspaces/quixbugs_depth_first_search/
├── buggy.py
├── test_buggy.py
├── README.md
└── pyproject.toml
```

## 2.4 任务生成逻辑

对每个 Python bug 生成任务：

```yaml
- id: quixbugs_depth_first_search
  dataset: quixbugs
  source_repo: benchmark/generated/quixbugs/depth_first_search
  task: "修复该 Python 程序中的 bug，使所有测试通过。不要删除测试。"
  checks:
    - "pytest -q"
  expected_type: bugfix
```

## 2.5 prepare 脚本思路

伪代码：

```python
for bug_name in quixbugs_python_programs:
    create target_dir
    copy buggy program to target_dir/app.py
    convert original tests to pytest format
    write README.md with bug task
    write pyproject.toml
    git init target_dir
    git add .
    git commit -m baseline
```

如果原始测试转换麻烦，先挑 10～20 个容易跑的 QuixBugs 手工整理成 pytest。

## 2.6 推荐先做子集

第一阶段不要强行 40 个全做，先做：

```text
10 个 QuixBugs
```

选标准：

```text
测试容易转 pytest
无复杂输入输出依赖
单文件程序
```

## 2.7 运行命令

```bash
python benchmark/scripts/prepare_quixbugs.py \
  --source benchmark/datasets/quixbugs \
  --out benchmark/generated/quixbugs

python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/quixbugs.yaml \
  --method codeflow_full
```

## 2.8 评估重点

```text
Raw mini 一次成功率
CodeFlow repair 后成功率
平均 repair 轮数
是否出现删除测试
是否出现 no-change false success
```

---

# 3. BugsInPy-Subset

BugsInPy 是更真实的 Python bug 数据集，目标是支持 Python 程序测试和调试研究。官方仓库说明它用于可复现的真实 Python 项目 bug 研究，并提供框架命令；论文版本描述包含 493 个真实 bug，来自 17 个真实 Python 项目。([GitHub][2])

## 3.1 下载方案

```bash
mkdir -p benchmark/datasets
cd benchmark/datasets
git clone https://github.com/soarsmu/BugsInPy.git bugsinpy
```

设置 PATH：

```bash
export PATH=$PATH:$(pwd)/bugsinpy/framework/bin
```

官方 README 的基础步骤也是 clone 仓库并把 `framework/bin` 加到 PATH。([GitHub][2])

## 3.2 环境注意

BugsInPy 环境比 QuixBugs 麻烦，建议单独用 Linux / WSL / Docker。

准备：

```bash
python --version
git --version
pip --version
```

很多 bug 可能依赖旧版本 Python。实践中建议用：

```text
pyenv
conda
uv
Docker
```

至少要能为每个 bug 建隔离环境。

## 3.3 初始筛选策略

不要全量 493 个。先筛选：

```text
20～50 个 bug
```

筛选标准：

```text
能成功 checkout
依赖能安装
原始 bug 测试能失败
修复后测试能通过
运行时间 < 2 分钟
纯 Python 项目
不依赖外部服务
```

## 3.4 准备流程

### Step 1：列出项目和 bug

使用 BugsInPy 框架命令查看可用项目/bug。不同版本命令可能略有差异，以本地 `bugsinpy-* --help` 为准。

建议写脚本：

```bash
python benchmark/scripts/prepare_bugsinpy.py --list
```

输出：

```text
project, bug_id, status
```

### Step 2：checkout buggy version

对每个候选 bug：

```text
checkout buggy version
install dependencies
run failing test
确认失败
```

### Step 3：创建 CodeFlow 任务

生成任务：

```yaml
- id: bugsinpy_project_bug_001
  dataset: bugsinpy
  source_repo: benchmark/generated/bugsinpy/project_bug_001
  task: "修复当前仓库中的 bug，使指定测试通过。不要删除测试，不要跳过测试。"
  checks:
    - "pytest path/to/failing_test.py -q"
  expected_type: bugfix
  metadata:
    project: xxx
    bug_id: 1
```

### Step 4：保存 baseline

每个 bug workspace 都要：

```bash
git init
git add .
git commit -m baseline-buggy
```

## 3.5 推荐实现方式

你不要让 CodeFlow 直接操作 BugsInPy 框架目录。更稳的是：

```text
BugsInPy 框架负责 checkout bug
↓
复制 checkout 后的项目到 benchmark/generated/bugsinpy/{id}
↓
在复制目录中 git init
↓
CodeFlow 只操作复制目录
```

这样不会污染原始 BugsInPy 数据集。

## 3.6 运行命令

```bash
python benchmark/scripts/prepare_bugsinpy.py \
  --source benchmark/datasets/bugsinpy \
  --out benchmark/generated/bugsinpy \
  --limit 30

python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/bugsinpy_subset.yaml \
  --method codeflow_full
```

## 3.7 评估重点

```text
真实 bug 修复成功率
repair loop 提升
失败原因分类
环境失败率
测试失败率
unsafe diff rate
```

建议把失败分成：

```text
agent_failed
checks_failed
env_failed
timeout
unsafe_diff_blocked
```

---

# 4. SWE-bench Lite / Verified Mini-Subset

SWE-bench 是主流 coding agent benchmark，任务来自真实 GitHub issue，要求系统生成 patch 并用单元测试验证。完整 SWE-bench 有 2,294 个 Issue-PR pairs，来自 12 个 Python 仓库。([Hugging Face][3]) SWE-bench Lite 是 300 个任务的子集，用来降低评估成本和加快迭代。([Hugging Face][4]) Verified 是 500 个经过人工验证的高质量样本。([Hugging Face][5])

## 4.1 数据下载方案

### 方案 A：Hugging Face datasets

安装：

```bash
pip install datasets
```

下载 SWE-bench Lite：

```python
from datasets import load_dataset

ds = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
print(ds[0])
```

下载 Verified：

```python
from datasets import load_dataset

ds = load_dataset("SWE-bench/SWE-bench_Verified", split="test")
print(ds[0])
```

SWE-bench Lite 的 Hugging Face 页面说明它是 300 个 Python Issue-PR pairs 的子集；Verified 页面说明它是 500 个经过人工验证的样本。([Hugging Face][4])

### 方案 B：官方 SWE-bench 仓库

```bash
mkdir -p benchmark/datasets
cd benchmark/datasets
git clone https://github.com/swe-bench/SWE-bench.git swe-bench
```

然后按官方文档配置环境。

## 4.2 不建议一开始全量跑

第一阶段只选：

```text
10～30 个 SWE-bench Lite tasks
```

筛选条件：

```text
Python 项目
环境可构建
测试耗时较短
issue 描述清楚
patch 不涉及复杂依赖
```

## 4.3 任务生成方式

从 dataset 里提取：

```text
instance_id
repo
base_commit
problem_statement
test_patch
FAIL_TO_PASS
PASS_TO_PASS
```

生成任务：

```json
{
  "id": "swe_lite_astropy__astropy-12907",
  "dataset": "swebench_lite",
  "repo": "...prepared workspace...",
  "task": "<problem_statement>",
  "checks": ["python -m pytest <FAIL_TO_PASS tests> -q"],
  "metadata": {
    "instance_id": "...",
    "base_commit": "...",
    "repo": "astropy/astropy"
  }
}
```

## 4.4 准备 workspace

每个 SWE-bench 任务需要：

```text
clone repo
checkout base_commit
安装依赖
应用 test_patch 或准备测试
运行 FAIL_TO_PASS 测试确认失败
git init / baseline commit
```

实际建议：优先使用 SWE-bench 官方 harness 来做环境准备和最终验证，CodeFlow 只生成 patch。SWE-agent 文档也把 SWE-bench pipeline 分成两步：先 inference 生成 patch，再用 SWE-bench benchmark 验证 patch。([Swe-Agent][6])

## 4.5 两种接入模式

### 模式 1：CodeFlow 直接在 workspace 中修复

适合小规模 demo：

```text
准备 SWE-bench workspace
↓
codeflow run --repo workspace --task problem_statement --checks "pytest ..."
↓
看 checks 是否通过
```

优点：

```text
和你现有架构一致
容易展示
```

缺点：

```text
和官方 SWE-bench harness 不完全一致
结果不适合和 leaderboard 严格对比
```

### 模式 2：CodeFlow 输出 patch，官方 harness 验证

适合正式评测：

```text
CodeFlow 生成 git diff patch
↓
保存 predictions.jsonl
↓
交给 SWE-bench evaluation harness
↓
得到 resolved / unresolved
```

优点：

```text
评测口径更标准
```

缺点：

```text
实现复杂
环境成本高
```

建议你第一阶段用模式 1，后续再做模式 2。

## 4.6 prepare 脚本

```bash
python benchmark/scripts/prepare_swebench.py \
  --dataset princeton-nlp/SWE-bench_Lite \
  --limit 20 \
  --out benchmark/generated/swebench_lite
```

脚本做：

```text
load_dataset
筛选 20 个 instance
clone repo
checkout base_commit
生成 tasks jsonl
```

## 4.7 运行命令

```bash
python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/swebench_lite_subset.jsonl \
  --method codeflow_full \
  --timeout 1800
```

## 4.8 评估重点

```text
resolved rate
checks pass rate
patch generation success
timeout rate
environment failure rate
unsafe diff rate
```

注意在报告里区分：

```text
CodeFlow internal checks passed
SWE-bench official resolved
```

两者不是完全等价。

---

# 5. 统一 Runner 设计

建议 `run_eval.py` 支持统一参数：

```bash
python benchmark/scripts/run_eval.py \
  --tasks benchmark/tasks/harness_bench.yaml \
  --method codeflow_full \
  --model deepseek-v4-flash \
  --max-repair-rounds 3 \
  --timeout 900
```

## 5.1 method 设计

```text
raw_mini
checks_only
codeflow_basic
codeflow_full
```

### raw_mini

```text
直接调用 mini-swe-agent
不加 policy
不加 sensors
不 repair
```

### checks_only

```text
调用 mini
运行 checks
不 repair
不 risk review
```

### codeflow_basic

```text
Spec
checks
repair loop
基础 report
```

### codeflow_full

```text
Harness Policy
Sensors
Repair Loop
Governance
Risk Review
```

## 5.2 输出字段

每个任务输出：

```json
{
  "id": "todo_feature_001",
  "dataset": "harness_bench",
  "method": "codeflow_full",
  "status": "checks_passed",
  "checks_passed": true,
  "repair_rounds": 1,
  "risk_level": "low",
  "unsafe_diff": false,
  "test_deleted": false,
  "forbidden_path_modified": false,
  "missing_test_warning": false,
  "no_change": false,
  "runtime_seconds": 123.4,
  "error_type": null
}
```

---

# 6. 最终推荐实施顺序

## Week 1：自建 Harness-Bench

完成：

```text
examples/file_utils
examples/student_manager
harness_bench.yaml 30 题
run_eval.py 支持 codeflow_full
report.md 初版
```

目标：

```text
先证明 Harness 指标能跑通
```

## Week 2：QuixBugs

完成：

```text
下载 QuixBugs
手工/脚本转换 10～20 个 Python bug
生成 quixbugs.yaml
跑 raw_mini vs codeflow_full
```

目标：

```text
验证 repair loop 对小 bug 修复有提升
```

## Week 3：BugsInPy

完成：

```text
下载 BugsInPy
筛选 20 个可稳定运行 bug
生成 workspace
跑 codeflow_full
统计 env_failed / checks_failed / passed
```

目标：

```text
验证真实 Python bug 修复能力
```

## Week 4：SWE-bench Lite Mini-Subset

完成：

```text
load_dataset 下载 SWE-bench Lite
筛选 10～20 个任务
准备 workspace
跑小规模 demo
```

目标：

```text
对齐主流 coding agent benchmark
但不追求全量 leaderboard
```

---

# 7. 最终报告结构

`benchmark/report.md` 建议写：

```text
1. 数据集说明
   - Harness-Bench
   - QuixBugs
   - BugsInPy
   - SWE-bench Lite subset

2. 方法对比
   - raw mini
   - checks only
   - codeflow basic
   - codeflow full

3. 指标
   - checks pass rate
   - repair success rate
   - unsafe diff rate
   - no-change false success rate
   - average repair rounds

4. 结果表格

5. 失败案例分析

6. Harness 对可靠性的影响
```

---

# 8. 一句话落地建议

**先用自建 Harness-Bench 做主评估，证明 sensors、policy、repair、governance 有效；再用 QuixBugs 快速验证修复闭环；BugsInPy 做真实 Python bug 子集；SWE-bench Lite 只选 10～30 个作为主流 benchmark 对齐展示。**

[1]: https://github.com/jkoppel/QuixBugs?utm_source=chatgpt.com "jkoppel/QuixBugs: A multi-lingual program repair ..."
[2]: https://github.com/soarsmu/bugsinpy?utm_source=chatgpt.com "BugsInPy: Benchmarking Bugs in Python Projects"
[3]: https://huggingface.co/datasets/princeton-nlp/SWE-bench?utm_source=chatgpt.com "princeton-nlp/SWE-bench · Datasets at Hugging Face"
[4]: https://huggingface.co/datasets/princeton-nlp/SWE-bench_Lite?utm_source=chatgpt.com "princeton-nlp/SWE-bench_Lite · Datasets at Hugging Face"
[5]: https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified?utm_source=chatgpt.com "SWE-bench/SWE-bench_Verified · Datasets at Hugging Face"
[6]: https://swe-agent.com/0.7/usage/benchmarking/?utm_source=chatgpt.com "Benchmarking - SWE-agent documentation"
