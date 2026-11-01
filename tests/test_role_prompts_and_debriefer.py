"""Tests for the role prompts (Phase 1 / Phase 2 framing) and the
Debriefer's RESEARCH CONTEXT block (Phase 4).

Covers:
  * Role prompts include the STRATEGIC DEPTH block (epistemic honesty,
    "no off-the-shelf methodology", elaborate-where-conviction).
  * Artefact framings include the same depth reminder.
  * The Debriefer's RESEARCH CONTEXT block contains the study's
    research question + theoretical lens, framed as background for
    relevance judgement only, with the anti-steering binding rule.
  * The orchestrator detects near-verbatim repeat questions and
    re-prompts the debriefer.
  * The coverage map nags the debriefer about non-F areas still at
    zero exchanges.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass

import pytest

PKG = "open-innovation-strategy"


def _conc():
    return importlib.import_module(f"{PKG}.orchestrator.concurrent_mode")


def _artefact_collection():
    return importlib.import_module(f"{PKG}.orchestrator.artefact_collection")


def _pd():
    return importlib.import_module(f"{PKG}.orchestrator.panel_debriefing")


def _rs():
    return importlib.import_module(f"{PKG}.roles.researcher_schemas")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _StubAgent:
    name: str
    instruction: str = ""
    model: str = "stub-model"


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


def _make_state(role: str = "CTO"):
    c = _conc()
    return c.RoleState(role=role, scratchpad=[], draft="", inbox=[])


# ===========================================================================
# 1. Item 2 — Role prompts ask for soft 5W + lifecycle engagement
# ===========================================================================

class TestRolePromptStrategicDepth:
    """The concurrent-deliberation role prompt asks each role to
    engage with strategic depth + epistemic honesty + own-words
    framing (no off-the-shelf methodology label, no enumerated
    dimensions checklist)."""

    def test_prompt_includes_strategic_depth_block(self):
        c = _conc()
        p = c._compose_role_prompt(
            role="CTO", task=_make_task("CTO"),
            my_state=_make_state("CTO"), transcript=[],
        )
        assert "STRATEGIC DEPTH" in p

    def test_prompt_keeps_epistemic_honesty_rule(self):
        """Even without the dimension enumeration the prompt must still
        encourage flagging uncertainty rather than fabricating
        confidence."""
        c = _conc()
        p = c._compose_role_prompt(
            role="CTO", task=_make_task("CTO"),
            my_state=_make_state("CTO"), transcript=[],
        )
        lower = p.lower()
        assert "we don't know" in lower
        assert "fabricat" in lower  # "fabricate" / "fabricating"

    def test_prompt_applies_to_every_role_not_just_cto(self):
        """The depth block + epistemic-honesty phrasing should be in
        every role's prompt — they're team-wide framing rules, not
        CTO-only."""
        c = _conc()
        for role in ("CEO", "CTO", "COO", "CMO",
                     "Product_Strategist", "Product_Designer"):
            p = c._compose_role_prompt(
                role=role, task=_make_task(role),
                my_state=_make_state(role), transcript=[],
            )
            assert "STRATEGIC DEPTH" in p, (
                f"{role} prompt missing STRATEGIC DEPTH block"
            )
            assert "we don't know" in p.lower(), (
                f"{role} prompt missing epistemic-honesty phrasing"
            )


# ===========================================================================
# 2. Artefact framings: depth reminder appended, but no dimension list
# ===========================================================================

class TestArtefactFramingDepth:
    """Each role's artefact framing includes the shared depth
    reminder (elaborate writing + epistemic honesty + own-words
    methodology framing)."""

    def test_depth_reminder_appended_to_every_role_framing(self):
        """The DEPTH reminder is appended verbatim to every role's
        framing so the rule applies team-wide."""
        ac = _artefact_collection()
        reminder = ac._DEPTH_REMINDER
        for role, framing in ac._ROLE_DOC_FRAMING.items():
            assert reminder in framing, (
                f"{role} framing should include the shared "
                f"_DEPTH_REMINDER constant verbatim"
            )

    def test_each_framing_says_in_your_own_words(self):
        """Roles should describe their approach in their own words
        rather than borrowing an off-the-shelf methodology."""
        ac = _artefact_collection()
        for role, framing in ac._ROLE_DOC_FRAMING.items():
            lower = framing.lower()
            assert "own words" in lower, (
                f"{role} framing missing 'in your own words' phrasing"
            )

    def test_depth_reminder_keeps_epistemic_honesty(self):
        """The reminder must contain the epistemic-honesty phrase
        regardless of any other content."""
        ac = _artefact_collection()
        reminder = ac._DEPTH_REMINDER
        lower = reminder.lower()
        assert "don't know" in lower
        assert "fabricat" in lower


# ===========================================================================
# 3. Item 8 — Debriefer prompt has the RESEARCH-QUESTION LENS block
# ===========================================================================

class TestDebrieferResearchQuestionLens:
    """The debriefer's system prompt should be grounded in the
    openness-maneuvering research question, so that the questions it
    asks are RQ-relevant rather than meandering. The forbidden-vocab
    rule still binds — the lens drives which anchor items to choose,
    not the words used in the probes.
    """

    def _make_observation_summary(self):
        rs = _rs()
        return rs.ObservationSummary(
            decisions=["keep inference API internal"],
            components=["inference API"],
            disagreements=[],
            commitments=[],
            uncertainties=[],
            notable_quotes=[],
            timeline_markers=[],
        )

    def _build(self, study=None):
        pd = _pd()
        return pd._build_debriefer(
            company="OpenAI",
            observation_summary=self._make_observation_summary(),
            artefacts=None,
            industry_context="Dynamic",
            product_type="Novel",
            model=None,
            study=study,
        )

    def _openness_study(self):
        return importlib.import_module(f"{PKG}.studies").load_study(
            "openness_maneuvering"
        )

    def test_debriefer_instruction_contains_research_context_header(self):
        agent = self._build(study=self._openness_study())
        assert "RESEARCH CONTEXT" in agent.instruction

    def test_debriefer_instruction_includes_study_research_question(self):
        """The debriefer must see the study's research question text —
        verbatim — inside its prompt. This is what makes the prompt
        study-driven (rather than reading from a hardcoded constant)."""
        study = self._openness_study()
        agent = self._build(study=study)
        # The first ~60 chars of the RQ should appear verbatim.
        rq_snippet = study.research_question[:60]
        assert rq_snippet in agent.instruction

    def test_debriefer_instruction_includes_theoretical_lens(self):
        study = self._openness_study()
        agent = self._build(study=study)
        # First 60 chars of the lens.
        lens_snippet = study.theoretical_lens[:60]
        assert lens_snippet in agent.instruction

    def test_debriefer_instruction_forbids_steering(self):
        """The new RESEARCH CONTEXT framing must explicitly tell the
        debriefer that the RQ may or may not be answered, and not to
        steer the panel toward it."""
        agent = self._build(study=self._openness_study())
        lower = agent.instruction.lower()
        assert "may or may not" in lower
        assert ("do not steer" in lower) or ("absence is itself" in lower)

    def test_debriefer_instruction_keeps_forbidden_vocab_rule(self):
        """The forbidden-vocab rule must still bind. The merged list
        includes the study's construct vocabulary."""
        agent = self._build(study=self._openness_study())
        instr = agent.instruction
        assert "FORBIDDEN VOCABULARY" in instr
        # Study-specific construct words appear in the merged list.
        assert "'open'" in instr


