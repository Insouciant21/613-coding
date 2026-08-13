"""Progress bridging and stable terminal output serializers."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from threading import Lock
from uuid import UUID

from coding613.domain.events import redact_payload
from coding613.domain.session_events import (
    EventType,
    RunEnvelope,
    SessionEnvelope,
    SessionEvent,
)
from coding613.ports.events import EventSink
from coding613.ports.progress import ProgressKind, ProgressSink, RunProgress


class SequencedEventSink:
    """Assign ordered sequence numbers before forwarding events."""

    def __init__(self, downstream: EventSink) -> None:
        self._downstream = downstream
        self._sequence = 0
        self._lock = Lock()

    def publish(self, event: SessionEvent) -> None:
        with self._lock:
            self._sequence += 1
            sequenced = event.model_copy(update={"sequence": self._sequence})
        self._downstream.publish(sequenced)


class ProgressEventBridge:
    """Adapt ephemeral loop progress to the shared session event contract."""

    def __init__(
        self,
        session_id: UUID,
        run_id: UUID,
        events: EventSink,
        progress: ProgressSink | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_id = session_id
        self._run_id = run_id
        self._events = events
        self._progress = progress
        self._clock = clock or (lambda: datetime.now(UTC))

    def publish(self, update: RunProgress) -> None:
        if update.run_id != self._run_id:
            raise ValueError("progress run does not match event bridge run")
        if self._progress is not None:
            self._progress.publish(update)
        event_type = self._event_type(update)
        data = dict(update.payload)
        if update.text:
            data.setdefault("text", update.text)
        self._events.publish(
            SessionEvent(
                session_id=self._session_id,
                run_id=self._run_id,
                type=event_type,
                timestamp=self._clock(),
                data=redact_payload(data),
            )
        )

    @staticmethod
    def _event_type(update: RunProgress) -> EventType:
        if update.kind is ProgressKind.TEXT_DELTA:
            return EventType.ASSISTANT_DELTA
        if update.kind is ProgressKind.TOOL_STARTED:
            return EventType.TOOL_STARTED
        if update.kind is ProgressKind.TOOL_FINISHED:
            return EventType.TOOL_FINISHED
        if update.kind is ProgressKind.VALIDATION_STARTED:
            return EventType.VALIDATION_STARTED
        if update.kind is ProgressKind.VALIDATION_FINISHED:
            return EventType.VALIDATION_FINISHED
        if update.kind is ProgressKind.ERROR:
            return EventType.RUN_FAILED
        state = str(update.payload.get("to", update.text)).lower()
        return EventType.RUN_PAUSED if state == "paused" else EventType.RUN_STATE


class StreamJsonSerializer:
    def render_event(self, event: SessionEvent) -> str:
        return (
            json.dumps(
                redact_payload(event.model_dump(mode="json")),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )


class JsonOutputSerializer:
    def render(self, envelope: RunEnvelope) -> str:
        return self._render_value(envelope)

    def render_session(self, envelope: SessionEnvelope) -> str:
        return self._render_value(envelope)

    @staticmethod
    def _render_value(value: RunEnvelope | SessionEnvelope) -> str:
        return (
            json.dumps(
                redact_payload(value.model_dump(mode="json")),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )


class TextOutputSerializer:
    def render(self, envelope: RunEnvelope, verbose: bool = False) -> str:
        lines: list[str] = []
        if envelope.assistant_text:
            lines.append(envelope.assistant_text)
        lines.append(
            f"status={envelope.status.value} "
            f"stop_reason={envelope.stop_reason.value if envelope.stop_reason else 'none'} "
            f"permission_mode={envelope.permission_mode.value}"
        )
        if verbose:
            if envelope.changed_files:
                lines.append("changed_files=" + ",".join(envelope.changed_files))
            if envelope.validation_evidence:
                lines.append(
                    "validation_evidence="
                    + json.dumps(
                        redact_payload(envelope.validation_evidence),
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
            if envelope.completion_blockers:
                lines.append(
                    "completion_blockers="
                    + ",".join(item.value for item in envelope.completion_blockers)
                )
            if envelope.approvals:
                lines.append(f"approvals={len(envelope.approvals)}")
            if envelope.diagnostics is not None:
                lines.append(
                    "diagnostics="
                    + json.dumps(
                        redact_payload(envelope.diagnostics.model_dump(mode="json")),
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
            lines.append(
                "resource_usage="
                + json.dumps(
                    envelope.resource_usage.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        return "\n".join(lines) + "\n"


def assistant_text_from_events(events: Sequence[SessionEvent]) -> str:
    return "".join(
        str(event.data.get("text", ""))
        for event in events
        if event.type is EventType.ASSISTANT_DELTA
    )
