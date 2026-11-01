"""The debrief researcher follows what it finds; the areas only guide it."""

from __future__ import annotations

import importlib

PKG = "open-innovation-strategy"
TARGET = [15, 25]


def _pd():
    return importlib.import_module(f"{PKG}.orchestrator.panel_debriefing")


def _transcript(*utterances):
    rs = importlib.import_module(f"{PKG}.roles.researcher_schemas")
    transcript = _pd().DebriefingTranscript(company="ACME", research_question="rq")
    for area, followup, emerging in utterances:
        transcript.exchanges.append(rs.PanelExchange(
            utterance=rs.PanelUtterance(
                area_id=area, addressed_to="group", text="q", anchor_refs=["x"],
                is_followup=followup, emerging_question=emerging,
            ),
            responses=[],
        ))
    return transcript


def _coverage(transcript, mode="structured_then_followup"):
    return _pd()._render_coverage_map(
        transcript, all_areas=["A", "B", "C", "J"], closing_area="J",
        traversal_mode=mode, target_exchanges=TARGET,
    )


def test_first_pass_does_not_force_the_next_area():
    out = _coverage(_transcript(("A", False, "")))
    assert "MUST use" not in out
    assert "probe it first" in out
    assert "area_id='B'" in out


def test_strict_structured_mode_still_binds():
    assert "MUST use" in _coverage(_transcript(("A", False, "")), mode="structured")


def test_a_probe_chain_is_not_told_to_switch():
    out = _coverage(_transcript(("A", False, ""), ("A", True, "")))
    assert "TWO consecutive" not in out


def test_repeating_an_area_without_probing_still_warns():
    out = _coverage(_transcript(("A", False, ""), ("A", False, "")))
    assert "TWO consecutive" in out


def test_close_is_held_until_the_target_length():
    assert "Do not ask Area J or end yet" in _coverage(_transcript(("A", False, "")))
    long_run = _transcript(*[("A", True, "")] * 15)
    assert "Do not ask Area J or end yet" not in _coverage(long_run)


def test_recorded_questions_reach_the_researcher_but_not_the_panel():
    note = "Why does the team trust the vendor?"
    transcript = _transcript(("A", False, note))
    assert f"Exchange 1: {note}" in _coverage(transcript)
    assert note not in _pd()._render_transcript_for_prompt(transcript)


def test_debrief_context_invites_exploration():
    qual = importlib.import_module(f"{PKG}.roles.qualitative_researcher_agent")
    study = importlib.import_module(f"{PKG}.studies").load_study("openness_maneuvering")
    text = qual._render_research_context(study)
    assert "exploring a field" in text
    assert "new phenomenon" in text
    assert "may or may not" in text
    assert "Do NOT steer" in text
