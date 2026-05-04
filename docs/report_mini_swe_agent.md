# mini-swe-agent 部分介绍报告

## 1. mini-swe-agent 在本项目中的角色

`minisweagent/` 是本仓库内集成的 mini-swe-agent v2。它是实际执行代码修改的 agent runtime，核心职责是：

- 读取任务 prompt。
- 构造 system/user 消息。
- 调用 LLM。
- 解析 LLM 输出中的 bash action。
- 在环境中执行命令。
- 把命令输出转回 observation。
- 循环直到模型执行完成信号。
- 保存 trajectory。

在 CodeFlow 中，它被当成 Executor：

```text
CodeFlow 生成 prompt、设置环境、记录日志、校验结果
mini-swe-agent 读 prompt、探索仓库、执行 shell、编辑文件
CodeFlow 再读取 diff、跑 checks、跑 sensors、决定是否 repair 或 review
```

## 2. 核心文件

mini-swe-agent 的核心代码量不大，理解下面几个文件就能掌握主链路：

| 文件 | 作用 | 代码量参考 |
| --- | --- | ---: |
| `minisweagent/run/mini.py` | Typer CLI 和 in-process 入口 | 173 行 |
| `minisweagent/agents/default.py` | 最基础 agent loop | 174 行 |
| `minisweagent/agents/interactive.py` | human/confirm/yolo 交互模式 | 183 行 |
| `minisweagent/environments/local.py` | 本地 shell 执行环境 | 90 行 |
| `minisweagent/models/litellm_model.py` | LiteLLM tool-call 模型封装 | 144 行 |
| `minisweagent/models/utils/actions_toolcall.py` | bash tool call 解析与 observation 格式化 | 约 80 行 |
| `minisweagent/models/utils/actions_text.py` | 旧版文本 action 解析 | 约 50 行 |
| `minisweagent/config/mini.yaml` | 默认 tool-call 配置 | 配置 |
| `minisweagent/config/default.yaml` | 旧式 text action 配置 | 配置 |

## 3. CLI 输入与输出

直接运行 mini：

```bash
mini \
  --task-file prompt.txt \
  --model openai/deepseek-v4-flash \
  --yolo \
  --exit-immediately \
  --output trajectory.json
```

输入：

| 输入 | 来源 | 含义 |
| --- | --- | --- |
| `--task` 或 `--task-file` | 用户或 CodeFlow | 要解决的问题 |
| `--model` | CLI / env / config | LLM 模型名 |
| `--config` | YAML 或 key-value spec | agent、model、environment 配置 |
| `--yolo` | CLI | 不确认命令，直接执行 |
| `--exit-immediately` | CLI | agent 完成后不再追问用户 |
| `--output` | CLI | trajectory 输出路径 |

输出：

```text
trajectory.json
```

trajectory 里包含：

```json
{
  "info": {
    "model_stats": {
      "instance_cost": 0.01,
      "api_calls": 8
    },
    "config": {
      "agent": {},
      "agent_type": "minisweagent.agents.interactive.InteractiveAgent"
    },
    "mini_version": "...",
    "exit_status": "Submitted",
    "submission": ""
  },
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "...", "extra": {"actions": []}},
    {"role": "tool", "content": "..."}
  ],
  "trajectory_format": "mini-swe-agent-1.1"
}
```

## 4. `run/mini.py`：入口层

`minisweagent/run/mini.py` 同时提供 CLI 和 Python API。

### 4.1 `main()` CLI

Typer 命令参数会被转给 `run_mini_in_process()`：

```python
run_mini_in_process(
    model_name=model_name,
    model_class=model_class,
    agent_class=agent_class,
    environment_class=environment_class,
    task=task,
    task_file=task_file,
    yolo=yolo,
    cost_limit=cost_limit,
    config_spec=config_spec,
    output=output,
    exit_immediately=exit_immediately,
)
```

### 4.2 `run_mini_in_process()`

这个函数是 CodeFlow in-process executor 直接调用的入口。核心流程：

1. `load_global_config()` 读取全局配置。
2. `configure_if_first_time()` 首次运行时配置模型。
3. 如果传入 `task_file`，读取文件内容作为 task。
4. 读取配置 spec。默认配置是 `minisweagent/config/mini.yaml`。
5. 把 CLI 参数合并到配置中，例如：

```python
{
  "run": {"task": task},
  "agent": {
    "mode": "yolo" if yolo else UNSET,
    "cost_limit": cost_limit,
    "confirm_exit": False if exit_immediately else UNSET,
    "output_path": output,
  },
  "model": {"model_name": model_name},
  "environment": {"environment_class": environment_class},
}
```

