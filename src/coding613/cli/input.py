"""Validated stdin decoders for non-interactive prompt execution."""

from __future__ import annotations

import json
from typing import TextIO


class InputFormatError(ValueError):
    """Raised when stdin does not match the selected prompt schema."""


def parse_text_input(stream: TextIO) -> tuple[str, ...]:
    text = stream.read().strip()
    if not text:
        raise InputFormatError("prompt input must not be blank")
    return (text,)


def parse_stream_json_input(stream: TextIO) -> tuple[str, ...]:
    prompts: list[str] = []
    for line_number, line in enumerate(stream, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            raise InputFormatError(f"line {line_number} is not valid JSON") from None
        if not isinstance(value, dict):
            raise InputFormatError(f"line {line_number} must be a JSON object")
        if value.get("schema_version") != 1:
            raise InputFormatError(f"line {line_number} has unsupported schema_version")
        if value.get("type") != "user.message":
            raise InputFormatError(f"line {line_number} has unknown event type")
        text = value.get("text")
        if not isinstance(text, str) or not text.strip():
            raise InputFormatError(f"line {line_number} prompt must not be blank")
        prompts.append(text.strip())
    if not prompts:
        raise InputFormatError("prompt input must not be blank")
    return tuple(prompts)
