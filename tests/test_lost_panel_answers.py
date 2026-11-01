"""A panel answer lost to a failed call must not read as a choice to stay silent."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.persist_artefacts import _render_debriefing_md, burst_run  # noqa: E402
from orchestrator import llm_retry, panel_debriefing as pd  # noqa: E402
from roles.researcher_schemas import PanelExchange, PanelUtterance  # noqa: E402
from run_research_session import _active_phase_handlers, _code_commit, _lost_panel_answers  # noqa: E402
from studies import load_study  # noqa: E402


class TransportError(Exception):
    """Same class name as `google.auth.exceptions.TransportError`."""


def _utterance(addressed_to="group"):
    return PanelUtterance(
        text="Walk me through that.", addressed_to=addressed_to,
        area_id="A", anchor_refs=["x"],
    )


def test_transport_error_is_retried_whatever_its_message_says():
    assert llm_retry.is_transient_error(TransportError("request failed"))
    assert not llm_retry.is_transient_error(ValueError("request failed"))


@pytest.mark.parametrize("addressed_to", ["group", "CTO"])
def test_failed_call_is_recorded_and_a_pass_is_not(monkeypatch, addressed_to):
    answers = {"CEO": "[PASS]", "CTO": None, "COO": "We capped it at three."}

    async def fake_safe_run(run_agent, agent, prompt):
        return answers[agent]

    monkeypatch.setattr(pd, "_safe_run", fake_safe_run)
    lost: list[str] = []
    responses = asyncio.run(pd._collect_panel_responses(
        utterance=_utterance(addressed_to),
        panel_agents={role: role for role in answers},
        history_block="",
        artefacts=None,
        run_agent=None,
        lost_roles=lost,
    ))
    assert lost == ["CTO"]
    assert [r.role for r in responses] == ["COO"]


def test_lost_answers_reach_the_errors_and_the_transcript():
    transcript = pd.DebriefingTranscript(
        company="X", research_question="Q",
        exchanges=[
            PanelExchange(utterance=_utterance()),
            PanelExchange(utterance=_utterance(), lost_roles=["CTO"]),
        ],
    )
    assert _lost_panel_answers(transcript) == ["exchange 2: CTO"]
    assert _lost_panel_answers(None) == []
    md = _render_debriefing_md(transcript.model_dump(mode="json"))
    assert "model call failed, not silence" in md
    assert md.count("not silence") == 1


def test_field_notes_are_saved(tmp_path):
    base = burst_run(
        out_dir=tmp_path, company="X", industry_context="Dynamic",
        product_type="Novel", observation_summary=None,
        field_notes=["First note.", "Second note."],
    )
    assert "Second note." in (base / "03_researcher" / "field_notes.md").read_text()
    assert json.loads((base / "03_researcher" / "field_notes.json").read_text())[0] == "First note."
    assert json.loads((base / "00_meta.json").read_text())["phases_captured"]["field_notes"] is True


def test_judges_run_only_when_asked_for():
    study = load_study("openness_maneuvering")
    names = lambda judge: [h.name for h in _active_phase_handlers(study, judge)]
    assert names(False) == []
    assert names(True) == ["construct_judging"]


def test_citations_wrapped_around_an_answer_are_separated():
    from roles.researcher_schemas import split_panel_reply

    citation = {"doc_id": "a.txt", "quote": "q", "supports": "s"}
    plain = "We capped it at three. {not json}"
    assert split_panel_reply(plain) == (plain, [])
    fenced = '```json\n' + json.dumps({"body": "The answer.", "citations": [citation]}) + '\n```'
    assert split_panel_reply(fenced) == ("The answer.", [citation])
    trailing = "The answer.\n\n```json\n" + json.dumps({"citations": [citation]}) + "\n```"
    assert split_panel_reply(trailing) == ("The answer.", [citation])


def test_code_commit_is_recorded_when_in_git():
    commit = _code_commit()
    assert commit is None or len(commit.split("-")[0]) >= 7
