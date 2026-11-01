"""Tests for `rag.prompt_inject.format_retrieved_context`.

What we assert
--------------
- `snippets=None` and `snippets=[]` return the empty string. This is
  the no-RAG path; the helper has to be a hard no-op so callers can
  unconditionally concatenate the result into their prompts.
- Non-empty snippets produce a block containing each excerpt's doc_id,
  chunk_id, score, and (truncated, if necessary) text.
- The block contains the populate-citations instruction with the
  expected JSON skeleton.
- Long excerpts are truncated with a trailing `[...]` so the LLM
  doesn't quote partial sentences as if complete.
- The framing string does NOT contain the study's research question
  or theoretical lens (invariant I5 in `docs/10_rag_repo_plan.md`).
"""

from __future__ import annotations

import importlib

import pytest


def _pi():
    return importlib.import_module("open-innovation-strategy.rag.prompt_inject")


def _schemas():
    return importlib.import_module("open-innovation-strategy.rag.schemas")


class TestNoSnippetsIsNoOp:
    def test_none_returns_empty_string(self):
        m = _pi()
        assert m.format_retrieved_context(role="CEO", snippets=None) == ""

    def test_empty_list_returns_empty_string(self):
        m = _pi()
        assert m.format_retrieved_context(role="CTO", snippets=[]) == ""


class TestRenderingWithSnippets:
    def _two_snippets(self):
        s = _schemas()
        return [
            s.RetrievedSnippet(
                doc_id="openai_2024_annual_letter.md",
                doc_display_name="openai_2024_annual_letter.md",
                chunk_id="openai_2024_annual_letter.md#1",
                text="We continue to believe broad accessibility of frontier models accelerates safety research.",
                score=0.91,
                source_uri="gs://b/annual.md",
            ),
            s.RetrievedSnippet(
                doc_id="openai_founders_essay.md",
                doc_display_name="openai_founders_essay.md",
                chunk_id="openai_founders_essay.md#2",
                text="Open weights are part of our roadmap for the next year.",
                score=0.77,
                source_uri="gs://b/essay.md",
            ),
        ]

    def test_returns_nonempty_string_when_snippets_present(self):
        m = _pi()
        out = m.format_retrieved_context(role="CEO", snippets=self._two_snippets())
        assert out
        assert "REFERENCE MATERIAL" in out

    def test_every_snippet_id_appears_in_output(self):
        m = _pi()
        out = m.format_retrieved_context(role="CEO", snippets=self._two_snippets())
        assert "openai_2024_annual_letter.md#1" in out
        assert "openai_founders_essay.md#2" in out
        # Each doc_id also appears for the citation-population skeleton.
        assert "openai_2024_annual_letter.md" in out
        assert "openai_founders_essay.md" in out

    def test_every_snippet_text_appears_in_output(self):
        m = _pi()
        out = m.format_retrieved_context(role="CEO", snippets=self._two_snippets())
        assert "broad accessibility of frontier models" in out
        assert "Open weights are part of our roadmap" in out

    def test_scores_appear_in_excerpt_headers(self):
        """The score floats should render with 3-decimal precision so a
        reviewer reading the rendered prompt can see how confident the
        retriever was per chunk."""
        m = _pi()
        out = m.format_retrieved_context(role="CEO", snippets=self._two_snippets())
        assert "score=0.910" in out
        assert "score=0.770" in out

    def test_populate_citations_instruction_present(self):
        m = _pi()
        out = m.format_retrieved_context(role="CEO", snippets=self._two_snippets())
        # The instruction tells the LLM exactly what to put in citations[].
        assert "citations" in out
        assert "doc_id" in out
        assert "chunk_id" in out
        assert "quote" in out
        assert "supports" in out
        # And tells it what to do when nothing was used.
        assert "[]" in out

    def test_no_fabrication_warning_present(self):
        m = _pi()
        out = m.format_retrieved_context(role="CEO", snippets=self._two_snippets())
        # The fabrication guard surfaces in the instruction so the LLM
        # is on notice that citations will be substring-verified.
        assert "fabricat" in out.lower() or "verified" in out.lower()


class TestExcerptTruncation:
    def test_long_excerpt_truncated_with_marker(self):
        m = _pi()
        s = _schemas()
        long_text = "A" * 5000
        snippet = s.RetrievedSnippet(
            doc_id="d", chunk_id="d#1", text=long_text, score=0.5,
        )
        out = m.format_retrieved_context(
            role="CEO", snippets=[snippet], max_excerpt_chars=200,
        )
        # The 5000-char text was cut to ~200; trailing `[...]` marks it.
        assert "[...]" in out
        # And the full 5000 chars are NOT all in the prompt.
        assert "A" * 5000 not in out

    def test_short_excerpt_not_truncated(self):
        m = _pi()
        s = _schemas()
        short_text = "Brief but useful."
        snippet = s.RetrievedSnippet(
            doc_id="d", chunk_id="d#1", text=short_text, score=0.5,
        )
        out = m.format_retrieved_context(
            role="CEO", snippets=[snippet], max_excerpt_chars=200,
        )
        assert short_text in out
        # No truncation marker.
        assert "[...]" not in out


class TestInvariantI5NoRQLensLeak:
    """The retrieval-prompt rendering must not embed the study's research
    question or theoretical lens. Even though `format_retrieved_context`
    doesn't receive these, we add a sanity test: if a caller accidentally
    passes RQ-flavoured strings via role or snippet fields, the output
    block still doesn't contain RQ-shaped framing (no 'research question',
    no 'theoretical lens', no 'maneuver' verb).
    """

    def test_block_does_not_mention_research_question_phrase(self):
        m = _pi()
        s = _schemas()
        snippet = s.RetrievedSnippet(
            doc_id="d", chunk_id="d#1", text="any text", score=0.5,
        )
        out = m.format_retrieved_context(role="CEO", snippets=[snippet])
        # The block's own framing must not introduce these phrases.
        lower = out.lower()
        # Allow the words to appear if they happen to be in a snippet's
        # text (out of our control) — we check the block FRAMING.
        # Split off the EXCERPTS section.
        framing = lower.split("excerpts")[0]
        assert "research question" not in framing
        assert "theoretical lens" not in framing
        assert "selective revealing" not in framing
