from __future__ import annotations

import importlib.util
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from dotenv import dotenv_values

from codeflow.harness.policy import load_harness_policy


def _result(name: str, ok: bool, message: str = "", suggestion: str = "") -> dict[str, object]:
    return {
        "name": name,
        "ok": ok,
        "message": message,
        "suggestion": suggestion,
    }


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)


def _command_exists(command: str) -> bool:
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    return bool(parts and shutil.which(parts[0]))


def _mini_available() -> tuple[bool, str, str]:
    configured = os.environ.get("CODEFLOW_MINI_COMMAND")
    if configured:
        try:
            parts = shlex.split(configured)
        except ValueError as exc:
            return False, str(exc), "Fix CODEFLOW_MINI_COMMAND."
        if parts and shutil.which(parts[0]):
            return True, f"CODEFLOW_MINI_COMMAND={configured}", ""
        return False, f"Command not found: {configured}", "Install mini-swe-agent or fix CODEFLOW_MINI_COMMAND."
    if shutil.which("mini"):
        return True, "mini found on PATH", ""
    if importlib.util.find_spec("minisweagent.run.mini") is not None:
        return True, "local minisweagent package is importable", ""
    return False, "mini command not found", "Run `pip install -e .` or set CODEFLOW_MINI_COMMAND."


def _llm_env_ok(repo: Path) -> tuple[bool, str, str]:
    env_file = Path(os.environ.get("CODEFLOW_ENV_FILE", repo / ".env")).expanduser()
    values = dotenv_values(env_file) if env_file.exists() else {}
    model = os.environ.get("MSWEA_MODEL_NAME") or values.get("model_id") or values.get("MODEL_ID")
    api_key = os.environ.get("OPENAI_API_KEY") or values.get("api_key") or values.get("API_KEY")
    base_url = (
        os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("OPENAI_API_BASE")
        or values.get("base_url")
        or values.get("BASE_URL")
    )
    missing = [
        name
        for name, value in (
            ("model", model),
            ("api_key", api_key),
            ("base_url", base_url),
        )
        if not value
    ]
    if missing:
        return (
            False,
            f"Missing LLM setting(s): {', '.join(missing)}",
            "Set .env keys model_id/api_key/base_url or standard OpenAI-compatible env vars.",
        )
    return True, f"LLM environment configured via {env_file if env_file.exists() else 'process env'}", ""


def run_doctor(repo: str, *, skip_checks: bool = False, skip_llm: bool = False) -> list[dict[str, object]]:
    root = Path(repo).expanduser().resolve()
    results: list[dict[str, object]] = []

    git = _run(["git", "rev-parse", "--is-inside-work-tree"], root)
    git_ok = git.returncode == 0 and git.stdout.strip() == "true"
    results.append(
        _result(
            "Git repository",
            git_ok,
            "OK" if git_ok else (git.stderr.strip() or "Not a Git repository"),
            "Run `git init` in the target project." if not git_ok else "",
        )
    )

    status = _run(["git", "status", "--porcelain"], root) if git_ok else None
    clean_ok = bool(status and status.returncode == 0 and not status.stdout.strip())
    results.append(
        _result(
            "Clean worktree",
            clean_ok,
            "OK" if clean_ok else "Git worktree has uncommitted changes.",
            "Commit or stash changes before running CodeFlow." if not clean_ok else "",
        )
    )

    policy_path = root / ".codeflow" / "codeflow.yaml"
    rules_path = root / ".codeflow" / "project_rules.md"
    results.append(
        _result(
            "Policy file",
            policy_path.exists(),
            str(policy_path) if policy_path.exists() else "Missing .codeflow/codeflow.yaml",
            "Run `codeflow init --repo <repo>`." if not policy_path.exists() else "",
        )
    )
    results.append(
        _result(
            "Project rules",
            rules_path.exists(),
            str(rules_path) if rules_path.exists() else "Missing .codeflow/project_rules.md",
            "Run `codeflow init --repo <repo>`." if not rules_path.exists() else "",
        )
    )

    try:
        policy = load_harness_policy(str(root))
        results.append(_result("Policy parse", True, "OK"))
    except Exception as exc:
        policy = None
        results.append(_result("Policy parse", False, str(exc), "Fix .codeflow/codeflow.yaml."))

    for tool in ("pytest", "ruff"):
        ok = shutil.which(tool) is not None
        results.append(
            _result(
                tool,
                ok,
                "found on PATH" if ok else f"{tool} not found",
                f"Install {tool} or remove it from required checks." if not ok else "",
            )
        )

    if policy:
        for command in policy.required_checks:
            exists = _command_exists(command)
            ok = exists
            message = "command found"
            suggestion = ""
            if not exists:
                message = "command executable not found"
                suggestion = "Install the command or update required_checks."
            elif not skip_checks:
                check = subprocess.run(command, cwd=root, shell=True, text=True, capture_output=True)
                ok = check.returncode == 0
                message = "OK" if ok else (check.stderr.strip() or check.stdout.strip() or "check failed")
                suggestion = "Fix project checks before running CodeFlow." if not ok else ""
            results.append(_result(f"Required check: {command}", ok, message, suggestion))

    mini_ok, mini_message, mini_suggestion = _mini_available()
    results.append(_result("mini CLI", mini_ok, mini_message, mini_suggestion))

    if not skip_llm:
        llm_ok, llm_message, llm_suggestion = _llm_env_ok(root)
        results.append(_result("LLM environment", llm_ok, llm_message, llm_suggestion))

    return results
