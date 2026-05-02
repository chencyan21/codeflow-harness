from __future__ import annotations

import importlib.util
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

from codeflow.harness.policy import load_harness_policy
from codeflow.test_gate import check_command_executable_exists, run_check, scan_shell_check_risk


def _result(
    name: str,
    ok: bool,
    message: str = "",
    suggestion: str = "",
    *,
    level: str | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "ok": ok,
        "level": level or ("ok" if ok else "error"),
        "message": message,
        "suggestion": suggestion,
    }


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)


def _python_command_target_error(parts: list[str]) -> str:
    if not parts:
        return "Empty command."
    executable = Path(parts[0]).name
    if executable not in {Path(sys.executable).name, "python", "python3"}:
        return ""
    args = parts[1:]
    index = 0
    while index < len(args) and args[index].startswith("-") and args[index] != "-m":
        index += 1
    if index >= len(args):
        return ""
    if args[index] == "-m":
        if index + 1 >= len(args):
            return "Python -m command is missing a module name."
        module = args[index + 1]
        if importlib.util.find_spec(module) is None:
            return f"Python module not found: {module}"
        return ""
    target = Path(args[index])
    if target.suffix == ".py" and not target.exists():
        return f"Python script not found: {target}"
    return ""


def _probe_mini_command(parts: list[str]) -> tuple[bool, str]:
    if not parts:
        return False, "Empty command."
    env = os.environ.copy()
    env.setdefault("MSWEA_SILENT_STARTUP", "1")
    try:
        result = subprocess.run(
            [*parts, "--help"],
            text=True,
            capture_output=True,
            timeout=10,
            env=env,
        )
    except FileNotFoundError:
        return False, f"Command executable not found: {parts[0]}"
    except subprocess.TimeoutExpired:
        return False, "Command probe timed out while running --help."
    except OSError as exc:
        return False, str(exc)
    if result.returncode == 0:
        return True, "command probe passed"
    output = (result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}")
    return False, output


def _mini_available() -> tuple[bool, str, str]:
    configured = os.environ.get("CODEFLOW_MINI_COMMAND")
    if configured:
        try:
            parts = shlex.split(configured)
        except ValueError as exc:
            return False, str(exc), "Fix CODEFLOW_MINI_COMMAND."
        target_error = _python_command_target_error(parts)
        if target_error:
            return False, target_error, "Fix CODEFLOW_MINI_COMMAND."
        if parts and (shutil.which(parts[0]) or Path(parts[0]).exists()):
            probe_ok, probe_message = _probe_mini_command(parts)
            if probe_ok:
                return True, f"CODEFLOW_MINI_COMMAND={configured}; {probe_message}", ""
            return False, probe_message, "Fix CODEFLOW_MINI_COMMAND so it can run with --help."
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
            exists = check_command_executable_exists(command, allow_shell=policy.allow_shell_checks)
            ok = exists
            message = "command found"
            suggestion = ""
            if not exists:
                if command.strip().startswith("shell:") and not policy.allow_shell_checks:
                    message = "shell check disabled by policy"
                    suggestion = "Set allow_shell_checks: true only for trusted shell checks."
                else:
                    message = "command executable not found"
                    suggestion = "Install the command or update required_checks."
            elif not skip_checks:
                check = run_check(str(root), command, allow_shell=policy.allow_shell_checks)
                ok = check.success
                message = "OK" if ok else (check.stderr.strip() or check.stdout.strip() or "check failed")
                suggestion = "Fix project checks before running CodeFlow." if not ok else ""
            results.append(_result(f"Required check: {command}", ok, message, suggestion))
            shell_risks = scan_shell_check_risk(command)
            if exists and shell_risks:
                results.append(
                    _result(
                        f"Shell check risk: {command}",
                        True,
                        f"Shell check contains high-risk pattern(s): {', '.join(shell_risks)}",
                        "Review the shell check and keep allow_shell_checks enabled only for trusted projects.",
                        level="warning",
                    )
                )

    mini_ok, mini_message, mini_suggestion = _mini_available()
    results.append(_result("mini CLI", mini_ok, mini_message, mini_suggestion))

    if not skip_llm:
        llm_ok, llm_message, llm_suggestion = _llm_env_ok(root)
        results.append(_result("LLM environment", llm_ok, llm_message, llm_suggestion))

    return results
