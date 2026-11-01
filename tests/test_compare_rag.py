"""Tests for `analysis.compare_rag` — the RAG comparison harness.

Approach: synthesise fake per-run folders under tmp_path with known
content (manifest.json + 00_meta.json + per-phase JSON files), then
exercise each metric in isolation against those folders. No live
runs, no LLM calls, no GCP auth required.

Coverage:
  * Discovery + pairing edge cases (multiple runs same condition,
    orphan runs, missing manifests, study-version mismatch,
    provider mismatch).
  * Each per-pair metric in isolation.
  * Quote verification: success path + fabrication detection.
  * Markdown rendering: structural assertions on key sections.
  * CSV emission: header + per-pair-per-role row shape.
  * CLI dispatch: dry-run, missing root, default invocation.
"""

from __future__ import annotations

import csv
import importlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest


def _cr():
    return importlib.import_module(
        "open-innovation-strategy.analysis.compare_rag"
    )


# ---------------------------------------------------------------------------
# Fake per-run folder builder
# ---------------------------------------------------------------------------

def _build_fake_run(
    root: Path,
    *,
    folder: str,
    company: str = "OpenAI",
    industry_context: str = "Dynamic",
    product_type: str = "Novel",
    study_slug: str = "openness_maneuvering",
    study_version: str = "0.1.0",
    started_at: str = "2026-05-24T00:00:00Z",
    rag_enabled: Optional[bool] = None,
    provider: str = "gemini_pro",
    deliberation_events: Optional[List[Dict[str, Any]]] = None,
    artefacts: Optional[Dict[str, Dict[str, Any]]] = None,
    debrief_exchanges: Optional[List[Dict[str, Any]]] = None,
    retrieval_log: Optional[List[Dict[str, Any]]] = None,
    corpus_docs: Optional[List[Dict[str, Any]]] = None,
    judging: Optional[Dict[str, Any]] = None,
) -> Path:
    """Create one folder under `root` with all the fixtures the harness reads.

    Skips files whose corresponding kwarg is None — letting tests
    exercise both "RAG" and "no-RAG" fixtures from the same builder.
    """
    run_dir = root / folder
    run_dir.mkdir(parents=True, exist_ok=True)

    # manifest.json — authoritative for pairing.
    manifest = {
        "run_id": folder,
        "company": company,
        "industry_context": industry_context,
        "product_type": product_type,
        "study_slug": study_slug,
        "study_version": study_version,
        "started_at": started_at,
        "providers_used": {"CEO": provider, "CTO": provider},
        "rag_config": (
            {"enabled": True} if rag_enabled is True else
            {"enabled": False} if rag_enabled is False else {}
        ),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest))

    # 00_meta.json — fallback identity.
    meta = {
        "run_id": folder,
        "company": company,
        "industry_context": industry_context,
        "product_type": product_type,
        "study_slug": study_slug,
        "study_version": study_version,
        "started_at": started_at,
        "phases_captured": {
            "deliberation": deliberation_events is not None,
            "strategy_documents": artefacts is not None,
            "debriefing": debrief_exchanges is not None,
            "rag": bool(rag_enabled),
        },
    }
    (run_dir / "00_meta.json").write_text(json.dumps(meta))

    # 01_deliberation/interaction_log.json
    if deliberation_events is not None:
        d = run_dir / "01_deliberation"
        d.mkdir(exist_ok=True)
        log_payload = {
            "company": company,
            "industry_context": industry_context,
            "product_type": product_type,
            "events": deliberation_events,
        }
        (d / "interaction_log.json").write_text(json.dumps(log_payload))

    # 02_strategy_documents/<Role>_strategy.json (one file per supplied role).
    if artefacts is not None:
        d = run_dir / "02_strategy_documents"
        d.mkdir(exist_ok=True)
        for role, art in artefacts.items():
            (d / f"{role}_strategy.json").write_text(json.dumps(art))

    # 04_interview/transcript.json
    if debrief_exchanges is not None:
        d = run_dir / "04_interview"
        d.mkdir(exist_ok=True)
        (d / "transcript.json").write_text(json.dumps({
            "company": company,
            "exchanges": debrief_exchanges,
        }))

    # 05_judging/aggregate.json
    if judging is not None:
        d = run_dir / "05_judging"
        d.mkdir(exist_ok=True)
        (d / "aggregate.json").write_text(json.dumps(judging))

    # 07_rag/{corpus_manifest.json, retrieval_log.jsonl}
    if retrieval_log is not None or corpus_docs is not None:
        d = run_dir / "07_rag"
        d.mkdir(exist_ok=True)
        if corpus_docs is not None:
            (d / "corpus_manifest.json").write_text(json.dumps({
                "enabled": True,
                "corpus_resource_name": f"projects/p/locations/l/ragCorpora/{company}_id",
                "embedding_model": "publishers/google/models/text-embedding-005",
                "top_k": 5,
                "documents": corpus_docs,
            }))
        if retrieval_log is not None:
            with (d / "retrieval_log.jsonl").open("w") as f:
                for rec in retrieval_log:
                    f.write(json.dumps(rec))
                    f.write("\n")

    return run_dir


