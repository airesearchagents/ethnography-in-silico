"""Tests for `_apply_study_overlay` — the deep-merge that lets a
study extend the framework-level ethnographic protocol via
`StudyConfig.protocol_overlay`.

The merge contract:
  * `thematic_areas_overlay` → appended to `thematic_areas`.
  * `behavioural_rules_additions` → appended as a separate paragraph
    to `behavioural_rules` (the framework rules stay verbatim above).
  * `panel_format_additions` → dict-merged into `panel_format`; the
    overlay's keys override the framework's defaults.
  * Unknown overlay keys are silently ignored.
  * `study=None` or empty overlay → the input dict is returned
    unchanged.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

PKG = "open-innovation-strategy"


def _researcher():
    return importlib.import_module(f"{PKG}.roles.qualitative_researcher_agent")


def _make_protocol() -> dict:
    """Minimal framework-shaped protocol dict for testing the merge."""
    return {
        "stance": "be inductive",
        "behavioural_rules": "anchor every question in observation.",
        "thematic_areas": [
            {"id": "A", "name": "Decision anchoring", "stems": ["q1"]},
            {"id": "J", "name": "Reflection", "always_ask": True, "stems": ["q-close"]},
        ],
        "panel_format": {
            "default_addressing": "group",
            "target_exchanges": [15, 25],
            "max_probe_chain_depth": 5,
        },
    }


def _make_fake_study(overlay: dict):
    """Build a duck-typed study fixture carrying the overlay dict."""
    return SimpleNamespace(
        protocol_overlay=overlay,
        construct_forbidden_vocabulary=[],
        research_question="rq",
        theoretical_lens="lens",
        debriefer_background_block="bg",
    )


class TestApplyOverlayBasics:
    def test_none_study_returns_input_unchanged(self):
        m = _researcher()
        protocol = _make_protocol()
        result = m._apply_study_overlay(protocol, None)
        assert result is protocol

    def test_empty_overlay_returns_input_unchanged(self):
        m = _researcher()
        protocol = _make_protocol()
        study = _make_fake_study({})
        result = m._apply_study_overlay(protocol, study)
        # Different identity (we return a copy when something is in
        # the overlay), but functionally identical when overlay is
        # empty. Either way: input not mutated.
        assert result.get("thematic_areas") == protocol["thematic_areas"]


class TestThematicAreasOverlay:
    def test_overlay_areas_merged_in_order_with_closing_last(self):
        m = _researcher()
        protocol = _make_protocol()
        study = _make_fake_study({
            "thematic_areas_overlay": [
                {"id": "D", "name": "Asymmetric treatment", "stems": ["dq1"]},
                {"id": "E", "name": "Process and exchange", "stems": ["eq1"]},
            ],
        })
        result = m._apply_study_overlay(protocol, study)
        ids = [a["id"] for a in result["thematic_areas"]]
        assert ids == ["A", "D", "E", "J"]

    def test_input_protocol_not_mutated_by_overlay(self):
        m = _researcher()
        protocol = _make_protocol()
        original_ids = [a["id"] for a in protocol["thematic_areas"]]
        study = _make_fake_study({
            "thematic_areas_overlay": [
                {"id": "D", "name": "Asymmetric", "stems": ["dq1"]},
            ],
        })
        _ = m._apply_study_overlay(protocol, study)
        # Caller's protocol dict still has only the framework areas.
        assert [a["id"] for a in protocol["thematic_areas"]] == original_ids


class TestBehaviouralRulesAdditions:
    def test_additions_appended_as_separate_paragraph(self):
        m = _researcher()
        protocol = _make_protocol()
        study = _make_fake_study({
            "behavioural_rules_additions": "When a panellist contradicts themselves, probe deeper.",
        })
        result = m._apply_study_overlay(protocol, study)
        rules = result["behavioural_rules"]
        # Both parts are present.
        assert "anchor every question in observation." in rules
        assert "probe deeper" in rules
        # Separated by a blank line.
        assert "\n\n" in rules

    def test_additions_added_when_base_is_empty(self):
        m = _researcher()
        protocol = _make_protocol()
        protocol["behavioural_rules"] = ""
        study = _make_fake_study({
            "behavioural_rules_additions": "Surprise → probe.",
        })
        result = m._apply_study_overlay(protocol, study)
        assert result["behavioural_rules"] == "Surprise → probe."


class TestPanelFormatAdditions:
    def test_panel_format_dict_merged(self):
        m = _researcher()
        protocol = _make_protocol()
        study = _make_fake_study({
            "panel_format_additions": {
                "max_probe_chain_depth": 7,
                "extra_setting": "value",
            },
        })
        result = m._apply_study_overlay(protocol, study)
        # Overlay overrode the framework default.
        assert result["panel_format"]["max_probe_chain_depth"] == 7
        # Overlay added a new key.
        assert result["panel_format"]["extra_setting"] == "value"
        # Framework's other keys preserved.
        assert result["panel_format"]["default_addressing"] == "group"
        assert result["panel_format"]["target_exchanges"] == [15, 25]


class TestUnknownOverlayKeysIgnored:
    def test_unknown_keys_dont_raise(self):
        m = _researcher()
        protocol = _make_protocol()
        study = _make_fake_study({
            "thematic_areas_overlay": [
                {"id": "D", "name": "X", "stems": ["q"]},
            ],
            "unrecognised_key_for_future_extension": {"foo": "bar"},
        })
        # Should not raise — unknown keys are ignored with a debug log.
        result = m._apply_study_overlay(protocol, study)
        # The recognised parts still applied.
        assert "D" in [a["id"] for a in result["thematic_areas"]]


class TestClosingAreaResolution:
    def test_closing_area_id_from_always_ask_flag(self):
        m = _researcher()
        protocol = _make_protocol()
        # Framework's Area J is flagged `always_ask: true`.
        assert m.closing_area_id(protocol) == "J"

    def test_closing_area_id_none_when_no_flag(self):
        m = _researcher()
        protocol = _make_protocol()
        for a in protocol["thematic_areas"]:
            a.pop("always_ask", None)
        assert m.closing_area_id(protocol) is None

    def test_overlay_areas_dont_change_closing_area(self):
        """Overlay areas can be added without affecting which area
        carries `always_ask: true`. The framework's J stays the
        closing area after the openness overlay is merged."""
        m = _researcher()
        protocol = _make_protocol()
        study = _make_fake_study({
            "thematic_areas_overlay": [
                {"id": "D", "name": "X", "stems": ["q"]},
            ],
        })
        merged = m._apply_study_overlay(protocol, study)
        assert m.closing_area_id(merged) == "J"


class TestOpennessStudyOverlayEndToEnd:
    """The real openness study's overlay should land cleanly on the
    framework YAML at runtime — covers the integration of the loaded
    YAML overlay + the merger."""

    def test_openness_study_overlay_adds_five_areas(self):
        m = _researcher()
        studies_mod = importlib.import_module(f"{PKG}.studies")
        study = studies_mod.load_study("openness_maneuvering")
        protocol = m._apply_study_overlay(m._load_protocol(), study)
        ids = [a["id"] for a in protocol["thematic_areas"]]
        for overlay_id in ("D", "E", "F", "G", "H"):
            assert overlay_id in ids, f"openness overlay should add Area {overlay_id}"

    def test_openness_study_overlay_areas_each_have_stems(self):
        m = _researcher()
        studies_mod = importlib.import_module(f"{PKG}.studies")
        study = studies_mod.load_study("openness_maneuvering")
        protocol = m._apply_study_overlay(m._load_protocol(), study)
        overlay_areas = [
            a for a in protocol["thematic_areas"] if a["id"] in {"D", "E", "F", "G", "H"}
        ]
        for area in overlay_areas:
            assert area.get("stems"), f"Area {area['id']} should have stems"
            assert len(area["stems"]) >= 3, (
                f"Area {area['id']} should have at least 3 stems for variety"
            )

    def test_framework_areas_still_present_after_openness_overlay(self):
        m = _researcher()
        studies_mod = importlib.import_module(f"{PKG}.studies")
        study = studies_mod.load_study("openness_maneuvering")
        protocol = m._apply_study_overlay(m._load_protocol(), study)
        ids = [a["id"] for a in protocol["thematic_areas"]]
        for framework_id in ("A", "B", "C", "I", "J"):
            assert framework_id in ids
