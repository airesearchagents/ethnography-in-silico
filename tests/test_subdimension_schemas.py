"""Tests for the v0.4 sub-dimensional judge schemas + percent ↔ Likert
back-bin conversion.

PR-D moves construct scoring from a coarse 1-7 Likert at the
parent-dimension level (v0.3) to a native 0-100 percent score at the
**sub-dimension** level (v0.4), with a Likert back-bin computed for
reviewer-compatible reporting. 26 sub-dimensions, each backed by ≥2
verbatim quotes sourced exclusively from the run's persisted markdown.

This commit (PR-D commit 1) lands the schema layer + the conversion
helpers. Subsequent commits land the lexicon helpers, the judge-prompt
update, the aggregator change, and the post-hoc quote verifier.

Coverage in this module:

* `percent_to_likert` and `percent_to_anchor` — bucket assignment is
  correct at every boundary (especially the 14.5 / 28.5 / 42.5 / 56.5 /
  70.5 / 85.5 thresholds where small numerical jitter could otherwise
  bounce the Likert one way or the other).
* `percent_to_likert` and `percent_to_anchor` agree (both derived from
  the same anchor table; same input → same Likert + same anchor).
* `EvidenceQuote` schema — 300-char cap is enforced; `source_file`
  and `quote` are required; `source_role` is optional.
* `SubDimensionAssessment` schema — score_pct range, all required
  fields, evidence list present.
* `ConstructAssessment.sub_dimension_assessments` is optional + back-
  compatible (v0.3 fixtures continue to validate; default is `[]`).
"""

from __future__ import annotations

import importlib

import pytest

PKG = "open-innovation-strategy"


def _schemas():
    return importlib.import_module(f"{PKG}.roles.judge_schemas")


# ===========================================================================
# Score conversion — percent → Likert
# ===========================================================================

class TestPercentToLikert:
    """Boundary-driven tests for the 7-bucket back-bin. Each Likert
    value maps to a known [lower, upper) range; we probe the lower-edge,
    middle, and upper-edge of each bucket to catch off-by-one bugs."""

    def test_zero_percent_is_likert_one(self):
        s = _schemas()
        assert s.percent_to_likert(0) == 1
        assert s.percent_to_likert(0.0) == 1

    def test_first_bucket_upper_edge_still_likert_one(self):
        s = _schemas()
        # 14.49 still in bucket 1; threshold is exclusive at 14.5
        assert s.percent_to_likert(14.49) == 1

    def test_boundary_14_5_is_likert_two(self):
        s = _schemas()
        # 14.5 is the threshold — should land in bucket 2 (minimal)
        assert s.percent_to_likert(14.5) == 2

    def test_middle_of_each_bucket(self):
        s = _schemas()
        # Middles: 7 / 22 / 36 / 50 / 64 / 78 / 93 → 1 / 2 / 3 / 4 / 5 / 6 / 7
        cases = [
            (7.0, 1), (22.0, 2), (36.0, 3), (50.0, 4),
            (64.0, 5), (78.0, 6), (93.0, 7),
        ]
        for pct, expected in cases:
            assert s.percent_to_likert(pct) == expected, (
                f"{pct}% should be Likert {expected}, got "
                f"{s.percent_to_likert(pct)}"
            )

    def test_one_hundred_percent_is_likert_seven(self):
        s = _schemas()
        assert s.percent_to_likert(100) == 7
        assert s.percent_to_likert(100.0) == 7

    def test_clamps_negative_to_likert_one(self):
        """Out-of-range negatives should clamp rather than raise — the
        judge occasionally emits e.g. -0.5 due to arithmetic edge cases,
        and clamping is more forgiving than failing the whole bundle."""
        s = _schemas()
        assert s.percent_to_likert(-1) == 1
        assert s.percent_to_likert(-100) == 1

    def test_clamps_above_hundred_to_likert_seven(self):
        s = _schemas()
        assert s.percent_to_likert(101) == 7
        assert s.percent_to_likert(500) == 7

    def test_all_seven_likert_values_are_reachable(self):
        """Sanity: every Likert value 1-7 must be producible from some
        valid percent input. Catches a regression where someone narrows
        the anchor table and one bucket goes dead."""
        s = _schemas()
        likerts_seen = {s.percent_to_likert(p) for p in range(0, 101, 5)}
        assert likerts_seen == {1, 2, 3, 4, 5, 6, 7}


# ===========================================================================
# Score conversion — percent → qualitative anchor
# ===========================================================================