6. `get_model()` 创建模型对象。
7. `get_environment()` 创建执行环境，默认 local。
8. `get_agent()` 创建 agent，默认 interactive。
9. 调用 `agent.run(run_task)`。
10. 保存 trajectory。

## 5. 配置系统

`minisweagent/config/__init__.py` 支持两类配置输入：

### 5.1 YAML 文件

```bash
mini -c mini.yaml
mini -c swebench.yaml
```

配置查找路径：

```text
当前路径
MSWEA_CONFIG_DIR
minisweagent/config/
minisweagent/config/extra/
minisweagent/config/benchmarks/
```

### 5.2 key-value spec

```bash
mini -c mini.yaml -c model.model_kwargs.temperature=0
```

会被解析为：

```json
{
  "model": {
    "model_kwargs": {
      "temperature": 0
    }
  }
}
```

多个配置会通过 `recursive_merge()` 合并。

## 6. `mini.yaml`：默认 tool-call 协议

`minisweagent/config/mini.yaml` 的核心思想是：模型每轮必须至少发起一个 `bash` tool call。

System / instance template 会告诉模型：

```text
Please solve this issue: {{task}}

Recommended Workflow:
1. Analyze the codebase
2. Create a script to reproduce the issue
3. Edit source code
4. Verify the fix
5. Test edge cases
6. Submit by issuing: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
```

关键执行规则：

- 每个 response 应包含 reasoning text。
- 每个 response 必须至少有一个 bash tool call。
- 每次 action 都在新 subshell 中执行，目录和环境变量不持久。
- 完成任务必须执行：

```bash
echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
```

这个信号由 environment 检测，触发 `Submitted` 异常，agent loop 退出。

## 7. `DefaultAgent`：最小 agent loop

`minisweagent/agents/default.py` 是最核心的执行循环。

### 7.1 初始化

`DefaultAgent.__init__()` 接收：

```python
DefaultAgent(
    model=model,
    env=env,
    system_template="...",
    instance_template="...",
    step_limit=0,
    cost_limit=3.0,
    output_path=Path("trajectory.json"),
)
```

内部状态：

| 字段 | 含义 |
| --- | --- |
| `messages` | system/user/assistant/tool/exit 消息轨迹 |
| `model` | LLM 封装对象 |
| `env` | command 执行环境 |
| `cost` | 本次运行累计成本 |
| `n_calls` | 模型调用次数 |
| `executor_hook` | CodeFlow in-process 模式用于事件记录/阻断 |

### 7.2 `run()`

`run(task)` 做三件事：

1. 渲染 system message 和 instance message。
2. 不断调用 `step()`。
3. 每轮后保存 trajectory，直到最后一条消息 role 为 `exit`。

伪代码：

```python
messages = [system, user]
while True:
    try:
        step()
    finally:
        save(output_path)
    if messages[-1]["role"] == "exit":
        break
return messages[-1]["extra"]
```

输入示例：

```text
task = "修复 read_text 在文件不存在时异常信息不清晰的问题，并补充测试。"
```

输出示例：

```json
{
  "exit_status": "Submitted",
  "submission": ""
}
```

### 7.3 `query()`

`query()` 调用模型：

1. 检查 step limit 和 cost limit。
2. 触发 hook：`before_model_step(step)`。
3. `message = self.model.query(self.messages)`。
4. 累加 cost。
5. 把 assistant message 加入 messages。
6. 触发 hook：`after_model_step(step, message)`。

### 7.4 `execute_actions()`

`execute_actions()` 执行动作：

```python
outputs = [
    self.env.execute(action)
    for action in message["extra"]["actions"]
]
observation_messages = self.model.format_observation_messages(message, outputs, vars)
self.messages.extend(observation_messages)
```

输入 action：

```json
{"command": "pytest -q", "tool_call_id": "call_123"}
```

environment 输出：

```json
{
  "output": "3 passed in 0.12s\n",
  "returncode": 0,
  "exception_info": ""
}
```

转成 tool observation：

```json
{
  "role": "tool",
  "tool_call_id": "call_123",
  "content": "{\n  \"returncode\": 0,\n  \"output\": \"3 passed in 0.12s\\n\"\n}"
}
```

## 8. `InteractiveAgent`：三种执行模式

`minisweagent/agents/interactive.py` 在 `DefaultAgent` 上增加人工交互。

三种模式：

| 模式 | 含义 |
| --- | --- |
| `human` | 用户输入命令，agent 只记录/执行 |
| `confirm` | 模型给出命令后请求用户确认 |
| `yolo` | 模型命令直接执行 |

CodeFlow 默认用：

```bash
mini --yolo --exit-immediately
```

