#!/usr/bin/env python3

import json
import re
from pathlib import Path
from unittest.mock import patch

from minisweagent.models.test_models import DeterministicModel, make_output
from minisweagent.run.mini import DEFAULT_CONFIG_FILE, main


def _make_model_response(content: str) -> dict:
    match = re.search(r"```mswea_bash_command\s*\n(.*?)\n```", content, re.DOTALL)
    actions = [{"command": match.group(1)}] if match else []
    return make_output(content, actions)


def update_trajectory():
    traj_path = Path(__file__).parent / "local.traj.json"
    trajectory = json.loads(traj_path.read_text())

    task = "Blah blah blah"

    model_responses = [msg["content"] for msg in trajectory[2:] if msg["role"] == "assistant"]
    print(f"Got {len(model_responses)} model responses")

    with patch("minisweagent.run.mini.get_model") as mock_get_model:
        mock_get_model.return_value = DeterministicModel(outputs=[_make_model_response(text) for text in model_responses])
        main(model_name="tardis", config_spec=DEFAULT_CONFIG_FILE, output=traj_path, task=task, yolo=True, model_class=None)


if __name__ == "__main__":
    update_trajectory()