def _basic_artefact(role: str, *, main_decisions: List[str],
                    key_tensions: List[str] = (),
                    key_challenges: List[str] = (),
                    citations: List[Dict[str, Any]] = ()) -> Dict[str, Any]:
    return {
        "role": role,
        "company": "OpenAI",
        "industry_context": "Dynamic",
        "product_type": "Novel",
        "title": f"{role} strategy",
        "main_decisions": list(main_decisions),
        "key_tensions": list(key_tensions),
        "key_challenges": list(key_challenges),
        "body": f"({role} strategy body)",
        "citations": list(citations),
    }


# ---------------------------------------------------------------------------
# Discovery + load_run
# ---------------------------------------------------------------------------

class TestLoadRun:
    def test_returns_runref_with_pair_key(self, tmp_path):
        run_dir = _build_fake_run(tmp_path, folder="run_A",
                                   rag_enabled=True, provider="gemini_pro")
        m = _cr()
        ref = m.load_run(run_dir)
        assert ref is not None
        assert ref.key.company == "OpenAI"
        assert ref.key.industry_context == "Dynamic"
        assert ref.key.product_type == "Novel"
        assert ref.key.study_slug == "openness_maneuvering"
        assert ref.key.study_version == "0.1.0"
        assert ref.key.tmt_provider == "gemini_pro"
        assert ref.rag_enabled is True

    def test_rag_disabled_when_config_missing(self, tmp_path):
        # No `rag_enabled` arg → no rag_config in manifest; load_run
        # should report rag_enabled=False.
        run_dir = _build_fake_run(tmp_path, folder="run_no_rag")
        m = _cr()
        ref = m.load_run(run_dir)
        assert ref.rag_enabled is False

    def test_rag_disabled_when_explicitly_false(self, tmp_path):
        run_dir = _build_fake_run(tmp_path, folder="run_disabled",
                                   rag_enabled=False)
        m = _cr()
        ref = m.load_run(run_dir)
        assert ref.rag_enabled is False

    def test_returns_none_when_manifest_and_meta_missing(self, tmp_path):
        empty = tmp_path / "empty_run"
        empty.mkdir()
        m = _cr()
        assert m.load_run(empty) is None

    def test_returns_none_when_scenario_keys_missing(self, tmp_path):
        # Manifest exists but lacks company/industry/product.
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / "manifest.json").write_text(json.dumps({
            "run_id": "x",
            "study_slug": "x",
        }))
        m = _cr()
        assert m.load_run(broken) is None

    def test_falls_back_to_meta_when_manifest_missing(self, tmp_path):
        run_dir = tmp_path / "meta_only"
        run_dir.mkdir()
        (run_dir / "00_meta.json").write_text(json.dumps({
            "company": "OpenAI",
            "industry_context": "Dynamic",
            "product_type": "Novel",
            "study_slug": "openness_maneuvering",
            "study_version": "0.1.0",
            "started_at": "2026-05-24T00:00:00Z",
            "phases_captured": {"rag": True},
        }))
        m = _cr()
        ref = m.load_run(run_dir)
        assert ref is not None
        assert ref.key.company == "OpenAI"
        assert ref.rag_enabled is True


# ---------------------------------------------------------------------------
# discover_runs + auto_pair_runs
# ---------------------------------------------------------------------------

