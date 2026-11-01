"""Tests for the R2 wiring — the three prompt-composition functions
now accept an optional `retrieved_snippets` argument.

This is a thin integration test: it constructs each function's input
fixtures, calls the function with and without snippets, and asserts
the rendered prompt contains the REFERENCE MATERIAL block when (and
only when) snippets were supplied. Nothing in this PR (R2) actually
threads snippets into these calls from the orchestrator loops — that
wiring lands in R3. These tests guard the seam.
"""

from __future__ import annotations

import importlib

import pytest


def _cm():
    return importlib.import_module("open-innovation-strategy.orchestrator.concurrent_mode")


def _ac():
    return importlib.import_module("open-innovation-strategy.orchestrator.artefact_collection")


def _pd():
    return importlib.import_module("open-innovation-strategy.orchestrator.panel_debriefing")


def _schemas():
    return importlib.import_module("open-innovation-strategy.rag.schemas")


def _two_snippets():
    s = _schemas()
    return [
        s.RetrievedSnippet(
            doc_id="acme_2024_annual_letter.md",
            doc_display_name="acme_2024_annual_letter.md",
            chunk_id="acme_2024_annual_letter.md#1",
            text="Our roadmap prioritises permissive licensing on inference APIs.",
            score=0.88,
        ),
        s.RetrievedSnippet(
            doc_id="acme_2023_founders_essay.md",
            doc_display_name="acme_2023_founders_essay.md",
            chunk_id="acme_2023_founders_essay.md#2",
            text="We believe broad accessibility accelerates the ecosystem.",
            score=0.74,
        ),
    ]


# ---------------------------------------------------------------------------
# _compose_role_prompt (Phase 1)
# ---------------------------------------------------------------------------

class TestComposeRolePromptRagSeam:
    def _fixture(self, cm):
        task = cm.RoleTaskSpec(
            role="CEO",
            company="ACME",
            industry_context="Dynamic",
            product_type="Novel",
            strategic_question="What should we build next?",
            doc_framing="Write a board memo.",
        )
        my_state = cm.RoleState(
            role="CEO",
            inbox=[],
            scratchpad=[],
            draft="",
        )
        return task, my_state

    def test_no_snippets_arg_is_default_no_op(self):
        cm = _cm()
        task, my_state = self._fixture(cm)
        prompt_without = cm._compose_role_prompt(
            role="CEO", task=task, my_state=my_state, transcript=[],
        )
        # REFERENCE MATERIAL is not in the default prompt.
        assert "REFERENCE MATERIAL" not in prompt_without

    def test_none_snippets_is_no_op(self):
        cm = _cm()
        task, my_state = self._fixture(cm)
        prompt = cm._compose_role_prompt(
            role="CEO", task=task, my_state=my_state, transcript=[],
            retrieved_snippets=None,
        )
        assert "REFERENCE MATERIAL" not in prompt

    def test_empty_snippets_is_no_op(self):
        cm = _cm()
        task, my_state = self._fixture(cm)
        prompt = cm._compose_role_prompt(
            role="CEO", task=task, my_state=my_state, transcript=[],
            retrieved_snippets=[],
        )
        assert "REFERENCE MATERIAL" not in prompt

    def test_snippets_arg_inserts_reference_block(self):
        cm = _cm()
        task, my_state = self._fixture(cm)
        prompt = cm._compose_role_prompt(
            role="CEO", task=task, my_state=my_state, transcript=[],
            retrieved_snippets=_two_snippets(),
        )
        # The block is now present.
        assert "REFERENCE MATERIAL" in prompt
        # Each snippet ID lands in the prompt.
        assert "acme_2024_annual_letter.md#1" in prompt
        assert "acme_2023_founders_essay.md#2" in prompt
        # And the populate-citations instruction is visible.
        assert "citations" in prompt
        assert "doc_id" in prompt

    def test_snippet_text_lands_in_prompt(self):
        cm = _cm()
        task, my_state = self._fixture(cm)
        prompt = cm._compose_role_prompt(
            role="CEO", task=task, my_state=my_state, transcript=[],
            retrieved_snippets=_two_snippets(),
        )
        assert "permissive licensing" in prompt
        assert "broad accessibility accelerates" in prompt


