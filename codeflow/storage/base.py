from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Protocol

SUCCESS_STATUSES = {"checks_passed", "committed", "kept_uncommitted"}


@dataclass(frozen=True)
class RunFilters:
    query: str | None = None
    status: str | None = None
    risk_level: str | None = None
    repo: str | None = None
    created_from: str | None = None
    created_to: str | None = None
    limit: int = 100


@dataclass(frozen=True)
class FindingFilters:
    category: str | None = None
    severity: str | None = None
    repo: str | None = None
    limit: int = 100


class RunStore(Protocol):
    def list_runs(self, filters: RunFilters) -> list[dict[str, Any]]:
        ...

    def summarize(self, filters: RunFilters) -> dict[str, Any]:
        ...

    def list_findings(self, filters: FindingFilters) -> list[dict[str, Any]]:
        ...

    def trends(self, filters: RunFilters) -> dict[str, Any]:
        ...

    def failures(self, filters: RunFilters) -> list[dict[str, Any]]:
        ...


def record_matches_filters(record: dict[str, Any], filters: RunFilters) -> bool:
    if filters.repo and str(record.get("repo", "")) != filters.repo:
        return False
    if filters.status and record.get("status") != filters.status:
        return False
    if filters.risk_level and record.get("risk_level") != filters.risk_level:
        return False
    created_at = str(record.get("created_at", ""))
    if filters.created_from and created_at and created_at < filters.created_from:
        return False
    if filters.created_to and created_at and created_at > filters.created_to:
        return False
    if filters.query:
        query = filters.query.lower()
        searchable = " ".join(
            str(record.get(key, ""))
            for key in ("repo", "run_id", "task", "branch", "status", "risk_level")
        ).lower()
        if query not in searchable:
            return False
    return True


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(str(record.get("status", "unknown")) for record in records)
    risk_counts = Counter(str(record.get("risk_level", "unknown")) for record in records)
    repo_counts = Counter(str(record.get("repo", "unknown")) for record in records)
    daily_counts = Counter(_day_for_record(record) for record in records)
    finding_counts: Counter[str] = Counter()
    finding_categories: Counter[str] = Counter()
    high_risk_files: Counter[str] = Counter()
    for record in records:
        finding_counts.update(
            {str(key): int(value) for key, value in (record.get("finding_counts") or {}).items()}
        )
        finding_categories.update(
            {str(key): int(value) for key, value in (record.get("finding_categories") or {}).items()}
        )
        high_risk_files.update(str(path) for path in record.get("high_risk_files") or [])
    repair_rounds = [int(record.get("repair_round", 0) or 0) for record in records]
    return {
        "total_runs": len(records),
        "repo_counts": dict(sorted(repo_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "risk_counts": dict(sorted(risk_counts.items())),
        "daily_counts": dict(sorted(daily_counts.items())),
        "failed_runs": failed_records(records)[:20],
        "checks_passed": sum(1 for record in records if record.get("checks_passed")),
        "sensor_passed": sum(1 for record in records if record.get("sensor_passed")),
        "finding_counts": dict(sorted(finding_counts.items())),
        "finding_categories": dict(sorted(finding_categories.items())),
        "high_risk_files": dict(sorted(high_risk_files.items())),
        "average_repair_rounds": round(sum(repair_rounds) / len(repair_rounds), 2)
        if repair_rounds
        else 0.0,
        "latest_run_id": records[0].get("run_id") if records else None,
    }


def trends_from_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    days: dict[str, dict[str, Any]] = {}
    for record in records:
        day = _day_for_record(record)
        bucket = days.setdefault(
            day,
            {
                "date": day,
                "total_runs": 0,
                "status_counts": {},
                "risk_counts": {},
                "repo_counts": {},
            },
        )
        bucket["total_runs"] += 1
        _increment(bucket["status_counts"], str(record.get("status", "unknown")))
        _increment(bucket["risk_counts"], str(record.get("risk_level", "unknown")))
        _increment(bucket["repo_counts"], str(record.get("repo", "unknown")))
    return {"daily": [days[key] for key in sorted(days, reverse=True)]}


def failed_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "repo": record.get("repo"),
            "run_id": record.get("run_id"),
            "task": record.get("task"),
            "status": record.get("status"),
            "risk_level": record.get("risk_level"),
            "run_dir": record.get("run_dir"),
        }
        for record in records
        if record.get("status") not in SUCCESS_STATUSES
    ]


def _day_for_record(record: dict[str, Any]) -> str:
    created_at = str(record.get("created_at") or "")
    if created_at:
        return created_at[:10]
    return str(record.get("run_id", ""))[:8] or "unknown"


def _increment(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1
