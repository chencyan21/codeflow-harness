from __future__ import annotations

from pydantic import BaseModel, Field

from codeflow.config import DEFAULT_CHECKS, DEFAULT_MAX_REPAIR_ROUNDS, MAX_REPAIR_ROUNDS


class CodeFlowConfig(BaseModel):
    repo: str
    task: str
    checks: list[str] = Field(default_factory=lambda: DEFAULT_CHECKS.copy())
    max_repair_rounds: int = Field(default=DEFAULT_MAX_REPAIR_ROUNDS, ge=0, le=MAX_REPAIR_ROUNDS)
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
    commit_action: str = "pending"