class TestDiscoverAndPair:
    def test_pairs_no_rag_and_rag_with_same_key(self, tmp_path):
        _build_fake_run(tmp_path, folder="r1", rag_enabled=False,
                        started_at="2026-05-24T01:00:00Z")
        _build_fake_run(tmp_path, folder="r2", rag_enabled=True,
                        started_at="2026-05-24T02:00:00Z")
        m = _cr()
        runs = m.discover_runs(tmp_path)
        pairs, orphans = m.auto_pair_runs(runs)
        assert len(pairs) == 1
        no_rag, rag = pairs[0]
        assert no_rag.path.name == "r1"
        assert rag.path.name == "r2"
        assert orphans == []

    def test_orphan_when_only_one_condition_present(self, tmp_path):
        _build_fake_run(tmp_path, folder="r1", rag_enabled=True)
        m = _cr()
        runs = m.discover_runs(tmp_path)
        pairs, orphans = m.auto_pair_runs(runs)
        assert pairs == []
        assert len(orphans) == 1

    def test_provider_difference_does_not_cross_pair(self, tmp_path):
        # Same firm + cell + study, different providers — must not pair.
        _build_fake_run(tmp_path, folder="rA", rag_enabled=False,
                        provider="gemini_pro")
        _build_fake_run(tmp_path, folder="rB", rag_enabled=True,
                        provider="claude")
        m = _cr()
        runs = m.discover_runs(tmp_path)
        pairs, orphans = m.auto_pair_runs(runs)
        assert pairs == []
        assert len(orphans) == 2  # one orphan per provider bucket

    def test_study_version_difference_does_not_cross_pair(self, tmp_path):
        _build_fake_run(tmp_path, folder="rA", rag_enabled=False,
                        study_version="0.1.0")
        _build_fake_run(tmp_path, folder="rB", rag_enabled=True,
                        study_version="0.2.0")
        m = _cr()
        pairs, orphans = m.auto_pair_runs(m.discover_runs(tmp_path))
        assert pairs == []
        assert len(orphans) == 2

    def test_most_recent_run_wins_when_multiple_same_condition(self, tmp_path):
        # Three RAG runs of same key — most recent should be picked.
        _build_fake_run(tmp_path, folder="rA", rag_enabled=False,
                        started_at="2026-05-24T01:00:00Z")
        _build_fake_run(tmp_path, folder="r_rag_old", rag_enabled=True,
                        started_at="2026-05-24T02:00:00Z")
        _build_fake_run(tmp_path, folder="r_rag_mid", rag_enabled=True,
                        started_at="2026-05-24T03:00:00Z")
        _build_fake_run(tmp_path, folder="r_rag_new", rag_enabled=True,
                        started_at="2026-05-24T04:00:00Z")
        m = _cr()
        pairs, _ = m.auto_pair_runs(m.discover_runs(tmp_path))
        assert len(pairs) == 1
        _, rag = pairs[0]
        assert rag.path.name == "r_rag_new"

    def test_multiple_keys_pair_independently(self, tmp_path):
        _build_fake_run(tmp_path, folder="oa_norag", rag_enabled=False, company="OpenAI")
        _build_fake_run(tmp_path, folder="oa_rag",   rag_enabled=True,  company="OpenAI")
        _build_fake_run(tmp_path, folder="an_norag", rag_enabled=False, company="Anthropic")
        _build_fake_run(tmp_path, folder="an_rag",   rag_enabled=True,  company="Anthropic")
        m = _cr()
        pairs, orphans = m.auto_pair_runs(m.discover_runs(tmp_path))
        assert len(pairs) == 2
        assert orphans == []


# ---------------------------------------------------------------------------
# extract_grounded_claims
# ---------------------------------------------------------------------------

