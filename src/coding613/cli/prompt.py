"""Root prompt/print command parsing and execution."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TextIO
from uuid import UUID

from coding613.application.composition import LocalServices, build_services
from coding613.application.events import (
    JsonOutputSerializer,
    ProgressEventBridge,
    SequencedEventSink,
    StreamJsonSerializer,
    TextOutputSerializer,
    assistant_text_from_events,
)
from coding613.application.progress import CancellationToken
from coding613.cli.exit_codes import ExitCode
from coding613.cli.input import InputFormatError, parse_stream_json_input, parse_text_input
from coding613.domain.conversation import PromptRequest, RunOptions
from coding613.domain.events import redact_payload
from coding613.domain.models import FeedbackKind, PermissionMode, RunState, StopReason
from coding613.domain.session_events import EventType, RunEnvelope, SessionEnvelope, SessionEvent


class InputFormat(StrEnum):
    TEXT = "text"
    STREAM_JSON = "stream-json"


class OutputFormat(StrEnum):
    TEXT = "text"
    JSON = "json"
    STREAM_JSON = "stream-json"


@dataclass(frozen=True, slots=True)
class RootLaunchRequest:
    repo: Path
    prompt: str | None
    print_mode: bool
    continue_latest: bool
    resume: str | None
    input_format: InputFormat
    output_format: OutputFormat
    model: str | None
    permission_mode: PermissionMode | None
    options: RunOptions
    verbose: bool


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="613-coding",
        description="Open the local 613 Coding terminal interface or run a prompt.",
    )
    parser.add_argument("--repo", default=".", help="Repository directory")
    parser.add_argument("--add-dir", action="append", default=[], help="Additional allowed directory")
    parser.add_argument("-p", "--print", dest="print_mode", action="store_true")
    parser.add_argument("--continue", dest="continue_latest", action="store_true")
    parser.add_argument("--resume")
    parser.add_argument("--input-format", choices=[item.value for item in InputFormat], default=InputFormat.TEXT.value)
    parser.add_argument("--output-format", choices=[item.value for item in OutputFormat], default=OutputFormat.TEXT.value)
    parser.add_argument("--model")
    parser.add_argument("--permission-mode", choices=[item.value for item in PermissionMode])
    parser.add_argument(
        "--dangerously-skip-permissions",
        action="store_true",
        help="Skip approval prompts; deterministic denials and sandbox limits remain active",
    )
    parser.add_argument("--allowed-tools", "--allowedTools", action="append", default=[])
    parser.add_argument("--disallowed-tools", "--disallowedTools", action="append", default=[])
    parser.add_argument("--max-turns", type=int)
    parser.add_argument("--max-model-calls", type=int)
    parser.add_argument("--max-wall-time", type=float)
    parser.add_argument("--max-cost", type=float)
    parser.add_argument("--system-prompt")
    parser.add_argument("--append-system-prompt")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("prompt", nargs="*", help="Initial coding prompt")
    return parser


def _positive(value: float | None, name: str, parser: argparse.ArgumentParser) -> int | float | None:
    if value is not None and value <= 0:
        parser.error(f"{name} must be positive")
    return value


def _tool_names(values: Sequence[str]) -> frozenset[str]:
    names: set[str] = set()
    for value in values:
        names.update(item for item in value.split(",") if item)
    return frozenset(names)


def parse_root_args(argv: Sequence[str]) -> RootLaunchRequest:
    parser = _parser()
    namespace = parser.parse_args(list(argv))
    if namespace.continue_latest and namespace.resume is not None:
        parser.error("--continue and --resume cannot be selected together")
    if (
        namespace.dangerously_skip_permissions
        and namespace.permission_mode not in {None, PermissionMode.BYPASS.value}
    ):
        parser.error(
            "--dangerously-skip-permissions conflicts with a non-bypass "
            "--permission-mode"
        )
    permission_mode_value = (
        PermissionMode.BYPASS.value
        if namespace.dangerously_skip_permissions
        else namespace.permission_mode
    )
    if namespace.resume is not None and namespace.resume != "latest":
        try:
            UUID(namespace.resume)
        except ValueError:
            parser.error("--resume expects latest or a session UUID")
    repo = Path(namespace.repo).expanduser()
    try:
        repo = repo.resolve(strict=True)
    except FileNotFoundError:
        parser.error(f"repository does not exist: {repo}")
    if not repo.is_dir():
        parser.error(f"repository is not a directory: {repo}")
    additional_dirs = tuple(
        str(Path(value).expanduser().resolve(strict=True)) for value in namespace.add_dir
    )
    if any(not Path(value).is_dir() for value in additional_dirs):
        parser.error("--add-dir values must be directories")
    budget_overrides = {
        key: value
        for key, value in {
            "per_agent_turns": _positive(namespace.max_turns, "--max-turns", parser),
            "total_model_calls": _positive(namespace.max_model_calls, "--max-model-calls", parser),
            "wall_time_seconds": _positive(namespace.max_wall_time, "--max-wall-time", parser),
            "provider_cost": _positive(namespace.max_cost, "--max-cost", parser),
        }.items()
        if value is not None
    }
    try:
        options = RunOptions(
            model=namespace.model,
            allowed_tools=_tool_names(namespace.allowed_tools),
            disallowed_tools=_tool_names(namespace.disallowed_tools),
            additional_dirs=additional_dirs,
            system_prompt=namespace.system_prompt,
            append_system_prompt=namespace.append_system_prompt,
            budget_overrides=budget_overrides,
        )
    except ValueError as error:
        parser.error(str(error))
    prompt = " ".join(namespace.prompt).strip() or None
    return RootLaunchRequest(
        repo=repo,
        prompt=prompt,
        print_mode=namespace.print_mode,
        continue_latest=namespace.continue_latest,
        resume=namespace.resume,
        input_format=InputFormat(namespace.input_format),
        output_format=OutputFormat(namespace.output_format),
        model=namespace.model,
        permission_mode=(
            PermissionMode(permission_mode_value)
            if permission_mode_value is not None
            else None
        ),
        options=options,
        verbose=namespace.verbose,
    )


def run_print(
    request: RootLaunchRequest,
    services_factory: Callable[[str | Path], LocalServices] = build_services,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    input_stream = stdin or sys.stdin
    output_stream = stdout or sys.stdout
    try:
        prompts: tuple[str, ...]
        if request.prompt is not None:
            prompts = (request.prompt,)
        elif request.input_format is InputFormat.TEXT:
            prompts = parse_text_input(input_stream)
        else:
            prompts = parse_stream_json_input(input_stream)
        services = services_factory(request.repo)
        project_id = services.run_service.project.id
        diagnostic_report = None
        if request.verbose:
            diagnostics = getattr(services, "diagnostics", None)
            if diagnostics is not None:
                diagnostic_report = diagnostics.run(project_id)
        events_by_run: list[tuple[RunEnvelope, tuple[SessionEvent, ...]]] = []
        recording = _RecordingEventSink()
        sequenced = SequencedEventSink(recording)
        started_session_id: UUID | None = None
        diagnostic_emitted = False
        session_id = _resume_session_id(request.resume)
        for index, prompt in enumerate(prompts):
            use_latest = (
                (request.continue_latest or request.resume == "latest") and index == 0
            )
            prompt_request = PromptRequest(
                project_id=project_id,
                text=prompt,
                session_id=session_id,
                continue_latest=use_latest,
                permission_mode=request.permission_mode,
                options=request.options,
            )
            run = services.conversation.submit(prompt_request)
            if run.session_id is None:
                raise RuntimeError("conversation service returned a run without a session")
            session_id = run.session_id
            event_start = len(recording.events)
            if (
                diagnostic_report is not None
                and request.output_format is OutputFormat.STREAM_JSON
                and not diagnostic_emitted
            ):
                diagnostic_emitted = True
                sequenced.publish(
                    SessionEvent(
                        session_id=session_id,
                        run_id=run.id,
                        type=EventType.DIAGNOSTIC_COMPLETED,
                        data=redact_payload(
                            diagnostic_report.model_dump(mode="json")
                        ),
                    )
                )
            if started_session_id is None:
                started_session_id = session_id
                sequenced.publish(
                    SessionEvent(
                        session_id=session_id,
                        run_id=run.id,
                        type=EventType.SESSION_STARTED,
                        data={"project_id": str(project_id)},
                    )
                )
            sequenced.publish(
                SessionEvent(
                    session_id=session_id,
                    run_id=run.id,
                    type=EventType.USER_MESSAGE,
                    data=redact_payload({"text": prompt}),
                )
            )
            bridge = ProgressEventBridge(session_id, run.id, sequenced)
            summary = services.conversation.execute(
                run.id,
                bridge,
                CancellationToken(),
            )
            terminal_type = (
                EventType.RUN_COMPLETED
                if summary.status is RunState.COMPLETED
                else EventType.RUN_FAILED
            )
            sequenced.publish(
                SessionEvent(
                    session_id=session_id,
                    run_id=run.id,
                    type=terminal_type,
                    data={
                        "status": summary.status.value,
                        "permission_mode": run.permission_mode.value,
                        "stop_reason": summary.stop_reason.value
                        if summary.stop_reason
                        else None,
                    },
                )
            )
            events = tuple(recording.events[event_start:])
            envelope = RunEnvelope.from_summary(
                summary,
                session_id,
                assistant_text_from_events(events),
                permission_mode=run.permission_mode,
                diagnostics=diagnostic_report,
            )
            events_by_run.append((envelope, events))
            if summary.status is not RunState.COMPLETED:
                break
        _write_output(request, events_by_run, output_stream)
        return int(_exit_code(events_by_run[-1][0]))
    except InputFormatError as error:
        print(f"invalid input: {error}", file=output_stream)
        return int(ExitCode.INVALID_INPUT)
    except Exception as error:  # noqa: BLE001 - CLI boundary maps safe typed outcome
        print(f"command failed: {type(error).__name__}", file=output_stream)
        return int(_exception_exit_code(error))


class _RecordingEventSink:
    def __init__(self) -> None:
        self.events: list[SessionEvent] = []

    def publish(self, event: SessionEvent) -> None:
        self.events.append(event)


def _resume_session_id(value: str | None) -> UUID | None:
    if value is None or value == "latest":
        return None
    try:
        return UUID(value)
    except ValueError:
        raise ValueError("--resume expects latest or a session UUID") from None


def _write_output(
    request: RootLaunchRequest,
    values: Sequence[tuple[RunEnvelope, tuple[SessionEvent, ...]]],
    output: TextIO,
) -> None:
    if request.output_format is OutputFormat.STREAM_JSON:
        stream_serializer = StreamJsonSerializer()
        for _, events in values:
            output.writelines(stream_serializer.render_event(event) for event in events)
        return
    if request.output_format is OutputFormat.JSON:
        json_serializer = JsonOutputSerializer()
        if len(values) == 1:
            output.write(json_serializer.render(values[0][0]))
        else:
            output.write(
                json_serializer.render_session(
                    SessionEnvelope(
                        session_id=values[0][0].session_id,
                        runs=tuple(envelope for envelope, _ in values),
                    )
                )
            )
        return
    text_serializer = TextOutputSerializer()
    for envelope, _ in values:
        output.write(text_serializer.render(envelope, verbose=request.verbose))


def _exit_code(envelope: RunEnvelope) -> ExitCode:
    if envelope.status is RunState.COMPLETED:
        return ExitCode.SUCCESS
    if FeedbackKind.POLICY_BLOCKED in envelope.completion_blockers:
        return ExitCode.POLICY_BLOCKED
    if envelope.stop_reason in {StopReason.BUDGET_EXHAUSTED, StopReason.TIMEOUT}:
        return ExitCode.BUDGET_STOP
    if envelope.stop_reason is StopReason.PROVIDER_ERROR:
        return ExitCode.PROVIDER_UNAVAILABLE
    return ExitCode.FAILURE


def _exception_exit_code(error: Exception) -> ExitCode:
    if type(error).__name__ in {"ProviderCredentialError", "ProviderAuthenticationError"}:
        return ExitCode.PROVIDER_UNAVAILABLE
    if type(error).__name__ in {"BudgetExceededError", "ProviderTimeoutError"}:
        return ExitCode.BUDGET_STOP
    if type(error).__name__ in {"PolicyBlockedError", "PolicyDeniedError"}:
        return ExitCode.POLICY_BLOCKED
    return ExitCode.FAILURE
