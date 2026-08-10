"""Stable root CLI exit codes."""

from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    FAILURE = 1
    INVALID_INPUT = 2
    POLICY_BLOCKED = 3
    PROVIDER_UNAVAILABLE = 4
    BUDGET_STOP = 5