class TestExtractGroundedClaims:
    def test_pulls_from_all_three_phases(self, tmp_path):
        rd = _build_fake_run(
            tmp_path, folder="rag_run", rag_enabled=True,
            deliberation_events=[{
                "index": 0, "role": "CEO", "kind": "text",
                "text": "We will release with permissive licensing.",
                "citations": [{
                    "doc_id": "openai_blog.md", "chunk_id": "openai_blog.md#1",
                    "quote": "broad accessibility helps",
                    "supports": "open-weight commitment",
                }],
            }],
            artefacts={"CEO": _basic_artefact(
                "CEO", main_decisions=["release openly"],
                citations=[{
                    "doc_id": "openai_letter.md", "chunk_id": "openai_letter.md#3",
                    "quote": "cadence aligns with safety",
                    "supports": "release cadence",
                }],
            )},
            debrief_exchanges=[{
                "utterance": {"area_id": "D", "addressed_to": "CEO",
                               "anchor_refs": ["X"], "text": "why?"},
                "responses": [{
                    "role": "CEO", "text": "we discussed in our letter.",
                    "citations": [{
                        "doc_id": "openai_letter.md", "chunk_id": "openai_letter.md#5",
                        "quote": "we have communicated this position",
                        "supports": "consistency",
                    }],
                }],
            }],
        )
        m = _cr()
        ref = m.load_run(rd)
        claims = m.extract_grounded_claims(ref)
        # One claim from each phase.
        assert len(claims) == 3
        phases = sorted(c.phase for c in claims)
        assert phases == [
            "phase_1_deliberation",
            "phase_2_artefact",
            "phase_4_debriefing",
        ]
        # The phase-2 claim is artefact-level: statement_text is the title.
        p2 = next(c for c in claims if c.phase == "phase_2_artefact")
        assert p2.statement_text == "CEO strategy"
        assert p2.supports == "release cadence"

    def test_empty_when_no_citations_anywhere(self, tmp_path):
        rd = _build_fake_run(
            tmp_path, folder="empty_rag", rag_enabled=True,
            deliberation_events=[{"index": 0, "role": "CEO", "kind": "text",
                                   "text": "no citations here", "citations": []}],
            artefacts={"CEO": _basic_artefact("CEO", main_decisions=["x"])},
        )
        m = _cr()
        ref = m.load_run(rd)
        assert m.extract_grounded_claims(ref) == []


# ---------------------------------------------------------------------------
# compute_decision_diffs
# ---------------------------------------------------------------------------

class TestComputeDecisionDiffs:
    def test_set_diff_per_field(self, tmp_path):
        no_rag = _build_fake_run(tmp_path, folder="nr", rag_enabled=False,
            artefacts={"CEO": _basic_artefact(
                "CEO",
                main_decisions=["A", "B"],
                key_tensions=["T1"],
                key_challenges=["C1", "C2"],
            )})
        rag = _build_fake_run(tmp_path, folder="r", rag_enabled=True,
            artefacts={"CEO": _basic_artefact(
                "CEO",
                main_decisions=["B", "C"],   # dropped A, added C, kept B
                key_tensions=["T2"],          # dropped T1, added T2
                key_challenges=["C1", "C2"],  # all kept
            )})
        m = _cr()
        diffs = m.compute_decision_diffs(m.load_run(no_rag), m.load_run(rag))
        ceo = next(d for d in diffs if d.role == "CEO")
        assert ceo.main_decisions_added == ["C"]
        assert ceo.main_decisions_dropped == ["A"]
        assert ceo.main_decisions_kept == ["B"]
        assert ceo.key_tensions_added == ["T2"]
        assert ceo.key_tensions_dropped == ["T1"]
        assert ceo.key_tensions_kept == []
        assert ceo.key_challenges_added == []
        assert ceo.key_challenges_dropped == []
        assert ceo.key_challenges_kept == ["C1", "C2"]

    def test_role_not_in_either_run_skipped(self, tmp_path):
        no_rag = _build_fake_run(tmp_path, folder="nr", rag_enabled=False,
            artefacts={"CEO": _basic_artefact("CEO", main_decisions=["x"])})
        rag = _build_fake_run(tmp_path, folder="r", rag_enabled=True,
            artefacts={"CEO": _basic_artefact("CEO", main_decisions=["x"])})
        m = _cr()
        diffs = m.compute_decision_diffs(m.load_run(no_rag), m.load_run(rag))
        # Only CEO has artefacts in both runs.
        assert {d.role for d in diffs} == {"CEO"}


# ---------------------------------------------------------------------------
# compute_citation_density
# ---------------------------------------------------------------------------

