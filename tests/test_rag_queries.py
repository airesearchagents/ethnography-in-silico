"""Tests for `rag.queries` — the three retrieval-query builders.

Asserts:
  - Each builder embeds the role + the question it's answering.
  - Recent transcript / scratchpad / history appears (last few entries).
  - Long inputs get truncated to the max char budget.
  - **Invariant I5** — none of the helpers receive (or surface) the
    study's research_question or theoretical_lens. The framework
    fixtures verify this at the call-site level in
    `test_rag_no_query_leak.py`; here we cover the helpers in
    isolation.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace


def _q():
    return importlib.import_module("open-innovation-strategy.rag.queries")


class _Task(SimpleNamespace):
    pass


class _State(SimpleNamespace):
    pass


class _Entry(SimpleNamespace):
    pass


# ---------------------------------------------------------------------------
# Phase 1 — role turn
# ---------------------------------------------------------------------------

class TestBuildRoleTurnQuery:
    def _fixture(self):
        task = _Task(
            company="ACME",
            industry_context="Dynamic",
            product_type="Novel",
            strategic_question="What should we build next?",
        )
        my_state = _State(scratchpad=[
            "Need to know our prior position on open weights.",
        ])
        transcript = [
            _Entry(role="CEO", text="We're at a fork on licensing."),
            _Entry(role="CTO", text="Engineering can support either path."),
        ]
        return task, my_state, transcript

    def test_role_and_strategic_question_present(self):
        m = _q()
        task, my_state, transcript = self._fixture()
        q = m.build_role_turn_query(
            role="CMO", task=task, my_state=my_state, transcript=transcript,
        )
        assert "CMO" in q
        assert "What should we build next?" in q

    def test_recent_transcript_entries_present(self):
        m = _q()
        task, my_state, transcript = self._fixture()
        q = m.build_role_turn_query(
            role="CMO", task=task, my_state=my_state, transcript=transcript,
        )
        assert "fork on licensing" in q
        assert "Engineering can support" in q

    def test_only_last_5_transcript_entries(self):
        m = _q()
        task, my_state, _ = self._fixture()
        # 8 entries; only the last 5 should appear.
        transcript = [
            _Entry(role="R", text=f"Entry {i}") for i in range(8)
        ]
        q = m.build_role_turn_query(
            role="CMO", task=task, my_state=my_state, transcript=transcript,
        )
        assert "Entry 7" in q
        assert "Entry 3" in q
        assert "Entry 0" not in q
        assert "Entry 1" not in q

    def test_scratchpad_latest_note_present(self):
        m = _q()
        task, my_state, transcript = self._fixture()
        q = m.build_role_turn_query(
            role="CMO", task=task, my_state=my_state, transcript=transcript,
        )
        assert "prior position on open weights" in q

    def test_empty_inputs_yield_short_query(self):
        m = _q()
        q = m.build_role_turn_query(
            role="CEO",
            task=_Task(company="", industry_context="", product_type="",
                       strategic_question=""),
            my_state=_State(scratchpad=[]),
            transcript=[],
        )
        # Even with empty inputs, the role still surfaces.
        assert "CEO" in q

    def test_long_inputs_truncated(self):
        m = _q()
        task = _Task(
            company="ACME",
            industry_context="Dynamic",
            product_type="Novel",
            strategic_question="x" * 5000,
        )
        my_state = _State(scratchpad=["y" * 5000])
        transcript = [_Entry(role="R", text="z" * 5000)]
        q = m.build_role_turn_query(
            role="CEO", task=task, my_state=my_state, transcript=transcript,
            max_chars=300,
        )
        assert len(q) <= 305  # 300 + small ellipsis allowance


# ---------------------------------------------------------------------------
# Phase 2 — artefact authoring
# ---------------------------------------------------------------------------

class TestBuildArtefactQuery:
    def test_role_company_and_summary_present(self):
        m = _q()
        q = m.build_artefact_query(
            role="CTO",
            company="ACME",
            deliberation_summary=(
                "Team decided to release with permissive licensing on "
                "inference API but keep training data internal."
            ),
        )
        assert "CTO" in q
        assert "ACME" in q
        assert "permissive licensing" in q

    def test_context_optional(self):
        m = _q()
        q = m.build_artefact_query(
            role="CTO", company="ACME",
            deliberation_summary="",
            industry_context="Dynamic",
            product_type="Novel",
        )
        assert "Dynamic" in q
        assert "Novel" in q

    def test_truncation_respects_max_chars(self):
        m = _q()
        q = m.build_artefact_query(
            role="CTO", company="ACME",
            deliberation_summary="x" * 5000,
            max_chars=300,
        )
        assert len(q) <= 305


# ---------------------------------------------------------------------------
# Phase 4 — panellist response
# ---------------------------------------------------------------------------

class TestBuildPanellistQuery:
    def test_utterance_text_and_role_present(self):
        m = _q()
        q = m.build_panellist_query(
            role="COO",
            utterance_text="Walk me through how the licensing decision was made.",
        )
        assert "COO" in q
        assert "licensing decision" in q

    def test_history_optional(self):
        m = _q()
        q1 = m.build_panellist_query(
            role="COO", utterance_text="any question",
        )
        q2 = m.build_panellist_query(
            role="COO", utterance_text="any question",
            recent_history_block="Earlier the CTO described the rollout plan.",
        )
        assert "rollout plan" not in q1
        assert "rollout plan" in q2

    def test_truncation_respects_max_chars(self):
        m = _q()
        q = m.build_panellist_query(
            role="COO",
            utterance_text="x" * 5000,
            recent_history_block="y" * 5000,
            max_chars=200,
        )
        assert len(q) <= 205


# ---------------------------------------------------------------------------
# Invariant I5 — no RQ/lens leak when builders are called normally
# ---------------------------------------------------------------------------

class TestInvariantI5NoRQLensLeak:
    """The helpers receive role + task + transcript + state. None of
    these carry the study's research_question or theoretical_lens — they
    carry the *user-facing* strategic_question, which is distinct. This
    test class verifies a defensive scenario: even if a caller passed an
    RQ-shaped string via the task's strategic_question (which would be
    methodologically wrong on its own), the helper does not introduce
    the words 'research question' / 'theoretical lens' / 'selective
    revealing' into its own framing.
    """

    def test_role_query_does_not_introduce_rq_phrases(self):
        m = _q()
        task = _Task(
            company="ACME", industry_context="Dynamic", product_type="Novel",
            strategic_question="What should we build?",
        )
        my_state = _State(scratchpad=[])
        q = m.build_role_turn_query(
            role="CEO", task=task, my_state=my_state, transcript=[],
        )
        lower = q.lower()
        assert "research question" not in lower
        assert "theoretical lens" not in lower
        assert "selective revealing" not in lower

    def test_artefact_query_does_not_introduce_rq_phrases(self):
        m = _q()
        q = m.build_artefact_query(
            role="CTO", company="ACME", deliberation_summary="anything",
        )
        lower = q.lower()
        assert "research question" not in lower
        assert "theoretical lens" not in lower

    def test_panellist_query_does_not_introduce_rq_phrases(self):
        m = _q()
        q = m.build_panellist_query(
            role="COO", utterance_text="any question",
        )
        lower = q.lower()
        assert "research question" not in lower
        assert "theoretical lens" not in lower


# ---------------------------------------------------------------------------
# The latest context must survive the query's size limit
# ---------------------------------------------------------------------------

class TestQueriesKeepTheLatestContext:
    def test_panel_query_takes_the_end_of_the_history(self):
        history = "--- Exchange 1 --- opening words " + "filler " * 200 + "the latest answer"
        query = _q().build_panellist_query(
            role="CTO", utterance_text="Why?", recent_history_block=history,
        )
        assert "the latest answer" in query
        assert "opening words" not in query

    def test_role_turn_query_keeps_the_note_and_the_newest_lines(self):
        task = _Task(
            company="ACME", industry_context="Dynamic", product_type="Novel",
            strategic_question="What next? " * 80,
        )
        my_state = _State(scratchpad=["old note", "my newest note"], draft="")
        transcript = [_Entry(role="CEO", text=f"entry {i} " + "word " * 60) for i in range(8)]
        query = _q().build_role_turn_query(
            role="CTO", task=task, my_state=my_state, transcript=transcript,
        )
        assert len(query) <= 803
        assert "my newest note" in query
        assert "entry 7" in query
        assert "entry 0" not in query
