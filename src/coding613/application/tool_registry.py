"""Validated dispatch registry for model-visible tools."""

from __future__ import annotations

from dataclasses import dataclass

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from coding613.domain.actions import ToolCall
from coding613.ports.llm import ToolDefinition
from coding613.ports.tools import ToolContext, ToolExecutor, ToolResult


class ToolRegistryError(RuntimeError):
    pass


class DuplicateToolError(ToolRegistryError):
    pass


class UnknownToolError(ToolRegistryError):
    pass


class ToolSchemaError(ToolRegistryError):
    pass


@dataclass(frozen=True, slots=True)
class _Registration:
    definition: ToolDefinition
    executor: ToolExecutor
    validator: Draft202012Validator


class ToolRegistry:
    def __init__(self) -> None:
        self._registrations: dict[str, _Registration] = {}

    def register(self, definition: ToolDefinition, executor: ToolExecutor) -> None:
        if definition.name in self._registrations:
            raise DuplicateToolError(f"tool already registered: {definition.name}")
        try:
            Draft202012Validator.check_schema(definition.input_schema)
        except SchemaError as error:
            raise ToolSchemaError(f"invalid schema for tool: {definition.name}") from error
        self._registrations[definition.name] = _Registration(
            definition=definition,
            executor=executor,
            validator=Draft202012Validator(definition.input_schema),
        )

    def dispatch(self, call: ToolCall, context: ToolContext) -> ToolResult:
        registration = self._validated_registration(call)
        return registration.executor.execute(call, context)

    def validate(self, call: ToolCall) -> None:
        self._validated_registration(call)

    def _validated_registration(self, call: ToolCall) -> _Registration:
        registration = self._registrations.get(call.name)
        if registration is None:
            raise UnknownToolError(f"unknown tool: {call.name}")
        try:
            registration.validator.validate(call.arguments)
        except ValidationError as error:
            raise ToolSchemaError(f"invalid arguments for tool: {call.name}") from error
        return registration

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(
            registration.definition
            for name, registration in sorted(self._registrations.items())
        )
