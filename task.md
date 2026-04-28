目标是：**基于 mini-swe-agent v2 做二次开发，不从零写 Agent，只做 CodeFlow 的可信工作流增强层**。mini-swe-agent v2 本身是轻量 coding agent，官方说明它是 v2 版本，并默认支持 native tool calling；SWE-bench 官网也支持用 mini-SWE-agent v2 作为统一 scaffold 做评测。([GitHub](https://github.com/SWE-agent/mini-swe-agent?utm_source=chatgpt.com))

------

# CodeFlow Agent 实现方案

## 1. 项目目标

基于 `mini-swe-agent v2` 实现一个 Python 项目的可信 AI 编程工作流系统。

不要从零实现 coding agent。
直接把 `mini-swe-agent` 作为代码执行引擎，在外层增加：

```text
Git 分支隔离
Spec 任务规格化
项目规则注入
强制测试门禁
失败自动修复循环
Diff 风险审查
人工确认 commit / rollback
小型 benchmark
```

最终命令效果：

```bash
codeflow run \
  --repo ./examples/todo_api \
  --task "给 Todo 增加 due_date 字段，并补充测试" \
  --checks "pytest -q" \
  --checks "ruff check ."
```

------

## 2. 技术边界

只支持：

```text
Python 项目
本地 Git 仓库
pytest
ruff
CLI 使用
mini-swe-agent v2
最多 3 轮自动修复
人工确认后 commit
```

暂时不要做：

```text
Web 前端
IDE 插件
Docker 沙盒
多语言支持
复杂数据库
SWE-bench 全量评测
```

------

## 3. 目标架构

```text
codeflow run
   ↓
检查 Git 仓库状态
   ↓
创建 ai/* 独立分支
   ↓
生成结构化 Spec
   ↓
读取 .codeflow/project_rules.md
   ↓
构造 mini-swe-agent 任务 prompt
   ↓
调用 mini-swe-agent 执行代码修改
   ↓
运行 pytest / ruff
   ↓
失败则再次调用 mini-swe-agent 修复，最多 3 轮
   ↓
读取 git diff
   ↓
生成风险报告
   ↓
人工选择 commit / rollback / keep
```

------

## 4. 项目目录结构

在新仓库中实现：

```text
codeflow-agent/
├── codeflow/
│   ├── __init__.py
│   ├── cli.py
│   ├── runner.py
│   ├── config.py
│   ├── models.py
│   ├── mini_runner.py
│   ├── spec_builder.py
│   ├── prompt_builder.py
│   ├── git_guard.py
│   ├── test_gate.py
│   ├── diff_reviewer.py
│   ├── report_writer.py
│   └── utils.py
├── examples/
│   └── todo_api/
├── benchmark/
│   ├── tasks.yaml
│   └── run_benchmark.py
├── tests/
├── pyproject.toml
└── README.md
```

------

## 5. 依赖

`pyproject.toml` 使用：

```toml
[project]
name = "codeflow-agent"
version = "0.1.0"
description = "Trusted workflow wrapper for mini-swe-agent v2"
requires-python = ">=3.10"
dependencies = [
    "typer>=0.12.0",
    "rich>=13.0.0",
    "pydantic>=2.0.0",
    "pyyaml>=6.0.0",
    "mini-swe-agent>=2.0.0",
]

[project.scripts]
codeflow = "codeflow.cli:app"

[tool.ruff]
line-length = 100

[tool.pytest.ini_options]
testpaths = ["tests"]
```

------

## 6. 核心数据结构

创建 `codeflow/models.py`：

```python
from __future__ import annotations

from pydantic import BaseModel, Field


class CodeFlowConfig(BaseModel):
    repo: str
    task: str
    checks: list[str] = Field(default_factory=lambda: ["pytest -q"])
    max_repair_rounds: int = 3
    model: str | None = None
    mini_config: str | None = None
    no_commit: bool = False
    dry_run: bool = False


class Spec(BaseModel):
    task_type: str
    goal: str
    acceptance_criteria: list[str]
    constraints: list[str]


class CheckResult(BaseModel):
    command: str
    success: bool
    returncode: int
    stdout: str
    stderr: str


class RunState(BaseModel):
    repo: str
    task: str
    branch: str
    spec: Spec | None = None
    rules: str = ""
    mini_runs: list[str] = Field(default_factory=list)
    check_results: list[CheckResult] = Field(default_factory=list)
    repair_round: int = 0
    diff: str = ""
    report: str = ""
    status: str = "initialized"
```

------

## 7. CLI

创建 `codeflow/cli.py`：

```python
import typer
from rich.console import Console

from codeflow.models import CodeFlowConfig
from codeflow.runner import run_codeflow

app = typer.Typer(help="CodeFlow Agent: trusted workflow wrapper for mini-swe-agent v2")
console = Console()


@app.command()
def run(
    repo: str = typer.Option(..., help="Path to target Git repository"),
    task: str = typer.Option(..., help="Natural language coding task"),
    checks: list[str] = typer.Option(["pytest -q"], help="Validation commands"),
    max_repair_rounds: int = typer.Option(3, help="Maximum repair attempts"),
    model: str | None = typer.Option(None, help="Model name passed to mini-swe-agent"),
    mini_config: str | None = typer.Option(None, help="mini-swe-agent config path"),
    no_commit: bool = typer.Option(False, help="Do not commit automatically"),
    dry_run: bool = typer.Option(False, help="Build prompt but do not run agent"),
):
    config = CodeFlowConfig(
        repo=repo,
        task=task,
        checks=checks,
        max_repair_rounds=max_repair_rounds,
        model=model,
        mini_config=mini_config,
        no_commit=no_commit,
        dry_run=dry_run,
    )
    state = run_codeflow(config)
    console.print(state.report)
```

------

## 8. Git Guard

创建 `codeflow/git_guard.py`：

功能要求：

```text
1. 检查 repo 是否是 Git 仓库
2. 检查工作区是否干净
3. 创建 ai/{slug} 分支
4. 获取 git diff
5. commit
6. rollback
```

实现要求：

```python
import re
import subprocess
from datetime import datetime
from pathlib import Path


def run_cmd(cmd: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)


def ensure_git_repo(repo: str) -> None:
    result = run_cmd(["git", "rev-parse", "--is-inside-work-tree"], repo)
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise RuntimeError(f"{repo} is not a Git repository")


def ensure_clean_worktree(repo: str) -> None:
    result = run_cmd(["git", "status", "--porcelain"], repo)
    if result.stdout.strip():
        raise RuntimeError("Git worktree is not clean. Commit or stash changes first.")


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text)
    text = text.strip("-")
    return text[:40] or "task"


def create_ai_branch(repo: str, task: str) -> str:
    branch = f"ai/{slugify(task)}-{datetime.now().strftime('%m%d-%H%M%S')}"
    result = run_cmd(["git", "checkout", "-b", branch], repo)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return branch


def get_diff(repo: str) -> str:
    return run_cmd(["git", "diff"], repo).stdout


def commit_changes(repo: str, message: str) -> None:
    add = run_cmd(["git", "add", "."], repo)
    if add.returncode != 0:
        raise RuntimeError(add.stderr)

    commit = run_cmd(["git", "commit", "-m", message], repo)
    if commit.returncode != 0:
        raise RuntimeError(commit.stderr)


def rollback(repo: str) -> None:
    run_cmd(["git", "restore", "."], repo)
```

------

## 9. Spec Builder

创建 `codeflow/spec_builder.py`。

先不要调用大模型，第一版用规则生成，确保稳定。

```python
from codeflow.models import Spec


def build_spec(task: str) -> Spec:
    return Spec(
        task_type="coding_task",
        goal=task,
        acceptance_criteria=[
            "Implementation satisfies the user task.",
            "Existing tests pass.",
            "New or updated tests are added when appropriate.",
            "No unrelated files are modified.",
        ],
        constraints=[
            "Do not delete existing tests.",
            "Do not bypass failing tests.",
            "Do not modify environment secrets.",
            "Keep changes minimal and relevant.",
        ],
    )
```

后续再替换成 LLM Spec Agent。

------

## 10. 项目规则读取

创建 `codeflow/utils.py`：

```python
from pathlib import Path


def read_project_rules(repo: str) -> str:
    path = Path(repo) / ".codeflow" / "project_rules.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return """
Default project rules:
- Keep changes minimal.
- Do not delete existing tests.
- Do not modify .env or secret files.
- Run required checks before reporting success.
"""
```

------

## 11. Prompt Builder

创建 `codeflow/prompt_builder.py`：

```python
from codeflow.models import CheckResult, Spec


def build_initial_prompt(task: str, spec: Spec, rules: str, checks: list[str]) -> str:
    criteria = "\n".join(f"- {x}" for x in spec.acceptance_criteria)
    constraints = "\n".join(f"- {x}" for x in spec.constraints)
    checks_text = "\n".join(f"- {x}" for x in checks)

    return f"""
You are working inside a local Git repository.

User task:
{task}

Structured spec:
Goal: {spec.goal}

Acceptance criteria:
{criteria}

Constraints:
{constraints}

Project rules:
{rules}

Required validation commands:
{checks_text}

Instructions:
1. Inspect the repository before editing.
2. Make the minimal necessary code changes.
3. Add or update tests when appropriate.
4. Do not claim success unless the required validation commands can pass.
5. Do not modify unrelated files.
"""


def build_repair_prompt(
    task: str,
    spec: Spec,
    rules: str,
    failed_results: list[CheckResult],
    checks: list[str],
) -> str:
    failure_logs = "\n\n".join(
        f"Command: {r.command}\nReturn code: {r.returncode}\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
        for r in failed_results
    )
    checks_text = "\n".join(f"- {x}" for x in checks)

    return f"""
The previous implementation did not pass validation.

Original task:
{task}

Goal:
{spec.goal}

Project rules:
{rules}

Failed validation logs:
{failure_logs}

Required validation commands:
{checks_text}

Please fix the implementation with minimal changes.
Do not delete tests.
Do not bypass tests.
Do not modify unrelated files.
"""
```

------

## 12. mini-swe-agent 调用器

创建 `codeflow/mini_runner.py`。

优先使用 subprocess 调用 `mini`，因为这样最稳定、最容易落地。

```python
import subprocess
from pathlib import Path
from uuid import uuid4


def run_mini_agent(
    repo: str,
    prompt: str,
    model: str | None = None,
    mini_config: str | None = None,
) -> str:
    run_id = str(uuid4())[:8]
    prompt_path = Path(repo) / f".codeflow_prompt_{run_id}.txt"
    prompt_path.write_text(prompt, encoding="utf-8")

    cmd = ["mini", "--prompt", prompt]
    if model:
        cmd.extend(["--model", model])
    if mini_config:
        cmd.extend(["--config", mini_config])

    result = subprocess.run(
        cmd,
        cwd=repo,
        text=True,
        capture_output=True,
    )

    log_path = Path(repo) / f".codeflow_mini_run_{run_id}.log"
    log_path.write_text(
        f"COMMAND: {' '.join(cmd)}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}",
        encoding="utf-8",
    )

    prompt_path.unlink(missing_ok=True)

    if result.returncode != 0:
        raise RuntimeError(f"mini-swe-agent failed. See {log_path}")

    return str(log_path)
```

注意：如果本地 `mini` 的参数不是 `--prompt`，就让 Codex 根据当前安装版本调整这一处。mini-swe-agent 文档说明 `mini` 是本地 REPL 风格 CLI，且 v2 默认使用 native tool calling；不同安装版本 CLI 参数可能会有轻微差异。([Mini Swe Agent](https://mini-swe-agent.com/latest/usage/mini/?utm_source=chatgpt.com))

------

## 13. Test Gate

创建 `codeflow/test_gate.py`：

```python
import subprocess

from codeflow.models import CheckResult


def run_checks(repo: str, checks: list[str]) -> list[CheckResult]:
    results: list[CheckResult] = []

    for command in checks:
        result = subprocess.run(
            command,
            cwd=repo,
            shell=True,
            text=True,
            capture_output=True,
        )
        results.append(
            CheckResult(
                command=command,
                success=result.returncode == 0,
                returncode=result.returncode,
                stdout=result.stdout[-8000:],
                stderr=result.stderr[-8000:],
            )
        )

    return results


def all_checks_passed(results: list[CheckResult]) -> bool:
    return all(r.success for r in results)


def failed_checks(results: list[CheckResult]) -> list[CheckResult]:
    return [r for r in results if not r.success]
```

------

## 14. Diff Reviewer

创建 `codeflow/diff_reviewer.py`。

第一版先用规则打分，不依赖 LLM。

```python
from codeflow.models import CheckResult


HIGH_RISK_PATTERNS = [
    "auth",
    "permission",
    "migration",
    ".env",
    "secret",
    "password",
    "token",
    "delete",
    "drop",
]

MEDIUM_RISK_PATTERNS = [
    "api",
    "schema",
    "model",
    "database",
    "config",
]


def score_risk(diff: str) -> tuple[str, list[str]]:
    lower = diff.lower()
    risks: list[str] = []

    for pattern in HIGH_RISK_PATTERNS:
        if pattern in lower:
            risks.append(f"High-risk keyword found in diff: {pattern}")

    if risks:
        return "high", risks

    for pattern in MEDIUM_RISK_PATTERNS:
        if pattern in lower:
            risks.append(f"Medium-risk keyword found in diff: {pattern}")

    if risks:
        return "medium", risks

    return "low", ["No obvious high-risk pattern detected."]


def build_review_report(
    task: str,
    branch: str,
    diff: str,
    check_results: list[CheckResult],
) -> str:
    risk_level, risks = score_risk(diff)
    changed_lines = len(diff.splitlines())
    check_summary = "\n".join(
        f"- {r.command}: {'PASS' if r.success else 'FAIL'}"
        for r in check_results
    )
    risk_text = "\n".join(f"- {x}" for x in risks)

    return f"""
# CodeFlow Review Report

## Task
{task}

## Branch
{branch}

## Validation
{check_summary}

## Risk Level
{risk_level}

## Risk Notes
{risk_text}

## Diff Size
{changed_lines} diff lines

## Recommendation
{"Commit is allowed after human review." if all(r.success for r in check_results) else "Do not commit until validation passes."}
"""
```

------

## 15. Runner 主流程

创建 `codeflow/runner.py`：

```python
from rich.console import Console
from rich.prompt import Prompt

from codeflow.diff_reviewer import build_review_report
from codeflow.git_guard import (
    commit_changes,
    create_ai_branch,
    ensure_clean_worktree,
    ensure_git_repo,
    get_diff,
    rollback,
)
from codeflow.mini_runner import run_mini_agent
from codeflow.models import CodeFlowConfig, RunState
from codeflow.prompt_builder import build_initial_prompt, build_repair_prompt
from codeflow.spec_builder import build_spec
from codeflow.test_gate import all_checks_passed, failed_checks, run_checks
from codeflow.utils import read_project_rules

console = Console()


def run_codeflow(config: CodeFlowConfig) -> RunState:
    ensure_git_repo(config.repo)
    ensure_clean_worktree(config.repo)

    branch = create_ai_branch(config.repo, config.task)
    state = RunState(repo=config.repo, task=config.task, branch=branch)

    console.print(f"[bold green]Created branch:[/bold green] {branch}")

    rules = read_project_rules(config.repo)
    spec = build_spec(config.task)

    state.rules = rules
    state.spec = spec

    prompt = build_initial_prompt(
        task=config.task,
        spec=spec,
        rules=rules,
        checks=config.checks,
    )

    if config.dry_run:
        state.report = prompt
        state.status = "dry_run"
        return state

    console.print("[bold]Running mini-swe-agent...[/bold]")
    log_path = run_mini_agent(
        repo=config.repo,
        prompt=prompt,
        model=config.model,
        mini_config=config.mini_config,
    )
    state.mini_runs.append(log_path)

    for round_idx in range(config.max_repair_rounds + 1):
        console.print(f"[bold]Running validation checks, round {round_idx}...[/bold]")
        results = run_checks(config.repo, config.checks)
        state.check_results = results

        if all_checks_passed(results):
            state.status = "checks_passed"
            break

        if round_idx >= config.max_repair_rounds:
            state.status = "checks_failed"
            break

        failed = failed_checks(results)
        repair_prompt = build_repair_prompt(
            task=config.task,
            spec=spec,
            rules=rules,
            failed_results=failed,
            checks=config.checks,
        )

        console.print(f"[yellow]Checks failed. Repair round {round_idx + 1}...[/yellow]")
        log_path = run_mini_agent(
            repo=config.repo,
            prompt=repair_prompt,
            model=config.model,
            mini_config=config.mini_config,
        )
        state.mini_runs.append(log_path)
        state.repair_round = round_idx + 1

    diff = get_diff(config.repo)
    state.diff = diff
    state.report = build_review_report(
        task=config.task,
        branch=branch,
        diff=diff,
        check_results=state.check_results,
    )

    console.print(state.report)

    if config.no_commit:
        state.status = "finished_no_commit"
        return state

    decision = Prompt.ask(
        "Choose action",
        choices=["commit", "rollback", "keep"],
        default="keep",
    )

    if decision == "commit":
        if not all_checks_passed(state.check_results):
            console.print("[red]Refusing to commit because checks failed.[/red]")
            state.status = "commit_refused_checks_failed"
            return state
        commit_changes(config.repo, f"codeflow: {config.task[:60]}")
        state.status = "committed"
    elif decision == "rollback":
        rollback(config.repo)
        state.status = "rolled_back"
    else:
        state.status = "kept_uncommitted"

    return state
```

------

## 16. 示例项目

创建 `examples/todo_api/`，必须是一个完整 Git 仓库，包含：

```text
examples/todo_api/
├── app/
│   ├── __init__.py
│   └── todo.py
├── tests/
│   └── test_todo.py
├── pyproject.toml
└── README.md
```

`app/todo.py`：

```python
from dataclasses import dataclass


@dataclass
class Todo:
    title: str
    done: bool = False


def create_todo(title: str) -> Todo:
    if not title:
        raise ValueError("title is required")
    return Todo(title=title)


def mark_done(todo: Todo) -> Todo:
    todo.done = True
    return todo
```

`tests/test_todo.py`：

```python
import pytest

from app.todo import create_todo, mark_done


def test_create_todo():
    todo = create_todo("learn agent")
    assert todo.title == "learn agent"
    assert todo.done is False


def test_create_todo_empty_title():
    with pytest.raises(ValueError):
        create_todo("")


def test_mark_done():
    todo = create_todo("learn agent")
    mark_done(todo)
    assert todo.done is True
```

------

## 17. Benchmark

创建 `benchmark/tasks.yaml`：

```yaml
tasks:
  - repo: examples/todo_api
    task: "给 Todo 增加 priority 字段，默认值为 medium，并补充测试"
    checks:
      - "pytest -q"

  - repo: examples/todo_api
    task: "给 create_todo 增加标题最大长度校验，超过 100 字符时报错，并补充测试"
    checks:
      - "pytest -q"

  - repo: examples/todo_api
    task: "给 Todo 增加 due_date 字段，允许为空，并补充测试"
    checks:
      - "pytest -q"
```

创建 `benchmark/run_benchmark.py`：

```python
import json
from pathlib import Path

import yaml

from codeflow.models import CodeFlowConfig
from codeflow.runner import run_codeflow


def main():
    tasks = yaml.safe_load(Path("benchmark/tasks.yaml").read_text(encoding="utf-8"))["tasks"]
    results = []

    for item in tasks:
        config = CodeFlowConfig(
            repo=item["repo"],
            task=item["task"],
            checks=item.get("checks", ["pytest -q"]),
            no_commit=True,
            max_repair_rounds=3,
        )
        try:
            state = run_codeflow(config)
            results.append(
                {
                    "task": item["task"],
                    "status": state.status,
                    "repair_round": state.repair_round,
                    "checks_passed": all(r.success for r in state.check_results),
                    "report": state.report,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "task": item["task"],
                    "status": "error",
                    "error": str(exc),
                }
            )

    Path("benchmark/results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
```

------

## 18. README 最小内容

README 只写：

~~~markdown
# CodeFlow Agent

A trusted workflow wrapper around mini-swe-agent v2 for Python projects.

## Features

- Git branch isolation
- Structured task spec
- Project rule injection
- pytest / ruff validation gate
- Repair loop using mini-swe-agent
- Diff risk review
- Human approval before commit

## Install

```bash
pip install -e .
pip install mini-swe-agent
~~~

## Usage

```bash
codeflow run \
  --repo ./examples/todo_api \
  --task "给 Todo 增加 due_date 字段，并补充测试" \
  --checks "pytest -q" \
  --no-commit
```

## Project Rules

Create `.codeflow/project_rules.md` in target repo:

~~~markdown
- Do not delete existing tests.
- Do not modify .env files.
- Keep changes minimal.
- Add tests for new behavior.
---

## 19. 完成标准

Codex 执行完成后，项目必须满足：

```text
1. pip install -e . 成功
2. codeflow --help 可用
3. codeflow run 能接收 repo/task/checks 参数
4. 能检查 Git 仓库和干净工作区
5. 能创建 ai/* 分支
6. 能生成 Spec
7. 能调用 mini-swe-agent
8. 能运行 pytest / ruff checks
9. 失败后能最多修复 3 轮
10. 能生成 Diff Review Report
11. 能人工选择 commit / rollback / keep
12. benchmark/run_benchmark.py 能跑多个任务并输出 results.json
~~~

------

## 20. 给 Codex 的最终执行指令

可以直接使用下面这段作为 Codex 任务：

```text
请在当前仓库中实现 CodeFlow Agent。

目标：
基于 mini-swe-agent v2 实现一个 Python 项目的可信 AI 编程工作流 wrapper。不要从零写 coding agent，只调用 mini-swe-agent 作为执行引擎；外层实现 Git Guard、Spec Builder、Prompt Builder、Test Gate、Repair Loop、Diff Reviewer、Human Approval 和 Benchmark。

请按以下结构创建文件：
- codeflow/cli.py
- codeflow/runner.py
- codeflow/config.py
- codeflow/models.py
- codeflow/mini_runner.py
- codeflow/spec_builder.py
- codeflow/prompt_builder.py
- codeflow/git_guard.py
- codeflow/test_gate.py
- codeflow/diff_reviewer.py
- codeflow/report_writer.py
- codeflow/utils.py
- examples/todo_api/
- benchmark/tasks.yaml
- benchmark/run_benchmark.py
- pyproject.toml
- README.md

功能要求：
1. 提供 CLI 命令：
   codeflow run --repo <repo> --task <task> --checks "pytest -q" --max-repair-rounds 3 --no-commit

2. Git Guard：
   - 检查目标 repo 是 Git 仓库
   - 检查工作区干净
   - 创建 ai/{task_slug}-{timestamp} 分支
   - 支持 git diff
   - 支持 commit
   - 支持 rollback

3. Spec Builder：
   - 把 task 转成结构化 Spec
   - 包含 goal、acceptance_criteria、constraints

4. Project Rules：
   - 读取目标 repo 下 .codeflow/project_rules.md
   - 如果不存在，使用默认规则

5. Prompt Builder：
   - 生成传给 mini-swe-agent 的 initial prompt
   - 生成 repair prompt
   - prompt 中必须包含 task、spec、project rules、required checks

6. mini_runner：
   - 使用 subprocess 调用 mini-swe-agent CLI
   - 在目标 repo cwd 下运行
   - 保存 stdout/stderr 到日志文件
   - 如果当前 mini CLI 参数和方案不一致，请根据本地 mini --help 调整调用方式

7. Test Gate：
   - 运行用户传入的 checks
   - 默认 pytest -q
   - 保存 stdout/stderr
   - 返回结构化 CheckResult

8. Repair Loop：
   - 初次调用 mini-swe-agent 后运行 checks
   - 如果失败，将失败日志构造成 repair prompt，再调用 mini-swe-agent
   - 最多 max_repair_rounds 轮
   - 成功则停止
   - 失败则生成失败报告，不允许 commit

9. Diff Reviewer：
   - 读取 git diff
   - 生成 Markdown Review Report
   - 包含 task、branch、validation result、risk level、risk notes、diff size、recommendation
   - 风险评分先用规则实现：auth、permission、migration、.env、secret、password、token、delete、drop 为 high；api、schema、model、database、config 为 medium；否则 low

10. Human Approval：
   - checks 通过后，询问 commit / rollback / keep
   - commit 前必须保证 checks 全部通过
   - rollback 执行 git restore .
   - keep 保留当前分支和修改

11. 示例项目：
   - 在 examples/todo_api 中创建一个最小 Python 项目
   - 包含 app/todo.py 和 tests/test_todo.py
   - pytest 能通过

12. Benchmark：
   - benchmark/tasks.yaml 包含至少 3 个 todo_api 任务
   - benchmark/run_benchmark.py 能逐个调用 CodeFlow
   - 输出 benchmark/results.json

13. README：
   - 写清楚安装方式、使用方式、项目规则、功能列表

验收命令：
- pip install -e .
- codeflow --help
- cd examples/todo_api && git init && git add . && git commit -m init
- cd ../..
- codeflow run --repo ./examples/todo_api --task "给 Todo 增加 priority 字段，默认值为 medium，并补充测试" --checks "pytest -q" --no-commit

注意：
- 不要实现复杂 Web 前端
- 不要重写 mini-swe-agent
- 不要引入 LangGraph
- 不要引入数据库
- 优先保证 CLI 闭环跑通
```