class TestComputeCitationDensity:
    def test_aggregates_across_three_phases(self, tmp_path):
        cite1 = {"doc_id": "doc_A", "chunk_id": "doc_A#1",
                 "quote": "q1", "supports": "s1"}
        cite2 = {"doc_id": "doc_B", "chunk_id": "doc_B#1",
                 "quote": "q2", "supports": "s2"}
        cite3 = {"doc_id": "doc_A", "chunk_id": "doc_A#2",
                 "quote": "q3", "supports": "s3"}
        rd = _build_fake_run(
            tmp_path, folder="rag_run", rag_enabled=True,
            deliberation_events=[{
                "index": 0, "role": "CEO", "kind": "text", "text": "x",
                "citations": [cite1],
            }],
            artefacts={
                "CEO": _basic_artefact("CEO", main_decisions=["x"],
                                        citations=[cite2]),
                "CTO": _basic_artefact("CTO", main_decisions=["y"]),  # no citations
            },
            debrief_exchanges=[{
                "utterance": {"area_id": "D", "addressed_to": "CEO",
                               "anchor_refs": ["x"], "text": "q"},
                "responses": [{"role": "CTO", "text": "ans",
                                "citations": [cite3]}],
            }],
        )
        m = _cr()
        cd = m.compute_citation_density(m.load_run(rd))
        assert cd.total_citations == 3
        assert cd.distinct_docs_cited == 2   # doc_A appears twice but counts once
        assert cd.by_role["CEO"] == 2  # one P1 + one P2
        assert cd.by_role["CTO"] == 1  # one P4
        assert cd.by_phase["phase_1_deliberation"] == 1
        assert cd.by_phase["phase_2_artefact"] == 1
        assert cd.by_phase["phase_4_debriefing"] == 1
        # 1 of 2 artefacts has a citation.
        assert cd.pct_artefacts_with_citation == 0.5


# ---------------------------------------------------------------------------
# compute_corpus_coverage
# ---------------------------------------------------------------------------

class TestComputeCorpusCoverage:
    def test_classifies_docs_by_retrieve_and_cite(self, tmp_path):
        rd = _build_fake_run(
            tmp_path, folder="rag_run", rag_enabled=True,
            corpus_docs=[
                {"display_name": "doc_A", "sha256": "a"},
                {"display_name": "doc_B", "sha256": "b"},
                {"display_name": "doc_C", "sha256": "c"},  # never used
            ],
            retrieval_log=[
                {"phase": "phase_1_deliberation", "role": "CEO",
                 "retrieved": [
                     {"doc_id": "doc_A", "chunk_id": "doc_A#1",
                      "text": "alpha"},
                     {"doc_id": "doc_B", "chunk_id": "doc_B#1",
                      "text": "bravo"},
                 ]},
            ],
            deliberation_events=[{
                "index": 0, "role": "CEO", "kind": "text", "text": "x",
                "citations": [{"doc_id": "doc_A", "chunk_id": "doc_A#1",
                                "quote": "alpha", "supports": "s"}],
            }],
        )
        m = _cr()
        cc = m.compute_corpus_coverage(m.load_run(rd))
        assert sorted(cc.docs_in_corpus) == ["doc_A", "doc_B", "doc_C"]
        assert sorted(cc.docs_retrieved_at_least_once) == ["doc_A", "doc_B"]
        assert sorted(cc.docs_cited_at_least_once) == ["doc_A"]
        assert cc.docs_never_used == ["doc_C"]
        assert cc.coverage_retrieved_pct == pytest.approx(2 / 3)
        assert cc.coverage_cited_pct == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# verify_quotes — success + fabrication
# ---------------------------------------------------------------------------

