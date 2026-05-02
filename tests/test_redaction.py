from __future__ import annotations

from codeflow.redaction import redact_text


def test_redact_text_masks_common_secret_formats() -> None:
    text = "\n".join(
        [
            "api_key=sk-plain123456789",
            '"api_key": "json-secret-value"',
            "Authorization: Bearer bearer-secret-value",
            "token: ghp_abcdefghijklmnopqrstuvwxyz123456",
        ]
    )

    redacted = redact_text(text)

    assert "sk-plain" not in redacted
    assert "json-secret-value" not in redacted
    assert "bearer-secret-value" not in redacted
    assert "ghp_" not in redacted
    assert redacted.count("[REDACTED]") >= 4
    assert '"api_key": "[REDACTED]"' in redacted
