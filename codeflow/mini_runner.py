from __future__ import annotations

import contextlib
import fnmatch
import importlib
import io
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Iterator, Protocol
from uuid import uuid4

from dotenv import dotenv_values

from codeflow.models import HarnessPolicy, MiniEvent, MiniRunRequest, MiniRunResult
from codeflow.redaction import redact_file_in_place, redact_text
from codeflow.test_gate import scan_shell_check_risk


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

    def after_file_write(self, path: str) -> None:
        ...

    def before_model_step(self, step: int) -> None:
        ...

    def after_model_step(self, step: int, result: object) -> None:
        ...


class MiniExecutor(Protocol):
    def run(
        self,
        request: MiniRunRequest,
        *,
        hook: ExecutorHook | None = None,
    ) -> subprocess.CompletedProcess[str]:
        ...


class MiniExecutionError(RuntimeError):
    def __init__(self, message: str, *, error_type: str) -> None:
        super().__init__(message)
        self.error_type = error_type


class JsonlExecutorHook:
    def __init__(self, path: Path, *, forbidden_paths: list[str] | None = None) -> None:
        self.path = path
        self.forbidden_paths = forbidden_paths or []
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def before_command(self, command: str) -> None:
        risks = _scan_realtime_command_risk(command)
        if risks:
            message = f"Blocked high-risk mini command: {', '.join(risks)}"
            self._write(
                "before_command",
                {
                    "command": command,
                    "risk_level": "high",
                    "blocked": True,
                    "message": message,
                    "details": {"risks": risks},
                },
            )
            raise MiniExecutionError(message, error_type="policy_blocked")
        self._write("before_command", {"command": command})

    def after_command(self, command: str, result: object) -> None:
        self._write(
            "after_command",
            {
                "command": command,
                "returncode": getattr(result, "returncode", None),
            },
        )

    def before_file_write(self, path: str) -> None:
        matches = _forbidden_path_matches(path, self.forbidden_paths)
        if matches:
            message = f"Blocked mini write to forbidden path: {path}"
            self._write(
                "before_file_write",
                {
                    "path": path,
                    "risk_level": "high",
                    "blocked": True,
                    "message": message,
                    "details": {"matched_patterns": matches},
                },
            )
            raise MiniExecutionError(message, error_type="policy_blocked")
        self._write("before_file_write", {"path": path})

    def after_file_write(self, path: str) -> None:
        self._write("after_file_write", {"path": path})

    def before_model_step(self, step: int) -> None:
        self._write("before_model_step", {"step": step})

    def after_model_step(self, step: int, result: object) -> None:
        details: dict[str, object] = {}
        if isinstance(result, dict):
            details["role"] = str(result.get("role", result.get("object", "")))
            actions = result.get("extra", {}).get("actions", [])
            if isinstance(actions, list):
                details["actions_count"] = len(actions)
        self._write("after_model_step", {"step": step, "details": details})

    def _write(self, event_type: str, payload: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        event = MiniEvent.model_validate({"event": event_type, "ts": time.time(), **payload})
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.model_dump(exclude_none=True), ensure_ascii=False) + "\n")


class SubprocessMiniExecutor:
    def run(
        self,
        request: MiniRunRequest,
        *,
        hook: ExecutorHook | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = _command_for_log(request.command, Path(request.prompt_path))
        if hook:
            hook.before_command(command)
        result = _run_mini_subprocess(
            request.command,
            cwd=request.repo,
            env=request.env,
            timeout_seconds=request.timeout_seconds,
        )
        if hook:
            hook.after_command(command, result)
        return result


class InProcessMiniExecutor:
    def run(
        self,
        request: MiniRunRequest,
        *,
        hook: ExecutorHook | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = _command_for_log(request.command, Path(request.prompt_path))
        stdout = io.StringIO()
        stderr = io.StringIO()
        if hook:
            hook.before_command(command)
        try:
            with (
                _temporary_cwd(request.repo),
                _temporary_environ(request.env),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
                _inprocess_timeout(request.timeout_seconds, request.command),
            ):
                run_module = importlib.import_module("minisweagent.run.mini")
                run_mini_in_process: Any = getattr(run_module, "run_mini_in_process")
                run_mini_in_process(
                    model_name=request.model,
                    task_file=Path(request.prompt_path),
                    yolo=True,
                    config_spec=[request.mini_config] if request.mini_config else None,
                    output=Path(request.trajectory_path),
                    exit_immediately=True,
                    executor_hook=hook,
                )
            result = subprocess.CompletedProcess(
                request.command,
                0,
                stdout.getvalue(),
                stderr.getvalue(),
            )
        except subprocess.TimeoutExpired:
            raise subprocess.TimeoutExpired(
                request.command,
                request.timeout_seconds,
                output=stdout.getvalue(),
                stderr=stderr.getvalue(),
            )
        except MiniExecutionError:
            raise
        except Exception:
            stderr.write(traceback.format_exc())
            result = subprocess.CompletedProcess(
                request.command,
                1,
                stdout.getvalue(),
                stderr.getvalue(),
            )
        if hook:
            hook.after_command(command, result)
        return result


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
        return _provider_model_name(model)
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


@contextlib.contextmanager
def _temporary_cwd(path: str) -> Iterator[None]:
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


@contextlib.contextmanager
def _temporary_environ(env: dict[str, str]) -> Iterator[None]:
    previous = os.environ.copy()
    os.environ.clear()
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


@contextlib.contextmanager
def _inprocess_timeout(timeout_seconds: float, command: list[str]) -> Iterator[None]:
    if (
        os.name == "nt"
        or not hasattr(signal, "setitimer")
        or threading.current_thread() is not threading.main_thread()
    ):
        yield
        return
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)

    def _raise_timeout(_signum: int, _frame: object) -> None:
        raise subprocess.TimeoutExpired(command, timeout_seconds)

    signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])


