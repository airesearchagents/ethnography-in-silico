"""A debrief replay reuses the saved run, never changes it, and says what it is."""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest

PKG = "open-innovation-strategy"
ROLES = ("CEO", "CTO")


def _saved():
    return importlib.import_module(f"{PKG}.analysis.saved_run")


def _replay():
    return importlib.import_module(f"{PKG}.analysis.replay_debrief")


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    studies = importlib.import_module(f"{PKG}.studies")
    version = studies.load_study("openness_maneuvering").version
    for name in ("01_deliberation", "03_researcher", "04_interview", "06_private_channel"):
        (tmp_path / name).mkdir()
    (tmp_path / "00_meta.json").write_text(json.dumps({
        "run_id": "ACME_run", "company": "ACME", "industry_context": "Dynamic",
        "product_type": "Novel", "study_slug": "openness_maneuvering",
        "study_version": version,
    }))
    (tmp_path / "01_deliberation" / "interaction_log.json").write_text(json.dumps({
        "company": "ACME", "industry_context": "Dynamic", "product_type": "Novel",
        "events": [{"index": 0, "role": "CTO", "kind": "text", "text": "We should price per seat."}],
    }))
    (tmp_path / "03_researcher" / "field_notes.json").write_text(json.dumps(["A field note."]))
    (tmp_path / "03_researcher" / "observation_summary.json").write_text(json.dumps({
        "decisions": ["pricing"], "components": ["pricing"],
    }))
    (tmp_path / "04_interview" / "transcript.json").write_text(json.dumps({
        "company": "ACME", "research_question": "rq",
        "exchanges": [{
            "utterance": {
                "area_id": "A", "addressed_to": "group", "text": "Old question?",
                "anchor_refs": ["pricing"],
            },
            "responses": [{"role": "CEO", "text": "Old answer."}],
        }],
        "ended_reason": "researcher_signalled",
    }))
    (tmp_path / "06_private_channel" / "private_state.json").write_text(json.dumps({
        role: {"role": role, "scratchpad": [f"{role} private note"], "draft": f"{role} draft"}
        for role in ROLES
    }))
    return tmp_path


def _stub_runner(seen: list, turns: int = 2):
    researcher_calls = []

    def make_runner():
        async def run_agent(*, agent, prompt):
            seen.append((agent.name, prompt))
            if agent.name.startswith("QualitativeResearcher"):
                researcher_calls.append(1)
                return json.dumps({
                    "area_id": "J", "addressed_to": "group",
                    "text": f"New question number {len(researcher_calls)}?",
                    "anchor_refs": ["pricing"], "is_followup": True,
                    "emerging_question": "Why per seat?",
                    "ends_debriefing": len(researcher_calls) >= turns,
                })
            return f"{agent.name} answers."
        return run_agent
    return make_runner


def _run(run, seen, **kwargs):
    kwargs.setdefault("roles", list(ROLES))
    return asyncio.run(_replay().replay_debrief(run, make_runner=_stub_runner(seen), **kwargs))


def test_deliberation_is_not_rerun(run_dir):
    run = _saved().load_saved_run(run_dir)
    seen: list = []
    transcript, counter = _run(run, seen)
    assert {name for name, _ in seen} == {"QualitativeResearcher_Debriefer", *ROLES}
    assert len(transcript.exchanges) == 2
    assert counter.calls == len(seen)


def test_panellist_gets_its_memory_every_call_and_only_its_own_notes(run_dir):
    run = _saved().load_saved_run(run_dir)
    seen: list = []
    _run(run, seen)
    ceo = [prompt for name, prompt in seen if name == "CEO"]
    assert len(ceo) == 2
    for prompt in ceo:
        assert "We should price per seat." in prompt
        assert "CEO private note" in prompt
        assert "CTO private note" not in prompt


def test_researcher_gets_the_deliberation_and_its_field_notes(run_dir):
    run = _saved().load_saved_run(run_dir)
    seen: list = []
    _run(run, seen)
    asked = [prompt for name, prompt in seen if name.startswith("QualitativeResearcher")]
    assert asked
    for prompt in asked:
        assert "We should price per seat." in prompt
        assert "A field note." in prompt


def test_panel_never_sees_the_research_question(run_dir):
    run = _saved().load_saved_run(run_dir)
    seen: list = []
    _run(run, seen)
    for name, prompt in seen:
        if name in ROLES:
            assert run.study.research_question not in prompt


def test_grounded_run_needs_retrieval(run_dir):
    (run_dir / "07_rag").mkdir()
    run = _saved().load_saved_run(run_dir)
    with pytest.raises(_saved().SavedRunError, match="grounded"):
        _run(run, [])


def test_grounded_run_replays_with_its_passages(run_dir, monkeypatch):
    (run_dir / "07_rag").mkdir()
    run = _saved().load_saved_run(run_dir)
    runtime = importlib.import_module(f"{PKG}.rag.runtime")
    schemas = importlib.import_module(f"{PKG}.rag.schemas")
    monkeypatch.setattr(runtime._vertex_corpus, "retrieve", lambda *_, **__: [schemas.RetrievedSnippet(
        doc_id="doc.txt", doc_display_name="doc.txt", chunk_id="doc.txt#1",
        text="A passage about pricing.", score=0.3,
    )])
    seen: list = []
    rag = runtime.RagSession(corpus_name="corpus")
    _run(run, seen, rag_session=rag)
    panel = [prompt for name, prompt in seen if name in ROLES]
    assert all("A passage about pricing." in prompt for prompt in panel)
    assert all(r["phase"] == "phase_4_debriefing" for r in rag.retrieval_log)


def test_unknown_role_is_refused(run_dir):
    run = _saved().load_saved_run(run_dir)
    with pytest.raises(_saved().SavedRunError, match="Unknown roles"):
        _run(run, [], roles=["Intern"])


def test_output_compares_and_leaves_the_source_alone(run_dir, tmp_path_factory):
    before = {p: p.read_bytes() for p in run_dir.rglob("*") if p.is_file()}
    run = _saved().load_saved_run(run_dir)
    transcript, counter = _run(run, [])
    out = tmp_path_factory.mktemp("replay") / "out"
    replay = _replay()
    replay.write_replay(run, transcript, counter, out, roles=list(ROLES), max_exchanges=5)
    assert before == {p: p.read_bytes() for p in run_dir.rglob("*") if p.is_file()}
    comparison = (out / "comparison.md").read_text()
    assert "| Exchanges | 1 | 2 |" in comparison
    assert "| Follow-ups | 0 | 2 |" in comparison
    assert "Why per seat?" in comparison
    assert "not a full run" in comparison
    assert json.loads((out / "replay_meta.json").read_text())["kind"] == "debrief_replay"
    assert (out / "04_interview" / "transcript.md").exists()


def test_output_cannot_go_inside_the_source(run_dir):
    run = _saved().load_saved_run(run_dir)
    transcript, counter = _run(run, [])
    with pytest.raises(_saved().SavedRunError):
        _replay().write_replay(
            run, transcript, counter, run_dir / "replay", roles=None, max_exchanges=5,
        )