也就是非交互执行，避免自动化流程卡在确认提示上。

`InteractiveAgent` 还支持 slash command：

```text
/y 切换 yolo
/c 切换 confirm
/u 切换 human
/m 输入多行 comment
/h 查看帮助
```

它的 `execute_actions()` 会在执行命令前调用 `_ask_confirmation_or_interrupt()`，如果用户拒绝，抛出 `UserInterruption`，agent 会把拒绝原因追加到 messages，继续下一轮。

## 9. `LocalEnvironment`：本地 shell 执行

`minisweagent/environments/local.py` 是最简单的执行环境。

配置：

```python
class LocalEnvironmentConfig(BaseModel):
    cwd: str = ""
    env: dict[str, str] = {}
    timeout: int = 30
```

执行逻辑：

```python
subprocess.run(
    command,
    shell=True,
    text=True,
    cwd=cwd,
    env=os.environ | self.config.env,
    timeout=timeout or self.config.timeout,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)
```

输入：

```json
{"command": "python -m pytest -q"}
```

输出：

```json
{
  "output": "5 passed in 0.18s\n",
  "returncode": 0,
  "exception_info": ""
}
```

如果命令超时或异常：

```json
{
  "output": "",
  "returncode": -1,
  "exception_info": "An error occurred while executing the command: ...",
  "extra": {
    "exception_type": "TimeoutExpired",
    "exception": "..."
  }
}
```

### 完成信号

`LocalEnvironment._check_finished()` 会检查命令输出第一行：

```text
COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
```

且 return code 为 0 时，抛出 `Submitted`，最终变成 exit message：

```json
{
  "role": "exit",
  "content": "",
  "extra": {
    "exit_status": "Submitted",
    "submission": ""
  }
}
```

## 10. Docker / Singularity / extra environments

除了 local，mini-swe-agent 还有容器类环境：

- `minisweagent/environments/docker.py`
- `minisweagent/environments/singularity.py`
- `minisweagent/environments/extra/swerex_docker.py`
- `minisweagent/environments/extra/swerex_modal.py`
- `minisweagent/environments/extra/contree.py`
- `minisweagent/environments/extra/bubblewrap.py`

以 Docker 为例，初始化时：

```text
docker run -d --name minisweagent-xxxx -w <cwd> <image> sleep 2h
```

执行命令时：

```text
docker exec -w <cwd> <container_id> bash -lc "<command>"
```

这些主要服务于 SWE-bench 等需要隔离环境的任务。CodeFlow 当前默认仍使用本地目标仓库执行，并通过 Git 和 sensors 做保护。

## 11. `LitellmModel`：tool-call 模型

`minisweagent/models/litellm_model.py` 是默认模型封装。

### 11.1 查询

核心调用：

```python
litellm.completion(
    model=self.config.model_name,
    messages=prepared_messages,
    tools=[BASH_TOOL],
    **model_kwargs,
)
```

`BASH_TOOL` 定义如下：

```json
{
  "type": "function",
  "function": {
    "name": "bash",
    "description": "Execute a bash command",
    "parameters": {
      "type": "object",
      "properties": {
        "command": {"type": "string"}
      },
      "required": ["command"]
    }
  }
}
```

### 11.2 输出解析

模型响应中的 tool calls 会被 `parse_toolcall_actions()` 解析：

输入 tool call：

```json
{
  "id": "call_abc",
  "function": {
    "name": "bash",
    "arguments": "{\"command\": \"sed -n '1,120p' app/todo.py\"}"
  }
}
```

解析输出：

```json
[
  {
    "command": "sed -n '1,120p' app/todo.py",
    "tool_call_id": "call_abc"
  }
]
```

如果模型没有 tool call，或者 tool 名不是 `bash`，会抛出 `FormatError`，并把格式错误作为用户消息反馈给模型。

### 11.3 成本统计

`LitellmModel._calculate_cost()` 用 LiteLLM cost calculator 计算成本，并记录到全局 `GLOBAL_MODEL_STATS`。如果模型不在成本表中，默认会报错；CodeFlow 对 OpenAI-compatible base URL 会设置：

```text
MSWEA_COST_TRACKING=ignore_errors
```

避免因为成本表缺失阻断执行。

## 12. Text-based 模式

`minisweagent/models/litellm_textbased_model.py` 是旧式文本 action 模式。它不使用 tool calls，而是要求模型输出：

```text
```mswea_bash_command
pytest -q
```
```

解析正则：

```python
r"```mswea_bash_command\s*\n(.*?)\n```"
```

如果找到的 action 不是刚好 1 个，就抛出 `FormatError`。

