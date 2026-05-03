from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from codeflow.models import HarnessPolicy
from codeflow.mini_runner import MiniExecutionError, run_mini_agent
from minisweagent.run import mini as mini_module


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, text=True, capture_output=True, check=True)


def _capture_script(path: Path) -> Path:
    script = path / "capture_env.py"
    script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "import os",
                "import sys",
                "from pathlib import Path",
                "capture = {",
                "    'argv': sys.argv[1:],",
                "    'OPENAI_API_KEY': os.environ.get('OPENAI_API_KEY'),",
                "    'OPENAI_BASE_URL': os.environ.get('OPENAI_BASE_URL'),",
                "    'OPENAI_API_BASE': os.environ.get('OPENAI_API_BASE'),",
                "    'MSWEA_CONFIGURED': os.environ.get('MSWEA_CONFIGURED'),",
                "    'MSWEA_MODEL_NAME': os.environ.get('MSWEA_MODEL_NAME'),",
                "    'MSWEA_COST_TRACKING': os.environ.get('MSWEA_COST_TRACKING'),",
                "}",
                "Path(os.environ['CODEFLOW_CAPTURE_FILE']).write_text(json.dumps(capture), encoding='utf-8')",
            ]
        ),
        encoding="utf-8",
    )
    return script


def test_run_mini_agent_maps_codeflow_env_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    env_dir = tmp_path / "env"
    env_dir.mkdir()
    (env_dir / ".env").write_text(
        'model_id = "deepseek-v4-flash"\n'
        'api_key = "secret-key"\n'
        'base_url = "https://example.test/v1"\n',
        encoding="utf-8",
    )
    capture_file = tmp_path / "capture.json"
    script = _capture_script(tmp_path)

    monkeypatch.chdir(env_dir)
    monkeypatch.setenv("CODEFLOW_MINI_COMMAND", f"{sys.executable} {script}")
    monkeypatch.setenv("CODEFLOW_CAPTURE_FILE", str(capture_file))
    monkeypatch.delenv("MSWEA_MODEL_NAME", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.delenv("MSWEA_CONFIGURED", raising=False)
    monkeypatch.delenv("MSWEA_COST_TRACKING", raising=False)

    run_mini_agent(str(repo), "prompt")

    capture = json.loads(capture_file.read_text(encoding="utf-8"))
    assert capture["OPENAI_API_KEY"] == "secret-key"
    assert capture["OPENAI_BASE_URL"] == "https://example.test/v1"
    assert capture["OPENAI_API_BASE"] == "https://example.test/v1"
    assert capture["MSWEA_CONFIGURED"] == "true"
    assert capture["MSWEA_MODEL_NAME"] == "openai/deepseek-v4-flash"
    assert capture["MSWEA_COST_TRACKING"] == "ignore_errors"
    assert "--task" not in capture["argv"]
    task_file = Path(capture["argv"][capture["argv"].index("--task-file") + 1])
    assert task_file.read_text(encoding="utf-8") == "prompt"
    assert capture["argv"][capture["argv"].index("--model") + 1] == "openai/deepseek-v4-flash"


def test_explicit_model_overrides_env_model_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    env_file = tmp_path / "codeflow.env"
    env_file.write_text('model_id = "from-env"\napi_key = "secret-key"\n', encoding="utf-8")
    capture_file = tmp_path / "capture.json"
    script = _capture_script(tmp_path)

    monkeypatch.setenv("CODEFLOW_ENV_FILE", str(env_file))
    monkeypatch.setenv("CODEFLOW_MINI_COMMAND", f"{sys.executable} {script}")
    monkeypatch.setenv("CODEFLOW_CAPTURE_FILE", str(capture_file))
    monkeypatch.delenv("MSWEA_MODEL_NAME", raising=False)

    run_mini_agent(str(repo), "prompt", model="openai/explicit-model")

    capture = json.loads(capture_file.read_text(encoding="utf-8"))
    assert capture["MSWEA_MODEL_NAME"] == "openai/explicit-model"
    assert capture["argv"][capture["argv"].index("--model") + 1] == "openai/explicit-model"


def test_existing_openai_env_values_are_preserved(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    env_file = tmp_path / "codeflow.env"
    env_file.write_text('api_key = "file-key"\nbase_url = "https://file.test/v1"\n', encoding="utf-8")
    capture_file = tmp_path / "capture.json"
    script = _capture_script(tmp_path)

    monkeypatch.setenv("CODEFLOW_ENV_FILE", str(env_file))
    monkeypatch.setenv("CODEFLOW_MINI_COMMAND", f"{sys.executable} {script}")
    monkeypatch.setenv("CODEFLOW_CAPTURE_FILE", str(capture_file))
    monkeypatch.setenv("OPENAI_API_KEY", "existing-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://existing.test/v1")

    run_mini_agent(str(repo), "prompt", model="openai/model")

    capture = json.loads(capture_file.read_text(encoding="utf-8"))
    assert capture["OPENAI_API_KEY"] == "existing-key"
    assert capture["OPENAI_BASE_URL"] == "https://existing.test/v1"
    assert capture["OPENAI_API_BASE"] == "https://file.test/v1"


def test_run_mini_agent_times_out_and_writes_log(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    script = tmp_path / "sleep_mini.py"
    script.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")

    monkeypatch.setenv("CODEFLOW_MINI_COMMAND", f"{sys.executable} {script}")
    monkeypatch.setenv("CODEFLOW_MINI_TIMEOUT_SECONDS", "0.1")

    with pytest.raises(MiniExecutionError, match="mini-swe-agent timed out") as exc_info:
        run_mini_agent(str(repo), "prompt")

    assert exc_info.value.error_type == "timeout"
    logs = list((repo / ".git" / "codeflow").glob("mini_run_*.log"))
    assert len(logs) == 1
    log_text = logs[0].read_text(encoding="utf-8")
    assert "TIMEOUT_SECONDS: 0.1" in log_text
    assert "ERROR_TYPE: timeout" in log_text
    assert "PROMPT:" in log_text


def test_run_mini_agent_redacts_prompt_and_logs(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    script = tmp_path / "echo_secret.py"
    script.write_text("print('api_key=sk-output123456789')\n", encoding="utf-8")

    monkeypatch.setenv("CODEFLOW_MINI_COMMAND", f"{sys.executable} {script}")

    run_mini_agent(str(repo), "api_key=sk-prompt123456789")

    artifact_dir = repo / ".git" / "codeflow"
    log_text = next(artifact_dir.glob("mini_run_*.log")).read_text(encoding="utf-8")
    prompt_text = next(artifact_dir.glob("prompt_*.txt")).read_text(encoding="utf-8")
    assert "sk-prompt" not in log_text
    assert "sk-output" not in log_text
    assert "sk-prompt" not in prompt_text
    assert "[REDACTED]" in log_text


def test_run_mini_agent_classifies_nonzero_exit(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    script = tmp_path / "fail_mini.py"
    script.write_text("import sys\nprint('bad', file=sys.stderr)\nraise SystemExit(7)\n", encoding="utf-8")

    monkeypatch.setenv("CODEFLOW_MINI_COMMAND", f"{sys.executable} {script}")

    with pytest.raises(MiniExecutionError) as exc_info:
        run_mini_agent(str(repo), "prompt")

    assert exc_info.value.error_type == "nonzero_exit"
    log_text = next((repo / ".git" / "codeflow").glob("mini_run_*.log")).read_text(encoding="utf-8")
    assert "ERROR_TYPE: nonzero_exit" in log_text


def test_run_mini_agent_reports_missing_trajectory_status(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    script = tmp_path / "ok_no_trajectory.py"
    script.write_text("print('ok')\n", encoding="utf-8")

    monkeypatch.setenv("CODEFLOW_MINI_COMMAND", f"{sys.executable} {script}")

    result = run_mini_agent(str(repo), "prompt")

    assert result.status == "trajectory_missing"
    assert result.error_type == "trajectory_missing"


def test_run_mini_agent_writes_executor_events(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    script = tmp_path / "ok.py"
    script.write_text("print('ok')\n", encoding="utf-8")

    monkeypatch.setenv("CODEFLOW_MINI_COMMAND", f"{sys.executable} {script}")

    result = run_mini_agent(str(repo), "prompt")

    assert result.events_path is not None
    events = [
        json.loads(line)
        for line in Path(result.events_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [event["event"] for event in events] == [
        "before_file_write",
        "after_file_write",
        "before_command",
        "after_command",
        "before_file_write",
        "after_file_write",
    ]
    assert events[3]["returncode"] == 0


def test_run_mini_agent_can_use_inprocess_executor(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    calls: dict[str, object] = {}

    def fake_run_mini_in_process(**kwargs: object) -> object:
        task_file = Path(str(kwargs["task_file"]))
        calls["task"] = task_file.read_text(encoding="utf-8")
        calls["model_name"] = kwargs["model_name"]
        calls["config_spec"] = kwargs["config_spec"]
        calls["yolo"] = kwargs["yolo"]
        output = Path(str(kwargs["output"]))
        output.write_text("{}", encoding="utf-8")
        return object()

    monkeypatch.setattr(mini_module, "run_mini_in_process", fake_run_mini_in_process)
    monkeypatch.setenv("CODEFLOW_MINI_EXECUTOR", "inprocess")

    result = run_mini_agent(
        str(repo),
        "prompt",
        model="openai/test-model",
        mini_config="mini.yaml",
    )

    assert result.status == "completed"
    assert calls == {
        "task": "prompt",
        "model_name": "openai/test-model",
        "config_spec": ["mini.yaml"],
        "yolo": True,
    }
    assert result.events_path is not None
    assert Path(result.events_path).exists()


def test_invalid_executor_name_is_clear(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    monkeypatch.setenv("CODEFLOW_MINI_EXECUTOR", "unknown")

    with pytest.raises(MiniExecutionError) as exc_info:
        run_mini_agent(str(repo), "prompt")

    assert exc_info.value.error_type == "invalid_executor"


def test_inprocess_executor_blocks_high_risk_internal_command(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    def fake_run_mini_in_process(**kwargs: object) -> object:
        hook = kwargs["executor_hook"]
        hook.before_command("rm -rf build")
        return object()

    monkeypatch.setattr(mini_module, "run_mini_in_process", fake_run_mini_in_process)
    monkeypatch.setenv("CODEFLOW_MINI_EXECUTOR", "inprocess")

    with pytest.raises(MiniExecutionError) as exc_info:
        run_mini_agent(str(repo), "prompt")

    assert exc_info.value.error_type == "policy_blocked"
    artifact_dir = repo / ".git" / "codeflow"
    events_path = next(artifact_dir.glob("mini_run_*.events.jsonl"))
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    blocked = [event for event in events if event.get("blocked")]
    assert blocked
    assert blocked[0]["risk_level"] == "high"
    assert "rm -rf" in blocked[0]["message"]
    log_text = next(artifact_dir.glob("mini_run_*.log")).read_text(encoding="utf-8")
    assert "ERROR_TYPE: policy_blocked" in log_text


def test_forbidden_path_write_hook_blocks_policy_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    class ForbiddenWriteExecutor:
        def run(self, request, *, hook=None):
            assert hook is not None
            hook.before_file_write(str(Path(request.repo) / ".env"))
            raise AssertionError("forbidden write should be blocked")

    with pytest.raises(MiniExecutionError) as exc_info:
        run_mini_agent(
            str(repo),
            "prompt",
            executor=ForbiddenWriteExecutor(),
            policy=HarnessPolicy(forbidden_paths=[".env"]),
        )

    assert exc_info.value.error_type == "policy_blocked"