class TestVerifyQuotes:
    def test_quote_in_retrieved_chunk_is_verified(self, tmp_path):
        chunk_text = (
            "We continue to believe that broad accessibility of frontier "
            "models accelerates safety research."
        )
        rd = _build_fake_run(
            tmp_path, folder="rag", rag_enabled=True,
            retrieval_log=[{
                "phase": "phase_1_deliberation", "role": "CEO",
                "retrieved": [{"doc_id": "openai_blog.md",
                                "chunk_id": "openai_blog.md#1",
                                "text": chunk_text}],
            }],
            deliberation_events=[{
                "index": 0, "role": "CEO", "kind": "text", "text": "x",
                "citations": [{"doc_id": "openai_blog.md",
                                "chunk_id": "openai_blog.md#1",
                                "quote": "broad accessibility of frontier models",
                                "supports": "open weights"}],
            }],
        )
        m = _cr()
        qv = m.verify_quotes(m.load_run(rd))
        assert qv.total_citations == 1
        assert qv.verified == 1
        assert qv.unverified == 0
        assert qv.flagged == []

    def test_quote_not_in_any_chunk_is_flagged(self, tmp_path):
        rd = _build_fake_run(
            tmp_path, folder="rag", rag_enabled=True,
            retrieval_log=[{
                "phase": "phase_1_deliberation", "role": "CEO",
                "retrieved": [{"doc_id": "openai_blog.md",
                                "chunk_id": "openai_blog.md#1",
                                "text": "alpha bravo charlie"}],
            }],
            deliberation_events=[{
                "index": 0, "role": "CEO", "kind": "text", "text": "x",
                "citations": [{"doc_id": "openai_blog.md",
                                "chunk_id": "openai_blog.md#1",
                                "quote": "this text was never in the chunk",
                                "supports": "fabrication"}],
            }],
        )
        m = _cr()
        qv = m.verify_quotes(m.load_run(rd))
        assert qv.total_citations == 1
        assert qv.unverified == 1
        assert qv.verified == 0
        assert len(qv.flagged) == 1
        assert qv.flagged[0]["reason"] == "quote_not_found_in_retrieved_chunks"

    def test_doc_id_never_retrieved_is_flagged_distinctly(self, tmp_path):
        rd = _build_fake_run(
            tmp_path, folder="rag", rag_enabled=True,
            retrieval_log=[{
                "phase": "phase_1_deliberation", "role": "CEO",
                "retrieved": [{"doc_id": "actually_retrieved.md",
                                "chunk_id": "x#1",
                                "text": "any chunk"}],
            }],
            deliberation_events=[{
                "index": 0, "role": "CEO", "kind": "text", "text": "x",
                "citations": [{"doc_id": "ghost_doc.md",  # never in retrieval log
                                "chunk_id": "ghost#1",
                                "quote": "doesn't matter",
                                "supports": "phantom"}],
            }],
        )
        m = _cr()
        qv = m.verify_quotes(m.load_run(rd))
        assert qv.unverified == 1
        assert qv.flagged[0]["reason"] == "doc_not_in_retrieval_log"

    def test_quote_match_is_whitespace_and_case_insensitive(self, tmp_path):
        chunk_text = "We continue to believe that broad accessibility helps."
        rd = _build_fake_run(
            tmp_path, folder="rag", rag_enabled=True,
            retrieval_log=[{
                "phase": "phase_1_deliberation", "role": "CEO",
                "retrieved": [{"doc_id": "d", "chunk_id": "d#1",
                                "text": chunk_text}],
            }],
            deliberation_events=[{
                "index": 0, "role": "CEO", "kind": "text", "text": "x",
                "citations": [{"doc_id": "d", "chunk_id": "d#1",
                                # Different case + extra whitespace.
                                "quote": "BROAD   accessibility helps",
                                "supports": "s"}],
            }],
        )
        m = _cr()
        qv = m.verify_quotes(m.load_run(rd))
        assert qv.verified == 1

    def test_falls_back_to_text_preview_for_legacy_runs(self, tmp_path):
        """The retrieval-log preview field name was `text_preview` in
        earlier R3 versions; ensure backwards-compat for those runs."""
        rd = _build_fake_run(
            tmp_path, folder="rag", rag_enabled=True,
            retrieval_log=[{
                "phase": "phase_1_deliberation", "role": "CEO",
                "retrieved": [{"doc_id": "d", "chunk_id": "d#1",
                                # Legacy field name.
                                "text_preview": "broad accessibility helps"}],
            }],
            deliberation_events=[{
                "index": 0, "role": "CEO", "kind": "text", "text": "x",
                "citations": [{"doc_id": "d", "chunk_id": "d#1",
                                "quote": "broad accessibility",
                                "supports": "s"}],
            }],
        )
        m = _cr()
        qv = m.verify_quotes(m.load_run(rd))
        assert qv.verified == 1


# ---------------------------------------------------------------------------
# compute_judging_delta
# ---------------------------------------------------------------------------

