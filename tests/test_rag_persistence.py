"""Tests for the R3 persistence layer: citation footnotes + 07_rag/ folder.

Covers:
  - `CitationCounter` registers + renders Markdown footnote definitions.
  - `_render_artefact_md` / `_render_debriefing_md` / `_render_deliberation_md`
    expand citations into inline markers + a References section.
  - `burst_run` writes 07_rag/ when given a `rag_session`.
  - `ReplicationManifest.rag_config` round-trips and can be empty.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _persist():
    return importlib.import_module("open-innovation-strategy.analysis.persist_artefacts")


def _cr():
    return importlib.import_module("open-innovation-strategy.analysis.citation_rendering")


def _rt():
    return importlib.import_module("open-innovation-strategy.rag.runtime")


def _schemas():
    return importlib.import_module("open-innovation-strategy.rag.schemas")


def _replication():
    return importlib.import_module("open-innovation-strategy.analysis.replication_package")


# ---------------------------------------------------------------------------
# CitationCounter
# ---------------------------------------------------------------------------

class TestCitationCounter:
    def test_register_returns_inline_marker(self):
        cr = _cr()
        s = _schemas()
        counter = cr.CitationCounter()
        marker = counter.register(s.Citation(
            doc_id="a.md", quote="hello world", supports="some claim",
        ))
        assert marker == "[^c1]"

    def test_multiple_registers_get_sequential_ids(self):
        cr = _cr()
        s = _schemas()
        counter = cr.CitationCounter()
        m1 = counter.register(s.Citation(doc_id="a.md", quote="x"))
        m2 = counter.register(s.Citation(doc_id="b.md", quote="y"))
        m3 = counter.register(s.Citation(doc_id="c.md", quote="z"))
        assert (m1, m2, m3) == ("[^c1]", "[^c2]", "[^c3]")

    def test_duplicate_citation_reuses_marker(self):
        cr = _cr()
        s = _schemas()
        counter = cr.CitationCounter()
        m1 = counter.register(s.Citation(doc_id="a.md", quote="x"))
        m2 = counter.register(s.Citation(doc_id="a.md", quote="x"))  # same key
        assert m1 == m2  # collapsed
        # Only one footnote definition.
        assert len(counter.footnote_lines) == 1

    def test_footnote_block_rendering(self):
        cr = _cr()
        s = _schemas()
        counter = cr.CitationCounter()
        counter.register(s.Citation(
            doc_id="acme_letter.md",
            chunk_id="acme_letter.md#3",
            quote="We will release with permissive licensing.",
            supports="open-weight commitment",
        ))
        block = counter.footnote_block()
        assert "## References" in block
        assert "[^c1]:" in block
        assert "acme_letter.md" in block
        assert "chunk acme_letter.md#3" in block
        assert "permissive licensing" in block
        assert "open-weight commitment" in block

    def test_footnote_block_empty_when_no_citations(self):
        cr = _cr()
        assert cr.CitationCounter().footnote_block() == ""

    def test_register_all_concatenates_markers(self):
        cr = _cr()
        s = _schemas()
        counter = cr.CitationCounter()
        markers = counter.register_all([
            s.Citation(doc_id="a.md", quote="x"),
            s.Citation(doc_id="b.md", quote="y"),
        ])
        assert markers == "[^c1][^c2]"

    def test_register_accepts_dict_form(self):
        """Persisted JSON gives us dicts, not Citation instances. The
        counter must accept both."""
        cr = _cr()
        counter = cr.CitationCounter()
        marker = counter.register({
            "doc_id": "x.md", "chunk_id": "x.md#1",
            "quote": "q", "supports": "s",
        })
        assert marker == "[^c1]"
        block = counter.footnote_block()
        assert "x.md" in block


# ---------------------------------------------------------------------------
# Markdown renderers expand citations
# ---------------------------------------------------------------------------

class TestArtefactMdRendersCitations:
    def test_no_citations_no_references_section(self):
        p = _persist()
        md = p._render_artefact_md({
            "role": "CEO", "company": "ACME",
            "industry_context": "Dynamic", "product_type": "Novel",
            "title": "T", "key_challenges": [], "main_decisions": [],
            "key_tensions": [], "body": "body text",
            "citations": [],
        })
        assert "## References" not in md

    def test_with_citations_renders_inline_marker_and_references(self):
        p = _persist()
        md = p._render_artefact_md({
            "role": "CEO", "company": "ACME",
            "industry_context": "Dynamic", "product_type": "Novel",
            "title": "T", "key_challenges": [], "main_decisions": [],
            "key_tensions": [], "body": "We will release openly.",
            "citations": [{
                "doc_id": "acme_letter.md",
                "chunk_id": "acme_letter.md#1",
                "quote": "We continue to believe broad accessibility helps.",
                "supports": "open-weight commitment",
            }],
        })
        # Inline marker appended to the body.
        assert "[^c1]" in md
        # References section at the bottom.
        assert "## References" in md
        assert "acme_letter.md" in md
        assert "broad accessibility" in md


class TestDebriefingMdRendersCitations:
    def _exchange(self, role_citations):
        return {
            "utterance": {
                "area_id": "D", "addressed_to": "CEO",
                "anchor_refs": ["decision X"], "text": "Q?",
            },
            "responses": [{
                "role": "CEO", "text": "we did X.",
                "is_cross_talk": False,
                "citations": role_citations,
            }],
        }

    def test_panellist_response_with_citations(self):
        p = _persist()
        md = p._render_debriefing_md({
            "company": "ACME", "research_question": "rq",
            "ended_reason": "ok", "forbidden_vocab_violations": 0,
            "exchanges": [self._exchange([{
                "doc_id": "letter.md", "quote": "...quote...",
                "supports": "X",
            }])],
        })
        assert "[^c1]" in md
        assert "## References" in md
        assert "letter.md" in md


class TestDeliberationMdRendersCitations:
    def test_event_with_citations(self):
        p = _persist()
        md = p._render_deliberation_md({
            "company": "ACME",
            "industry_context": "Dynamic",
            "product_type": "Novel",
            "events": [{
                "index": 0, "role": "CEO", "kind": "text",
                "text": "we will release openly.",
                "citations": [{
                    "doc_id": "essay.md",
                    "chunk_id": "essay.md#2",
                    "quote": "broad accessibility helps",
                    "supports": "X",
                }],
            }],
        })
        assert "[^c1]" in md
        assert "essay.md" in md
        assert "broad accessibility" in md


# ---------------------------------------------------------------------------
# burst_run writes 07_rag/ when given a rag_session
# ---------------------------------------------------------------------------

class TestBurstRunWrites07Rag:
    def _make_session_enabled(self):
        rt = _rt()
        return rt.RagSession(
            corpus_name="projects/p/locations/l/ragCorpora/x",
            embedding_model="publishers/google/models/text-embedding-005",
            corpus_documents=[
                {"display_name": "a.md", "sha256": "abc", "source_uri": "gs://"},
            ],
            top_k=5,
            retrieval_log=[
                {
                    "phase": "phase_1_deliberation", "role": "CEO",
                    "query": "q", "retrieved_count": 2,
                    "retrieved": [
                        {"doc_id": "a.md", "chunk_id": "a.md#1",
                         "score": 0.9, "text": "alpha"},
                    ],
                    "timestamp": "2026-05-23T00:00:00Z",
                },
                {
                    "phase": "phase_2_artefact", "role": "CTO",
                    "query": "q2", "retrieved_count": 0,
                    "skipped_reason": "empty_query",
                    "timestamp": "2026-05-23T00:00:01Z",
                },
            ],
        )

    def test_07_rag_folder_written_with_three_files(self, tmp_path):
        p = _persist()
        sess = self._make_session_enabled()
        out = p.burst_run(
            out_dir=tmp_path,
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            rag_session=sess,
        )
        rag_dir = out / "07_rag"
        assert rag_dir.is_dir()
        assert (rag_dir / "corpus_manifest.json").exists()
        assert (rag_dir / "retrieval_log.jsonl").exists()
        assert (rag_dir / "README.md").exists()

    def test_corpus_manifest_json_carries_resource_name_and_documents(self, tmp_path):
        p = _persist()
        sess = self._make_session_enabled()
        out = p.burst_run(
            out_dir=tmp_path, company="X",
            industry_context="Dynamic", product_type="Novel",
            rag_session=sess,
        )
        manifest = json.loads((out / "07_rag" / "corpus_manifest.json").read_text())
        assert manifest["corpus_resource_name"].endswith("ragCorpora/x")
        assert manifest["documents"][0]["sha256"] == "abc"
        assert manifest["embedding_model"].endswith("text-embedding-005")

    def test_retrieval_log_is_one_record_per_line(self, tmp_path):
        p = _persist()
        sess = self._make_session_enabled()
        out = p.burst_run(
            out_dir=tmp_path, company="X",
            industry_context="Dynamic", product_type="Novel",
            rag_session=sess,
        )
        lines = (out / "07_rag" / "retrieval_log.jsonl").read_text().splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["role"] == "CEO"
        assert first["retrieved_count"] == 2

    def test_disabled_session_still_writes_07_rag_folder(self, tmp_path):
        p = _persist()
        rt = _rt()
        sess = rt.RagSession(corpus_name=None)
        out = p.burst_run(
            out_dir=tmp_path, company="X",
            industry_context="Dynamic", product_type="Novel",
            rag_session=sess,
        )
        assert (out / "07_rag" / "README.md").exists()
        # README marks disabled.
        assert "Enabled:** no" in (out / "07_rag" / "README.md").read_text()

    def test_no_07_rag_folder_when_session_is_none(self, tmp_path):
        p = _persist()
        out = p.burst_run(
            out_dir=tmp_path, company="X",
            industry_context="Dynamic", product_type="Novel",
            rag_session=None,
        )
        assert not (out / "07_rag").exists()


# ---------------------------------------------------------------------------
# ReplicationManifest.rag_config
# ---------------------------------------------------------------------------

class TestManifestRagConfig:
    def test_default_is_empty_dict(self):
        rp = _replication()
        m = rp.ReplicationManifest(
            run_id="r1", company="X", industry_context="Dynamic",
            product_type="Novel", launch_year=2030,
            started_at="2026-05-23T00:00:00Z",
        )
        assert m.rag_config == {}

    def test_round_trip(self):
        rp = _replication()
        payload = {
            "enabled": True,
            "corpus_resource_name": "projects/p/locations/l/ragCorpora/x",
            "embedding_model": "publishers/google/models/text-embedding-005",
            "top_k": 5,
            "documents": [{"display_name": "a.md", "sha256": "abc"}],
        }
        m = rp.ReplicationManifest(
            run_id="r1", company="X", industry_context="Dynamic",
            product_type="Novel", launch_year=2030,
            started_at="2026-05-23T00:00:00Z",
            rag_config=payload,
        )
        # Round-trip via JSON.
        s = m.model_dump_json()
        m2 = rp.ReplicationManifest.model_validate_json(s)
        assert m2.rag_config == payload

    def test_build_replication_manifest_accepts_rag_config(self):
        rp = _replication()
        m = rp.build_replication_manifest(
            run_id="r1", company="X", industry_context="Dynamic",
            product_type="Novel", launch_year=2030,
            started_at="2026-05-23T00:00:00Z",
            rag_config={"enabled": False},
            include_git=False, include_env=False, vertex_config={},
        )
        assert m.rag_config == {"enabled": False}


# ---------------------------------------------------------------------------
# Invariant I5 — query never contains RQ or lens
# ---------------------------------------------------------------------------

class TestInvariantI5NoQueryLeakAcrossStudies:
    """Parametric: for the two study fixtures the framework already
    uses (the real openness study + the synthetic _test_alt), build a
    role-turn query from a representative task fixture and assert no
    prefix of study.research_question / study.theoretical_lens shows
    up in the query.
    """

    @pytest.fixture(params=["openness_maneuvering", "_test_alt"])
    def study(self, request):
        load = importlib.import_module("open-innovation-strategy.studies")
        return load.load_study(request.param)

    def test_role_turn_query_carries_no_rq_or_lens(self, study):
        q_mod = importlib.import_module("open-innovation-strategy.rag.queries")
        # Synthesise a task that uses the study's strategic question.
        task = SimpleNamespace(
            company="ACME", industry_context="Dynamic", product_type="Novel",
            # Note: strategic_question is the user-facing deliberation
            # prompt, NOT the study's analytical research_question. By
            # construction the two are distinct in StudyConfig.
            strategic_question="What should we build next?",
        )
        my_state = SimpleNamespace(scratchpad=["a note"])
        transcript = [SimpleNamespace(role="CEO", text="we agree on X")]
        query = q_mod.build_role_turn_query(
            role="CEO", task=task, my_state=my_state, transcript=transcript,
        )

        # No prefix of research_question (50 chars is more than enough
        # to detect leakage of distinctive phrases).
        rq_prefix = study.research_question[:50].strip()
        if rq_prefix:
            assert rq_prefix not in query

        # No prefix of theoretical_lens. Lens texts open with the
        # construct's keywords (e.g. "Selective revealing").
        lens_prefix = study.theoretical_lens[:50].strip()
        if lens_prefix:
            assert lens_prefix not in query

    def test_artefact_query_carries_no_rq_or_lens(self, study):
        q_mod = importlib.import_module("open-innovation-strategy.rag.queries")
        query = q_mod.build_artefact_query(
            role="CTO", company="ACME",
            deliberation_summary="team converged on permissive licensing.",
        )
        rq_prefix = study.research_question[:50].strip()
        if rq_prefix:
            assert rq_prefix not in query
        lens_prefix = study.theoretical_lens[:50].strip()
        if lens_prefix:
            assert lens_prefix not in query

    def test_panellist_query_carries_no_rq_or_lens(self, study):
        q_mod = importlib.import_module("open-innovation-strategy.rag.queries")
        query = q_mod.build_panellist_query(
            role="COO",
            utterance_text="Walk me through how the licensing decision was made.",
            recent_history_block="Earlier the CTO laid out the rollout plan.",
        )
        rq_prefix = study.research_question[:50].strip()
        if rq_prefix:
            assert rq_prefix not in query
        lens_prefix = study.theoretical_lens[:50].strip()
        if lens_prefix:
            assert lens_prefix not in query
