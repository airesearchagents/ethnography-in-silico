"""Tests for discussion dynamics: role prompts, cross-talk routing, follow-ups.

Verifies:
  - Role-prompt structure: peers told to consult, CEO framed as
    facilitator/arbiter, status hints + nudges appear.
  - Cross-talk routing: addressed role first, others get a strict
    PASS-biased opt-in prompt referencing the addressee by name.
  - Researcher next-utterance prompt includes the "react to most-
    recent answer" block AND lists FOLLOW-UP vs AREA SWITCH options
    when there was a substantive prior response.
  - `_is_pass_response` detects literal PASS variants.
"""

from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass
from typing import List

import pytest

PKG = "open-innovation-strategy"


def _conc():
    return importlib.import_module(f"{PKG}.orchestrator.concurrent_mode")


def _pd():
    return importlib.import_module(f"{PKG}.orchestrator.panel_debriefing")


def _rs():
    return importlib.import_module(f"{PKG}.roles.researcher_schemas")


# ===========================================================================
# Helpers
# ===========================================================================

@dataclass
class _StubAgent:
    name: str
    instruction: str = ""
    model: str = "stub"


def _make_task(role: str = "CTO"):
    c = _conc()
    return c.RoleTaskSpec(
        role=role,
        company="OpenAI",
        industry_context="Dynamic",
        product_type="Novel",
        strategic_question="What should we build for 2030?",
        product_description="",
        doc_framing=f"{role} deliverable",
    )


def _make_state(
    role: str = "CTO",
    scratchpad=None,
    draft: str = "",
    inbox=None,
):
    c = _conc()
    return c.RoleState(
        role=role,
        scratchpad=scratchpad or [],
        draft=draft,
        inbox=inbox or [],
    )


# ===========================================================================
# 1. Role-prompt rewrites (item 1, 3)
# ===========================================================================

class TestRolePromptStructure:
    def test_peer_prompt_mentions_consulting_ceo_for_conflicts(self):
        c = _conc()
        p = c._compose_role_prompt(
            role="CTO", task=_make_task("CTO"),
            my_state=_make_state("CTO"), transcript=[],
        )
        assert "escalate" in p.lower() or "escalat" in p.lower()
        # Peer prompt should mention CEO as arbiter / final-call resolver.
        assert "CEO" in p

    def test_ceo_prompt_frames_facilitator_not_dictator(self):
        c = _conc()
        p = c._compose_role_prompt(
            role="CEO", task=_make_task("CEO"),
            my_state=_make_state("CEO"), transcript=[],
        )
        # CEO place-on-team block.
        assert "facilitate" in p.lower() or "arbiter" in p.lower() or "arbitrate" in p.lower()
        assert "SOFT rule" in p or "soft rule" in p.lower()
        # Explicit: must consult before deciding.
        assert "consult" in p.lower()

    def test_prompt_includes_discussion_status_block(self):
        c = _conc()
        p = c._compose_role_prompt(
            role="CTO", task=_make_task("CTO"),
            my_state=_make_state("CTO"), transcript=[],
        )
        assert "YOUR DISCUSSION STATUS" in p
        # Zero state on a fresh role.
        assert "Public contributions you've made (SPEAK): 0" in p
        assert "Questions you've asked peers (ASK from you): 0" in p

    def test_status_reflects_transcript_counts(self):
        c = _conc()
        # Build a fake transcript where CTO has SPOKEN once and ASKed once.
        transcript = [
            c.TranscriptEntry(index=0, role="CTO", kind="speak",
                              text="Tech is feasible."),
            c.TranscriptEntry(index=1, role="CTO", kind="ask_public_echo",
                              text="CMO, what's the market?",
                              addressed_to="CMO"),
            c.TranscriptEntry(index=2, role="CMO", kind="answer_public",
                              text="Large.",
                              answer_to_question_id="q1"),
        ]
        p = c._compose_role_prompt(
            role="CTO", task=_make_task("CTO"),
            my_state=_make_state("CTO"), transcript=transcript,
        )
        assert "Public contributions you've made (SPEAK): 1" in p
        assert "Questions you've asked peers (ASK from you): 1" in p

    def test_nudges_to_answer_inbox_when_open_asks(self):
        c = _conc()
        msg = c.DirectedMessage(
            id="qX", sender="CEO", recipient="CTO",
            kind="ASK", text="Tech risks?",
        )
        state = _make_state("CTO", inbox=[msg])
        p = c._compose_role_prompt(
            role="CTO", task=_make_task("CTO"),
            my_state=state, transcript=[],
        )
        # Guidance block should highlight inbox.
        assert "open question" in p.lower() or "OPEN QUESTION" in p

    def test_nudges_to_ask_peers_when_drafting_without_engagement(self):
        c = _conc()
        # Big draft, no transcript engagement.
        state = _make_state("CTO", draft="x" * 1000)
        p = c._compose_role_prompt(
            role="CTO", task=_make_task("CTO"),
            my_state=state, transcript=[],
        )
        # Guidance should call this out.
        assert "haven't ASKed any peer" in p or "haven't asked" in p.lower()