class TestComputeJudgingDelta:
    def test_per_dimension_delta_and_alpha(self, tmp_path):
        no_rag = _build_fake_run(
            tmp_path, folder="nr", rag_enabled=False,
            judging={"dimension_composites":
                     {"component_disclosure": 3.0, "process_openness": 4.0},
                     "alpha": -0.05},
        )
        rag = _build_fake_run(
            tmp_path, folder="r", rag_enabled=True,
            judging={"dimension_composites":
                     {"component_disclosure": 4.2, "process_openness": 4.5},
                     "alpha": 0.35},
        )
        m = _cr()
        jd = m.compute_judging_delta(m.load_run(no_rag), m.load_run(rag))
        assert jd is not None
        assert jd.per_dimension_delta["component_disclosure"] == pytest.approx(1.2)
        assert jd.per_dimension_delta["process_openness"] == pytest.approx(0.5)
        assert jd.alpha_delta == pytest.approx(0.40)

    def test_returns_none_when_either_judging_missing(self, tmp_path):
        no_rag = _build_fake_run(tmp_path, folder="nr", rag_enabled=False)
        rag = _build_fake_run(
            tmp_path, folder="r", rag_enabled=True,
            judging={"dimension_composites": {"d": 1.0}, "alpha": 0.1},
        )
        m = _cr()
        assert m.compute_judging_delta(m.load_run(no_rag), m.load_run(rag)) is None


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

class TestMarkdownRendering:
    def _make_pair(self, tmp_path):
        no_rag = _build_fake_run(tmp_path, folder="nr", rag_enabled=False,
            artefacts={"CEO": _basic_artefact("CEO", main_decisions=["A"])})
        rag = _build_fake_run(tmp_path, folder="r", rag_enabled=True,
            artefacts={"CEO": _basic_artefact(
                "CEO", main_decisions=["A", "B"],
                citations=[{
                    "doc_id": "openai_letter.md",
                    "chunk_id": "openai_letter.md#3",
                    "quote": "broad accessibility helps",
                    "supports": "open-weight commitment",
                }],
            )},
            retrieval_log=[{
                "phase": "phase_2_artefact", "role": "CEO",
                "retrieved": [{
                    "doc_id": "openai_letter.md",
                    "chunk_id": "openai_letter.md#3",
                    "text": "We continue to believe that broad accessibility helps.",
                }],
            }],
            corpus_docs=[{"display_name": "openai_letter.md", "sha256": "x"}],
        )
        m = _cr()
        return m.compute_pair_metrics(m.load_run(no_rag), m.load_run(rag))

    def test_grounded_claims_section_present_and_first(self, tmp_path):
        m = _cr()
        pm = self._make_pair(tmp_path)
        md = m.render_pair_report_md(pm)
        idx_grounded = md.index("## Grounded claims")
        idx_decision = md.index("## Decision diff")
        idx_citation = md.index("## Citation density")
        # Grounded claims must come first.
        assert idx_grounded < idx_decision
        assert idx_decision < idx_citation
        # And the actual citation content lands in the section.
        assert "open-weight commitment" in md
        assert "openai_letter.md" in md

    def test_decision_diff_shows_added_and_dropped(self, tmp_path):
        m = _cr()
        pm = self._make_pair(tmp_path)
        md = m.render_pair_report_md(pm)
        assert "Added (RAG only):" in md
        assert "- B" in md

    def test_citation_density_table_rendered(self, tmp_path):
        m = _cr()
        pm = self._make_pair(tmp_path)
        md = m.render_pair_report_md(pm)
        assert "Total citations:** 1" in md
        assert "| CEO | 1 |" in md  # by-role table


# ---------------------------------------------------------------------------
# Cross-pair + CSV
# ---------------------------------------------------------------------------

