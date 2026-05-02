from __future__ import annotations

from collections.abc import Mapping


def authorized(headers: Mapping[str, str], token: str | None) -> bool:
    if not token:
        return True
    auth_header = headers.get("Authorization", "")
    if auth_header == f"Bearer {token}":
        return True
    return headers.get("X-CodeFlow-Token", "") == token
