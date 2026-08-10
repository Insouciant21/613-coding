from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from coding613.application.events import ProgressEventBridge, SequencedEventSink
from coding613.domain.session_events import EventType, SessionEvent
from coding613.ports.progress import ProgressKind, RunProgress


class RecordingEventSink:
    def __init__(self) -> None:
        self.events: list[SessionEvent] = []

    def publish(self, event: SessionEvent) -> None:
        self.events.append(event)


def test_progress_bridge_sequences_and_redacts_tool_output() -> None:
    session_id = uuid4()
    run_id = uuid4()
    recording = RecordingEventSink()
    bridge = ProgressEventBridge(
        session_id,
        run_id,
        SequencedEventSink(recording),
    )

    bridge.publish(
        RunProgress(
            run_id=run_id,
            kind=ProgressKind.TOOL_FINISHED,
            payload={"tool_call_id": "c1", "output": "token=secret-value"},
        )
    )
    bridge.publish(RunProgress(run_id=run_id, kind=ProgressKind.TEXT_DELTA, text="done"))

    assert [event.sequence for event in recording.events] == [1, 2]
    assert recording.events[0].type is EventType.TOOL_FINISHED
    assert recording.events[0].data["tool_call_id"] == "c1"
    assert "secret-value" not in json.dumps(recording.events[0].data)


def test_event_sink_reassigns_sequence_without_mutating_input() -> None:
    recording = RecordingEventSink()
    sink = SequencedEventSink(recording)
    event = SessionEvent(
        session_id=uuid4(),
        run_id=uuid4(),
        type=EventType.USER_MESSAGE,
        timestamp=datetime.now(UTC),
        data={"text": "hello"},
    )

    sink.publish(event)

    assert event.sequence == 1
    assert recording.events[0].sequence == 1