class TestPercentToAnchor:
    def test_each_anchor_descriptor_reachable(self):
        s = _schemas()
        expected = {
            "near-absent", "minimal", "partial", "moderate",
            "substantial", "comprehensive", "exemplary",
        }
        anchors_seen = {s.percent_to_anchor(p) for p in range(0, 101, 5)}
        assert anchors_seen == expected

    def test_anchor_matches_likert(self):
        """The two helpers are derived from the same table — for any
        input the (anchor, likert) pair is fixed. Catches drift where
        someone edits one table but not the other."""
        s = _schemas()
        likert_to_anchor = {
            1: "near-absent", 2: "minimal", 3: "partial",
            4: "moderate", 5: "substantial", 6: "comprehensive",
            7: "exemplary",
        }
        for pct in range(0, 101, 3):
            assert s.percent_to_anchor(pct) == likert_to_anchor[
                s.percent_to_likert(pct)
            ]

    def test_zero_is_near_absent(self):
        s = _schemas()
        assert s.percent_to_anchor(0) == "near-absent"

    def test_hundred_is_exemplary(self):
        s = _schemas()
        assert s.percent_to_anchor(100) == "exemplary"


# ===========================================================================
# EvidenceQuote schema
# ===========================================================================

class TestEvidenceQuote:
    def test_minimal_quote_validates(self):
        s = _schemas()
        q = s.EvidenceQuote(
            source_file="01_deliberation/interaction_log.md",
            quote="We will open-source the M2M transport layer.",
        )
        assert q.source_file == "01_deliberation/interaction_log.md"
        assert q.source_role is None  # optional

    def test_source_role_is_optional(self):
        s = _schemas()
        q = s.EvidenceQuote(
            source_file="02_strategy_documents/CTO_strategy.md",
            source_role="CTO",
            quote="hybrid edge-cloud is the only path that scales",
        )
        assert q.source_role == "CTO"

    def test_quote_over_300_chars_fails(self):
        """The 300-char cap keeps quotes auditable at a glance. A judge
        dumping a paragraph as 'evidence' is a known anti-pattern; the
        validator stops it at the schema boundary."""
        s = _schemas()
        with pytest.raises(Exception):
            s.EvidenceQuote(
                source_file="x.md",
                quote="x" * 301,
            )

    def test_quote_at_300_chars_validates(self):
        s = _schemas()
        q = s.EvidenceQuote(
            source_file="x.md",
            quote="x" * 300,
        )
        assert len(q.quote) == 300


# ===========================================================================
# SubDimensionAssessment schema
# ===========================================================================

class TestSubDimensionAssessment:
    def _ok_kwargs(self) -> dict:
        s = _schemas()
        return dict(
            sub_dimension_key="outbound_publication_intensity",
            parent_dimension="boundary_permeability_outbound",
            score_pct=64.0,
            likert_back_binned=5,
            qualitative_anchor="substantial",
            reasoning=(
                "The firm publishes architectural blueprints widely "
                "but restricts identity-layer specifications. Two "
                "passages directly address publication intensity."
            ),
            evidence_quotes=[
                s.EvidenceQuote(
                    source_file="01_deliberation/interaction_log.md",
                    quote="open-source the M2M transport layer",
                ),
                s.EvidenceQuote(
                    source_file="02_strategy_documents/CTO_strategy.md",
                    quote="we publish blueprints to force foundry alignment",
                ),
            ],
            confidence="high",
        )

    def test_minimal_valid_construction(self):
        s = _schemas()
        a = s.SubDimensionAssessment(**self._ok_kwargs())
        assert a.score_pct == 64.0
        assert a.likert_back_binned == 5
        assert a.qualitative_anchor == "substantial"
        assert len(a.evidence_quotes) == 2

    def test_score_pct_out_of_range_fails(self):
        s = _schemas()
        bad = dict(self._ok_kwargs())
        bad["score_pct"] = 101.0
        with pytest.raises(Exception):
            s.SubDimensionAssessment(**bad)
        bad["score_pct"] = -1.0
        with pytest.raises(Exception):
            s.SubDimensionAssessment(**bad)

    def test_likert_back_binned_must_be_1_to_7(self):
        s = _schemas()
        bad = dict(self._ok_kwargs())
        bad["likert_back_binned"] = 0
        with pytest.raises(Exception):
            s.SubDimensionAssessment(**bad)
        bad["likert_back_binned"] = 8
        with pytest.raises(Exception):
            s.SubDimensionAssessment(**bad)

    def test_qualitative_anchor_must_be_in_literal(self):
        s = _schemas()
        bad = dict(self._ok_kwargs())
        bad["qualitative_anchor"] = "very-open"  # not in the 7-anchor set
        with pytest.raises(Exception):
            s.SubDimensionAssessment(**bad)

    def test_invalid_confidence_rejected(self):
        s = _schemas()
        bad = dict(self._ok_kwargs())
        bad["confidence"] = "very-high"
        with pytest.raises(Exception):
            s.SubDimensionAssessment(**bad)


# ===========================================================================
# ConstructAssessment back-compat: sub_dimension_assessments is optional
# ===========================================================================

class TestConstructAssessmentBackCompat:
    """v0.3 assessment fixtures (the recovered Meta-2032 bundle, the
    existing test fixtures) must continue to validate against the new
    schema. `sub_dimension_assessments` defaults to `[]`."""

    _RUBRIC_KEYS = (
        "component_disclosure",
        "process_openness",
        "boundary_permeability_inbound",
        "boundary_permeability_outbound",
        "ecosystem_orchestration",
        "value_capture_posture",
        "temporal_openness_maneuvering",
    )

    def _v03_assessment_kwargs(self, judge_id: str = "gemini_pro") -> dict:
        s = _schemas()
        return dict(
            judge_id=judge_id,
            qualitative_summary="v0.3 parent-dimension scoring.",
            dimension_scores=[
                s.DimensionAssessment(
                    dimension=k, score=4,
                    reasoning="auto", evidence=[], confidence="medium",
                )
                for k in self._RUBRIC_KEYS
            ],
            composite_score=4.0,
            overall_confidence="medium",
            caveats="",
        )

    def test_v03_fixture_validates_with_empty_sub_dimensions(self):
        s = _schemas()
        a = s.ConstructAssessment(**self._v03_assessment_kwargs())
        assert a.sub_dimension_assessments == [], (
            "v0.3 fixtures must still validate; new field defaults to []"
        )

    def test_v04_fixture_validates_with_populated_sub_dimensions(self):
        s = _schemas()
        kwargs = self._v03_assessment_kwargs()
        kwargs["sub_dimension_assessments"] = [
            s.SubDimensionAssessment(
                sub_dimension_key="outbound_publication_intensity",
                parent_dimension="boundary_permeability_outbound",
                score_pct=64.0,
                likert_back_binned=5,
                qualitative_anchor="substantial",
                reasoning="three sentences of reasoning",
                evidence_quotes=[
                    s.EvidenceQuote(
                        source_file="01_deliberation/interaction_log.md",
                        quote="q1",
                    ),
                    s.EvidenceQuote(
                        source_file="02_strategy_documents/CTO_strategy.md",
                        quote="q2",
                    ),
                ],
                confidence="high",
            )
        ]
        a = s.ConstructAssessment(**kwargs)
        assert len(a.sub_dimension_assessments) == 1
        # parent_dimension list still populated (back-compat).
        assert len(a.dimension_scores) == 7

    def test_existing_recovered_meta_2032_json_still_loads(self, tmp_path):
        """A simulated v0.3-shaped JSON payload (no sub_dimension_assessments
        key) round-trips through `model_validate` cleanly. Mirrors the
        on-disk shape of the recovered Meta-2032 bundle so PR-D doesn't
        invalidate it."""
        import json
        s = _schemas()
        kwargs = self._v03_assessment_kwargs()
        a = s.ConstructAssessment(**kwargs)
        payload = a.model_dump(mode="json")
        # Strip the new field entirely — simulates a pre-v0.4 JSON.
        payload.pop("sub_dimension_assessments", None)
        round_tripped = s.ConstructAssessment.model_validate(payload)
        assert round_tripped.sub_dimension_assessments == []
        assert round_tripped.composite_score == 4.0


# ===========================================================================
# Study version lock — PR-D commit 6/6 bumped openness_maneuvering to v0.4.
# The replay tool's `--allow-version-mismatch` refusal keys off this
# field so a future accidental downgrade would silently allow cross-
# schema replay. The test locks the expected version.
# ===========================================================================

class TestStudyVersionLockedAtV04:
    def test_openness_study_version_is_locked(self):
        from studies import load_study
        s = load_study("openness_maneuvering")
        assert s.version == "0.5.0", (
            f"openness_maneuvering version unexpectedly at {s.version!r}. "
            "If you're intentionally bumping the version, update this "
            "test in lockstep AND add the new version to the DECISIONS "
            "log so cross-cell α-statistic comparisons stay honest."
        )
