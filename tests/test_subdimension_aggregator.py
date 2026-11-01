"""Tests for the v0.4 dual-granularity aggregator (PR-D commit 4/6).

The aggregator now computes:

* Parent-dimension α (unchanged from v0.3) — α per parent dim + the
  overall α across all parent ratings.
* **Sub-dimension α** — α per sub-dim (using each judge's Likert
  back-bin), keyed by `sub_dimension_key`.
* `per_sub_dimension_means_pct` — mean of judges' `score_pct` per
  sub-dim (the continuous 0-100 view the Likert hides).
* `per_sub_dimension_means_likert` — that mean back-binned to Likert
  for reviewer-compatible reporting.

These tests verify the new aggregator math + that the v0.3 path stays
identical when no sub-dim assessments are supplied.
"""

from __future__ import annotations

import importlib

import pytest

PKG = "open-innovation-strategy"


def _judging():
    return importlib.import_module(f"{PKG}.orchestrator.construct_judging")


def _schemas():
    return importlib.import_module(f"{PKG}.roles.judge_schemas")


_RUBRIC_KEYS = (
    "component_disclosure",
    "process_openness",
    "boundary_permeability_inbound",
    "boundary_permeability_outbound",
    "ecosystem_orchestration",
    "value_capture_posture",
    "temporal_openness_maneuvering",
)


def _make_parent_dim_assessments(judge_id: str, score: int = 4):
    """Build a v0.3-shape DimensionAssessment list (7 entries, Likert)."""
    sch = _schemas()
    return [
        sch.DimensionAssessment(
            dimension=k, score=score,
            reasoning="auto", evidence=[], confidence="medium",
        )
        for k in _RUBRIC_KEYS
    ]


def _make_subdim_assessment(
    *, key: str, parent: str, score_pct: float,
):
    sch = _schemas()
    return sch.SubDimensionAssessment(
        sub_dimension_key=key,
        parent_dimension=parent,
        score_pct=score_pct,
        likert_back_binned=sch.percent_to_likert(score_pct),
        qualitative_anchor=sch.percent_to_anchor(score_pct),
        reasoning="three sentences of reasoning",
        evidence_quotes=[
            sch.EvidenceQuote(
                source_file="01_deliberation/interaction_log.md",
                quote=f"evidence for {key} #1",
            ),
            sch.EvidenceQuote(
                source_file="02_strategy_documents/CEO_strategy.md",
                quote=f"evidence for {key} #2",
            ),
        ],
        confidence="high",
    )


def _build_assessment_with_subdims(
    judge_id: str,
    sub_scores: dict[str, tuple[str, float]],  # key → (parent, score_pct)
    parent_dim_likert: int = 4,
):
    """Build a ConstructAssessment that populates BOTH the v0.3
    parent-dim list and the v0.4 sub-dim list."""
    sch = _schemas()
    return sch.ConstructAssessment(
        judge_id=judge_id,
        qualitative_summary="auto",
        dimension_scores=_make_parent_dim_assessments(judge_id, parent_dim_likert),
        sub_dimension_assessments=[
            _make_subdim_assessment(key=k, parent=p, score_pct=pct)
            for k, (p, pct) in sub_scores.items()
        ],
        composite_score=float(parent_dim_likert),
        overall_confidence="medium",
        caveats="",
    )


# ===========================================================================
# v0.3 back-compat — bundles without sub-dim assessments
# ===========================================================================

class TestAggregatorV03BackCompat:
    """No sub-dim assessments supplied → sub-dim fields remain empty;
    parent-dim math is unchanged."""

    def test_v03_assessments_produce_empty_subdim_fields(self):
        j = _judging()
        sch = _schemas()
        assessments = [
            sch.ConstructAssessment(
                judge_id=jid,
                qualitative_summary="auto",
                dimension_scores=_make_parent_dim_assessments(jid, score=4),
                composite_score=4.0,
                overall_confidence="medium",
                caveats="",
            )
            for jid in ("gemini_pro", "claude", "openai")
        ]
        bundle = j._aggregate(
            assessments=assessments,
            rubric_dim_keys=list(_RUBRIC_KEYS),
        )
        # Sub-dim fields are empty under v0.3.
        assert bundle.per_sub_dimension_means_pct == {}
        assert bundle.per_sub_dimension_means_likert == {}
        assert bundle.inter_rater_agreement.per_sub_dimension_alpha == {}
        assert bundle.inter_rater_agreement.n_sub_dimensions == 0
        # Parent-dim path is unchanged.
        assert bundle.mean_composite == 4.0
        assert bundle.inter_rater_agreement.n_dimensions == 7


