"""The provenance report must credit phrases to the right source and flag what it cannot trace."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis import provenance as prov  # noqa: E402
from analysis.panel_probe import measure, parse_mix  # noqa: E402


def _run(tmp_path: Path, *, grounded: bool = False) -> Path:
    run = tmp_path / "run"
    for folder in ("01_deliberation", "02_strategy_documents", "03_researcher", "04_interview", "06_private_channel", "07_rag"):
        (run / folder).mkdir(parents=True)
    (run / "00_meta.json").write_text(json.dumps({"run_id": "r1", "errors": []}))
    (run / "01_deliberation" / "interaction_log.json").write_text(json.dumps({"events": [
        {"role": "CTO", "text": "We ring fenced compute budgets for the pilot."},
    ]}))
    (run / "06_private_channel" / "private_state.json").write_text(json.dumps({
        "CTO": {"scratchpad": ["Worried about vendor lock pricing."], "draft": ""},
    }))
    (run / "03_researcher" / "observation_summary.md").write_text("Observed.")
    citation = {"doc_id": "a.txt", "quote": "Shown passage text.", "supports": "x"}
    missing = {"doc_id": "b.txt", "quote": "Never shown words.", "supports": "x"}
    (run / "04_interview" / "transcript.json").write_text(json.dumps({"exchanges": [
        {
            "utterance": {"text": "How did the pilot budget come about?", "addressed_to": "group"},
            "responses": [
                {
                    "role": "CTO",
                    "text": "We ring fenced compute budgets. I mandated a 'Dual Key Hold' gate. The Dual Key Hold stopped runaway agents immediately.",
                    "citations": [citation, missing] if grounded else [],
                },
                {"role": "COO", "text": "Our quarterly staffing forecast slipped badly."},
            ],
        },
        {
            "utterance": {"text": "When an outsider contributes to the proxy, how does that contribution actually get in?", "addressed_to": "COO"},
            "responses": [{"role": "COO", "text": "Our quarterly staffing forecast slipped badly again."}],
            "lost_roles": ["CMO"],
        },
    ]}))
    if grounded:
        (run / "07_rag" / "retrieval_log.jsonl").write_text(json.dumps({
            "phase": "debrief", "role": "CTO",
            "retrieved": [{"doc_id": "a.txt", "text": "A shown  passage text. here"}],
        }) + "\n")
    return run


def _prompts(tmp_path: Path) -> Path:
    root = tmp_path / "prompts"
    (root / "protocols").mkdir(parents=True, exist_ok=True)
    (root / "protocols" / "ethnographic_protocol.yaml").write_text(
        'stems:\n  - "When an outsider contributes to [X], how does that contribution actually get in?"\n'
    )
    return root


def test_phrases_are_credited_to_their_earliest_source(tmp_path):
    report = prov.build_report(_run(tmp_path), prompts_root=_prompts(tmp_path))
    share = report["origins"]["share"]
    assert share["deliberation"] > 0
    assert share["another role's earlier answer"] == 0
    assert share["own earlier answer"] > 0
    assert share["new in this answer"] > 0
    assert abs(sum(share.values()) - 1) < 0.01
    assert report["lost_answers"] == 1


def test_terms_new_in_the_debrief_and_past_claims_are_flagged(tmp_path):
    report = prov.build_report(_run(tmp_path), prompts_root=_prompts(tmp_path))
    assert "dual key hold" in {t["term"] for t in report["new_in_debrief"]}
    assert "ring" not in {t["term"] for t in report["new_in_debrief"]}
    assert any("mandated" in c["sentence"] for c in report["unsupported_past_claims"])


def test_question_repeating_a_stem_is_flagged(tmp_path):
    report = prov.build_report(_run(tmp_path), prompts_root=_prompts(tmp_path))
    assert [e["exchange"] for e in report["question_echoes"]] == [2]
    assert "how does that contribution actually get in" in report["question_echoes"][0]["shared_words"]


def test_citation_check_separates_verbatim_quotes_from_problems(tmp_path):
    report = prov.build_report(_run(tmp_path, grounded=True), prompts_root=_prompts(tmp_path))
    citations = report["citations"]
    assert citations["per_phase"]["debrief"] == {
        "citations": 2, "quote_verbatim": 1, "document_was_shown": 1,
    }
    assert citations["problem_count"] == 1
    assert citations["problems"][0]["doc_id"] == "b.txt"
    assert "Ungrounded" in prov.render_report(prov.build_report(_run(tmp_path / "u"), prompts_root=_prompts(tmp_path)))


def test_probe_measure_compares_roles_with_a_second_sample():
    answers = [
        {"question": 1, "repeat": 0, "role": "A", "text": "compute budget ceiling"},
        {"question": 1, "repeat": 1, "role": "A", "text": "compute budget ceiling"},
        {"question": 1, "repeat": 0, "role": "B", "text": "brand narrative channels"},
        {"question": 1, "repeat": 1, "role": "B", "text": "brand narrative channels"},
    ]
    result = measure(answers)
    assert result["same_role_second_sample"] > result["between_roles_same_sample"]


def test_parse_mix():
    assert parse_mix("CTO=openai, CMO=deepseek") == {"CTO": "openai", "CMO": "deepseek"}
    assert parse_mix(None) == {}


def test_a_missing_run_or_prompt_folder_is_an_error_not_a_blank_report(tmp_path):
    import importlib

    import pytest

    provenance = importlib.import_module("open-innovation-strategy.analysis.provenance")
    with pytest.raises(FileNotFoundError):
        provenance.load_records(tmp_path / "nowhere")
    with pytest.raises(FileNotFoundError):
        provenance.prompt_text(tmp_path)


def test_prompts_saved_with_a_txt_suffix_are_found(tmp_path):
    import importlib

    provenance = importlib.import_module("open-innovation-strategy.analysis.provenance")
    (tmp_path / "roles").mkdir()
    (tmp_path / "roles" / "ceo_agent.py.txt").write_text("a saved role prompt")
    assert "a saved role prompt" in provenance.prompt_text(tmp_path)


def test_runs_that_did_not_log_it_are_read_at_the_old_limit():
    import importlib

    provenance = importlib.import_module("open-innovation-strategy.analysis.provenance")
    assert provenance.SHOWN_CHARS == 1200
