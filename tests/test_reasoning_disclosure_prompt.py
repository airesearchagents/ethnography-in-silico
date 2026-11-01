"""Tests for the reasoning-disclosure discipline added to the role
prompt and to the `AgentAction` field descriptions.

Background. Phase-1 deliberation transcripts produced before PR-C
showed a clear pattern: regular SPEAK turns were substantive (~100-200
words with reasoning surfaced) but ASK / ANSWER "delegation" turns
were terse (~50-90 words, position-only, no reasoning visible). When
read top-to-bottom the deliberation looked richer in some places and
cryptic in others — exactly the user-reported "deliberation messages
are short and cryptic" complaint. The field-description for ASK /
ANSWER was bare ("the question text", "the reply text"); the LLM
defaulted to terseness because nothing in the prompt told it
otherwise.

PR-C operationalises a `REASONING DISCIPLINE` block in the role
prompt plus length + structure targets on `AgentAction.text` /
`AgentAction.ask_question`. The targets are ~120-180 words on
substantive turns (SPEAK / ANSWER position+reasoning) and ~80-120
words on directed turns (ASK / ANSWER), with three required visible
elements: position, reasoning (assumptions / trade-offs / what's
being trusted), and open questions.

These tests assert the prompt-level contract: the relevant phrases
land in the composed prompt and in the schema field descriptions.
They are content tests, not behavioural — the actual word-count
shift in deliberation transcripts is a live-run verification (a
post-merge smoke run of the same Meta/Dynamic/Novel cell), which
this file deliberately does not attempt.
"""

from __future__ import annotations

import importlib

PKG = "open-innovation-strategy"


def _cm():
    return importlib.import_module(f"{PKG}.orchestrator.concurrent_mode")


def _build_task() -> "object":
    """A minimal RoleTaskSpec suitable for prompt composition."""
    cm = _cm()
    return cm.RoleTaskSpec(
        role="CTO",
        company="TestFirm",
        industry_context="Dynamic",
        product_type="Novel",
        strategic_question="how should we think about openness here",
        product_description="",
        doc_framing="a CTO strategy memo of 800-1500 words",
    )


def _build_role_state() -> "object":
    cm = _cm()
    return cm.RoleState(role="CTO")


# ===========================================================================
# 1. REASONING DISCIPLINE block lands in the composed role prompt
# ===========================================================================

class TestReasoningDisciplineBlockInPrompt:
    def test_block_header_appears_in_composed_prompt(self):
        cm = _cm()
        prompt = cm._compose_role_prompt(
            role="CTO",
            task=_build_task(),
            my_state=_build_role_state(),
            transcript=[],
        )
        assert "REASONING DISCIPLINE" in prompt, (
            "the REASONING DISCIPLINE section header must land in the "
            "composed role prompt — that's the load-bearing block PR-C "
            "introduced to fix the cryptic-deliberation complaint."
        )

    def test_three_required_elements_named_explicitly(self):
        """Position / reasoning / unanswered questions — the three things
        every substantive utterance must make visible. Each must be
        called out by name in the block so the LLM has the contract
        spelled out rather than implied."""
        cm = _cm()
        prompt = cm._compose_role_prompt(
            role="CTO", task=_build_task(),
            my_state=_build_role_state(), transcript=[],
        )
        # Lowercased contains-check — robust against minor copy edits.
        lower = prompt.lower()
        assert "your position" in lower
        assert "your reasoning" in lower
        assert "your unanswered questions" in lower

    def test_block_demands_assumptions_tradeoffs_and_trust_be_surfaced(self):
        """The reasoning element must specifically name 'assumptions',
        'trade-offs', and the 'what you are trusting' meta-bookkeeping
        — these are the three sub-pieces that distinguish a reasoned
        contribution from a bare position statement."""
        cm = _cm()
        prompt = cm._compose_role_prompt(
            role="CTO", task=_build_task(),
            my_state=_build_role_state(), transcript=[],
        )
        lower = prompt.lower()
        assert "assumption" in lower
        assert "trade-off" in lower or "trade off" in lower or "tradeoff" in lower
        assert "trusting" in lower or "trust" in lower

    def test_block_states_word_count_targets(self):
        cm = _cm()
        prompt = cm._compose_role_prompt(
            role="CTO", task=_build_task(),
            my_state=_build_role_state(), transcript=[],
        )
        # Substantive turns target.
        assert "120-180" in prompt
        # Directed (ASK/ANSWER) target.
        assert "80-120" in prompt

    def test_block_includes_anti_pattern_callouts(self):
        """The 'What NOT to do' list operationalises the discipline
        with concrete negatives — vague endorsement, named-methodology-
        without-articulation, fabricated confidence. The LLM defaults
        toward exactly these patterns; the explicit callouts are what
        push it off the default."""
        cm = _cm()
        prompt = cm._compose_role_prompt(
            role="CTO", task=_build_task(),
            my_state=_build_role_state(), transcript=[],
        )
        lower = prompt.lower()
        # At least one of the four named anti-patterns must appear.
        anti_patterns = [
            "conclusions without reasoning",
            "named methodologies",
            "agree-with-everything",
            "fabricate confidence",
        ]
        assert any(p in lower for p in anti_patterns), (
            f"expected at least one of the four anti-pattern callouts "
            f"in the prompt, found none of: {anti_patterns}"
        )

    def test_block_anchors_concrete_example_of_thin_vs_substantive(self):
        """The 'I agree with the CTO' → 'I agree because [reason]; the
        assumption is [X]; the worry is [Y]' contrast example is the
        anchor that makes the abstract discipline concrete. Without it
        the LLM tends to comply only formally."""
        cm = _cm()
        prompt = cm._compose_role_prompt(
            role="CTO", task=_build_task(),
            my_state=_build_role_state(), transcript=[],
        )
        # The phrase "I agree with the CTO" anchors the contrast.
        assert "I agree with the CTO" in prompt or "I agree" in prompt


