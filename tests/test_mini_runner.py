from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from codeflow.mini_runner import run_mini_agent


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

    with pytest.raises(RuntimeError, match="mini-swe-agent timed out"):
        run_mini_agent(str(repo), "prompt")

    logs = list((repo / ".git" / "codeflow").glob("mini_run_*.log"))
    assert len(logs) == 1
    log_text = logs[0].read_text(encoding="utf-8")
    assert "TIMEOUT_SECONDS: 0.1" in log_text
    assert "PROMPT:" in log_text
