"""Tests for the studies/ package.

Covers:
  * StudyConfig schema (required fields, defaults, validation).
  * `load_study(slug)` happy path + the three failure modes
    (missing sub-package, missing STUDY attr, wrong type).
  * The default openness study's research question matches the
    historical text (regression guard for the migration).
"""

from __future__ import annotations

import importlib

import pytest

PKG = "open-innovation-strategy"


def _studies():
    return importlib.import_module(f"{PKG}.studies")


def _base():
    return importlib.import_module(f"{PKG}.studies.base")


# ===========================================================================
# 1. StudyConfig schema
# ===========================================================================

class TestStudyConfigSchema:
    def test_required_fields(self):
        sc = _base().StudyConfig
        # Construct a minimal valid instance.
        cfg = sc(
            name="Demo",
            slug="demo",
            research_question="rq?",
            theoretical_lens="lens",
        )
        assert cfg.name == "Demo"
        assert cfg.slug == "demo"
        # Defaults present.
        assert cfg.version == "0.1.0"
        assert cfg.construct_forbidden_vocabulary == []
        assert cfg.flagged_vocabulary == []
        assert cfg.panel_roles == list(_base().DEFAULT_PANEL_ROLES)
        assert cfg.role_factories_module is None
        assert cfg.contexts_module is None
        assert cfg.protocol_overlay is None

    def test_missing_required_field_raises(self):
        sc = _base().StudyConfig
        with pytest.raises(Exception):
            sc(slug="demo", research_question="rq", theoretical_lens="lens")  # name missing

    def test_panel_roles_default_matches_six_tmt(self):
        sc = _base().StudyConfig(
            name="x", slug="x", research_question="rq", theoretical_lens="l",
        )
        assert sc.panel_roles == [
            "CEO", "CTO", "COO", "CMO",
            "Product_Strategist", "Product_Designer",
        ]

    def test_panel_roles_override_accepted(self):
        sc = _base().StudyConfig(
            name="x", slug="x", research_question="rq", theoretical_lens="l",
            panel_roles=["Head_of_RnD", "VP_Alliances"],
        )
        assert sc.panel_roles == ["Head_of_RnD", "VP_Alliances"]


# ===========================================================================
# 2. load_study()
# ===========================================================================

class TestLoadStudy:
    def test_loads_openness_maneuvering(self):
        s = _studies().load_study("openness_maneuvering")
        assert s.slug == "openness_maneuvering"
        assert "openness" in s.research_question.lower()
        # The lens reaches the Debriefer, so it names no literature.
        assert "inductive" in s.theoretical_lens.lower()

    def test_loads_test_alt(self):
        s = _studies().load_study("_test_alt")
        assert s.slug == "_test_alt"
        # Vocab is genuinely different from openness study.
        assert "openness" not in s.research_question.lower()
        assert "absorptive" in s.research_question.lower()

    def test_unknown_slug_raises(self):
        with pytest.raises(ModuleNotFoundError) as exc_info:
            _studies().load_study("does_not_exist_xyz")
        assert "does_not_exist_xyz" in str(exc_info.value)

    def test_empty_slug_raises(self):
        with pytest.raises(ValueError):
            _studies().load_study("")

    def test_default_study_slug_constant(self):
        assert _studies().DEFAULT_STUDY_SLUG == "openness_maneuvering"


# ===========================================================================
# 3. Migration regression — the default study mirrors historical wording
# ===========================================================================

class TestOpennessHistoricalContent:
    """Guards against accidental wording drift in the canonical study
    fields. Wording changes are NOT prevented by this test — they require
    the corresponding `study.version` bump, after which the expected text
    below must also be updated.

    Wording history (each line is the canonical text at that version):
      v0.1 / v0.2 (pre-2026-05-25, study.version 0.2.0):
        'How do firms shift or strategically maneuver their degree of
        openness (how open they are at a given point) in open innovation
        ecosystem for value capture.'
        Issues retired in v0.3: the parenthetical embedded a static-
        snapshot framing that contradicted the dynamic construct; the
        'for value capture' clause pre-named the strategic purpose.

      v0.3 / v0.4 (study.version 0.3.0, 0.4.0):
        'How do firms in volatile innovation ecosystems dynamically
        maneuver their degree of openness over time?'
        Restricted to the 'how' question only — mechanisms (e.g. the
        technological re-architecture and governance tuning identified
        in the v1.0 CrewAI pilot) are now treated as findings to be
        re-derived inductively under the new virtual-ethnography
        framework, not as RQ premises. See DECISIONS.md Session 3.

      v0.5 (current, study.version 0.5.0):
        'How do firms maneuver openness to create and capture value?'
        Matches the proposal. See DECISIONS.md §43.
    """

    def test_research_question_matches_current_text(self):
        s = _studies().load_study("openness_maneuvering")
        # Distinctive phrases from the v0.5 (current) text.
        for phrase in (
            "How do firms",
            "maneuver openness",
            "create and capture value",
        ):
            assert phrase in s.research_question, (
                f"missing phrase {phrase!r} in research_question — "
                "wording drift; if intentional, bump study.version "
                "and update this test"
            )

    def test_research_question_drops_retired_v0_2_phrases(self):
        """Negative guard: phrases retired in v0.3 must not creep back
        without a deliberate decision."""
        s = _studies().load_study("openness_maneuvering")
        for retired_phrase in (
            "how open they are at a given point",  # static-snapshot framing
            "for value capture",                   # pre-named outcome
            "shift or strategically maneuver",     # superseded phrasing
        ):
            assert retired_phrase not in s.research_question, (
                f"retired v0.2 phrase {retired_phrase!r} reappeared in "
                "research_question — see DECISIONS.md Session 3 for why "
                "these were removed"
            )

    def test_construct_forbidden_vocab_covers_historical_list(self):
        s = _studies().load_study("openness_maneuvering")
        # These words were in the pre-refactor protocol YAML as
        # `forbidden_vocabulary`. They must now appear in the study's
        # construct list (because they're construct-specific, not
        # methodological).
        for word in (
            "open", "closed", "open-source", "closed-source",
            "value capture", "modular", "boundary",
            "architectural leverage", "asset orchestration",
        ):
            assert word in s.construct_forbidden_vocabulary, (
                f"{word!r} should be in construct_forbidden_vocabulary"
            )