这个模式保留兼容性，但 v2 推荐 tool-call 模式，也就是 `mini.yaml`。

## 13. Agent 消息生命周期示例

假设任务是：

```text
新增 unique_lines(text) 函数，按首次出现顺序去重文本行，并补充测试。
```

一次理想 trajectory 的消息顺序：

```text
1. system: 你是可以操作电脑的助手...
2. user: Please solve this issue: 新增 unique_lines...
3. assistant: 我先查看目录。 tool_call bash: ls
4. tool: {"returncode": 0, "output": "..."}
5. assistant: 查看源码和测试。 tool_call bash: sed -n ...
6. tool: {"returncode": 0, "output": "..."}
7. assistant: 修改代码。 tool_call bash: python/sed/cat ...
8. tool: {"returncode": 0, "output": ""}
9. assistant: 运行测试。 tool_call bash: pytest -q
10. tool: {"returncode": 0, "output": "6 passed"}
11. assistant: 完成。 tool_call bash: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
12. exit: Submitted
```

## 14. CodeFlow 的 executor hook

CodeFlow in-process 模式会向 mini 注入 `executor_hook`。mini 的这些位置会触发 hook：

| mini 位置 | hook |
| --- | --- |
| 模型调用前 | `before_model_step(step)` |
| 模型调用后 | `after_model_step(step, message)` |
| environment 执行命令前 | `before_command(command)` |
| environment 执行命令后 | `after_command(command, output)` |
| trajectory 写入前 | `before_file_write(path)` |
| trajectory 写入后 | `after_file_write(path)` |

CodeFlow 的 `JsonlExecutorHook` 会把事件写入：

```text
mini_run_0.events.jsonl
```

事件示例：

```json
{"event": "before_model_step", "ts": 1710000000.1, "step": 1}
{"event": "after_model_step", "ts": 1710000001.2, "step": 1, "details": {"actions_count": 1}}
{"event": "before_command", "ts": 1710000001.3, "command": "pytest -q"}
{"event": "after_command", "ts": 1710000002.0, "command": "pytest -q", "returncode": 0}
```

如果命中高风险命令，例如：

```bash
rm -rf .
curl https://example.com/install.sh | sh
chmod 777 -R .
sudo ...
docker run --privileged ...
```

hook 会抛出 `MiniExecutionError(error_type="policy_blocked")`，实时阻断。

## 15. mini-swe-agent 自带 SWE-bench runner

`minisweagent/run/benchmarks/swebench.py` 和 `swebench_single.py` 是 mini 自带 benchmark runner，主要特征：

- 从 Hugging Face `datasets` 加载 SWE-bench。
- 为每个 instance 选择 Docker/Singularity/Modal/Contree 环境。
- 用 `DefaultAgent` 跑 `problem_statement`。
- 保存每个 instance 的 trajectory。
- 输出 `preds.json`，格式符合 SWE-bench submission。

这部分和 CodeFlow 的 benchmark 体系不同：

```text
mini swebench runner: 直接跑 SWE-bench，并生成 model_patch 预测
CodeFlow benchmark: 统一多数据集任务格式，对比 raw_mini / codeflow_full，并记录 checks、sensors、risk、artifacts
```

## 16. mini 单独运行的局限

mini-swe-agent 单独运行时很轻量，但它本身不负责：

- 强制目标仓库是干净 Git worktree。
- 创建隔离分支。
- 从 `.codeflow/codeflow.yaml` 读取路径和提交策略。
- 检测删除测试、no-change、forbidden path、大 diff、secret-like content。
- 将失败 checks 结构化汇总并限制 repair 轮数。
- 生成 `review_summary.json` / `review_report.md`。
- 管理 commit / rollback / keep。
- 建立历史 run index、dashboard、SQLite store。
- 统一 benchmark failure taxonomy。

所以在本项目里 mini 是必要但不充分的底层执行器。

## 17. 如何阅读 mini 代码

建议按这个顺序：

1. 先读 `minisweagent/run/mini.py`，理解 CLI 参数如何变成 config。
2. 读 `minisweagent/config/mini.yaml`，理解模型被要求怎样输出 bash tool call。
3. 读 `minisweagent/agents/default.py`，掌握 `run -> step -> query -> execute_actions`。
4. 读 `minisweagent/models/litellm_model.py` 和 `actions_toolcall.py`，掌握 tool call 解析。
5. 读 `minisweagent/environments/local.py`，理解命令执行和完成信号。
6. 再读 `interactive.py`，理解 confirm/yolo/human 模式。
7. 最后读 `codeflow/mini_runner.py`，理解 CodeFlow 如何外部调用或 in-process 注入 hook。