# ---------------------------------------------------------------------------
# _build_artefact_prompt (Phase 2)
# ---------------------------------------------------------------------------

class TestBuildArtefactPromptRagSeam:
    def test_no_snippets_arg_is_default_no_op(self):
        ac = _ac()
        prompt = ac._build_artefact_prompt(
            role="CEO",
            company="ACME",
            industry_context="Dynamic",
            product_type="Novel",
            deliberation_summary="(summary)",
            ceo_final_synthesis="(synthesis)",
        )
        assert "REFERENCE MATERIAL" not in prompt

    def test_snippets_arg_inserts_reference_block(self):
        ac = _ac()
        prompt = ac._build_artefact_prompt(
            role="CEO",
            company="ACME",
            industry_context="Dynamic",
            product_type="Novel",
            deliberation_summary="(summary)",
            ceo_final_synthesis="(synthesis)",
            retrieved_snippets=_two_snippets(),
        )
        assert "REFERENCE MATERIAL" in prompt
        assert "acme_2024_annual_letter.md#1" in prompt
        assert "permissive licensing" in prompt


# ---------------------------------------------------------------------------
# AgentAction / StrategicArtefact / PanelResponse — citations field
# ---------------------------------------------------------------------------

class TestCitationsFieldOnSchemas:
    def test_agent_action_default_citations_is_empty_list(self):
        cm = _cm()
        a = cm.AgentAction(kind=cm.ActionKind.SPEAK, text="hi")
        assert a.citations == []

    def test_agent_action_accepts_citations_list(self):
        cm = _cm()
        s = _schemas()
        a = cm.AgentAction(
            kind=cm.ActionKind.SPEAK,
            text="We will release with permissive licensing.",
            citations=[
                s.Citation(
                    doc_id="acme_2024_annual_letter.md",
                    chunk_id="acme_2024_annual_letter.md#1",
                    quote="Our roadmap prioritises permissive licensing on inference APIs.",
                    supports="open-weight commitment",
                ),
            ],
        )
        assert len(a.citations) == 1
        assert a.citations[0].doc_id == "acme_2024_annual_letter.md"

    def test_strategic_artefact_default_citations_is_empty_list(self):
        from pydantic import BaseModel  # noqa: F401
        m = importlib.import_module("open-innovation-strategy.roles.artefact_schemas")
        art = m.StrategicArtefact(
            role="CEO",
            company="ACME",
            industry_context="Dynamic",
            product_type="Novel",
            title="t",
            key_challenges=["c"],
            main_decisions=["d"],
            key_tensions=["t"],
            body="body",
        )
        assert art.citations == []

    def test_strategic_artefact_accepts_citations(self):
        m = importlib.import_module("open-innovation-strategy.roles.artefact_schemas")
        s = _schemas()
        art = m.StrategicArtefact(
            role="CEO",
            company="ACME",
            industry_context="Dynamic",
            product_type="Novel",
            title="t",
            key_challenges=["c"],
            main_decisions=["d"],
            key_tensions=["t"],
            body="body",
            citations=[
                s.Citation(
                    doc_id="x", quote="some quote", supports="something",
                ),
            ],
        )
        assert len(art.citations) == 1

    def test_panel_response_default_citations_is_empty_list(self):
        m = importlib.import_module("open-innovation-strategy.roles.researcher_schemas")
        r = m.PanelResponse(role="CEO", text="some answer")
        assert r.citations == []

    def test_panel_response_accepts_citations(self):
        m = importlib.import_module("open-innovation-strategy.roles.researcher_schemas")
        s = _schemas()
        r = m.PanelResponse(
            role="CEO",
            text="some answer",
            citations=[
                s.Citation(doc_id="x", quote="q", supports="s"),
            ],
        )
        assert len(r.citations) == 1
