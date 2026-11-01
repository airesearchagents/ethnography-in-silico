"""Methodological invariants — the load-bearing tests of the multi-study refactor.

These tests guard the boundary between *study framing* (research
question, theoretical lens, construct vocabulary) and *researcher
behaviour* (note-taking style, voice continuity, methodological
forbidden vocab, panel format).

The refactor's promise:
  * The Observer and FieldNoter are BLIND to the study's research
    question and theoretical lens. They observe and describe; they
    do not seek evidence of a specific construct.
  * The Debriefer KNOWS the research question and lens, but its
    prompt frames them as background context with a binding rule:
    "may or may not be answered — do not steer; if absent, that
    absence is itself a finding."
  * Swapping the study config swaps the Debriefer's prompt without
    affecting the Observer/FieldNoter prompts (modulo the flagged
    vocabulary watch-list, which is a capture mechanism).

The tests parameterise over two studies (`openness_maneuvering` +
`_test_alt`) so the assertions hold across genuinely different
vocabulary, not just for the framework's default.
"""

from __future__ import annotations

import importlib

import pytest

PKG = "open-innovation-strategy"


def _qual():
    return importlib.import_module(f"{PKG}.roles.qualitative_researcher_agent")


def _studies():
    return importlib.import_module(f"{PKG}.studies")


STUDY_SLUGS = ("openness_maneuvering", "_test_alt")


def _build_observer(slug):
    qual = _qual()
    s = _studies().load_study(slug)
    return qual.create_observer_agent(company="OpenAI", study=s), s


def _build_field_noter(slug):
    qual = _qual()
    s = _studies().load_study(slug)
    return qual.create_field_noter_agent(company="OpenAI", study=s), s


def _build_debriefer(slug):
    """Build the Debriefer (base agent, NOT _build_debriefer) so we can
    inspect the study-driven RESEARCH CONTEXT block in isolation.
    _build_debriefer appends artefact + scratchpad extras which aren't
    relevant here."""
    qual = _qual()
    rs = importlib.import_module(f"{PKG}.roles.researcher_schemas")
    s = _studies().load_study(slug)
    obs = rs.ObservationSummary(decisions=[], components=[])
    return qual.create_debriefer_agent(
        company="OpenAI",
        observation_summary=obs,
        model=None,
        study=s,
    ), s


# ===========================================================================
# 1. Observer is blind to RQ + lens
# ===========================================================================

@pytest.mark.parametrize("slug", STUDY_SLUGS)
class TestObserverIsBlindToStudyFraming:
    """The Observer's instruction must not leak the study's research
    question or theoretical lens. It can see the merged forbidden-
    vocabulary list and the flagged-vocabulary watch-list (those are
    capture mechanisms), but NOT the framing rationale."""

    def test_research_question_text_not_in_observer_instruction(self, slug):
        agent, study = _build_observer(slug)
        # Check a distinctive prefix substring (long enough to be
        # study-specific, short enough to survive minor rephrasing).
        rq_prefix = study.research_question[:50]
        assert rq_prefix not in agent.instruction, (
            f"Observer leaks research_question prefix for study {slug!r}"
        )

    def test_theoretical_lens_text_not_in_observer_instruction(self, slug):
        agent, study = _build_observer(slug)
        lens_prefix = study.theoretical_lens[:50]
        assert lens_prefix not in agent.instruction, (
            f"Observer leaks theoretical_lens prefix for study {slug!r}"
        )

    def test_observer_does_not_say_research_question(self, slug):
        agent, _ = _build_observer(slug)
        # Belt-and-braces — the literal phrase shouldn't appear either.
        assert "RESEARCH QUESTION" not in agent.instruction.upper().split("CONTEXT")[0]


# ===========================================================================
# 2. FieldNoter is blind to RQ + lens
# ===========================================================================

@pytest.mark.parametrize("slug", STUDY_SLUGS)
class TestFieldNoterIsBlindToStudyFraming:
    def test_research_question_text_not_in_field_noter_instruction(self, slug):
        agent, study = _build_field_noter(slug)
        rq_prefix = study.research_question[:50]
        assert rq_prefix not in agent.instruction, (
            f"FieldNoter leaks research_question prefix for study {slug!r}"
        )

    def test_theoretical_lens_text_not_in_field_noter_instruction(self, slug):
        agent, study = _build_field_noter(slug)
        lens_prefix = study.theoretical_lens[:50]
        assert lens_prefix not in agent.instruction, (
            f"FieldNoter leaks theoretical_lens prefix for study {slug!r}"
        )


# ===========================================================================
# 3. Debriefer DOES know RQ + lens, but with anti-steering framing
# ===========================================================================

