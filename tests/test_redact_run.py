"""A published grounded run must not carry its source text."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

PKG = "open-innovation-strategy"
SOURCE = "the quick brown fox jumps over the lazy dog near the old river bank today"


def _module():
    return importlib.import_module(f"{PKG}.analysis.redact_run")


def _run(tmp: Path) -> Path:
    run = tmp / "run"
    for folder in ("01_deliberation", "02_strategy_documents", "04_interview", "05_judging", "07_rag"):
        (run / folder).mkdir(parents=True)
    (run / "05_judging" / "secret.md").write_text("scores")
    (run / "00_meta.json").write_text(json.dumps({"corpus": "projects/my-project/locations/x"}))
    (run / "01_deliberation" / "interaction_log.json").write_text(json.dumps({"events": [
        {"index": 0, "role": "CTO", "kind": "speak", "text": f"As he said, {SOURCE}. We agree.", "citations": []},
    ]}))
    (run / "01_deliberation" / "interaction_log.md").write_text(f"CTO: {SOURCE}")
    answer = json.dumps({"body": "Our own view.", "citations": [{"doc_id": "a.txt", "quote": "short quote", "supports": "x"}]})
    (run / "04_interview" / "transcript.json").write_text(json.dumps({
        "company": "X", "research_question": "Q", "ended_reason": "x", "forbidden_vocab_violations": 0,
        "exchanges": [{"utterance": {"text": "Why?", "area_id": "A", "addressed_to": "CTO"},
                       "responses": [{"role": "CTO", "text": f"```json\n{answer}\n```"}]}],
    }))
    (run / "07_rag" / "retrieval_log.jsonl").write_text(json.dumps({
        "phase": "p", "role": "CTO", "query": "q",
        "retrieved": [{"doc_id": "a.txt", "chunk_id": "a#1", "score": 0.3, "text": SOURCE}],
    }) + "\n")
    return run


def test_source_text_quotes_and_scores_are_gone(tmp_path):
    out = tmp_path / "out"
    _module().redact_run(_run(tmp_path), out)
    everything = "\n".join(p.read_text() for p in out.rglob("*") if p.is_file())
    assert "quick brown fox" not in everything
    assert "short quote" not in everything
    assert "my-project" not in everything
    assert "```json" not in everything
    assert not (out / "05_judging").exists()
    assert "Our own view." in (out / "04_interview" / "transcript.md").read_text()


def test_retrieval_log_keeps_the_trace_without_the_text(tmp_path):
    out = tmp_path / "out"
    _module().redact_run(_run(tmp_path), out)
    record = json.loads((out / "07_rag" / "retrieval_log.jsonl").read_text())
    passage = record["retrieved"][0]
    assert passage["doc_id"] == "a.txt"
    assert passage["score"] == 0.3
    assert len(passage["text_sha256"]) == 64
    assert "text" not in passage


def test_a_short_shared_phrase_stays():
    module = _module()
    grams = module.source_grams([SOURCE])
    assert module.scrub("a quick brown fox appeared", grams) == "a quick brown fox appeared"
    assert module.MARKER in module.scrub(f"he said {SOURCE} there", grams)


def test_refuses_an_existing_output_folder(tmp_path):
    import pytest

    run = _run(tmp_path)
    existing = tmp_path / "out"
    existing.mkdir()
    (existing / "keep.txt").write_text("mine")
    with pytest.raises(ValueError):
        _module().redact_run(run, existing)
    assert (existing / "keep.txt").read_text() == "mine"
    assert (run / "00_meta.json").exists()


def test_document_identifiers_survive_redaction():
    module = _module()
    grams = module.source_grams(["one two three four five six seven eight"])
    cleaned = module.clean_value(
        {"doc_id": "one two three four five six seven eight.pdf", "note": "one two three four five six seven"},
        grams,
    )
    assert cleaned["doc_id"].startswith("one two")
    assert module.MARKER in cleaned["note"]


def test_published_copy_hides_the_cloud_project(tmp_path):
    import importlib
    import json

    redact = importlib.import_module("open-innovation-strategy.analysis.redact_run")
    run = tmp_path / "run"
    (run / "07_rag").mkdir(parents=True)
    name = "projects/a-private-project/locations/us-west1/ragCorpora/1"
    (run / "07_rag" / "corpus_manifest.json").write_text(json.dumps({"corpus_resource_name": name}))
    (run / "07_rag" / "README.md").write_text(f"Corpus: {name}\n")
    (run / "manifest.json").write_text(json.dumps({"rag_config": {"corpus_resource_name": name}}))
    out = tmp_path / "out"
    redact.redact_run(run, out)
    for path in out.rglob("*"):
        if path.is_file():
            assert "a-private-project" not in path.read_text(), path