# ===========================================================================
# 2. Cross-talk routing (item 6)
# ===========================================================================

class TestCrossTalkOptIn:
    """For a role-addressed researcher utterance, only the addressed role
    answers freely; peers are invited via a PASS-biased opt-in prompt."""

    def _make_utterance(self, addressed_to: str):
        rs = _rs()
        return rs.PanelUtterance(
            area_id="A",
            addressed_to=addressed_to,
            text="Walk me through the inference API decision.",
            anchor_refs=["inference API"],
            is_followup=False,
            ends_debriefing=False,
        )

    def test_addressed_role_gets_full_answer_prompt(self):
        pd = _pd()
        # Capture prompts.
        sent: list[tuple[str, str]] = []

        async def runner(*, agent, prompt):
            sent.append((agent.name, prompt))
            return ""  # all PASS — we only inspect prompts here

        async def go():
            await pd._collect_panel_responses(
                utterance=self._make_utterance(addressed_to="CTO"),
                panel_agents={
                    "CEO": _StubAgent("CEO"), "CTO": _StubAgent("CTO"),
                    "COO": _StubAgent("COO"), "CMO": _StubAgent("CMO"),
                    "Product_Strategist": _StubAgent("Product_Strategist"),
                    "Product_Designer": _StubAgent("Product_Designer"),
                },
                history_block="(empty)",
                artefacts=None,
                run_agent=runner,
            )

        asyncio.run(go())

        # CTO's prompt: "addressed YOU (CTO) directly".
        cto_prompts = [p for name, p in sent if name == "CTO"]
        assert len(cto_prompts) == 1
        assert "addressed YOU (CTO) directly" in cto_prompts[0]
        # CEO's prompt: "researcher addressed CTO directly. You are CEO".
        ceo_prompts = [p for name, p in sent if name == "CEO"]
        assert len(ceo_prompts) == 1
        ceo_prompt = ceo_prompts[0]
        assert "addressed CTO directly" in ceo_prompt
        assert "DEFAULT: PASS" in ceo_prompt
        assert "BUILDS ON or CONTRADICTS what CTO just said" in ceo_prompt

    def test_strict_pass_prompt_dropped_responses_are_silence(self):
        pd = _pd()

        async def runner(*, agent, prompt):
            # Addressed role answers; others PASS.
            if agent.name == "CTO":
                return "I pushed for the inference API."
            return "[PASS]"

        async def go():
            return await pd._collect_panel_responses(
                utterance=self._make_utterance(addressed_to="CTO"),
                panel_agents={
                    "CEO": _StubAgent("CEO"), "CTO": _StubAgent("CTO"),
                    "COO": _StubAgent("COO"), "CMO": _StubAgent("CMO"),
                    "Product_Strategist": _StubAgent("Product_Strategist"),
                    "Product_Designer": _StubAgent("Product_Designer"),
                },
                history_block="(empty)",
                artefacts=None,
                run_agent=runner,
            )

        responses = asyncio.run(go())
        # Only CTO speaks; others all PASS.
        assert len(responses) == 1
        assert responses[0].role == "CTO"

    def test_group_addressed_uses_moderate_bias_prompt(self):
        pd = _pd()
        sent: list[tuple[str, str]] = []

        async def runner(*, agent, prompt):
            sent.append((agent.name, prompt))
            return "[PASS]"

        async def go():
            await pd._collect_panel_responses(
                utterance=self._make_utterance(addressed_to="group"),
                panel_agents={
                    "CEO": _StubAgent("CEO"), "CTO": _StubAgent("CTO"),
                },
                history_block="(empty)",
                artefacts=None,
                run_agent=runner,
            )

        asyncio.run(go())
        for _, p in sent:
            assert "addressed the WHOLE PANEL" in p
            # Not the strict-pass framing.
            assert "DEFAULT: PASS" not in p


