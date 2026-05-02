import os
import subprocess
import sys


def test_minisweagent_import_is_quiet_and_does_not_create_config_dir(tmp_path):
    config_dir = tmp_path / "mini-config"
    env = os.environ.copy()
    env["MSWEA_GLOBAL_CONFIG_DIR"] = str(config_dir)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import os; import minisweagent; "
            "print(Path(os.environ['MSWEA_GLOBAL_CONFIG_DIR']).exists())",
        ],
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )

    assert result.stdout == "False\n"
    assert result.stderr == ""


def test_minisweagent_import_does_not_configure_console_logger(tmp_path):
    config_dir = tmp_path / "mini-config"
    env = os.environ.copy()
    env["MSWEA_GLOBAL_CONFIG_DIR"] = str(config_dir)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import logging; import minisweagent; "
            "logger = logging.getLogger('minisweagent'); "
            "print(sum(1 for handler in logger.handlers "
            "if getattr(handler, '_minisweagent_console_handler', False)))",
        ],
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )

    assert result.stdout == "0\n"
    assert result.stderr == ""


def test_prompt_user_import_does_not_create_config_dir(tmp_path):
    config_dir = tmp_path / "mini-config"
    env = os.environ.copy()
    env["MSWEA_GLOBAL_CONFIG_DIR"] = str(config_dir)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import os; import minisweagent.agents.utils.prompt_user; "
            "print(Path(os.environ['MSWEA_GLOBAL_CONFIG_DIR']).exists())",
        ],
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )

    assert result.stdout == "False\n"
    assert result.stderr == ""