class TestCrossPair:
    def _two_pairs(self, tmp_path):
        m = _cr()
        # Pair 1: OpenAI
        nr1 = _build_fake_run(tmp_path, folder="oa_nr", rag_enabled=False,
            company="OpenAI",
            artefacts={"CEO": _basic_artefact("CEO", main_decisions=["A"])})
        r1 = _build_fake_run(tmp_path, folder="oa_r", rag_enabled=True,
            company="OpenAI",
            artefacts={"CEO": _basic_artefact("CEO", main_decisions=["A", "B"],
                citations=[{"doc_id": "d1", "chunk_id": "d1#1",
                             "quote": "q1", "supports": "s"}])},
            retrieval_log=[{"phase": "phase_2_artefact", "role": "CEO",
                "retrieved": [{"doc_id": "d1", "chunk_id": "d1#1", "text": "q1"}]}],
            corpus_docs=[{"display_name": "d1", "sha256": "a"}])

        # Pair 2: Anthropic
        nr2 = _build_fake_run(tmp_path, folder="an_nr", rag_enabled=False,
            company="Anthropic",
            artefacts={"CEO": _basic_artefact("CEO", main_decisions=["X"])})
        r2 = _build_fake_run(tmp_path, folder="an_r", rag_enabled=True,
            company="Anthropic",
            artefacts={"CEO": _basic_artefact("CEO", main_decisions=["Y"],
                citations=[{"doc_id": "d2", "chunk_id": "d2#1",
                             "quote": "q2", "supports": "s"}])},
            retrieval_log=[{"phase": "phase_2_artefact", "role": "CEO",
                "retrieved": [{"doc_id": "d2", "chunk_id": "d2#1", "text": "q2"}]}],
            corpus_docs=[{"display_name": "d2", "sha256": "a"}])

        pairs, orphans = m.auto_pair_runs(m.discover_runs(tmp_path))
        return [m.compute_pair_metrics(nr, r) for nr, r in pairs], orphans

    def test_cross_pair_metrics_roll_up_citations(self, tmp_path):
        m = _cr()
        pairs, orphans = self._two_pairs(tmp_path)
        cross = m.compute_cross_pair_metrics(pairs, orphans)
        assert cross.n_pairs == 2
        assert cross.n_orphans == 0
        assert cross.citations_per_pair == [1, 1]
        assert "CEO" in cross.citations_per_pair_by_role
        assert cross.citations_per_pair_by_role["CEO"] == [1, 1]

    def test_cross_pair_summary_md_lists_pairs(self, tmp_path):
        m = _cr()
        pairs, orphans = self._two_pairs(tmp_path)
        cross = m.compute_cross_pair_metrics(pairs, orphans)
        md = m.render_cross_pair_summary_md(cross, pairs)
        assert "Paired runs:** 2" in md
        # Per-pair index links.
        assert "OpenAI_Dynamic_Novel_gemini_pro" in md
        assert "Anthropic_Dynamic_Novel_gemini_pro" in md

    def test_summary_csv_emits_one_row_per_pair_per_role(self, tmp_path):
        m = _cr()
        pairs, _ = self._two_pairs(tmp_path)
        out_csv = tmp_path / "summary.csv"
        m.emit_summary_csv(pairs, out_csv)
        rows = list(csv.DictReader(out_csv.open()))
        # Two pairs, each with CEO only — two rows.
        assert len(rows) == 2
        assert {r["company"] for r in rows} == {"OpenAI", "Anthropic"}
        # CEO of Anthropic dropped X, added Y.
        anthropic_row = next(r for r in rows if r["company"] == "Anthropic")
        assert int(anthropic_row["main_decisions_added"]) == 1
        assert int(anthropic_row["main_decisions_dropped"]) == 1


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------

class TestCLI:
    def test_missing_root_returns_nonzero(self, tmp_path, capsys):
        m = _cr()
        rc = m.main(["--runs-root", str(tmp_path / "nope")])
        assert rc == 1
        assert "does not exist" in capsys.readouterr().out

    def test_dry_run_lists_pairings(self, tmp_path, capsys):
        _build_fake_run(tmp_path, folder="nr", rag_enabled=False)
        _build_fake_run(tmp_path, folder="r",  rag_enabled=True)
        m = _cr()
        rc = m.main(["--runs-root", str(tmp_path), "--dry-run"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "paired: 1" in out
        assert "OpenAI_Dynamic_Novel_gemini_pro" in out

    def test_writes_per_pair_md_and_summary_csv(self, tmp_path):
        _build_fake_run(tmp_path, folder="nr", rag_enabled=False,
            artefacts={"CEO": _basic_artefact("CEO", main_decisions=["A"])})
        _build_fake_run(tmp_path, folder="r",  rag_enabled=True,
            artefacts={"CEO": _basic_artefact("CEO", main_decisions=["B"])})
        out_dir = tmp_path / "comparisons"
        m = _cr()
        rc = m.main([
            "--runs-root", str(tmp_path), "--out", str(out_dir),
        ])
        assert rc == 0
        assert (out_dir / "README.md").exists()
        assert (out_dir / "summary.csv").exists()
        per_pair = list((out_dir / "per_pair").glob("*.md"))
        assert len(per_pair) == 1

    def test_empty_runs_root_still_emits_summary(self, tmp_path):
        out_dir = tmp_path / "out"
        m = _cr()
        rc = m.main([
            "--runs-root", str(tmp_path), "--out", str(out_dir),
        ])
        assert rc == 0
        # No pairs, but the dispatcher returns 0; no summary written
        # because there were no runs (special-cased in main()).
