"""The Debriefer's prompt and traversal must agree on which area closes.

The closing area is whichever one has `always_ask: true`, currently J.
The prompt used to name Area F, and the merged protocol put J in the
middle of the first pass, ahead of the study's own areas.
"""

from __future__ import annotations

import importlib

PKG = "open-innovation-strategy"


def _qual():
    return importlib.import_module(f"{PKG}.roles.qualitative_researcher_agent")


def _study():
    return importlib.import_module(f"{PKG}.studies").load_study("openness_maneuvering")


def _summary():
    rs = importlib.import_module(f"{PKG}.roles.researcher_schemas")
    return rs.ObservationSummary(decisions=["pricing"], components=["pricing"])


def _transcript(*areas):
    pd = importlib.import_module(f"{PKG}.orchestrator.panel_debriefing")
    rs = importlib.import_module(f"{PKG}.roles.researcher_schemas")
    transcript = pd.DebriefingTranscript(company="ACME", research_question="rq")
    for area in areas:
        transcript.exchanges.append(rs.PanelExchange(
            utterance=rs.PanelUtterance(
                area_id=area, addressed_to="group", text="q", anchor_refs=["x"],
            ),
            responses=[],
        ))
    return transcript


def _coverage(mode, *areas):
    pd = importlib.import_module(f"{PKG}.orchestrator.panel_debriefing")
    return pd._render_coverage_map(
        _transcript(*areas),
        all_areas=["A", "B", "J"],
        closing_area="J",
        traversal_mode=mode,
    )


def test_merged_areas_are_in_order_with_closing_last():
    qual = _qual()
    protocol = qual._apply_study_overlay(qual._load_protocol(), _study())
    ids = [a["id"] for a in protocol["thematic_areas"]]
    assert ids == ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
    assert qual.closing_area_id(protocol) == ids[-1]


def test_prompt_names_the_real_closing_area():
    text = _qual().create_debriefer_agent("ACME", _summary(), study=_study()).instruction
    assert "suggested order A → J; use judgement; Area J always closes" in text
    assert "(c) Area J has been asked" in text
    assert "(after Area J has" in text
    assert "'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J'." in text
    assert "Area F always closes" not in text
    assert "Area F has" not in text


def test_followup_mode_holds_the_closing_area_back():
    out = _coverage("structured_then_followup", "A")
    assert "area_id='B'" in out
    out = _coverage("structured_then_followup", "A", "B")
    assert "is COMPLETE" in out
    assert "area_id='J'" not in out
    assert "Area J closes the debriefing" in out


def test_closing_reminder_stops_once_asked():
    out = _coverage("structured_then_followup", "A", "B", "J")
    assert "Area J closes the debriefing" not in out


def test_strict_structured_mode_still_covers_the_closing_area():
    assert "area_id='J'" in _coverage("structured", "A", "B")
