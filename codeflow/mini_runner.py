from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values

from codeflow.models import MiniRunResult


OPENAI_COMPAT_ENV_KEYS = {
    "api_key": "OPENAI_API_KEY",
    "base_url": "OPENAI_BASE_URL",
}


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


def _command_for_log(cmd: list[str], prompt_path: Path) -> str:
    rendered: list[str] = []
    skip_next = False
    for item in cmd:
        if skip_next:
            rendered.append(f"@{prompt_path}")
            skip_next = False
            continue
        rendered.append(item)
        if item in {"--task", "-t"}:
            skip_next = True
    return shlex.join(rendered)


def run_mini_agent(
    repo: str,
    prompt: str,
    *,
    run_dir: Path | None = None,
    run_index: int | None = None,
    model: str | None = None,
    mini_config: str | None = None,
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
    cmd.extend(["--task", prompt, "--yolo", "--exit-immediately", "--output", str(trajectory_path)])
    if effective_model:
        cmd.extend(["--model", effective_model])
    if mini_config:
        cmd.extend(["--config", mini_config])
    env = _mini_env(command_env, env_values, effective_model)

    try:
        result = subprocess.run(
            cmd,
            cwd=repo,
            text=True,
            capture_output=True,
            env=env,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "mini-swe-agent CLI was not found. Install it or set CODEFLOW_MINI_COMMAND."
        ) from exc
    finally:
        prompt_path.unlink(missing_ok=True)

    log_path.write_text(
        "\n".join(
            [
                f"COMMAND: {_command_for_log(cmd, prompt_path)}",
                f"PROMPT_FILE: {prompt_path}",
                f"TRAJECTORY: {trajectory_path}",
                "",
                "PROMPT:",
                prompt,
                "",
                "STDOUT:",
                result.stdout,
                "",
                "STDERR:",
                result.stderr,
            ]
        ),
        encoding="utf-8",
    )

    if result.returncode != 0:
        raise RuntimeError(f"mini-swe-agent failed. See {log_path}")

    return MiniRunResult(
        log_path=str(log_path),
        trajectory_path=str(trajectory_path),
        returncode=result.returncode,
    )
