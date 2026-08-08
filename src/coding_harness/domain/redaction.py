"""Deterministic secret redaction used before persistence or embedding."""

import re

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|password|secret|token)\s*[:=]\s*[^\s,;]+"
    ),
)


def redact_text(text: str) -> str:
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted
