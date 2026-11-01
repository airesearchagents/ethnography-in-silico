"""Contract tests for the sub-dimension lexicon
(`studies/openness_maneuvering/subdimension_lexicon.py`, Phase B
of the measurement plan).

The lexicon is the methodological artefact that powers Method A
(anchored dictionary scoring). These tests pin:

  * the 21 expected sub-dimensions are present and named consistently;
  * every sub-dimension's `parent_dimension` exists in the active
    rubric — i.e. the lexicon stays in sync with the rubric;
  * every regex compiles under re.IGNORECASE — broken patterns can't
    sneak in;
  * each parent dimension has the expected sub-dimension count;
  * the measurability rating distribution matches the plan
    (5 H, 13 M, 3 L);
  * the helper functions return sensible values.

No network, no real ADK.
"""

from __future__ import annotations

import importlib
import re

import pytest

PKG = "open-innovation-strategy"


def _lexicon_module():
    return importlib.import_module(
        f"{PKG}.studies.openness_maneuvering.subdimension_lexicon"
    )


def _rubric():
    """Get the rubric to verify parent_dimension keys are valid."""
    study_module = importlib.import_module(
        f"{PKG}.studies.openness_maneuvering"
    )
    return study_module.STUDY.judgment_rubric


# ===========================================================================
# 1. Sub-dimension registry shape
# ===========================================================================

class TestRegistryShape:
    """The lexicon must declare exactly 26 sub-dimensions distributed
    as 4 + 4 + 2 + 4 + 4 + 5 + 3 across the 7 rubric dimensions.

    Bumped from 21 at rubric v0.2: boundary_permeability split into
    inbound (2 sub-dims, new) + outbound (4 sub-dims, re-parented from
    the v0.1 single-axis dimension), and 3 new sub-dims under the new
    temporal_openness_maneuvering dimension.
    """

    def test_lexicon_declares_26_subdimensions(self):
        lex = _lexicon_module()
        assert len(lex.OPENNESS_SUBDIMENSION_LEXICON) == 26

    def test_component_disclosure_has_4_subdimensions(self):
        lex = _lexicon_module()
        subs = lex.subdimensions_for("component_disclosure")
        assert len(subs) == 4

    def test_process_openness_has_4_subdimensions(self):
        lex = _lexicon_module()
        subs = lex.subdimensions_for("process_openness")
        assert len(subs) == 4

    def test_boundary_permeability_inbound_has_2_subdimensions(self):
        lex = _lexicon_module()
        subs = lex.subdimensions_for("boundary_permeability_inbound")
        assert len(subs) == 2

    def test_boundary_permeability_outbound_has_4_subdimensions(self):
        lex = _lexicon_module()
        subs = lex.subdimensions_for("boundary_permeability_outbound")
        assert len(subs) == 4

    def test_ecosystem_orchestration_has_4_subdimensions(self):
        lex = _lexicon_module()
        subs = lex.subdimensions_for("ecosystem_orchestration")
        assert len(subs) == 4

    def test_value_capture_posture_has_5_subdimensions(self):
        lex = _lexicon_module()
        subs = lex.subdimensions_for("value_capture_posture")
        assert len(subs) == 5

    def test_temporal_openness_maneuvering_has_3_subdimensions(self):
        lex = _lexicon_module()
        subs = lex.subdimensions_for("temporal_openness_maneuvering")
        assert len(subs) == 3

    def test_subdimensions_partition_the_lexicon(self):
        """No sub-dimension belongs to two parents; every sub-dimension
        is reachable from its parent's view."""
        lex = _lexicon_module()
        parents = (
            "component_disclosure", "process_openness",
            "boundary_permeability_inbound", "boundary_permeability_outbound",
            "ecosystem_orchestration", "value_capture_posture",
            "temporal_openness_maneuvering",
        )
        seen = set()
        for parent in parents:
            for key in lex.subdimensions_for(parent):
                assert key not in seen, f"{key} appears under two parents"
                seen.add(key)
        assert seen == set(lex.OPENNESS_SUBDIMENSION_LEXICON.keys())


# ===========================================================================
# 2. Lexicon stays in sync with the rubric
# ===========================================================================

class TestLexiconRubricSync:
    """Every sub-dimension's `parent_dimension` must be a real rubric
    dimension key. If the rubric changes, the lexicon must change with
    it; this test is the alarm."""

    def test_every_parent_dimension_exists_in_rubric(self):
        lex = _lexicon_module()
        rubric = _rubric()
        valid_parents = {d.key for d in rubric.dimensions}
        for sub_key, entry in lex.OPENNESS_SUBDIMENSION_LEXICON.items():
            assert entry["parent_dimension"] in valid_parents, (
                f"sub-dimension {sub_key!r} declares parent "
                f"{entry['parent_dimension']!r} which is not in the rubric"
            )

    def test_every_rubric_dimension_has_at_least_one_subdimension(self):
        lex = _lexicon_module()
        rubric = _rubric()
        for d in rubric.dimensions:
            assert lex.subdimensions_for(d.key), (
                f"rubric dimension {d.key!r} has no sub-dimensions in the lexicon"
            )


# ===========================================================================
# 3. Regex validity
# ===========================================================================

class TestRegexValidity:
    """Every pattern in every sub-dimension must compile under
    re.IGNORECASE. A broken regex would crash the scorer at runtime;
    this is the static guarantee that it can't."""

    def test_every_pro_openness_pattern_compiles(self):
        lex = _lexicon_module()
        for sub_key, entry in lex.OPENNESS_SUBDIMENSION_LEXICON.items():
            for pattern in entry["pro_openness"]:
                try:
                    re.compile(pattern, re.IGNORECASE)
                except re.error as exc:
                    pytest.fail(
                        f"sub-dimension {sub_key!r} pro pattern "
                        f"{pattern!r} does not compile: {exc}"
                    )

    def test_every_anti_openness_pattern_compiles(self):
        lex = _lexicon_module()
        for sub_key, entry in lex.OPENNESS_SUBDIMENSION_LEXICON.items():
            for pattern in entry["anti_openness"]:
                try:
                    re.compile(pattern, re.IGNORECASE)
                except re.error as exc:
                    pytest.fail(
                        f"sub-dimension {sub_key!r} anti pattern "
                        f"{pattern!r} does not compile: {exc}"
                    )


# ===========================================================================
# 4. Measurability distribution
# ===========================================================================

class TestMeasurabilityDistribution:
    """Per the lexicon construction at rubric v0.2: 4 H, 18 M, 4 L
    across 26 sub-dimensions (up from 4 H, 14 M, 3 L across 21 at
    v0.1). The added sub-dimensions are: 2 M under
    boundary_permeability_inbound (external_hiring,
    external_idea_absorption), 2 M + 1 L under
    temporal_openness_maneuvering (phased_rollout_language,
    conditional_triggers — both M; reversibility — L). All other
    sub-dimensions and ratings unchanged from v0.1."""

    def test_measurability_ratings_are_valid(self):
        lex = _lexicon_module()
        for sub_key, entry in lex.OPENNESS_SUBDIMENSION_LEXICON.items():
            assert entry["measurability"] in {"H", "M", "L"}, (
                f"sub-dimension {sub_key!r} has invalid measurability "
                f"{entry['measurability']!r}"
            )

    def test_measurability_distribution_matches_plan(self):
        lex = _lexicon_module()
        counts = {"H": 0, "M": 0, "L": 0}
        for entry in lex.OPENNESS_SUBDIMENSION_LEXICON.values():
            counts[entry["measurability"]] += 1
        # 4 H + 18 M + 4 L = 26 total at rubric v0.2. If this changes,
        # update the measurement plan in tandem.
        assert counts == {"H": 4, "M": 18, "L": 4}, (
            f"distribution drifted: {counts}. Update the measurement "
            "plan in docs/09 if this change is intended."
        )

    def test_low_measurability_subdimensions_are_in_intent_dimensions(self):
        """At rubric v0.2 the L (low-measurability) sub-dimensions
        belong to dimensions whose construct is paraphrasable
        strategic intent — value_capture_posture (firm's monetisation
        philosophy) or temporal_openness_maneuvering (firm's reasoning
        about when to open/close). Neither has a concrete lexical
        surface like 'we publish' or 'we hire from' for H/M dimensions.
        This test pins that contrast."""
        lex = _lexicon_module()
        intent_dimensions = {
            "value_capture_posture",
            "temporal_openness_maneuvering",
        }
        l_subs = [
            (key, entry["parent_dimension"])
            for key, entry in lex.OPENNESS_SUBDIMENSION_LEXICON.items()
            if entry["measurability"] == "L"
        ]
        for sub_key, parent in l_subs:
            assert parent in intent_dimensions, (
                f"sub-dimension {sub_key!r} is rated L but belongs to "
                f"{parent!r} — L sub-dimensions should only live under "
                f"intent-paraphrasable dimensions {intent_dimensions}."
            )


# ===========================================================================
# 5. Helper functions
# ===========================================================================

class TestHelperFunctions:
    """`subdimensions_for(parent)` and `measurability_weight(rating)`
    are the public API the scorer relies on."""

    def test_subdimensions_for_unknown_parent_returns_empty(self):
        lex = _lexicon_module()
        assert lex.subdimensions_for("not_a_dimension") == []

    def test_measurability_weight_h_m_l(self):
        lex = _lexicon_module()
        assert lex.measurability_weight("H") == 3
        assert lex.measurability_weight("M") == 2
        assert lex.measurability_weight("L") == 1

    def test_measurability_weight_unknown_defaults_to_zero(self):
        """An unknown rating should produce a zero weight rather than
        crashing — keeps the scorer robust to lexicon errors."""
        lex = _lexicon_module()
        assert lex.measurability_weight("Q") == 0
        assert lex.measurability_weight("") == 0
