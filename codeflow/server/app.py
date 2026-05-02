from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from codeflow.server.auth import authorized
from codeflow.server.views import build_service_dashboard_html
from codeflow.storage import FindingFilters, JsonlRunStore, RunFilters, RunStore, SQLiteRunStore


@dataclass(frozen=True)
class ObservabilityServerConfig:
    repos: list[str]
    token: str | None = None
    sqlite_db: str | None = None


def handle_server_request(
    config: ObservabilityServerConfig,
    raw_path: str,
    *,
    headers: Mapping[str, str] | None = None,
) -> tuple[int, str, bytes]:
    if not authorized(headers or {}, config.token):
        return 401, "application/json; charset=utf-8", b'{"error":"unauthorized"}\n'

    parsed = urlparse(raw_path)
    path = parsed.path.rstrip("/") or "/"
    query = parse_qs(parsed.query)
    store = _build_store(config)
    run_filters = _run_filters_from_query(query)

    if path in {"/", "/dashboard"}:
        runs = store.list_runs(run_filters)
        summary = store.summarize(run_filters)
        body = build_service_dashboard_html(
            repos=[Path(repo).expanduser().resolve().name for repo in config.repos],
            runs=runs,
            summary=summary,
        )
        return 200, "text/html; charset=utf-8", body.encode()
    if path == "/api/runs":
        return _json_response(store.list_runs(run_filters))
    if path == "/api/summary":
        return _json_response(store.summarize(run_filters))
    if path == "/api/findings":
        return _json_response(store.list_findings(_finding_filters_from_query(query)))
    if path == "/api/trends":
        return _json_response(store.trends(run_filters))
    if path == "/api/failures":
        return _json_response(store.failures(run_filters))
    return 404, "application/json; charset=utf-8", b'{"error":"not found"}\n'


def serve_codeflow(
    repos: list[str],
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str | None = None,
    sqlite_db: str | None = None,
) -> None:
    config = ObservabilityServerConfig(
        repos=repos,
        token=token or os.environ.get("CODEFLOW_DASHBOARD_TOKEN"),
        sqlite_db=sqlite_db,
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            status, content_type, body = handle_server_request(
                config,
                self.path,
                headers={key: value for key, value in self.headers.items()},
            )
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    ThreadingHTTPServer((host, port), Handler).serve_forever()


def _build_store(config: ObservabilityServerConfig) -> RunStore:
    if config.sqlite_db:
        store = SQLiteRunStore(config.sqlite_db)
        store.sync_from_repos(config.repos)
        return store
    return JsonlRunStore(config.repos)


def _run_filters_from_query(query: dict[str, list[str]]) -> RunFilters:
    return RunFilters(
        query=_first(query, "q") or _first(query, "query"),
        status=_first(query, "status"),
        risk_level=_first(query, "risk") or _first(query, "risk_level"),
        repo=_first(query, "repo"),
        created_from=_first(query, "from") or _first(query, "created_from"),
        created_to=_first(query, "to") or _first(query, "created_to"),
        limit=_positive_int(_first(query, "limit"), default=100),
    )


def _finding_filters_from_query(query: dict[str, list[str]]) -> FindingFilters:
    return FindingFilters(
        category=_first(query, "category"),
        severity=_first(query, "severity"),
        repo=_first(query, "repo"),
        limit=_positive_int(_first(query, "limit"), default=100),
    )


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _positive_int(raw: str | None, *, default: int) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _json_response(data: Any) -> tuple[int, str, bytes]:
    return 200, "application/json; charset=utf-8", (
        json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n"
    ).encode()