def _selected_executor() -> MiniExecutor:
    name = os.environ.get("CODEFLOW_MINI_EXECUTOR", "subprocess").strip().lower()
    if name in {"", "subprocess"}:
        return SubprocessMiniExecutor()
    if name in {"inprocess", "in-process", "python"}:
        return InProcessMiniExecutor()
    raise MiniExecutionError(
        "CODEFLOW_MINI_EXECUTOR must be either 'subprocess' or 'inprocess'.",
        error_type="invalid_executor",
    )


def _scan_realtime_command_risk(command: str) -> list[str]:
    return scan_shell_check_risk(f"shell: {command}")


def _forbidden_path_matches(path: str, patterns: list[str]) -> list[str]:
    return sorted({pattern for pattern in patterns if _path_matches_pattern(path, pattern)})


def _path_matches_pattern(path: str, pattern: str) -> bool:
    normalized_path = path.replace("\\", "/").strip("/")
    normalized_pattern = pattern.replace("\\", "/").strip("/")
    if not normalized_path or not normalized_pattern:
        return False
    name = Path(normalized_path).name
    if pattern.endswith("/"):
        prefix = normalized_pattern.rstrip("/")
        return (
            normalized_path == prefix
            or normalized_path.startswith(f"{prefix}/")
            or f"/{prefix}/" in f"/{normalized_path}/"
            or normalized_path.endswith(f"/{prefix}")
        )
    return (
        normalized_path == normalized_pattern
        or normalized_path.endswith(f"/{normalized_pattern}")
        or fnmatch.fnmatch(normalized_path, normalized_pattern)
        or fnmatch.fnmatch(name, normalized_pattern)
    )


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
    policy: HarnessPolicy | None = None,
    executor: MiniExecutor | None = None,
) -> MiniRunResult:
    run_id = str(uuid4())[:8]
    artifacts = run_dir or _artifact_dir(repo)
    artifacts.mkdir(parents=True, exist_ok=True)
    suffix = str(run_index) if run_index is not None else run_id
    prompt_path = artifacts / f"prompt_{suffix}.txt"
    log_path = artifacts / f"mini_run_{suffix}.log"
    trajectory_path = artifacts / f"mini_run_{suffix}.trajectory.json"
    events_path = artifacts / f"mini_run_{suffix}.events.jsonl"
    effective_policy = policy or HarnessPolicy()
    hook = JsonlExecutorHook(events_path, forbidden_paths=effective_policy.forbidden_paths)
    hook.before_file_write(str(prompt_path))
    prompt_path.write_text(prompt, encoding="utf-8")
    hook.after_file_write(str(prompt_path))

    env_values = _load_codeflow_env()
    effective_model = _resolve_model(model, env_values)

    try:
        timeout_seconds = _mini_timeout_seconds()
    except RuntimeError as exc:
        raise MiniExecutionError(str(exc), error_type="invalid_timeout") from exc
    executor = executor or _selected_executor()
    if isinstance(executor, InProcessMiniExecutor):
        cmd = ["inprocess-mini"]
        command_env = None
    else:
        cmd, command_env = _mini_command()
    cmd.extend(["--task-file", str(prompt_path), "--yolo", "--exit-immediately", "--output", str(trajectory_path)])
    if effective_model:
        cmd.extend(["--model", effective_model])
    if mini_config:
        cmd.extend(["--config", mini_config])
    env = _mini_env(command_env, env_values, effective_model)
    executor_name = executor.__class__.__name__
    request = MiniRunRequest(
        repo=repo,
        prompt=prompt,
        prompt_path=str(prompt_path),
        log_path=str(log_path),
        trajectory_path=str(trajectory_path),
        command=cmd,
        model=effective_model,
        mini_config=mini_config,
        env=env,
        timeout_seconds=timeout_seconds,
        executor_name=executor_name,
        events_path=str(events_path),
        forbidden_paths=effective_policy.forbidden_paths,
    )

    try:
        result = executor.run(request, hook=hook)
    except FileNotFoundError as exc:
        redact_file_in_place(prompt_path)
        hook.before_file_write(str(log_path))
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
        hook.after_file_write(str(log_path))
        raise MiniExecutionError(
            "mini-swe-agent CLI was not found. Install it or set CODEFLOW_MINI_COMMAND.",
            error_type="command_not_found",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        redact_file_in_place(prompt_path)
        redact_file_in_place(trajectory_path)
        hook.before_file_write(str(log_path))
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
        hook.after_file_write(str(log_path))
        raise MiniExecutionError(
            f"mini-swe-agent timed out after {timeout_seconds:g}s. See {log_path}",
            error_type="timeout",
        ) from exc
    except MiniExecutionError as exc:
        redact_file_in_place(prompt_path)
        redact_file_in_place(trajectory_path)
        hook.before_file_write(str(log_path))
        _write_mini_log(
            log_path=log_path,
            cmd=cmd,
            prompt_path=prompt_path,
            trajectory_path=trajectory_path,
            prompt=prompt,
            stdout="",
            stderr=str(exc),
            error_type=exc.error_type,
        )
        hook.after_file_write(str(log_path))
        raise

    redact_file_in_place(prompt_path)
    redact_file_in_place(trajectory_path)
    hook.before_file_write(str(log_path))
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
    hook.after_file_write(str(log_path))

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
        events_path=str(events_path),
    )