# ===========================================================================
# v0.4 — sub-dim assessments produce the new aggregate fields
# ===========================================================================

class TestAggregatorV04SubDim:
    def test_subdim_means_pct_computed_across_judges(self):
        """When two judges score the same sub-dim at different percents,
        the bundle's `per_sub_dimension_means_pct` shows the cross-judge
        mean."""
        j = _judging()
        # gemini: 60% on outbound_publication_intensity
        # claude: 80% on the same
        # → mean 70.0
        ga = _build_assessment_with_subdims(
            "gemini_pro",
            sub_scores={
                "outbound_publication_intensity": (
                    "boundary_permeability_outbound", 60.0,
                ),
            },
        )
        ca = _build_assessment_with_subdims(
            "claude",
            sub_scores={
                "outbound_publication_intensity": (
                    "boundary_permeability_outbound", 80.0,
                ),
            },
        )
        bundle = j._aggregate(
            assessments=[ga, ca],
            rubric_dim_keys=list(_RUBRIC_KEYS),
        )
        assert bundle.per_sub_dimension_means_pct[
            "outbound_publication_intensity"
        ] == pytest.approx(70.0)

    def test_subdim_means_likert_is_backbinned_correctly(self):
        """Mean of 70.0% → bucket 'substantial' → Likert 5."""
        j = _judging()
        sch = _schemas()
        ga = _build_assessment_with_subdims(
            "gemini_pro",
            sub_scores={
                "outbound_publication_intensity": (
                    "boundary_permeability_outbound", 60.0,
                ),
            },
        )
        ca = _build_assessment_with_subdims(
            "claude",
            sub_scores={
                "outbound_publication_intensity": (
                    "boundary_permeability_outbound", 80.0,
                ),
            },
        )
        bundle = j._aggregate(
            assessments=[ga, ca],
            rubric_dim_keys=list(_RUBRIC_KEYS),
        )
        # 70% → "substantial" → Likert 5.
        assert bundle.per_sub_dimension_means_likert[
            "outbound_publication_intensity"
        ] == 5
        # Sanity: matches the conversion helper directly.
        assert sch.percent_to_likert(70.0) == 5

    def test_subdim_alpha_uses_likert_backbin_not_percent(self):
        """α is computed on the judges' likert back-bin values, not raw
        percent. Two judges at 60% and 80% back-bin to Likert 5 and 6
        respectively — α should reflect that one-point Likert gap, not
        the larger numeric gap on the percent scale."""
        j = _judging()
        ga = _build_assessment_with_subdims(
            "gemini_pro",
            sub_scores={
                "outbound_publication_intensity": (
                    "boundary_permeability_outbound", 60.0,  # Likert 5
                ),
            },
        )
        ca = _build_assessment_with_subdims(
            "claude",
            sub_scores={
                "outbound_publication_intensity": (
                    "boundary_permeability_outbound", 80.0,  # Likert 6
                ),
            },
        )
        bundle = j._aggregate(
            assessments=[ga, ca],
            rubric_dim_keys=list(_RUBRIC_KEYS),
        )
        alpha = bundle.inter_rater_agreement.per_sub_dimension_alpha[
            "outbound_publication_intensity"
        ]
        # Two raters at adjacent Likert values → α between 0 and 1 (not
        # perfect agreement, not maximal disagreement).
        assert 0.0 < alpha < 1.0, (
            f"expected α in (0, 1) for one-point Likert gap; got {alpha}"
        )

    def test_perfect_subdim_agreement_alpha_is_one(self):
        j = _judging()
        # Both judges at exactly 60.0 → identical Likert (5) → α = 1.0
        ga = _build_assessment_with_subdims(
            "gemini_pro",
            sub_scores={
                "outbound_publication_intensity": (
                    "boundary_permeability_outbound", 60.0,
                ),
            },
        )
        ca = _build_assessment_with_subdims(
            "claude",
            sub_scores={
                "outbound_publication_intensity": (
                    "boundary_permeability_outbound", 60.0,
                ),
            },
        )
        bundle = j._aggregate(
            assessments=[ga, ca],
            rubric_dim_keys=list(_RUBRIC_KEYS),
        )
        alpha = bundle.inter_rater_agreement.per_sub_dimension_alpha[
            "outbound_publication_intensity"
        ]
        assert alpha == pytest.approx(1.0)

    def test_n_sub_dimensions_reflects_count_in_assessments(self):
        j = _judging()
        ga = _build_assessment_with_subdims(
            "gemini_pro",
            sub_scores={
                "outbound_publication_intensity": (
                    "boundary_permeability_outbound", 60.0,
                ),
                "external_hiring": (
                    "boundary_permeability_inbound", 40.0,
                ),
            },
        )
        ca = _build_assessment_with_subdims(
            "claude",
            sub_scores={
                "outbound_publication_intensity": (
                    "boundary_permeability_outbound", 80.0,
                ),
                "external_hiring": (
                    "boundary_permeability_inbound", 50.0,
                ),
            },
        )
        bundle = j._aggregate(
            assessments=[ga, ca],
            rubric_dim_keys=list(_RUBRIC_KEYS),
        )
        assert bundle.inter_rater_agreement.n_sub_dimensions == 2

    def test_single_judge_subdim_alpha_is_nan(self):
        """Only one judge providing a sub-dim value → α undefined."""
        j = _judging()
        a = _build_assessment_with_subdims(
            "gemini_pro",
            sub_scores={
                "outbound_publication_intensity": (
                    "boundary_permeability_outbound", 60.0,
                ),
            },
        )
        bundle = j._aggregate(
            assessments=[a],
            rubric_dim_keys=list(_RUBRIC_KEYS),
        )
        alpha = bundle.inter_rater_agreement.per_sub_dimension_alpha[
            "outbound_publication_intensity"
        ]
        # NaN is the standard signal for undefined α.
        assert alpha != alpha