# ===========================================================================
# 4. Item 8 — Repeat detection on the proposed researcher utterance
# ===========================================================================

class TestRepeatDetection:
    """The orchestrator detects near-verbatim repeats among the last
    few exchanges and re-prompts the debriefer. This was triggered by
    the smoke run producing exchange 6 ≡ exchange 7.
    """

    def _empty_transcript(self):
        pd = _pd()
        return pd.DebriefingTranscript(company="OpenAI", research_question="rq")

    def _push(self, transcript, text: str, addressed_to: str = "CTO"):
        rs = _rs()
        transcript.exchanges.append(rs.PanelExchange(
            utterance=rs.PanelUtterance(
                area_id="A",
                addressed_to=addressed_to,
                text=text,
                anchor_refs=["inference API"],
            ),
            responses=[],
        ))

    def test_detects_verbatim_repeat(self):
        pd = _pd()
        t = self._empty_transcript()
        self._push(t, "Walk me through the inference decision.")
        idx = pd._detect_recent_repeat(
            "Walk me through the inference decision.", t,
        )
        assert idx == 0

    def test_detects_near_verbatim_repeat(self):
        pd = _pd()
        t = self._empty_transcript()
        self._push(t, "Walk me through the inference decision, in detail.")
        idx = pd._detect_recent_repeat(
            "Walk me through the inference decision.", t,
        )
        # High Jaccard ≥ 0.65 → flagged as repeat.
        assert idx == 0

    def test_does_not_flag_genuinely_different_question(self):
        pd = _pd()
        t = self._empty_transcript()
        self._push(t, "Walk me through the inference decision.")
        idx = pd._detect_recent_repeat(
            "Who at the table pushed back against using the partner SDK?",
            t,
        )
        assert idx is None

    def test_only_looks_back_three_exchanges(self):
        pd = _pd()
        t = self._empty_transcript()
        # Old utterance that should NOT count (outside lookback window).
        self._push(t, "Walk me through the inference decision.")
        # 3 unrelated newer ones — these are the lookback window.
        self._push(t, "Tell me about the launch timeline.")
        self._push(t, "Tell me about the team composition.")
        self._push(t, "Tell me about the partner agreements.")
        idx = pd._detect_recent_repeat(
            "Walk me through the inference decision.", t,
        )
        # Exchange 0 is outside the last-3 window → not flagged.
        assert idx is None

    def test_empty_transcript_returns_none(self):
        pd = _pd()
        t = self._empty_transcript()
        idx = pd._detect_recent_repeat("anything", t)
        assert idx is None

    def test_empty_new_text_returns_none(self):
        pd = _pd()
        t = self._empty_transcript()
        self._push(t, "Walk me through the inference decision.")
        idx = pd._detect_recent_repeat("", t)
        assert idx is None


