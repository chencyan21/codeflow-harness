from __future__ import annotations

from unittest.mock import Mock

from codeflow.harness.governance import print_governance_summary
from codeflow.models import HarnessSensorReport, RunState


def test_governance_options_are_printed_without_rich_markup() -> None:
    console = Mock()
    state = RunState(
        repo="/tmp/repo",
        task="demo",
        branch="ai/demo",
        status="checks_passed",
        sensor_report=HarnessSensorReport(),
    )

    print_governance_summary(state, console)

    options_call = console.print.call_args_list[-1]
    assert "[c] commit" in options_call.args[0]
    assert options_call.kwargs == {"markup": False}
