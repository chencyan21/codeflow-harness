from __future__ import annotations

from codeflow.models import Spec


def build_spec(task: str) -> Spec:
    return Spec(
        task_type="coding_task",
        goal=task,
        acceptance_criteria=[
            "Implementation satisfies the user task.",
            "Existing tests pass.",
            "New or updated tests are added when appropriate.",
            "No unrelated files are modified.",
        ],
        constraints=[
            "Do not delete existing tests.",
            "Do not bypass failing tests.",
            "Do not modify environment secrets.",
            "Keep changes minimal and relevant.",
        ],
    )