@pytest.mark.parametrize("slug", STUDY_SLUGS)
class TestDebrieferSeesStudyFramingButNonSteering:
    def test_research_question_text_in_debriefer_instruction(self, slug):
        agent, study = _build_debriefer(slug)
        rq_prefix = study.research_question[:50]
        assert rq_prefix in agent.instruction, (
            f"Debriefer missing research_question prefix for study {slug!r}"
        )

    def test_theoretical_lens_text_in_debriefer_instruction(self, slug):
        agent, study = _build_debriefer(slug)
        lens_prefix = study.theoretical_lens[:50]
        assert lens_prefix in agent.instruction, (
            f"Debriefer missing theoretical_lens prefix for study {slug!r}"
        )

    def test_debriefer_contains_anti_steering_framing(self, slug):
        """The prompt must explicitly tell the researcher that the RQ
        may or may not be answered, and not to steer the panel."""
        agent, _ = _build_debriefer(slug)
        lower = agent.instruction.lower()
        assert "may or may not" in lower, (
            f"Debriefer missing 'may or may not' framing for study {slug!r}"
        )
        assert ("do not steer" in lower) or ("absence is itself" in lower), (
            f"Debriefer missing anti-steer framing for study {slug!r}"
        )

    def test_debriefer_contains_research_context_section_header(self, slug):
        agent, _ = _build_debriefer(slug)
        assert "RESEARCH CONTEXT" in agent.instruction


# ===========================================================================
# 4. Swap behaviour — different studies produce different Debriefer
#    prompts, while Observer + FieldNoter remain stable modulo the
#    flagged-vocabulary watch-list
# ===========================================================================

class TestStudySwapBehaviour:
    def test_debriefer_instructions_differ_across_studies(self):
        """Two different studies must produce two different Debriefer
        instructions (their research questions are different)."""
        d1, _ = _build_debriefer("openness_maneuvering")
        d2, _ = _build_debriefer("_test_alt")
        assert d1.instruction != d2.instruction

    def test_observer_instruction_shape_constant_across_studies(self):
        """The Observer's prompt structure should be largely the same
        between studies — only the embedded forbidden-vocab list and
        watch-list change.

        We assert the prompts SHARE the methodological scaffolding by
        checking that key generic section markers exist in BOTH and
        that the same section markers exist in both. (We cannot assert
        full equality because the vocab lists differ.)"""
        o1, _ = _build_observer("openness_maneuvering")
        o2, _ = _build_observer("_test_alt")
        for marker in (
            "OBSERVATIONAL DISCIPLINE",
            "SPONTANEOUS-USE WATCH-LIST",
            "ObservationSummary",  # output-schema name appears in both
        ):
            assert marker in o1.instruction
            assert marker in o2.instruction


# ===========================================================================
# 5. Construct vocabulary appears ONLY inside the forbidden-vocab list
#    block, not in instructional prose elsewhere
# ===========================================================================

class TestConstructWordsDoNotLeakIntoProse:
    """A construct word like 'open-source' appearing inside the
    forbidden-vocabulary list is fine (the researcher needs to know
    what to avoid). But the SAME word appearing in instructional
    prose elsewhere (e.g. "you are studying open-source firms")
    would be a leak — that's the bias we just removed."""

    def test_debriefer_construct_words_only_inside_forbidden_block(self):
        """For each construct word, find every occurrence in the
        instruction and check it lies within the FORBIDDEN VOCABULARY
        block (a finite window after that section header)."""
        agent, study = _build_debriefer("openness_maneuvering")
        instr = agent.instruction

        # Locate the forbidden-vocab block bounds: from the header
        # "FORBIDDEN VOCABULARY" to the next section header.
        forbidden_start = instr.find("FORBIDDEN VOCABULARY")
        assert forbidden_start != -1, "Forbidden-vocab block missing"
        # Next section is "THEMATIC AREAS" — bound the block there.
        next_section = instr.find("THEMATIC AREAS", forbidden_start)
        assert next_section != -1, "Could not find next section after FORBIDDEN VOCABULARY"
        forbidden_block = instr[forbidden_start:next_section]
        rest_of_instr = instr[:forbidden_start] + instr[next_section:]

        # No construct word should appear OUTSIDE the forbidden block.
        # Allow "open" matches inside the longer RQ string explicitly
        # though — the RQ text mentions "open innovation ecosystem"
        # and that's the legitimate RESEARCH CONTEXT exposure. Strip
        # the RQ string from the comparison.
        rest_clean = rest_of_instr.replace(study.research_question, "")
        # Same for the lens.
        rest_clean = rest_clean.replace(study.theoretical_lens, "")
        rest_clean = rest_clean.replace(study.debriefer_background_block or "", "")

        for word in study.construct_forbidden_vocabulary:
            # Multi-token / hyphenated words: use a simple boundary
            # check to avoid false positives on substrings like 'open'
            # inside 'openness'.
            import re
            pattern = re.compile(
                r"(?<!\w)" + re.escape(word.lower()) + r"(?!\w)"
            )
            assert not pattern.search(rest_clean.lower()), (
                f"Construct word {word!r} leaked into instructional "
                f"prose outside the forbidden-vocabulary block and "
                f"outside the RESEARCH CONTEXT block (RQ/lens/"
                f"background)."
            )
