"""Tests for the structured deliberation-log capture.

Covers:
- `DeliberationEvent` / `DeliberationLog` schemas round-trip.
- `walk_events` extracts author, addressee, kind, and text from
  duck-typed ADK-style event objects.
- `as_plain_transcript` produces a readable block suitable for prompt
  injection into the observer agent.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass

import pytest

PKG = "open-innovation-strategy"


def _data_capture():
    return importlib.import_module(f"{PKG}.data_capture")


# ---------------------------------------------------------------------------
# Stub ADK events
# ---------------------------------------------------------------------------

@dataclass
class _StubPart:
    text: str


@dataclass
class _StubContent:
    parts: list
    role: str | None = None


class _StubTextEvent:
    """Mimics an ADK content event with .content.parts[].text."""

    def __init__(self, author: str, text: str):
        self.author = author
        self.content = _StubContent(parts=[_StubPart(text=text)])


class _StubDelegationEvent:
    """Mimics an A2A / sub-agent delegation event."""

    def __init__(self, author: str, target: str, text: str = ""):
        self.author = author
        self.transfer_to_agent = target
        self.content = _StubContent(parts=[_StubPart(text=text)] if text else [])


class _StubToolCallEvent:
    """Mimics a tool call event."""

    def __init__(self, author: str, tool_name: str):
        self.author = author
        self.tool_name = tool_name
        self.content = _StubContent(parts=[_StubPart(text=f"calling {tool_name}")])

    @property
    def __class__(self):  # type: ignore[override]
        # Force the type name to contain 'tool' and 'call' so the
        # classifier picks `tool_call`.
        class _ToolCallEvent:
            pass
        _ToolCallEvent.__name__ = "ToolCallEvent"
        return _ToolCallEvent


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWalkEvents:
    def test_empty_stream_produces_empty_log(self):
        dc = _data_capture()
        log = dc.walk_events(
            [],
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
        )
        assert log.company == "OpenAI"
        assert log.events == []
        assert log.finished_at is not None

    def test_text_event_is_captured(self):
        dc = _data_capture()
        log = dc.walk_events(
            [_StubTextEvent("CEO", "We should think about this carefully.")],
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
        )
        assert len(log.events) == 1
        ev = log.events[0]
        assert ev.role == "CEO"
        assert ev.kind == "text"
        assert ev.text == "We should think about this carefully."
        assert ev.addressed_to is None

    def test_delegation_event_records_target(self):
        dc = _data_capture()
        log = dc.walk_events(
            [_StubDelegationEvent("CEO", target="CTO", text="What's the technical risk?")],
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
        )
        ev = log.events[0]
        assert ev.role == "CEO"
        assert ev.addressed_to == "CTO"
        assert ev.text == "What's the technical risk?"

    def test_mixed_stream_preserves_order(self):
        dc = _data_capture()
        log = dc.walk_events(
            [
                _StubTextEvent("CEO", "Opening question."),
                _StubDelegationEvent("CEO", "CTO", "Need tech input"),
                _StubTextEvent("CTO", "Here is the technical reality."),
                _StubTextEvent("CEO", "Closing synthesis."),
            ],
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
        )
        roles_in_order = [e.role for e in log.events]
        assert roles_in_order == ["CEO", "CEO", "CTO", "CEO"]
        indices_in_order = [e.index for e in log.events]
        assert indices_in_order == [0, 1, 2, 3]

    def test_unknown_event_falls_through_to_other(self):
        dc = _data_capture()

        class _Mystery:
            pass

        log = dc.walk_events(
            [_Mystery()],
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
        )
        ev = log.events[0]
        assert ev.kind == "other"
        assert ev.role == "unknown"
        assert ev.raw_type == "_Mystery"


class TestPlainTranscript:
    def test_renders_role_and_addressee(self):
        dc = _data_capture()
        log = dc.walk_events(
            [
                _StubTextEvent("CEO", "Hello team."),
                _StubDelegationEvent("CEO", "CTO", "Need your view."),
                _StubTextEvent("CTO", "Here it is."),
            ],
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
        )
        transcript = log.as_plain_transcript()
        assert "CEO" in transcript
        assert "CTO" in transcript
        assert "Need your view." in transcript
        assert "Here it is." in transcript
        # The delegation line should mark the addressee.
        assert "CEO → CTO" in transcript


class TestSchemaRoundtrip:
    def test_deliberation_log_roundtrip(self):
        dc = _data_capture()
        log = dc.walk_events(
            [_StubTextEvent("CEO", "Hello.")],
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
        )
        blob = log.model_dump_json()
        revived = dc.DeliberationLog.model_validate_json(blob)
        assert revived.events[0].role == "CEO"
        assert revived.company == "OpenAI"
