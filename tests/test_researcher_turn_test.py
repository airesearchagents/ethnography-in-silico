"""The turn test must never reach the panel, and must report what it saw."""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest

PKG = "open-innovation-strategy"


def _saved():
    return importlib.import_module(f"{PKG}.analysis.saved_run")


def _turn():
    return importlib.import_module(f"{PKG}.analysis.researcher_turn_test")


def _exchange(text: str) -> dict:
    return {
        "utterance": {
            "area_id": "A", "addressed_to": "group", "text": text,
            "anchor_refs": ["pricing"],
        },
        "responses": [{"role": "CEO", "text": "We chose a flat fee."}],
    }


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    studies = importlib.import_module(f"{PKG}.studies")
    version = studies.load_study("openness_maneuvering").version
    folders = {
        "researcher": tmp_path / "03_researcher",
        "interview": tmp_path / "04_interview",
        "private": tmp_path / "06_private_channel",
    }
    for folder in folders.values():
        folder.mkdir()
    (tmp_path / "00_meta.json").write_text(json.dumps({
        "run_id": "ACME_run", "company": "ACME", "industry_context": "Dynamic",
        "product_type": "Novel", "study_slug": "openness_maneuvering",
        "study_version": version,
    }))
    (folders["researcher"] / "observation_summary.json").write_text(json.dumps({
        "decisions": ["pricing"], "components": ["pricing"],
    }))
    (folders["interview"] / "transcript.json").write_text(json.dumps({
        "company": "ACME", "research_question": "rq",
        "exchanges": [_exchange("First?"), _exchange("Second?")],
        "ended_reason": "researcher_signalled",
    }))
    (folders["private"] / "private_state.json").write_text(json.dumps({
        "CEO": {"role": "CEO", "scratchpad": ["a private note"], "draft": "a draft"},
    }))
    return tmp_path


def _reply(**overrides) -> str:
    utterance = {
        "area_id": "A", "addressed_to": "group", "text": "Why a flat fee, exactly?",
        "anchor_refs": ["flat fee"], "is_followup": True,
    }
    utterance.update(overrides)
    return json.dumps(utterance)


def _runner_factory(reply: str, seen: list):
    def make_runner():
        async def run_agent(*, agent, prompt):
            seen.append((agent, prompt))
            return reply
        return run_agent
    return make_runner


def _test(run, seen, reply=None, **kwargs):
    return asyncio.run(_turn().run_turn_test(
        run,
        make_runner=_runner_factory(reply or _reply(), seen),
        **kwargs,
    ))


def test_loads_the_saved_run(run_dir):
    run = _saved().load_saved_run(run_dir)
    assert run.company == "ACME"
    assert len(run.transcript.exchanges) == 2
    assert run.shared_state.role_states["CEO"].scratchpad == ["a private note"]
    assert run.grounded is False


def test_refuses_another_study_version(run_dir):
    meta = json.loads((run_dir / "00_meta.json").read_text())
    meta["study_version"] = "0.0.1"
    (run_dir / "00_meta.json").write_text(json.dumps(meta))
    saved = _saved()
    with pytest.raises(saved.SavedRunError):
        saved.load_saved_run(run_dir)
    assert saved.load_saved_run(run_dir, allow_version_mismatch=True)


def test_missing_json_explains_itself(run_dir):
    (run_dir / "03_researcher" / "observation_summary.json").unlink()
    saved = _saved()
    with pytest.raises(saved.SavedRunError, match="--no-json"):
        saved.load_saved_run(run_dir)


def test_only_the_researcher_is_called(run_dir):
    run = _saved().load_saved_run(run_dir)
    seen: list = []
    result = _test(run, seen, after_exchange=1, repeats=3)
    assert len(result.completed) == 3
    assert result.calls == len(seen) == 3
    assert {agent.name for agent, _ in seen} == {"QualitativeResearcher_Debriefer"}


def test_uses_only_the_exchanges_before_the_turn(run_dir):
    run = _saved().load_saved_run(run_dir)
    seen: list = []
    result = _test(run, seen, after_exchange=1, repeats=1)
    assert "First?" in seen[0][1]
    assert "Second?" not in seen[0][1]
    assert result.last_question == "First?"


def test_each_attempt_gets_its_own_runner(run_dir):
    run = _saved().load_saved_run(run_dir)
    made = []
    seen: list = []
    inner = _runner_factory(_reply(), seen)

    def make_runner():
        made.append(1)
        return inner()

    asyncio.run(_turn().run_turn_test(
        run, after_exchange=1, repeats=4, make_runner=make_runner,
    ))
    assert len(made) == 4


def test_report_counts_followups_and_new_questions(run_dir):
    run = _saved().load_saved_run(run_dir)
    result = _test(
        run, [], reply=_reply(emerging_question="Why flat fees?"),
        after_exchange=2, repeats=2,
    )
    report = _turn().render_report(result)
    assert "Follow-ups: 2 of 2" in report
    assert "Recorded a new question: 2 of 2" in report
    assert "Why flat fees?" in report
    assert "not evidence for a paper" in report


def test_rejects_an_exchange_out_of_range(run_dir):
    run = _saved().load_saved_run(run_dir)
    with pytest.raises(_saved().SavedRunError):
        _test(run, [], after_exchange=9, repeats=1)
