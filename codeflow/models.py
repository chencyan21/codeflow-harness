from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from codeflow.config import DEFAULT_CHECKS, DEFAULT_MAX_REPAIR_ROUNDS, MAX_REPAIR_ROUNDS


class CodeFlowConfig(BaseModel):
    repo: str
    task: str
    checks: list[str] | None = None
    max_repair_rounds: int | None = Field(default=None, ge=0, le=MAX_REPAIR_ROUNDS)
    model: str | None = None
    mini_config: str | None = None
    no_commit: bool = False
    dry_run: bool = False
    allow_high_risk_commit: bool = False


class HarnessPolicy(BaseModel):
    required_checks: list[str] = Field(default_factory=lambda: DEFAULT_CHECKS.copy())
    max_repair_rounds: int = Field(default=DEFAULT_MAX_REPAIR_ROUNDS, ge=0, le=MAX_REPAIR_ROUNDS)
    max_diff_lines: int = 500
    allowed_paths: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(
        default_factory=lambda: [".env", ".env.*", "secrets/", "credentials/", "*.pem", "*.key"]
    )
    high_risk_paths: list[str] = Field(default_factory=list)
    require_test_change: bool = False
    allow_dependency_change: bool = True
    allow_delete_tests: bool = False
    allow_shell_checks: bool = False
    semantic_spec: bool = False
    semantic_review: bool = False
    require_semantic_review: bool = False
    semantic_timeout_seconds: float = Field(default=60, gt=0)
    semantic_max_diff_chars: int = Field(default=20000, gt=0)
    semantic_fail_open: bool = True
    semantic_required_for_paths: list[str] = Field(default_factory=list)
    block_commit_on_failed_checks: bool = True
    block_commit_on_high_risk: bool = False
    require_human_approval: bool = True
    rerun_checks_before_commit: bool = True


class Spec(BaseModel):
    task_type: str
    goal: str
    acceptance_criteria: list[str]
    constraints: list[str]
    semantic_notes: list[str] = Field(default_factory=list)


class CheckResult(BaseModel):
    command: str
    success: bool
    returncode: int
    stdout: str
    stderr: str


class ExecutorResult(BaseModel):
    log_path: str
    trajectory_path: str
    returncode: int
    status: str = "completed"
    error_type: str | None = None
    events_path: str | None = None


class MiniRunRequest(BaseModel):
    repo: str
    prompt: str
    prompt_path: str
    log_path: str
    trajectory_path: str
    command: list[str] = Field(default_factory=list)
    model: str | None = None
    mini_config: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(gt=0)
    executor_name: str = "subprocess"
    events_path: str | None = None


class MiniRunResult(ExecutorResult):
    pass


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


class SensorResult(BaseModel):
    name: str
    passed: bool
    severity: Literal["info", "low", "medium", "high"]
    message: str
    details: dict = Field(default_factory=dict)


class SensorContext(BaseModel):
    repo: str
    task: str
    diff: str
    changed_files: list[str]
    policy: HarnessPolicy
    check_results: list[CheckResult] = Field(default_factory=list)


class HarnessSensorReport(BaseModel):
    results: list[SensorResult] = Field(default_factory=list)
    overall_passed: bool = True
    max_severity: Literal["info", "low", "medium", "high"] = "info"
    blocking_reasons: list[str] = Field(default_factory=list)


class RunState(BaseModel):
    repo: str
    task: str
    branch: str
    run_id: str | None = None
    run_dir: str | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    spec: Spec | None = None
    policy: HarnessPolicy | None = None
    rules: str = ""
    mini_runs: list[str] = Field(default_factory=list)
    check_results: list[CheckResult] = Field(default_factory=list)
    sensor_report: HarnessSensorReport | None = None
    semantic_review: dict | None = None
    review_summary: ReviewSummary | None = None
    changed_files: list[str] = Field(default_factory=list)
    repair_history: list[dict[str, str | int]] = Field(default_factory=list)
    repair_round: int = 0
    diff: str = ""
    report: str = ""
    status: str = "initialized"
    commit_action: str = "pending"
