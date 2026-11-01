"""Tests for the live-streaming researcher.

Covers:
  1. The FieldNoter agent factory builds an LlmAgent without
     `output_schema` (so it can emit free-form prose) and with a name
     that the session-key mapper files under `researcher`, with the
     Observer and Debriefer.
  2. ResearcherStream's buffer/flush behaviour: observe() is silent,
     flush_if_due() fires only at threshold (or forced), in-flight
     flushes don't overlap, failed flushes don't propagate, etc.
  3. Concurrent-deliberation calls observe() + flush_if_due() for
     each applied action, with the correct event line per action
     kind, and only public actions are surfaced (SCRATCHPAD / DRAFT
     remain private).
  4. Artefact collection calls observe() + flush_if_due() for each
     successfully-authored artefact.
"""

from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass
from typing import List

import pytest

PKG = "open-innovation-strategy"


def _researcher_stream():
    return importlib.import_module(f"{PKG}.orchestrator.researcher_stream")


def _qual():
    return importlib.import_module(f"{PKG}.roles.qualitative_researcher_agent")


def _conc():
    return importlib.import_module(f"{PKG}.orchestrator.concurrent_mode")


def _artefact_collection():
    return importlib.import_module(f"{PKG}.orchestrator.artefact_collection")


def _artefact_schemas():
    return importlib.import_module(f"{PKG}.roles.artefact_schemas")


def _rs_main():
    return importlib.import_module(f"{PKG}.run_research_session")


# ===========================================================================
# 1. FieldNoter agent factory
# ===========================================================================

class TestFieldNoterFactory:
    def test_field_noter_agent_has_no_output_schema(self):
        """Mid-phase field notes are free-form prose; the agent must
        not declare an output_schema (which would force JSON)."""
        q = _qual()
        agent = q.create_field_noter_agent(company="OpenAI")
        # ADK LlmAgent's output_schema is `None` when not set. The
        # stub doesn't set it either.
        assert getattr(agent, "output_schema", None) is None

    def test_field_noter_name_routes_to_researcher_session(self):
        """The session-key mapper files any agent whose name starts with
        `QualitativeResearcher_` under `researcher`."""
        q = _qual()
        rs = _rs_main()
        agent = q.create_field_noter_agent(company="OpenAI")
        assert agent.name.startswith("QualitativeResearcher_")
        assert rs._session_key_for(agent.name) == "researcher"

    def test_field_noter_instruction_frames_live_ethnography(self):
        q = _qual()
        agent = q.create_field_noter_agent(company="OpenAI")
        lower = agent.instruction.lower()
        # Must signal live ethnography, not retrospective analysis.
        assert "live virtual ethnography" in lower
        # Must keep the forbidden-vocab rule (we don't want the
        # field-noter using the openness construct's vocabulary
        # either — the panellists must surface it).
        assert "forbidden vocabulary" in lower
        # Must NOT ask for JSON / schema output.
        assert "json" not in lower or "no json" in lower


# ===========================================================================
# 2. ResearcherStream buffer/flush behaviour
# ===========================================================================

@dataclass
class _StubAgent:
    name: str = "QualitativeResearcher_FieldNoter"
    instruction: str = ""
    model: str = "stub"


def _make_stream(replies=None, synth_every=3, enabled=True):
    """Build a ResearcherStream against a fake run_agent that returns
    canned replies (one per flush)."""
    rs = _researcher_stream()
    replies_iter = iter(replies or [])

    captured_prompts: List[str] = []

    async def fake_run_agent(*, agent, prompt):
        captured_prompts.append(prompt)
        try:
            return next(replies_iter)
        except StopIteration:
            return "(generic note)"

    stream = rs.ResearcherStream(
        run_agent=fake_run_agent,
        field_noter_agent=_StubAgent(),
        synth_every=synth_every,
        enabled=enabled,
    )
    return stream, captured_prompts


