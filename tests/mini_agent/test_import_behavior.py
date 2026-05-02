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