# ===========================================================================
# 3. Researcher follow-up framing (item 9)
# ===========================================================================

class TestResearcherFollowupFraming:
    def test_first_turn_block_says_first_turn(self):
        pd = _pd()
        empty = pd.DebriefingTranscript(company="OpenAI", research_question="rq")
        out = pd._render_latest_exchange_for_followup(empty)
        assert "FIRST TURN" in out
        assert "Area A" in out

    def test_post_response_block_offers_followup_or_area_switch(self):
        pd = _pd()
        rs = _rs()
        transcript = pd.DebriefingTranscript(
            company="OpenAI", research_question="rq",
        )
        transcript.exchanges.append(rs.PanelExchange(
            utterance=rs.PanelUtterance(
                area_id="A", addressed_to="CTO",
                text="Walk me through the inference decision.",
                anchor_refs=["inference API"],
            ),
            responses=[
                rs.PanelResponse(
                    role="CTO",
                    text="The decision came from a 3-week capacity review.",
                    is_cross_talk=False,
                ),
            ],
        ))
        out = pd._render_latest_exchange_for_followup(transcript)
        assert "MOST RECENT EXCHANGE" in out
        assert "(a) FOLLOW-UP" in out
        assert "(b) AREA SWITCH" in out
        assert "is_followup=true" in out
        # The CTO's actual answer is quoted/previewed.
        assert "3-week capacity review" in out

    def test_no_responses_block_warns_about_repetition(self):
        pd = _pd()
        rs = _rs()
        transcript = pd.DebriefingTranscript(
            company="OpenAI", research_question="rq",
        )
        transcript.exchanges.append(rs.PanelExchange(
            utterance=rs.PanelUtterance(
                area_id="A", addressed_to="group",
                text="Walk me through the inference decision.",
                anchor_refs=["inference API"],
            ),
            responses=[],
        ))
        out = pd._render_latest_exchange_for_followup(transcript)
        assert "No panellist responded" in out
        assert "Do NOT repeat" in out


# ===========================================================================
# 4. _is_pass_response detection
# ===========================================================================

class TestIsPassResponse:
    @pytest.mark.parametrize("text", [
        "", " ", "[PASS]", "  [PASS]  ", "pass", "PASS",
        "(PASS)", "[No comment]", "NO COMMENT",
    ])
    def test_recognised_as_pass(self, text: str):
        pd = _pd()
        assert pd._is_pass_response(text) is True

    @pytest.mark.parametrize("text", [
        "I pushed for the inference API.",
        "Passing the buck is what I'd say.",  # phrase, not abstention
        "I disagree.",
    ])
    def test_substantive_text_not_pass(self, text: str):
        pd = _pd()
        assert pd._is_pass_response(text) is False
