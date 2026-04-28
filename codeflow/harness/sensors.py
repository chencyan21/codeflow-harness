from __future__ import annotations

from typing import Protocol

from codeflow.models import HarnessSensorReport, SensorContext, SensorResult

SEVERITY_ORDER = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}


class BaseSensor(Protocol):
    name: str

    def run(self, context: SensorContext) -> SensorResult:
        ...


def build_sensor_report(results: list[SensorResult]) -> HarnessSensorReport:
    max_severity = "info"
    for result in results:
        if SEVERITY_ORDER[result.severity] > SEVERITY_ORDER[max_severity]:
            max_severity = result.severity

    return HarnessSensorReport(
        results=results,
        overall_passed=all(result.passed for result in results),
        max_severity=max_severity,  # type: ignore[arg-type]
        blocking_reasons=[result.message for result in results if not result.passed],
    )