# ===========================================================================
# 2. AgentAction field descriptions carry the new structure
# ===========================================================================

class TestAgentActionFieldDescriptions:
    def test_text_field_describes_speak_target_and_three_elements(self):
        cm = _cm()
        text_field = cm.AgentAction.model_fields["text"]
        desc = text_field.description or ""
        assert "120-180" in desc, (
            "SPEAK utterances should target ~120-180 words; the field "
            "description carries that target so the LLM sees it in the "
            "schema as well as the prompt."
        )
        lower = desc.lower()
        assert "position" in lower
        assert "reasoning" in lower
        assert "open question" in lower

    def test_text_field_describes_answer_target(self):
        cm = _cm()
        desc = cm.AgentAction.model_fields["text"].description or ""
        assert "80-120" in desc, (
            "ANSWER replies should target ~80-120 words — directed turns "
            "are tighter than SPEAK but still need to surface reasoning."
        )

    def test_ask_question_field_describes_three_part_structure(self):
        cm = _cm()
        ask_field = cm.AgentAction.model_fields["ask_question"]
        desc = ask_field.description or ""
        # Length target.
        assert "80-120" in desc, (
            "ASK questions should target ~80-120 words. Bare one-line "
            "questions are the cryptic-deliberation failure mode PR-C "
            "specifically targets."
        )
        # Three-part structure: context → specific need → constraints.
        lower = desc.lower()
        assert "context" in lower
        assert "constraint" in lower
        # The 'bare one-line question is almost always too thin' framing
        # makes the discipline explicit.
        assert "too thin" in lower or "one-line" in lower

    def test_unchanged_fields_still_describe_their_purpose(self):
        """Sanity: other AgentAction fields kept their semantic
        descriptions. Catches accidental collateral damage from the
        prompt-engineering edit."""
        cm = _cm()
        fields = cm.AgentAction.model_fields
        # ask_recipient: still describes the addressee semantics.
        assert "role-name" in (fields["ask_recipient"].description or "").lower()
        # answer_visibility: still describes public / private.
        ans_vis = (fields["answer_visibility"].description or "").lower()
        assert "public" in ans_vis and "private" in ans_vis


# ===========================================================================
# 3. The block lives in the right ordering relative to its neighbours
# ===========================================================================

class TestBlockOrdering:
    def test_block_lands_between_strategic_depth_and_discussion_status(self):
        """REASONING DISCIPLINE sits AFTER the high-level depth framing
        (so the role reads about depth first) and BEFORE the per-turn
        status block (so the discipline is in mind when the LLM reads
        the immediate situation). Ordering matters — a mis-ordered
        block would make the discipline feel like an afterthought."""
        cm = _cm()
        prompt = cm._compose_role_prompt(
            role="CTO", task=_build_task(),
            my_state=_build_role_state(), transcript=[],
        )
        idx_strategic = prompt.find("STRATEGIC DEPTH")
        idx_reasoning = prompt.find("REASONING DISCIPLINE")
        idx_status = prompt.find("YOUR DISCUSSION STATUS")
        assert idx_strategic > -1
        assert idx_reasoning > -1
        assert idx_status > -1
        assert idx_strategic < idx_reasoning < idx_status
