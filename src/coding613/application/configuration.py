"""Validated, repository-local configuration edits exposed by the TUI."""

from __future__ import annotations

import json
import math
import os
import re
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from coding613.config import HarnessConfig, load_config, load_config_text
from coding613.domain.models import PermissionMode
from coding613.domain.redaction import redact_text

_ValueKind = Literal["string", "bool", "int", "float"]
_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(?:#.*)?(?:\r?\n)?$")
_KEY_RE = re.compile(
    r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_-]+)(?P<separator>\s*=\s*)"
    r"(?P<value>.*?)(?P<newline>\r?\n)?$"
)


@dataclass(frozen=True, slots=True)
class _FieldSpec:
    sections: tuple[str | None, ...]
    target_section: str | None
    toml_key: str
    kind: _ValueKind


def _field(
    sections: tuple[str | None, ...],
    target_section: str | None,
    toml_key: str,
    kind: _ValueKind,
) -> _FieldSpec:
    return _FieldSpec(sections, target_section, toml_key, kind)


_FIELDS: dict[str, _FieldSpec] = {
    "mode": _field((None, "policy", "run"), "policy", "mode", "string"),
    "permission_mode": _field((None, "policy", "run"), "policy", "mode", "string"),
    "policy.mode": _field(("policy", "run", None), "policy", "mode", "string"),
    "policy.allow_network": _field((None, "policy", "run"), "policy", "allow_network", "bool"),
    "policy.allow_dependency_install": _field(
        (None, "policy", "run"), "policy", "allow_dependency_install", "bool"
    ),
    "policy.allow_git_writes": _field(
        (None, "policy", "run"), "policy", "allow_git_writes", "bool"
    ),
    "policy.allow_writes": _field((None, "policy", "run"), "policy", "allow_writes", "bool"),
    "allow_network": _field((None, "policy", "run"), "policy", "allow_network", "bool"),
    "allow_dependency_install": _field(
        (None, "policy", "run"), "policy", "allow_dependency_install", "bool"
    ),
    "allow_git_writes": _field((None, "policy", "run"), "policy", "allow_git_writes", "bool"),
    "allow_writes": _field((None, "policy", "run"), "policy", "allow_writes", "bool"),
}


class ConfigurationService:
    """Read and atomically update the supported scalar harness settings."""

    def __init__(self, repository_root: str | Path) -> None:
        self.repository_root = Path(repository_root).expanduser().resolve(strict=True)
        if not self.repository_root.is_dir():
            raise ValueError("repository root must be a directory")
        self.path = self.repository_root / "harness.toml"

    def load(self) -> HarnessConfig:
        return load_config(self.repository_root)

    def summary(self) -> str:
        config = self.load()
        mode_line = f"mode={config.permission_mode.value}"
        if config.permission_mode is PermissionMode.BYPASS:
            mode_line += " (DANGEROUS: BYPASS)"
        lines = [
            f"Configuration: {self.path}",
            mode_line,
            "validation="
            + ("; ".join(shlex.join(command) for command in config.validation_commands) or "none"),
            f"allow_network={config.allow_network}",
            f"allow_dependency_install={config.allow_dependency_install}",
            f"allow_git_writes={config.allow_git_writes}",
            f"allow_writes={config.allow_writes}",
        ]
        lines.append("scope=project-policy-only")
        return redact_text("\n".join(str(line) for line in lines))

    def set_value(self, key: str, value: str) -> HarnessConfig:
        normalized = key.strip().lower()
        spec = _FIELDS.get(normalized)
        if spec is None:
            supported = ", ".join(sorted(_FIELDS))
            raise ValueError(f"unsupported configuration key {key!r}; use one of: {supported}")
        encoded = _encode_value(_parse_value(value, spec.kind), spec.kind)
        current = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        candidate_text = _replace_toml_value(
            current,
            sections=spec.sections,
            target_section=spec.target_section,
            key=spec.toml_key,
            encoded=encoded,
        )
        candidate = load_config_text(self.repository_root, candidate_text)
        _atomic_write(self.path, candidate_text)
        return candidate


def _parse_value(raw: str, kind: _ValueKind) -> str | bool | int | float:
    value = raw.strip()
    if not value:
        raise ValueError("configuration value must not be empty")
    if kind == "string":
        return value
    if kind == "bool":
        if value.lower() in {"true", "on", "yes", "1"}:
            return True
        if value.lower() in {"false", "off", "no", "0"}:
            return False
        raise ValueError("boolean configuration values must be true or false")
    if kind == "int":
        try:
            return int(value)
        except ValueError as error:
            raise ValueError("configuration value must be an integer") from error
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError("configuration value must be a number") from error
    if not math.isfinite(parsed):
        raise ValueError("configuration value must be finite")
    return parsed


def _encode_value(value: str | bool | float, kind: _ValueKind) -> str:
    if kind == "string":
        return json.dumps(value, ensure_ascii=False)
    if kind == "bool":
        return "true" if value else "false"
    return str(value)


def _replace_toml_value(
    text: str,
    *,
    sections: tuple[str | None, ...],
    target_section: str | None,
    key: str,
    encoded: str,
) -> str:
    lines = text.splitlines(keepends=True)
    current_section: str | None = None
    for index, line in enumerate(lines):
        match = _SECTION_RE.match(line)
        if match is not None:
            current_section = match.group(1).strip()
            continue
        if current_section not in sections:
            continue
        key_match = _KEY_RE.match(line)
        if key_match is None or key_match.group("key") != key:
            continue
        newline = key_match.group("newline") or "\n"
        lines[index] = (
            f"{key_match.group('indent')}{key}{key_match.group('separator')}"
            f"{encoded}{newline}"
        )
        return "".join(lines)

    if target_section is None:
        insertion = f"{key} = {encoded}\n"
        for index, line in enumerate(lines):
            if _SECTION_RE.match(line) is not None:
                lines.insert(index, insertion)
                return "".join(lines)
        lines.append(insertion)
        return "".join(lines)

    section_start: int | None = None
    section_end: int | None = None
    for index, line in enumerate(lines):
        match = _SECTION_RE.match(line)
        if match is None:
            continue
        section_name = match.group(1).strip()
        if section_start is not None:
            section_end = index
            break
        if section_name == target_section:
            section_start = index
    if section_start is None:
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines.append("\n")
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.extend([f"[{target_section}]\n", f"{key} = {encoded}\n"])
        return "".join(lines)
    insertion_index = section_end if section_end is not None else len(lines)
    if insertion_index > section_start and lines[insertion_index - 1].strip():
        lines.insert(insertion_index, "\n")
        insertion_index += 1
    lines.insert(insertion_index, f"{key} = {encoded}\n")
    return "".join(lines)


def _atomic_write(path: Path, text: str) -> None:
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