class TestTokenset:
    """Tokenset helper used by the repeat detector."""

    def test_lowercases_and_strips_punctuation(self):
        pd = _pd()
        out = pd._tokenset("Walk me through, IT, please!")
        assert out == {"walk", "me", "through", "it", "please"}

    def test_returns_empty_set_on_empty_string(self):
        pd = _pd()
        assert pd._tokenset("") == set()

    def test_handles_unicode_dashes_and_keeps_alphanumerics(self):
        pd = _pd()
        out = pd._tokenset("inference — API v2")
        assert "inference" in out
        assert "api" in out
        assert "v2" in out


# ===========================================================================
# 5. Item 8 — Coverage map nags about untouched non-F areas
# ===========================================================================

class TestUntouchedAreaNag:
    """Coverage map should call out non-F areas that are still at zero
    exchanges, so the debriefer notices the missing area B (etc.)
    rather than silently skipping it.
    """

    def _empty_transcript(self):
        pd = _pd()
        return pd.DebriefingTranscript(company="OpenAI", research_question="rq")

    def _push(self, transcript, area_id: str):
        rs = _rs()
        transcript.exchanges.append(rs.PanelExchange(
            utterance=rs.PanelUtterance(
                area_id=area_id,
                addressed_to="CTO",
                text=f"Probe in area {area_id}.",
                anchor_refs=["x"],
            ),
            responses=[],
        ))

    def test_lists_untouched_non_closing_areas_explicitly(self):
        pd = _pd()
        t = self._empty_transcript()
        # Cover only A (with all 10 default areas A-J in play).
        self._push(t, "A")
        out = pd._render_coverage_map(t)
        assert "Untouched non-closing areas" in out
        # B and I (other non-closing areas) are still untouched.
        for area in ("B", "C", "I"):
            assert area in out

    def test_no_nag_when_all_non_closing_areas_touched(self):
        """When every area except the closing one (J) has been
        touched at least once, the nag is suppressed."""
        pd = _pd()
        t = self._empty_transcript()
        # Cover every area in the default 10-area layout except J.
        for area in ("A", "B", "C", "D", "E", "F", "G", "H", "I"):
            self._push(t, area)
        out = pd._render_coverage_map(t)
        assert "Untouched non-closing areas" not in out

    def test_closing_area_zero_does_not_appear_in_untouched_nag(self):
        """The closing area (J under the current protocol) has its
        own closing-area rule; it must not appear in the
        untouched-non-closing nag to avoid a duplicate signal."""
        pd = _pd()
        t = self._empty_transcript()
        self._push(t, "A")
        out = pd._render_coverage_map(t)
        for line in out.splitlines():
            if line.startswith("  Untouched non-closing areas"):
                assert "J" not in line.split(":")[1]

    def test_nag_message_tells_researcher_not_to_skip_silently(self):
        pd = _pd()
        t = self._empty_transcript()
        self._push(t, "A")
        out = pd._render_coverage_map(t)
        assert "skip silently" in out.lower() or "not skip silently" in out.lower()
