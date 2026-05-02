from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from dotenv import dotenv_values

from codeflow.models import MiniRunResult
from codeflow.redaction import redact_file_in_place, redact_text


OPENAI_COMPAT_ENV_KEYS = {
    "api_key": "OPENAI_API_KEY",
    "base_url": "OPENAI_BASE_URL",
}
DEFAULT_MINI_TIMEOUT_SECONDS = 3600.0


class ExecutorHook(Protocol):
    def before_command(self, command: str) -> None:
        ...

    def after_command(self, command: str, result: object) -> None:
        ...

    def before_file_write(self, path: str) -> None:
        ...


class MiniExecutionError(RuntimeError):
    def __init__(self, message: str, *, error_type: str) -> None:
        super().__init__(message)
        self.error_type = error_type


class SubprocessMiniExecutor:
    def run(
        self,
        cmd: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]:
        return _run_mini_subprocess(cmd, cwd=cwd, env=env, timeout_seconds=timeout_seconds)


def _nonempty(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _provider_model_name(model_id: str) -> str:
    if "/" in model_id or model_id.startswith("@"):
        return model_id
    return f"openai/{model_id}"


def _load_codeflow_env() -> dict[str, str]:
    env_file = os.environ.get("CODEFLOW_ENV_FILE")
    path = Path(env_file).expanduser() if env_file else Path.cwd() / ".env"
    if not path.exists():
        return {}
    return {key: value for key, value in dotenv_values(path).items() if value is not None}


def _resolve_model(model: str | None, env_values: dict[str, str]) -> str | None:
    if model:
        return model
    if os.environ.get("MSWEA_MODEL_NAME"):
        return None
    model_id = _nonempty(env_values.get("model_id") or env_values.get("MODEL_ID"))
    if model_id:
        return _provider_model_name(model_id)
    return None


def _mini_env(command_env: dict[str, str] | None, env_values: dict[str, str], model: str | None) -> dict[str, str]:
    env = os.environ.copy()
    if command_env:
        env.update(command_env)

    # CodeFlow runs mini non-interactively. Skipping the first-run wizard makes missing
    # model/API settings fail as actionable model errors instead of prompt aborts.
    env.setdefault("MSWEA_CONFIGURED", "true")

    if model:
        env.setdefault("MSWEA_MODEL_NAME", model)

    api_key = _nonempty(env_values.get("api_key") or env_values.get("API_KEY"))
    if api_key:
        env.setdefault(OPENAI_COMPAT_ENV_KEYS["api_key"], api_key)

    base_url = _nonempty(env_values.get("base_url") or env_values.get("BASE_URL"))
    if base_url:
        env.setdefault(OPENAI_COMPAT_ENV_KEYS["base_url"], base_url)
        env.setdefault("OPENAI_API_BASE", base_url)
        env.setdefault("MSWEA_COST_TRACKING", "ignore_errors")

    return env


def _artifact_dir(repo: str) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=repo,
        text=True,
        capture_output=True,
    )
    if result.returncode == 0:
        git_dir = Path(result.stdout.strip())
        if not git_dir.is_absolute():
            git_dir = Path(repo) / git_dir
        path = git_dir / "codeflow"
    else:
        path = Path(repo) / ".codeflow" / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _mini_command() -> tuple[list[str], dict[str, str] | None]:
    configured = os.environ.get("CODEFLOW_MINI_COMMAND")
    if configured:
        return shlex.split(configured), None

    if shutil.which("mini"):
        return ["mini"], None

    return [sys.executable, "-m", "minisweagent.run.mini"], None


def _mini_timeout_seconds() -> float:
    raw = os.environ.get("CODEFLOW_MINI_TIMEOUT_SECONDS")
    if raw is None:
        return DEFAULT_MINI_TIMEOUT_SECONDS
    try:
        timeout = float(raw)
    except ValueError as exc:
        raise RuntimeError("CODEFLOW_MINI_TIMEOUT_SECONDS must be a positive number.") from exc
    if timeout <= 0:
        raise RuntimeError("CODEFLOW_MINI_TIMEOUT_SECONDS must be a positive number.")
    return timeout


def _command_for_log(cmd: list[str], prompt_path: Path) -> str:
    rendered: list[str] = []
    skip_next = False
    for item in cmd:
        if skip_next:
            rendered.append(f"@{prompt_path}")
            skip_next = False
            continue
        rendered.append(item)
        if item in {"--task", "-t", "--task-file"}:
            skip_next = True
    return shlex.join(rendered)