# ===========================================================================
# Markdown render — sub-dim table appears under v0.4
# ===========================================================================

class TestSubDimMarkdownRender:
    def test_subdim_table_lands_when_subdim_means_present(self):
        from analysis.persist_artefacts import _render_judgment_aggregate_md
        bundle = {
            "judges_used": ["gemini_pro", "claude"],
            "mean_composite": 4.5,
            "per_dimension_means": {k: 4.5 for k in _RUBRIC_KEYS},
            "consensus_dimension_scores": {k: 4 for k in _RUBRIC_KEYS},
            "per_sub_dimension_means_pct": {
                "outbound_publication_intensity": 70.0,
                "external_hiring": 45.0,
            },
            "per_sub_dimension_means_likert": {
                "outbound_publication_intensity": 5,
                "external_hiring": 4,
            },
            "inter_rater_agreement": {
                "overall_alpha": 0.85,
                "per_dimension_alpha": {k: 1.0 for k in _RUBRIC_KEYS},
                "per_sub_dimension_alpha": {
                    "outbound_publication_intensity": 0.92,
                    "external_hiring": 0.74,
                },
                "n_judges": 2, "n_dimensions": 7, "n_sub_dimensions": 2,
            },
            "assessments": [],
            "judge_errors": {},
        }
        md = _render_judgment_aggregate_md(bundle)
        # The new section header lands.
        assert "Per-sub-dimension scores" in md
        # Each sub-dim row appears.
        assert "outbound_publication_intensity" in md
        assert "external_hiring" in md
        # Percent + Likert + α columns all rendered.
        assert "70.0" in md
        assert "45.0" in md

    def test_subdim_section_omitted_when_no_subdim_means(self):
        """v0.3 bundles without sub-dim assessments shouldn't render
        an empty sub-dim table."""
        from analysis.persist_artefacts import _render_judgment_aggregate_md
        bundle = {
            "judges_used": ["gemini_pro", "claude"],
            "mean_composite": 4.0,
            "per_dimension_means": {k: 4.0 for k in _RUBRIC_KEYS},
            "consensus_dimension_scores": {k: 4 for k in _RUBRIC_KEYS},
            "per_sub_dimension_means_pct": {},  # empty → skip section
            "per_sub_dimension_means_likert": {},
            "inter_rater_agreement": {
                "overall_alpha": 1.0,
                "per_dimension_alpha": {k: 1.0 for k in _RUBRIC_KEYS},
                "per_sub_dimension_alpha": {},
                "n_judges": 2, "n_dimensions": 7, "n_sub_dimensions": 0,
            },
            "assessments": [],
            "judge_errors": {},
        }
        md = _render_judgment_aggregate_md(bundle)
        assert "Per-sub-dimension scores" not in md
