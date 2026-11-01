"""What a panellist is shown in the debrief, and how its reply is recorded."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import panel_debriefing as pd  # noqa: E402
from roles.researcher_schemas import (  # noqa: E402
    ObservationSummary, PanelUtterance, split_panel_reply, valid_citations,
)

ROLES = ("CEO", "CTO", "COO")
SUMMARY = ObservationSummary(decisions=[], components=[])
CITATION = {"doc_id": "a.txt", "chunk_id": "a#1", "quote": "a phrase", "supports": "claim"}


def _utterance(addressed_to="group"):
    return PanelUtterance(
        text="Why that?", addressed_to=addressed_to, area_id="A", anchor_refs=["x"],
    )


def _collect(addressed_to="group", replies=None):
    """Run one exchange on stub agents. Returns responses, lost roles and prompts."""
    replies = replies or {}
    prompts: dict[str, str] = {}

    async def run_agent(*, agent, prompt):
        prompts[agent.name] = prompt
        return replies.get(agent.name, f"Answer from {agent.name}.")

    lost: list[str] = []
    responses = asyncio.run(pd._collect_panel_responses(
        utterance=_utterance(addressed_to),
        panel_agents={role: SimpleNamespace(name=role) for role in ROLES},
        history_block="(earlier exchanges)",
        artefacts=None,
        run_agent=run_agent,
        lost_roles=lost,
    ))
    return responses, lost, prompts


@pytest.mark.parametrize("addressed_to, first", [("group", "CEO"), ("CTO", "CTO")])
def test_later_speakers_see_the_answers_already_given(addressed_to, first):
    _, _, prompts = _collect(addressed_to)
    assert "Answer from" not in prompts[first]
    later = [role for role in ROLES if role != first]
    assert f"Answer from {first}." in prompts[later[0]]
    assert f"Answer from {first}." in prompts[later[1]]
    assert f"Answer from {later[0]}." in prompts[later[1]]


def test_a_role_is_told_when_the_addressee_gave_no_answer():
    _, _, prompts = _collect("CTO", {"CTO": "[PASS]"})
    assert "CTO gave no answer" in prompts["CEO"]


@pytest.mark.parametrize("reply", [
    "[PASS]", "**[PASS]**", '{"text": "[PASS]", "citations": []}',
    '{"response": "[PASS]"}', '```json\n{"body": "[PASS]"}\n```',
])
def test_a_pass_is_silence_however_it_is_wrapped(reply):
    responses, lost, _ = _collect("group", {"CEO": reply})
    assert "CEO" not in [r.role for r in responses]
    assert lost == []


@pytest.mark.parametrize("reply", ["   ", '{"text": "", "citations": []}'])
def test_an_empty_reply_is_a_lost_answer_not_silence(reply):
    responses, lost, _ = _collect("group", {"CEO": reply})
    assert "CEO" not in [r.role for r in responses]
    assert lost == ["CEO"]


@pytest.mark.parametrize("citations", [5, True, "a.txt", [{"doc_id": "a.txt"}], ["a.txt"]])
def test_malformed_citations_do_not_lose_the_answer(citations):
    reply = json.dumps({"text": "We capped it.", "citations": citations})
    responses, lost, _ = _collect("group", {"CEO": reply})
    assert responses[0].text == "We capped it."
    assert responses[0].citations == []
    assert lost == []


def test_good_citations_survive_beside_malformed_ones():
    reply = json.dumps({"text": "We capped it.", "citations": [{"doc_id": "x"}, CITATION]})
    responses, _, _ = _collect("group", {"CEO": reply})
    assert [c.quote for c in responses[0].citations] == ["a phrase"]


def test_plain_answers_with_braces_are_left_alone():
    text = "We set the {limit} ourselves."
    assert split_panel_reply(text) == (text, [])
    assert valid_citations([]) == []


def test_an_address_outside_the_panel_goes_to_everyone():
    responses, _, prompts = _collect("CTO and COO")
    assert [r.role for r in responses] == list(ROLES)
    assert all("WHOLE PANEL" in prompt for prompt in prompts.values())


def test_a_failed_exchange_keeps_the_exchanges_before_it(monkeypatch):
    calls = {"n": 0}

    async def utterance(**_):
        return _utterance()

    async def collect(**_):
        calls["n"] += 1
        if calls["n"] == 2:
            raise TypeError("bad reply")
        return []

    monkeypatch.setattr(pd, "_next_researcher_utterance", utterance)
    monkeypatch.setattr(pd, "_collect_panel_responses", collect)
    monkeypatch.setattr(pd, "_build_debriefer", lambda **_: SimpleNamespace(name="d"))
    transcript = asyncio.run(pd.run_panel_debriefing(
        company="X", observation_summary=SUMMARY, artefacts=None, panel_agents={},
        run_agent=None, max_exchanges=5,
    ))
    assert len(transcript.exchanges) == 1
    assert transcript.ended_reason == "error"


def test_the_debriefer_is_told_how_many_exchanges_remain():
    assert "EXCHANGES LEFT: 5 of 20." in pd._render_exchanges_left(15, 20)
    assert "last exchange" in pd._render_exchanges_left(19, 20)
    assert "last exchange" not in pd._render_exchanges_left(18, 20)


def test_the_debriefer_stays_on_the_researcher_model(monkeypatch):
    from providers import get_observer_model
    from roles.qualitative_researcher_agent import create_debriefer_agent
    from studies import load_study

    monkeypatch.setenv("TMT_PROVIDER", "claude")
    agent = create_debriefer_agent(
        company="X",
        observation_summary=SUMMARY,
        study=load_study("openness_maneuvering"),
    )
    assert agent.model == get_observer_model()
