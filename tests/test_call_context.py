"""Each kind of model call receives what it needs, once, and nothing it should not.

Runs a whole session with a stub model and reads the prompts each agent got.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PKG = "open-innovation-strategy"
ROOT = Path(__file__).resolve().parent.parent
ROLES = ("CEO", "CTO", "COO", "CMO", "Product_Strategist", "Product_Designer")
OPENING = "The opening remark, far from the end of the discussion."
DISCUSSION = [OPENING] + [f"Turn {i}. " + "filler words " * 60 for i in range(30)]


def _session():
    return importlib.import_module(f"{PKG}.run_research_session")


def _artefact(role):
    return json.dumps({
        "role": role, "company": "ACME", "industry_context": "Dynamic", "product_type": "Novel",
        "title": f"{role} document", "key_challenges": ["c"], "main_decisions": ["d"],
        "key_tensions": ["t"], "body": f"The whole body by {role}.",
    })


def _run_session(monkeypatch, *, exchanges=2):
    agent_module = importlib.import_module(f"{PKG}.agent")

    async def fake_discussion(self, **kwargs):
        stream = kwargs["researcher_stream"]
        stream.observe("A live event.")
        await stream.flush_if_due(force=True)
        self._last_concurrent_shared_state = SimpleNamespace(role_states={
            role: SimpleNamespace(
                scratchpad=[f"{role} private note"], draft=f"{role} private draft",
            )
            for role in ROLES
        })
        return {
            "conversation_log": [
                {"index": i, "role": "CEO", "kind": "text", "text": text}
                for i, text in enumerate(DISCUSSION)
            ],
            "ceo_decision": "The final synthesis.",
        }

    monkeypatch.setattr(agent_module.TMTSystemWithA2A, "run_strategic_discussion", fake_discussion)
    prompts = {}
    questions = []

    async def stub(*, agent, prompt):
        prompts.setdefault(agent.name, []).append(prompt)
        name = agent.name
        if name.endswith("_Artefact"):
            return _artefact(name.split("_Artefact")[0])
        if name == "QualitativeResearcher_FieldNoter":
            return "A field note."
        if name == "QualitativeResearcher_Observer":
            return json.dumps({"decisions": ["d"], "components": ["c"]})
        if name == "QualitativeResearcher_Debriefer":
            questions.append(1)
            return json.dumps({
                "area_id": "J", "addressed_to": "group",
                "text": f"Question number {len(questions)} on a new subject?",
                "anchor_refs": ["d"], "is_followup": False,
                "ends_debriefing": len(questions) >= exchanges,
            })
        return f"{name} answers."

    saves = []

    def on_save(out):
        saves.append((
            out.deliberation_log is not None,
            out.artefacts is not None,
            out.observation_summary is not None,
            len(out.debriefing_transcript.exchanges) if out.debriefing_transcript else 0,
        ))

    out = asyncio.run(_session().run_research_session(
        company="ACME", runner_fn=stub, on_phase_complete=on_save,
    ))
    return out, prompts, saves


@pytest.fixture
def session(monkeypatch):
    return _run_session(monkeypatch)


class TestDocuments:
    def test_role_has_the_whole_discussion(self, session):
        _, prompts, _ = session
        assert OPENING in prompts["CTO_Artefact"][0]
        assert "Turn 29." in prompts["CTO_Artefact"][0]

    def test_role_has_its_own_notes_and_draft_and_no_one_elses(self, session):
        _, prompts, _ = session
        prompt = prompts["CTO_Artefact"][0]
        assert "CTO private note" in prompt
        assert "CTO private draft" in prompt
        assert "CEO private note" not in prompt
        assert "CEO private draft" not in prompt


class TestDebriefPanel:
    def test_role_has_the_whole_discussion_every_call(self, session):
        _, prompts, _ = session
        assert len(prompts["CTO"]) == 2
        assert all(OPENING in prompt for prompt in prompts["CTO"])

    def test_role_has_its_own_notes_and_whole_document_and_no_one_elses(self, session):
        _, prompts, _ = session
        for prompt in prompts["CTO"]:
            assert "CTO private note" in prompt
            assert "The whole body by CTO." in prompt
            assert "CEO private note" not in prompt
            assert "The whole body by CEO." not in prompt

    def test_panel_never_sees_the_research_question(self, session):
        out, prompts, _ = session
        for role in ROLES:
            assert all(out.research_question not in prompt for prompt in prompts[role])

    def test_memory_comes_before_what_changes_so_it_can_be_cached(self, session):
        _, prompts, _ = session
        prompt = prompts["CTO"][1]
        assert prompt.index("WHAT YOU REMEMBER") < prompt.index("DEBRIEFING HISTORY SO FAR")
        assert prompt.index("DEBRIEFING HISTORY SO FAR") < prompt.index("RESEARCHER'S CURRENT QUESTION")

    def test_first_speaker_moves_round_the_table(self, session):
        out, _, _ = session
        first, second = out.debriefing_transcript.exchanges[:2]
        assert first.responses[0].role == "CEO"
        assert second.responses[0].role == "CTO"


class TestResearcher:
    def test_field_noter_sees_every_earlier_note(self, session):
        _, prompts, _ = session
        assert "A field note." in prompts["QualitativeResearcher_FieldNoter"][-1]

    def test_observer_receives_the_field_notes(self, session):
        _, prompts, _ = session
        prompt = prompts["QualitativeResearcher_Observer"][0]
        assert "YOUR RUNNING FIELD NOTES" in prompt
        assert "A field note." in prompt

    def test_debriefer_has_what_it_observed_every_call(self, session):
        _, prompts, _ = session
        asked = prompts["QualitativeResearcher_Debriefer"]
        assert len(asked) >= 2
        for prompt in asked:
            assert OPENING in prompt
            assert "A field note." in prompt
            assert "The whole body by CMO." in prompt


class TestSavingAsItGoes:
    def test_run_is_saved_after_each_phase_and_exchange(self, session):
        _, _, saves = session
        assert saves[0] == (True, False, False, 0)
        assert (True, True, False, 0) in saves
        assert (True, True, True, 0) in saves
        assert saves[-1] == (True, True, True, 2)

    def test_a_failed_save_does_not_stop_the_run(self, monkeypatch):
        agent_module = importlib.import_module(f"{PKG}.agent")

        async def fails(self, **_):
            raise RuntimeError("model down")

        monkeypatch.setattr(agent_module.TMTSystemWithA2A, "run_strategic_discussion", fails)

        def bad_save(_):
            raise OSError("disk full")

        out = asyncio.run(_session().run_research_session(
            company="ACME", on_phase_complete=bad_save,
        ))
        assert any("deliberation_failed" in error for error in out.errors)

    def test_folder_says_a_run_stopped_early(self, tmp_path):
        persist = importlib.import_module(f"{PKG}.analysis.persist_artefacts")
        base = persist.burst_run(
            out_dir=tmp_path, company="ACME", industry_context="Dynamic", product_type="Novel",
            run_id="ACME_run", extra_meta={"run_complete": False},
        )
        assert json.loads((base / "00_meta.json").read_text())["run_complete"] is False


class TestScenarioBrief:
    def test_it_reaches_the_team_in_the_default_mode(self):
        concurrent = importlib.import_module(f"{PKG}.orchestrator.concurrent_mode")
        task = concurrent.RoleTaskSpec(
            role="CEO", company="ACME", industry_context="Dynamic", product_type="Novel",
            strategic_question="What next?", doc_framing="A document.",
            scenario_brief="A firm in a busy market.",
        )
        prompt = concurrent._compose_role_prompt(
            role="CEO", task=task, my_state=concurrent.RoleState(role="CEO"), transcript=[],
        )
        assert "Company: ACME (A firm in a busy market)" in prompt


class TestPassages:
    def _snippet(self, text):
        schemas = importlib.import_module(f"{PKG}.rag.schemas")
        return schemas.RetrievedSnippet(
            doc_id="d.txt", doc_display_name="d.txt", chunk_id="d.txt#1", text=text, score=0.3,
        )

    def test_whole_passage_is_shown_by_default(self, monkeypatch):
        inject = importlib.import_module(f"{PKG}.rag.prompt_inject")
        monkeypatch.delenv("TMT_PASSAGE_CHARS", raising=False)
        text = "word " * 800 + "the part that matched"
        block = inject.format_retrieved_context(role="CEO", snippets=[self._snippet(text)])
        assert "the part that matched" in block
        assert "[...]" not in block

    def test_a_limit_can_be_set_and_is_marked(self, monkeypatch):
        inject = importlib.import_module(f"{PKG}.rag.prompt_inject")
        monkeypatch.setenv("TMT_PASSAGE_CHARS", "1200")
        text = "word " * 800 + "the part that matched"
        block = inject.format_retrieved_context(role="CEO", snippets=[self._snippet(text)])
        assert "the part that matched" not in block
        assert "[...]" in block


class TestUsageLog:
    def _log(self):
        return importlib.import_module(f"{PKG}.orchestrator.usage_log")

    def _usage(self, prompt, cached=0, output=0, thoughts=0):
        return SimpleNamespace(
            prompt_token_count=prompt, cached_content_token_count=cached,
            candidates_token_count=output, thoughts_token_count=thoughts,
        )

    def test_list_price_uses_the_lower_rate_up_to_200k(self):
        assert self._log().list_cost("gemini-3.1-pro-preview", 200_000, 0, 1000) == pytest.approx(
            0.4 + 0.012,
        )

    def test_above_200k_the_whole_request_moves_to_the_higher_rate(self):
        assert self._log().list_cost("gemini-3.1-pro-preview", 200_001, 0, 1000) == pytest.approx(
            0.800004 + 0.018,
        )

    def test_cached_tokens_are_cheaper(self):
        cost = self._log().list_cost("gemini-3.1-pro-preview", 100_000, 90_000, 0)
        assert cost == pytest.approx(0.02 + 0.018)

    def test_unknown_model_has_counts_but_no_cost(self):
        usage = self._log().UsageLog()
        usage.record(SimpleNamespace(name="CEO", model="other"), self._usage(1000, output=10))
        summary = usage.summary()
        assert summary["input_tokens"] == 1000
        assert summary["list_cost_usd"] is None

    def test_summary_groups_by_phase_and_counts_reasoning_as_output(self):
        usage = self._log().UsageLog()
        usage.phase = "phase_4_debrief"
        usage.record(
            SimpleNamespace(name="CEO", model="gemini-3.1-pro-preview"),
            self._usage(250_000, cached=1000, output=100, thoughts=50),
        )
        usage.record(SimpleNamespace(name="CEO"), None)
        summary = usage.summary()
        assert summary["calls"] == 1
        assert summary["output_tokens"] == 150
        assert summary["calls_over_200k"] == 1
        assert summary["by_phase"]["phase_4_debrief"]["largest_call_input_tokens"] == 250_000

    def test_run_folder_records_it(self, tmp_path):
        persist = importlib.import_module(f"{PKG}.analysis.persist_artefacts")
        usage = self._log().UsageLog()
        usage.record(
            SimpleNamespace(name="CEO", model="gemini-3.1-pro-preview"), self._usage(1000, output=10),
        )
        base = persist.burst_run(
            out_dir=tmp_path, company="ACME", industry_context="Dynamic", product_type="Novel",
            run_id="ACME_run", usage_log=usage,
        )
        assert json.loads((base / "00_meta.json").read_text())["token_usage"]["input_tokens"] == 1000
        assert (base / "08_usage" / "token_usage.jsonl").read_text().count("\n") == 1


class TestManifest:
    def test_it_identifies_neither_the_machine_nor_the_cloud_project(self, monkeypatch):
        package = importlib.import_module(f"{PKG}.analysis.replication_package")
        agent_module = importlib.import_module(f"{PKG}.agent")
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "a-private-project")
        rag = SimpleNamespace(manifest_dict=lambda: {
            "corpus_resource_name": "projects/a-private-project/locations/l/ragCorpora/1",
        })
        manifest = package.capture_from_system(
            agent_module.TMTSystemWithA2A("ACME"), rag_session=rag,
            run_id="r", started_at="t", study_slug="openness_maneuvering", study_version="v",
        )
        text = manifest.model_dump_json()
        assert "a-private-project" not in text
        assert "repo_path" not in text
        assert "python_executable" not in text

    def test_it_hashes_what_agents_are_told(self):
        package = importlib.import_module(f"{PKG}.analysis.replication_package")
        hashes = package.snapshot_protocol_hashes("openness_maneuvering")
        assert "protocols/ethnographic_protocol.yaml" in hashes
        assert "studies/openness_maneuvering/debriefing_overlay.yaml" in hashes
        assert all(len(value) == 64 for value in hashes.values())


def test_dry_run_sends_no_earlier_messages():
    """The whole pipeline on a stand-in model, through the real ADK."""
    pytest.importorskip("google.adk.models.registry")
    result = subprocess.run(
        [sys.executable, "-m", "analysis.dry_run", "--rag",
         "--max-exchanges", "2", "--max-actions-per-role", "3"],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Calls carrying earlier messages: 0" in result.stdout


class TestCitingInTheDebrief:
    """Debrief answers are prose, so they cannot populate a structured field."""

    def _block(self, **kwargs):
        inject = importlib.import_module(f"{PKG}.rag.prompt_inject")
        schemas = importlib.import_module(f"{PKG}.rag.schemas")
        snippet = schemas.RetrievedSnippet(
            doc_id="d.txt", doc_display_name="d.txt", chunk_id="d.txt#1", text="A passage.", score=0.3,
        )
        return inject.format_retrieved_context(role="CEO", snippets=[snippet], **kwargs)

    def test_debrief_prompt_says_how_to_cite_in_prose(self):
        block = self._block(plain_reply=True)
        assert "structured action" not in block
        assert '{"citations": [...]}' in block

    def test_other_calls_still_use_the_field(self):
        assert "`citations` field of your structured action" in self._block()

    def test_the_format_it_asks_for_is_the_format_that_is_parsed(self):
        schemas = importlib.import_module(f"{PKG}.roles.researcher_schemas")
        reply = (
            "We chose the narrow launch.\n"
            '{"citations": [{"doc_id": "d.txt", "chunk_id": "d.txt#1", '
            '"quote": "A passage.", "supports": "launch"}]}'
        )
        text, citations = schemas.split_panel_reply(reply)
        assert text == "We chose the narrow launch."
        assert citations[0]["quote"] == "A passage."