def _write_mini_log(
    *,
    log_path: Path,
    cmd: list[str],
    prompt_path: Path,
    trajectory_path: Path,
    prompt: str,
    stdout: object,
    stderr: object,
    timeout_seconds: float | None = None,
    error_type: str | None = None,
) -> None:
    header = [
        f"COMMAND: {_command_for_log(cmd, prompt_path)}",
        f"PROMPT_FILE: {prompt_path}",
        f"TRAJECTORY: {trajectory_path}",
    ]
    if timeout_seconds is not None:
        header.append(f"TIMEOUT_SECONDS: {timeout_seconds:g}")
    if error_type:
        header.append(f"ERROR_TYPE: {error_type}")
    log_path.write_text(
        "\n".join(
            [
                *header,
                "",
                "PROMPT:",
                redact_text(prompt),
                "",
                "STDOUT:",
                redact_text(stdout),
                "",
                "STDERR:",
                redact_text(stderr),
            ]
        ),
        encoding="utf-8",
    )


def _run_mini_subprocess(
    cmd: list[str],
    *,
    cwd: str,
    env: dict[str, str],
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(
            exc.cmd,
            exc.timeout,
            output=stdout,
            stderr=stderr,
        ) from exc
    return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)


def run_mini_agent(
    repo: str,
    prompt: str,
    *,
    run_dir: Path | None = None,
    run_index: int | None = None,
    model: str | None = None,
    mini_config: str | None = None,
    executor: SubprocessMiniExecutor | None = None,
) -> MiniRunResult:
    run_id = str(uuid4())[:8]
    artifacts = run_dir or _artifact_dir(repo)
    artifacts.mkdir(parents=True, exist_ok=True)
    suffix = str(run_index) if run_index is not None else run_id
    prompt_path = artifacts / f"prompt_{suffix}.txt"
    log_path = artifacts / f"mini_run_{suffix}.log"
    trajectory_path = artifacts / f"mini_run_{suffix}.trajectory.json"
    prompt_path.write_text(prompt, encoding="utf-8")

    env_values = _load_codeflow_env()
    effective_model = _resolve_model(model, env_values)

    cmd, command_env = _mini_command()
    cmd.extend(["--task-file", str(prompt_path), "--yolo", "--exit-immediately", "--output", str(trajectory_path)])
    if effective_model:
        cmd.extend(["--model", effective_model])
    if mini_config:
        cmd.extend(["--config", mini_config])
    env = _mini_env(command_env, env_values, effective_model)
    try:
        timeout_seconds = _mini_timeout_seconds()
    except RuntimeError as exc:
        raise MiniExecutionError(str(exc), error_type="invalid_timeout") from exc
    executor = executor or SubprocessMiniExecutor()

    try:
        result = executor.run(
            cmd,
            cwd=repo,
            env=env,
            timeout_seconds=timeout_seconds,
        )
    except FileNotFoundError as exc:
        redact_file_in_place(prompt_path)
        _write_mini_log(
            log_path=log_path,
            cmd=cmd,
            prompt_path=prompt_path,
            trajectory_path=trajectory_path,
            prompt=prompt,
            stdout="",
            stderr=str(exc),
            error_type="command_not_found",
        )
        raise MiniExecutionError(
            "mini-swe-agent CLI was not found. Install it or set CODEFLOW_MINI_COMMAND.",
            error_type="command_not_found",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        redact_file_in_place(prompt_path)
        redact_file_in_place(trajectory_path)
        _write_mini_log(
            log_path=log_path,
            cmd=cmd,
            prompt_path=prompt_path,
            trajectory_path=trajectory_path,
            prompt=prompt,
            stdout=exc.stdout,
            stderr=exc.stderr,
            timeout_seconds=timeout_seconds,
            error_type="timeout",
        )
        raise MiniExecutionError(
            f"mini-swe-agent timed out after {timeout_seconds:g}s. See {log_path}",
            error_type="timeout",
        ) from exc

    redact_file_in_place(prompt_path)
    redact_file_in_place(trajectory_path)
    _write_mini_log(
        log_path=log_path,
        cmd=cmd,
        prompt_path=prompt_path,
        trajectory_path=trajectory_path,
        prompt=prompt,
        stdout=result.stdout,
        stderr=result.stderr,
        error_type="nonzero_exit" if result.returncode != 0 else None,
    )

    if result.returncode != 0:
        raise MiniExecutionError(
            f"mini-swe-agent failed with nonzero_exit. See {log_path}",
            error_type="nonzero_exit",
        )

    status = "completed" if trajectory_path.exists() else "trajectory_missing"
    error_type = None if trajectory_path.exists() else "trajectory_missing"

    return MiniRunResult(
        log_path=str(log_path),
        trajectory_path=str(trajectory_path),
        returncode=result.returncode,
        status=status,
        error_type=error_type,
    )