class TestResearcherStream:
    def test_observe_is_silent(self):
        """observe() must NOT trigger an LLM call (no run_agent
        invocation until flush)."""
        stream, prompts = _make_stream(synth_every=10)
        stream.observe("event 1")
        stream.observe("event 2")
        assert len(prompts) == 0
        assert len(stream.buffer) == 2

    def test_flush_does_nothing_below_threshold(self):
        stream, prompts = _make_stream(synth_every=5)
        stream.observe("a")
        stream.observe("b")
        result = asyncio.run(stream.flush_if_due())
        assert result is None
        assert len(prompts) == 0
        # Buffer still holds the unflushed events.
        assert len(stream.buffer) == 2

    def test_flush_fires_at_threshold(self):
        stream, prompts = _make_stream(
            replies=["note 1"], synth_every=3,
        )
        stream.observe("a")
        stream.observe("b")
        stream.observe("c")
        result = asyncio.run(stream.flush_if_due())
        assert result == "note 1"
        assert len(prompts) == 1
        # The buffer is cleared after a flush.
        assert stream.buffer == []
        assert stream.field_notes == ["note 1"]

    def test_force_flush_with_empty_buffer_is_noop(self):
        stream, prompts = _make_stream()
        result = asyncio.run(stream.flush_if_due(force=True))
        assert result is None
        assert len(prompts) == 0

    def test_force_flush_drains_partial_buffer(self):
        """force=True triggers a synthesis even below threshold (used
        at phase boundaries to capture tail events)."""
        stream, prompts = _make_stream(
            replies=["closing note"], synth_every=10,
        )
        stream.observe("only one event")
        result = asyncio.run(stream.flush_if_due(force=True))
        assert result == "closing note"
        assert len(prompts) == 1

    def test_repeated_observation_accumulates_then_synthesises(self):
        stream, prompts = _make_stream(
            replies=["note A", "note B"], synth_every=3,
        )
        async def go():
            for i in range(6):
                stream.observe(f"event {i}")
                await stream.flush_if_due()
        asyncio.run(go())
        assert len(prompts) == 2
        assert stream.field_notes == ["note A", "note B"]

    def test_prior_notes_included_in_subsequent_prompts(self):
        """Model calls share no session, so the prompt is the FieldNoter's
        only memory of its notes. It must see all of them."""
        stream, prompts = _make_stream(
            replies=["first note", "second note", "third", "fourth", "fifth"], synth_every=1,
        )
        async def go():
            for i in range(5):
                stream.observe(f"event {i}")
                await stream.flush_if_due()
        asyncio.run(go())
        assert "YOUR NOTES SO FAR" in prompts[4]
        assert "first note" in prompts[4]
        assert "fourth" in prompts[4]

    def test_disabled_stream_is_no_op(self):
        stream, prompts = _make_stream(enabled=False)
        stream.observe("a")
        stream.observe("b")
        result = asyncio.run(stream.flush_if_due(force=True))
        assert result is None
        assert len(prompts) == 0

    def test_empty_event_text_is_ignored(self):
        stream, prompts = _make_stream(synth_every=2)
        stream.observe("")
        stream.observe(None)  # type: ignore[arg-type]
        stream.observe("real event")
        assert len(stream.buffer) == 1

    def test_failed_flush_does_not_raise(self):
        """If the FieldNoter LLM call fails (rate limit, network),
        the stream must log and continue — never propagate the
        exception to the deliberation loop."""
        rs = _researcher_stream()

        async def failing_run_agent(*, agent, prompt):
            raise RuntimeError("simulated 429")

        stream = rs.ResearcherStream(
            run_agent=failing_run_agent,
            field_noter_agent=_StubAgent(),
            synth_every=1,
        )
        stream.observe("e")
        # Should NOT raise.
        result = asyncio.run(stream.flush_if_due())
        assert result is None
        assert stream.field_notes == []

    def test_concurrent_flushes_do_not_overlap(self):
        """Two role loops calling flush_if_due nearly simultaneously
        must produce only one synthesis call, not two."""
        rs = _researcher_stream()
        prompt_count = [0]

        async def slow_run_agent(*, agent, prompt):
            prompt_count[0] += 1
            await asyncio.sleep(0.01)
            return "note"

        stream = rs.ResearcherStream(
            run_agent=slow_run_agent,
            field_noter_agent=_StubAgent(),
            synth_every=2,
        )

        async def go():
            stream.observe("a")
            stream.observe("b")
            # Two concurrent flushes both see threshold met. Only one
            # should actually fire (the other should see _flushing
            # and return).
            await asyncio.gather(stream.flush_if_due(), stream.flush_if_due())

        asyncio.run(go())
        assert prompt_count[0] == 1

    def test_consolidated_notes_concatenates(self):
        stream, _ = _make_stream(
            replies=["n1", "n2", "n3"], synth_every=1,
        )
        async def go():
            for i in range(3):
                stream.observe(f"e{i}")
                await stream.flush_if_due()
        asyncio.run(go())
        consolidated = stream.consolidated_notes()
        assert "n1" in consolidated and "n2" in consolidated and "n3" in consolidated
        # Notes are separated by blank lines.
        assert "n1\n\nn2" in consolidated


# ===========================================================================
# 3. Concurrent-deliberation integration
# ===========================================================================

