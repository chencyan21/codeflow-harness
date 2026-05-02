from __future__ import annotations

import re
from pathlib import Path


REDACTION_PATTERNS = [
    re.compile(
        r"(?i)(['\"]?(?:api[_-]?key|token|secret|password)['\"]?\s*[:=]\s*)"
        r"(['\"]?)[^'\"\s,}]+(['\"]?)"
    ),
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bsk-[A-Za-z0-9._-]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
]


def redact_text(value: object) -> str:
    text = "" if value is None else str(value)
    for pattern in REDACTION_PATTERNS:
        text = pattern.sub(_replacement, text)
    return text


def redact_file_in_place(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return
    redacted = redact_text(text)
    if redacted != text:
        path.write_text(redacted, encoding="utf-8")


def _replacement(match: re.Match[str]) -> str:
    if match.lastindex and match.lastindex >= 3:
        return f"{match.group(1)}{match.group(2)}[REDACTED]{match.group(3)}"
    if match.group(0).lower().startswith("authorization"):
        return f"{match.group(1)}[REDACTED]"
    return "[REDACTED]"
