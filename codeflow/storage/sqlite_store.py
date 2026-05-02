from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from codeflow.storage.base import (
    FindingFilters,
    RunFilters,
    failed_records,
    record_matches_filters,
    summarize_records,
    trends_from_records,
)
from codeflow.storage.jsonl_store import JsonlRunStore


class SQLiteRunStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def sync_from_repos(self, repos: list[str]) -> None:
        jsonl_store = JsonlRunStore(repos)
        records = jsonl_store.list_runs(RunFilters(limit=10000))
        findings = jsonl_store.list_findings(FindingFilters(limit=100000))
        with self._connect() as conn:
            for repo in {str(record.get("repo")) for record in records}:
                conn.execute("DELETE FROM runs WHERE repo = ?", (repo,))
                conn.execute("DELETE FROM findings WHERE repo = ?", (repo,))
            for record in records:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO runs (
                      repo, repo_path, run_id, created_at, task, branch, status, risk_level,
                      checks_passed, sensor_passed, repair_round, run_dir, raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.get("repo"),
                        record.get("repo_path"),
                        record.get("run_id"),
                        record.get("created_at"),
                        record.get("task"),
                        record.get("branch"),
                        record.get("status"),
                        record.get("risk_level"),
                        int(bool(record.get("checks_passed"))),
                        int(bool(record.get("sensor_passed"))),
                        int(record.get("repair_round", 0) or 0),
                        record.get("run_dir"),
                        json.dumps(record, ensure_ascii=False),
                    ),
                )
            for finding in findings:
                conn.execute(
                    """
                    INSERT INTO findings (
                      repo, run_id, severity, category, file, message, recommendation, source, raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        finding.get("repo"),
                        finding.get("run_id"),
                        finding.get("severity"),
                        finding.get("category"),
                        finding.get("file"),
                        finding.get("message"),
                        finding.get("recommendation"),
                        finding.get("source"),
                        json.dumps(finding, ensure_ascii=False),
                    ),
                )

    def list_runs(self, filters: RunFilters) -> list[dict[str, Any]]:
        rows = self._query_run_rows(filters)
        records = [_record_from_row(row) for row in rows]
        return [record for record in records if record_matches_filters(record, filters)][: filters.limit]

    def summarize(self, filters: RunFilters) -> dict[str, Any]:
        return summarize_records(self.list_runs(filters))

    def list_findings(self, filters: FindingFilters) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[object] = []
        if filters.repo:
            clauses.append("repo = ?")
            params.append(filters.repo)
        if filters.category:
            clauses.append("category = ?")
            params.append(filters.category)
        if filters.severity:
            clauses.append("severity = ?")
            params.append(filters.severity)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT raw_json FROM findings {where} ORDER BY rowid DESC LIMIT ?"
        params.append(filters.limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [json.loads(str(row["raw_json"])) for row in rows]

    def trends(self, filters: RunFilters) -> dict[str, Any]:
        return trends_from_records(self.list_runs(filters))

    def failures(self, filters: RunFilters) -> list[dict[str, Any]]:
        return failed_records(self.list_runs(filters))[: filters.limit]

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                  repo TEXT NOT NULL,
                  repo_path TEXT NOT NULL,
                  run_id TEXT NOT NULL,
                  created_at TEXT,
                  task TEXT,
                  branch TEXT,
                  status TEXT,
                  risk_level TEXT,
                  checks_passed INTEGER,
                  sensor_passed INTEGER,
                  repair_round INTEGER,
                  run_dir TEXT,
                  raw_json TEXT NOT NULL,
                  PRIMARY KEY (repo, run_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS findings (
                  repo TEXT NOT NULL,
                  run_id TEXT NOT NULL,
                  severity TEXT,
                  category TEXT,
                  file TEXT,
                  message TEXT,
                  recommendation TEXT,
                  source TEXT,
                  raw_json TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_repo ON runs(repo)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_findings_repo ON findings(repo)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings(severity)")

    def _query_run_rows(self, filters: RunFilters) -> list[sqlite3.Row]:
        clauses: list[str] = []
        params: list[object] = []
        if filters.repo:
            clauses.append("repo = ?")
            params.append(filters.repo)
        if filters.status:
            clauses.append("status = ?")
            params.append(filters.status)
        if filters.risk_level:
            clauses.append("risk_level = ?")
            params.append(filters.risk_level)
        if filters.created_from:
            clauses.append("created_at >= ?")
            params.append(filters.created_from)
        if filters.created_to:
            clauses.append("created_at <= ?")
            params.append(filters.created_to)
        if filters.query:
            clauses.append("(run_id LIKE ? OR task LIKE ? OR branch LIKE ?)")
            like = f"%{filters.query}%"
            params.extend([like, like, like])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM runs {where} ORDER BY run_id DESC LIMIT ?"
        params.append(filters.limit)
        with self._connect() as conn:
            return list(conn.execute(sql, params).fetchall())

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


def _record_from_row(row: sqlite3.Row) -> dict[str, Any]:
    raw = json.loads(str(row["raw_json"]))
    if not isinstance(raw, dict):
        raw = {}
    raw.update(
        {
            "repo": row["repo"],
            "repo_path": row["repo_path"],
            "run_id": row["run_id"],
            "created_at": row["created_at"],
            "task": row["task"],
            "branch": row["branch"],
            "status": row["status"],
            "risk_level": row["risk_level"],
            "checks_passed": bool(row["checks_passed"]),
            "sensor_passed": bool(row["sensor_passed"]),
            "repair_round": row["repair_round"],
            "run_dir": row["run_dir"],
        }
    )
    return raw