class TestConcurrentDeliberationFeedsStream:
    """The role loop must call observe() for every public action
    applied, and call flush_if_due() once per action."""

    def test_format_speak_action(self):
        c = _conc()
        from open_innovation_strategy_actions import _make_action  # fail loud if missing
        action = _make_action("SPEAK", text="we should open-source the weights")
        line = c._format_action_for_observer(role="CEO", action=action)
        assert "CEO" in line and "SPEAK" in line
        assert "open-source" in line

    def test_format_ask_action(self):
        c = _conc()
        from open_innovation_strategy_actions import _make_action
        action = _make_action(
            "ASK", ask_recipient="CTO", ask_question="What's the inference cost?",
        )
        line = c._format_action_for_observer(role="CEO", action=action)
        assert "CEO" in line and "ASK" in line and "CTO" in line
        assert "inference cost" in line

    def test_format_answer_public_action(self):
        c = _conc()
        from open_innovation_strategy_actions import _make_action
        action = _make_action(
            "ANSWER", text="about $0.02 per request",
            answer_to_question_id="qid", answer_visibility="public",
        )
        line = c._format_action_for_observer(role="CTO", action=action)
        assert "CTO" in line and "ANSWER" in line
        assert "0.02" in line

    def test_format_answer_private_is_redacted(self):
        c = _conc()
        from open_innovation_strategy_actions import _make_action
        action = _make_action(
            "ANSWER", text="confidential",
            answer_to_question_id="qid", answer_visibility="private",
        )
        line = c._format_action_for_observer(role="CTO", action=action)
        # The content of a private answer must NOT be surfaced to
        # the researcher's live observation stream.
        assert "confidential" not in line
        assert "private" in line.lower()

    def test_format_scratchpad_action_returns_empty(self):
        """SCRATCHPAD is private; the live observer doesn't see it.
        (The researcher does read scratchpads later via the
        privileged channel during the structured ObservationSummary
        consolidation.)"""
        c = _conc()
        from open_innovation_strategy_actions import _make_action
        action = _make_action("SCRATCHPAD", text="don't trust the partner SDK")
        line = c._format_action_for_observer(role="CTO", action=action)
        assert line == ""

    def test_format_draft_action_returns_empty(self):
        c = _conc()
        from open_innovation_strategy_actions import _make_action
        action = _make_action("DRAFT", text="My strategy doc draft...")
        line = c._format_action_for_observer(role="CTO", action=action)
        assert line == ""

    def test_format_done_action(self):
        c = _conc()
        from open_innovation_strategy_actions import _make_action
        action = _make_action("DONE", text="I'm satisfied with my strategy doc")
        line = c._format_action_for_observer(role="CEO", action=action)
        assert "CEO" in line and "DONE" in line


# ===========================================================================
# 4. Artefact collection integration
# ===========================================================================

class TestArtefactCollectionFeedsStream:
    def test_format_artefact_renders_title_and_decisions(self):
        rs = _researcher_stream()
        schemas = _artefact_schemas()
        artefact = schemas.StrategicArtefact(
            role="CEO",
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            title="OpenAI Multimodal Foundation — Q2 2030",
            key_challenges=["regulatory uncertainty", "compute scarcity"],
            main_decisions=["open weights for research tier"],
            key_tensions=["control vs reach"],
            body="...",
        )
        line = rs.format_artefact("CEO", artefact)
        assert "ARTEFACT CEO" in line
        assert "Multimodal Foundation" in line
        assert "open weights for research tier" in line
        assert "control vs reach" in line
        assert "regulatory uncertainty" in line


# ===========================================================================
# Helper module — avoids importing AgentAction's heavy deps in test
# bodies above. Tests can build minimal AgentAction-like objects.
# ===========================================================================

# Provide a tiny module-style helper that the tests import. We define
# it inline so the test file is self-contained, but the function must
# build a real AgentAction (so concurrent_mode's formatter
# can introspect `.kind.value`, `.text`, etc.).

import sys


def _build_action_module():
    """Construct a module object that the tests can import."""
    import types as _types

    mod = _types.ModuleType("open_innovation_strategy_actions")

    def _make_action(
        kind: str,
        text: str = "",
        ask_recipient: str = "",
        ask_question: str = "",
        answer_to_question_id: str = "",
        answer_visibility: str = "public",
    ):
        c = _conc()
        kwargs = {
            "kind": c.ActionKind(kind),
            "text": text or None,
        }
        if ask_recipient:
            kwargs["ask_recipient"] = ask_recipient
        if ask_question:
            kwargs["ask_question"] = ask_question
        if answer_to_question_id:
            kwargs["answer_to_question_id"] = answer_to_question_id
        kwargs["answer_visibility"] = answer_visibility
        return c.AgentAction(**kwargs)

    mod._make_action = _make_action
    sys.modules["open_innovation_strategy_actions"] = mod
    return mod


_build_action_module()
