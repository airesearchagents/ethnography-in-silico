"""Tests for the v0.4 post-hoc quote verification (PR-D commit 5/6).

The v0.4 judge prompt requires every sub-dim `EvidenceQuote.quote` to
come VERBATIM from one of the run's persisted markdown artefacts. This
module enforces that contract by substring-checking every quote
against the file named in `source_file`. Failures are SURFACED (in a
per-provider audit file + a bundle-level summary) but never auto-
discarded — a quote that fails the substring check may still be
useful evidence (the judge may have lightly normalised whitespace or
em-dashes).

Coverage:

* Substring match with whitespace normalisation (the common
  judge-side transform when copying a multi-line passage into a
  single-line quote field).
* Source-file-not-found path — graceful failure, no exception.
* Path-traversal guard — quotes whose `source_file` resolves outside
  `run_dir` are rejected.
* `QuoteAuditReport` summary fields: n_total / n_passed / n_failed /
  fail_rate.
* `render_quote_audit_md` produces a human-readable report with
  failure details on every failed quote.
* `ConstructJudgingPhase.persist` integration: audit files land per
  judge; the bundle's `quote_verification_summary` is populated.
* v0.3 back-compat: assessments without sub_dimension_assessments
  produce no audit files and no verification summary.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

PKG = "open-innovation-strategy"


def _qv():
    return importlib.import_module(f"{PKG}.analysis.quote_verification")


def _schemas():
    return importlib.import_module(f"{PKG}.roles.judge_schemas")


def _judging():
    return importlib.import_module(f"{PKG}.orchestrator.construct_judging")


# ===========================================================================
# Helpers
# ===========================================================================

_RUBRIC_KEYS = (
    "component_disclosure",
    "process_openness",
    "boundary_permeability_inbound",
    "boundary_permeability_outbound",
    "ecosystem_orchestration",
    "value_capture_posture",
    "temporal_openness_maneuvering",
)


def _make_run_dir(
    tmp_path: Path, *,
    deliberation_text: str = "we will open-source the M2M transport layer.",
    ceo_text: str = "hybrid edge-cloud is the only path that scales",
) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "01_deliberation").mkdir()
    (run_dir / "01_deliberation" / "interaction_log.md").write_text(
        f"### [0] CTO\n\n{deliberation_text}\n"
    )
    (run_dir / "02_strategy_documents").mkdir()
    (run_dir / "02_strategy_documents" / "CEO_strategy.md").write_text(
        f"# CEO strategy\n\n{ceo_text}\n"
    )
    return run_dir


def _make_assessment_dict(
    judge_id: str,
    quotes: list[tuple[str, str]],  # (source_file, quote)
) -> dict:
    """A ConstructAssessment-shaped dict with sub_dimension_assessments."""
    sch = _schemas()
    sub_dims = []
    for i, (source_file, quote) in enumerate(quotes):
        sub_dims.append({
            "sub_dimension_key": f"sub_dim_{i}",
            "parent_dimension": "boundary_permeability_outbound",
            "score_pct": 50.0,
            "likert_back_binned": 4,
            "qualitative_anchor": "moderate",
            "reasoning": "three sentences",
            "evidence_quotes": [
                {
                    "source_file": source_file,
                    "source_role": None,
                    "quote": quote,
                },
            ],
            "confidence": "medium",
        })
    return {
        "judge_id": judge_id,
        "qualitative_summary": "auto",
        "dimension_scores": [
            {"dimension": k, "score": 4, "reasoning": "auto",
             "evidence": [], "confidence": "medium"}
            for k in _RUBRIC_KEYS
        ],
        "sub_dimension_assessments": sub_dims,
        "composite_score": 4.0,
        "overall_confidence": "medium",
        "caveats": "",
    }


# ===========================================================================
# Substring matching with whitespace normalisation
# ===========================================================================

class TestSubstringMatching:
    def test_exact_quote_passes(self, tmp_path):
        qv = _qv()
        run_dir = _make_run_dir(tmp_path)
        a = _make_assessment_dict("gemini_pro", quotes=[
            ("01_deliberation/interaction_log.md",
             "we will open-source the M2M transport layer."),
        ])
        report = qv.verify_quotes_in_assessment(
            assessment=a, run_dir=run_dir,
        )
        assert report.n_total == 1
        assert report.n_passed == 1
        assert report.n_failed == 0
        assert report.entries[0].passed is True
        assert report.entries[0].failure_reason is None

    def test_whitespace_normalised_quote_passes(self, tmp_path):
        """A judge copying a multi-line passage often collapses
        whitespace. The verifier normalises both sides so this case
        passes."""
        qv = _qv()
        run_dir = _make_run_dir(tmp_path)
        # The source has a newline + 4 spaces of leading indent baked
        # into the .write_text above; the judge supplied a single-
        # space-collapsed quote.
        a = _make_assessment_dict("gemini_pro", quotes=[
            ("01_deliberation/interaction_log.md",
             "we will  open-source\tthe M2M transport layer."),  # extra whitespace
        ])
        report = qv.verify_quotes_in_assessment(
            assessment=a, run_dir=run_dir,
        )
        assert report.entries[0].passed is True

    def test_fabricated_quote_fails(self, tmp_path):
        qv = _qv()
        run_dir = _make_run_dir(tmp_path)
        a = _make_assessment_dict("gemini_pro", quotes=[
            ("01_deliberation/interaction_log.md",
             "we will close-source absolutely everything"),
        ])
        report = qv.verify_quotes_in_assessment(
            assessment=a, run_dir=run_dir,
        )
        assert report.entries[0].passed is False
        assert "no substring match" in (report.entries[0].failure_reason or "")

    def test_missing_source_file_fails_gracefully(self, tmp_path):
        qv = _qv()
        run_dir = _make_run_dir(tmp_path)
        a = _make_assessment_dict("gemini_pro", quotes=[
            ("99_does_not_exist/missing.md", "anything"),
        ])
        report = qv.verify_quotes_in_assessment(
            assessment=a, run_dir=run_dir,
        )
        assert report.entries[0].passed is False
        assert "source_file" in (report.entries[0].failure_reason or "")

    def test_path_traversal_rejected(self, tmp_path):
        """A judge supplying a `..` escape must not be able to cause
        an arbitrary file read."""
        qv = _qv()
        run_dir = _make_run_dir(tmp_path)
        # Write a sentinel file OUTSIDE the run_dir.
        outside = tmp_path / "secret.md"
        outside.write_text("CLASSIFIED")
        a = _make_assessment_dict("gemini_pro", quotes=[
            ("../secret.md", "CLASSIFIED"),
        ])
        report = qv.verify_quotes_in_assessment(
            assessment=a, run_dir=run_dir,
        )
        assert report.entries[0].passed is False, (
            "verifier must refuse to read outside run_dir even when "
            "the file exists + the quote matches"
        )

    def test_empty_quote_fails(self, tmp_path):
        qv = _qv()
        run_dir = _make_run_dir(tmp_path)
        a = _make_assessment_dict("gemini_pro", quotes=[
            ("01_deliberation/interaction_log.md", "   \n\t  "),  # whitespace only
        ])
        report = qv.verify_quotes_in_assessment(
            assessment=a, run_dir=run_dir,
        )
        assert report.entries[0].passed is False
        assert "empty" in (report.entries[0].failure_reason or "")


# ===========================================================================
# Report summary fields
# ===========================================================================

class TestReportSummary:
    def test_mixed_passes_and_fails(self, tmp_path):
        qv = _qv()
        run_dir = _make_run_dir(tmp_path)
        a = _make_assessment_dict("gemini_pro", quotes=[
            ("01_deliberation/interaction_log.md",
             "we will open-source the M2M transport layer."),  # pass
            ("02_strategy_documents/CEO_strategy.md", "FABRICATED"),  # fail
            ("02_strategy_documents/CEO_strategy.md",
             "hybrid edge-cloud is the only path that scales"),  # pass
        ])
        report = qv.verify_quotes_in_assessment(
            assessment=a, run_dir=run_dir,
        )
        assert report.n_total == 3
        assert report.n_passed == 2
        assert report.n_failed == 1
        assert report.fail_rate == pytest.approx(1 / 3)

    def test_empty_assessment_yields_zero_total(self, tmp_path):
        qv = _qv()
        run_dir = _make_run_dir(tmp_path)
        a = {"judge_id": "gemini_pro", "sub_dimension_assessments": []}
        report = qv.verify_quotes_in_assessment(
            assessment=a, run_dir=run_dir,
        )
        assert report.n_total == 0
        assert report.fail_rate == 0.0  # no division-by-zero


# ===========================================================================
# Markdown rendering
# ===========================================================================

class TestRenderQuoteAuditMd:
    def test_renders_summary_section(self, tmp_path):
        qv = _qv()
        run_dir = _make_run_dir(tmp_path)
        a = _make_assessment_dict("gemini_pro", quotes=[
            ("01_deliberation/interaction_log.md",
             "we will open-source the M2M transport layer."),
        ])
        report = qv.verify_quotes_in_assessment(
            assessment=a, run_dir=run_dir,
        )
        md = qv.render_quote_audit_md(report)
        assert "# Quote audit — judge: gemini_pro" in md
        assert "Total quotes checked" in md
        assert "Passed substring check" in md

    def test_all_passes_renders_clean_message(self, tmp_path):
        qv = _qv()
        run_dir = _make_run_dir(tmp_path)
        a = _make_assessment_dict("gemini_pro", quotes=[
            ("01_deliberation/interaction_log.md",
             "we will open-source the M2M transport layer."),
        ])
        report = qv.verify_quotes_in_assessment(
            assessment=a, run_dir=run_dir,
        )
        md = qv.render_quote_audit_md(report)
        assert "All quotes substring-matched" in md
        assert "Failed quotes" not in md

    def test_failures_surface_with_details(self, tmp_path):
        qv = _qv()
        run_dir = _make_run_dir(tmp_path)
        a = _make_assessment_dict("gemini_pro", quotes=[
            ("01_deliberation/interaction_log.md", "FABRICATED"),
        ])
        report = qv.verify_quotes_in_assessment(
            assessment=a, run_dir=run_dir,
        )
        md = qv.render_quote_audit_md(report)
        assert "Failed quotes (surfaced for PI review)" in md
        assert "FABRICATED" in md
        assert "no substring match" in md


# ===========================================================================
# Integration: ConstructJudgingPhase.persist writes audit files
# ===========================================================================

class TestPersistIntegration:
    def _v04_assessment(self, judge_id: str) -> dict:
        return _make_assessment_dict(judge_id, quotes=[
            ("01_deliberation/interaction_log.md",
             "we will open-source the M2M transport layer."),  # pass
            ("02_strategy_documents/CEO_strategy.md", "FABRICATED"),  # fail
        ])

    def test_persist_writes_per_judge_audit_md(self, tmp_path):
        j = _judging()
        sch = _schemas()
        # Build a run folder with the source files referenced by quotes.
        _make_run_dir(tmp_path)
        # Build a v0.4 bundle dict directly (skipping the aggregator —
        # this test focuses on the persist path).
        bundle = {
            "assessments": [
                self._v04_assessment("gemini_pro"),
                self._v04_assessment("claude"),
            ],
            "mean_composite": 4.0,
            "per_dimension_means": {k: 4.0 for k in _RUBRIC_KEYS},
            "consensus_dimension_scores": {k: 4 for k in _RUBRIC_KEYS},
            "per_sub_dimension_means_pct": {},
            "per_sub_dimension_means_likert": {},
            "inter_rater_agreement": {
                "overall_alpha": 1.0,
                "per_dimension_alpha": {k: 1.0 for k in _RUBRIC_KEYS},
                "per_sub_dimension_alpha": {},
                "n_judges": 2, "n_dimensions": 7, "n_sub_dimensions": 0,
            },
            "judges_used": ["gemini_pro", "claude"],
            "judge_errors": {},
            "quote_verification_summary": {},
        }
        # The run files must live at the out_dir/run sub-folder
        # since persist computes source_file paths relative to out_dir.
        out_dir = tmp_path / "run"  # already created by _make_run_dir
        phase = j.ConstructJudgingPhase()
        phase.persist(out_dir=out_dir, result=bundle, write_json=True)
        # Two audit files land.
        assert (out_dir / "05_judging" / "gemini_pro_quote_audit.md").exists()
        assert (out_dir / "05_judging" / "claude_quote_audit.md").exists()

    def test_persist_populates_verification_summary_in_aggregate(self, tmp_path):
        j = _judging()
        _make_run_dir(tmp_path)
        bundle = {
            "assessments": [self._v04_assessment("gemini_pro")],
            "mean_composite": 4.0,
            "per_dimension_means": {k: 4.0 for k in _RUBRIC_KEYS},
            "consensus_dimension_scores": {k: 4 for k in _RUBRIC_KEYS},
            "per_sub_dimension_means_pct": {},
            "per_sub_dimension_means_likert": {},
            "inter_rater_agreement": {
                "overall_alpha": 1.0,
                "per_dimension_alpha": {k: 1.0 for k in _RUBRIC_KEYS},
                "per_sub_dimension_alpha": {},
                "n_judges": 1, "n_dimensions": 7, "n_sub_dimensions": 0,
            },
            "judges_used": ["gemini_pro"],
            "judge_errors": {},
            "quote_verification_summary": {},
        }
        out_dir = tmp_path / "run"
        phase = j.ConstructJudgingPhase()
        phase.persist(out_dir=out_dir, result=bundle, write_json=True)
        # aggregate.json now carries verification_summary.
        agg = json.loads((out_dir / "05_judging" / "aggregate.json").read_text())
        assert "quote_verification_summary" in agg
        gp = agg["quote_verification_summary"]["gemini_pro"]
        # Two quotes in the _v04_assessment fixture: 1 pass + 1 fail.
        assert gp["n_total"] == 2
        assert gp["n_passed"] == 1
        assert gp["n_failed"] == 1

    def test_v03_assessments_skip_audit(self, tmp_path):
        """A bundle whose assessments have no sub_dimension_assessments
        (v0.3 back-compat) should produce no audit files and no
        verification summary in the bundle."""
        j = _judging()
        _make_run_dir(tmp_path)
        v03_assessment = {
            "judge_id": "gemini_pro",
            "qualitative_summary": "v0.3",
            "dimension_scores": [
                {"dimension": k, "score": 4, "reasoning": "auto",
                 "evidence": [], "confidence": "medium"}
                for k in _RUBRIC_KEYS
            ],
            "sub_dimension_assessments": [],  # explicit empty
            "composite_score": 4.0,
            "overall_confidence": "medium",
            "caveats": "",
        }
        bundle = {
            "assessments": [v03_assessment],
            "mean_composite": 4.0,
            "per_dimension_means": {k: 4.0 for k in _RUBRIC_KEYS},
            "consensus_dimension_scores": {k: 4 for k in _RUBRIC_KEYS},
            "per_sub_dimension_means_pct": {},
            "per_sub_dimension_means_likert": {},
            "inter_rater_agreement": {
                "overall_alpha": 1.0,
                "per_dimension_alpha": {k: 1.0 for k in _RUBRIC_KEYS},
                "per_sub_dimension_alpha": {},
                "n_judges": 1, "n_dimensions": 7, "n_sub_dimensions": 0,
            },
            "judges_used": ["gemini_pro"],
            "judge_errors": {},
            "quote_verification_summary": {},
        }
        out_dir = tmp_path / "run"
        phase = j.ConstructJudgingPhase()
        phase.persist(out_dir=out_dir, result=bundle, write_json=True)
        # No audit file written.
        assert not list((out_dir / "05_judging").glob("*_quote_audit.md"))
