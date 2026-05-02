from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codeflow.harness.observability import load_review_summary, search_run_states
from codeflow.storage.base import (
    FindingFilters,
    RunFilters,
    failed_records,
    record_matches_filters,
    summarize_records,
    trends_from_records,
)


class JsonlRunStore:
    def __init__(self, repos: list[str]) -> None:
        self.repos = [str(Path(repo).expanduser().resolve()) for repo in repos]

    def list_runs(self, filters: RunFilters) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for repo in self.repos:
            repo_name = _repo_name(repo)
            repo_records = search_run_states(
                repo,
                query=filters.query,
                status=filters.status,
                risk_level=filters.risk_level,
                limit=max(filters.limit, 1000),
            )
            for record in repo_records:
                enriched = {**record, "repo": repo_name, "repo_path": repo}
                if record_matches_filters(enriched, filters):
                    records.append(enriched)
        return sorted(records, key=lambda item: str(item.get("run_id", "")), reverse=True)[: filters.limit]

    def summarize(self, filters: RunFilters) -> dict[str, Any]:
        return summarize_records(self.list_runs(filters))

    def list_findings(self, filters: FindingFilters) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        run_filters = RunFilters(repo=filters.repo, limit=max(filters.limit, 1000))
        for run in self.list_runs(run_filters):
            run_dir = Path(str(run.get("run_dir", "")))
            if not run_dir.is_dir():
                continue
            summary = load_review_summary(run_dir)
            for item in summary.get("findings", []):
                if not isinstance(item, dict):
                    continue
                if filters.category and item.get("category") != filters.category:
                    continue
                if filters.severity and item.get("severity") != filters.severity:
                    continue
                findings.append(
                    {
                        "repo": run.get("repo"),
                        "run_id": run.get("run_id"),
                        "task": run.get("task"),
                        "source": item.get("source"),
                        "severity": item.get("severity"),
                        "category": item.get("category"),
                        "file": item.get("file"),
                        "message": item.get("message"),
                        "recommendation": item.get("recommendation"),
                        "raw": item,
                    }
                )
                if len(findings) >= filters.limit:
                    return findings
        return findings

    def trends(self, filters: RunFilters) -> dict[str, Any]:
        return trends_from_records(self.list_runs(filters))

    def failures(self, filters: RunFilters) -> list[dict[str, Any]]:
        return failed_records(self.list_runs(filters))[: filters.limit]

    def dump_records_jsonl(self) -> str:
        return "".join(
            json.dumps(record, ensure_ascii=False) + "\n"
            for record in self.list_runs(RunFilters(limit=10000))
        )


def _repo_name(repo: str) -> str:
    return Path(repo).resolve().name
