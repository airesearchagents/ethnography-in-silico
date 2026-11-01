"""Tests for analysis.persist_artefacts.

Verifies the folder-bursting works for both full-pipeline runs and
concurrent-only runs, and that markdown renderers don't choke on
empty / missing fields.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

PKG = "open-innovation-strategy"


def _persist():
    return importlib.import_module(f"{PKG}.analysis.persist_artefacts")


# ---------------------------------------------------------------------------
# Fixtures — minimal synthetic JSON payloads matching the production shapes.
# ---------------------------------------------------------------------------

def _delib_log() -> dict:
    return {
        "company": "OpenAI",
        "industry_context": "Dynamic",
        "product_type": "Novel",
        "events": [
            {"index": 0, "role": "CEO", "kind": "text",
             "text": "We need to decide on the release strategy.",
             "addressed_to": None, "phase": "concurrent"},
            {"index": 1, "role": "CEO", "kind": "ask_public_echo",
             "text": "CTO, what's the latency cost?",
             "addressed_to": "CTO", "phase": "concurrent"},
            {"index": 2, "role": "CTO", "kind": "answer_public",
             "text": "Under 200ms p50.",
             "answer_to_question_id": "q-001",
             "phase": "concurrent"},
        ],
    }


def _artefact_bundle() -> dict:
    return {
        "company": "OpenAI",
        "industry_context": "Dynamic",
        "product_type": "Novel",
        "artefacts": [
            {
                "role": "CEO",
                "company": "OpenAI",
                "industry_context": "Dynamic",
                "product_type": "Novel",
                "title": "Test CEO Strategy Memo",
                "key_challenges": ["challenge A"],
                "main_decisions": ["decision A"],
                "key_tensions": ["tension A"],
                "body": "# CEO body\nLorem ipsum.",
            },
        ],
    }


def _observation() -> dict:
    return {
        "decisions": ["decision A"],
        "components": ["inference API"],
        "disagreements": [
            {"topic": "release scope", "parties": ["CTO", "CMO"],
             "resolution": "internal-only for v1"}
        ],
        "role_contributions": [
            {"role": "CEO", "pushed_for": ["speed"],
             "pushed_back_on": [], "quiet_on": []},
        ],
        "alternatives_considered": ["partner-only release"],
        "loaded_vocabulary_used": [
            {"role": "CMO", "word": "strategic",
             "context": "'this is a strategic moment'"},
        ],
    }


def _debrief() -> dict:
    return {
        "company": "OpenAI",
        "research_question": "How do firms shift openness?",
        "ended_reason": "researcher_signalled",
        "forbidden_vocab_violations": 1,
        "exchanges": [
            {
                "utterance": {
                    "area_id": "A",
                    "addressed_to": "group",
                    "text": "Walk me through the inference API decision.",
                    "anchor_refs": ["inference API"],
                    "is_followup": False,
                    "ends_debriefing": False,
                },
                "responses": [
                    {"role": "CEO", "text": "It was about balance.",
                     "is_cross_talk": False},
                    {"role": "CTO", "text": "Technical risk was central.",
                     "is_cross_talk": True},
                ],
            },
        ],
    }


def _concurrent_payload() -> dict:
    return {
        "result_dict": {
            "company": "OpenAI",
            "industry_context": "Dynamic",
            "product_type": "Novel",
            "discussion_mode": "concurrent",
            "ended_reason": "all_done",
            "rounds_completed": 5,
            "events_count": 12,
            "strategic_question": "Open weights vs closed API?",
            "timestamp": "2026-05-21T12:00:00",
        },
        "transcript": _delib_log()["events"],
        "role_states": {
            "CEO": {
                "scratchpad": ["CTO seemed cautious", "watch for safety pushback"],
                "draft": "# CEO concurrent draft\nA full strategy memo here.",
                "inbox": [],
                "action_count": 6, "done": True,
                "finished_reason": "agent_declared_done",
            },
            "CTO": {
                "scratchpad": [],
                "draft": "# CTO concurrent draft\nTechnical strategy.",
                "inbox": [],
                "action_count": 5, "done": True,
                "finished_reason": "agent_declared_done",
            },
        },
    }


# ---------------------------------------------------------------------------
# 1. Full-pipeline burst — all four phases captured
# ---------------------------------------------------------------------------

class TestBurstFullPipeline:
    def test_writes_all_phase_folders(self, tmp_path: Path):
        p = _persist()
        out = p.burst_run(
            out_dir=tmp_path,
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            deliberation_log=_delib_log(),
            artefacts=_artefact_bundle(),
            observation_summary=_observation(),
            debriefing_transcript=_debrief(),
            research_question="How do firms shift openness?",
            run_id="test_full",
        )
        assert (out / "00_meta.json").is_file()
        assert (out / "01_deliberation" / "interaction_log.json").is_file()
        assert (out / "01_deliberation" / "interaction_log.md").is_file()
        assert (out / "02_strategy_documents" / "CEO_strategy.json").is_file()
        assert (out / "02_strategy_documents" / "CEO_strategy.md").is_file()
        assert (out / "03_researcher" / "observation_summary.json").is_file()
        assert (out / "03_researcher" / "observation_summary.md").is_file()
        assert (out / "04_interview" / "transcript.json").is_file()
        assert (out / "04_interview" / "transcript.md").is_file()
        assert (out / "README.md").is_file()

    def test_meta_records_all_phases_captured(self, tmp_path: Path):
        p = _persist()
        out = p.burst_run(
            out_dir=tmp_path,
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            deliberation_log=_delib_log(),
            artefacts=_artefact_bundle(),
            observation_summary=_observation(),
            debriefing_transcript=_debrief(),
            run_id="test_meta",
        )
        meta = json.loads((out / "00_meta.json").read_text())
        # Core Phase-1-to-4 entries are always present. Extra phases
        # (Phase 5+) only appear when the study registered a
        # PhaseHandler for them. No handlers registered here → no
        # extra entries.
        assert meta["phases_captured"] == {
            "deliberation": True,
            "strategy_documents": True,
            "observation_summary": True,
            "field_notes": False,
            "debriefing": True,
            # The private channel is CONCURRENT-mode-only and not
            # exercised in this test (no role_states supplied).
            "private_channel": False,
        }

    def test_artefact_markdown_includes_title_and_body(self, tmp_path: Path):
        p = _persist()
        out = p.burst_run(
            out_dir=tmp_path,
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            artefacts=_artefact_bundle(),
            run_id="test_art",
        )
        md = (out / "02_strategy_documents" / "CEO_strategy.md").read_text()
        assert "Test CEO Strategy Memo" in md
        assert "challenge A" in md
        assert "decision A" in md
        assert "tension A" in md
        assert "Lorem ipsum" in md

    def test_debriefing_markdown_includes_anchors_and_responses(self, tmp_path: Path):
        p = _persist()
        out = p.burst_run(
            out_dir=tmp_path,
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            debriefing_transcript=_debrief(),
            run_id="test_debrief",
        )
        md = (out / "04_interview" / "transcript.md").read_text()
        assert "Walk me through the inference API decision." in md
        assert "Anchored on" in md
        assert "It was about balance." in md
        assert "cross-talk" in md  # CTO marked as cross_talk


class TestWriteJsonFlag:
    """Markdown is always produced; JSON sub-files are optional via
    `write_json=False`. The top-level `00_meta.json` is still written
    so the per-run folder has a stable machine-readable identity."""

    def test_no_json_omits_phase_json_files(self, tmp_path: Path):
        p = _persist()
        out = p.burst_run(
            out_dir=tmp_path,
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            deliberation_log=_delib_log(),
            artefacts=_artefact_bundle(),
            observation_summary=_observation(),
            debriefing_transcript=_debrief(),
            run_id="test_no_json",
            write_json=False,
        )
        # Per-phase JSON files are absent.
        assert not (out / "01_deliberation" / "interaction_log.json").exists()
        assert not (out / "02_strategy_documents" / "CEO_strategy.json").exists()
        assert not (out / "03_researcher" / "observation_summary.json").exists()
        assert not (out / "04_interview" / "transcript.json").exists()

    def test_no_json_still_writes_all_markdown(self, tmp_path: Path):
        """Markdown is the source of truth for qualitative review;
        write_json=False must NOT suppress any markdown."""
        p = _persist()
        out = p.burst_run(
            out_dir=tmp_path,
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            deliberation_log=_delib_log(),
            artefacts=_artefact_bundle(),
            observation_summary=_observation(),
            debriefing_transcript=_debrief(),
            run_id="test_md_only",
            write_json=False,
        )
        assert (out / "01_deliberation" / "interaction_log.md").is_file()
        assert (out / "02_strategy_documents" / "CEO_strategy.md").is_file()
        assert (out / "03_researcher" / "observation_summary.md").is_file()
        assert (out / "04_interview" / "transcript.md").is_file()
        assert (out / "README.md").is_file()

    def test_no_json_still_writes_meta_json(self, tmp_path: Path):
        """The top-level `00_meta.json` is the per-run folder's
        machine-readable identity. It must be written regardless of
        write_json."""
        p = _persist()
        out = p.burst_run(
            out_dir=tmp_path,
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            deliberation_log=_delib_log(),
            run_id="test_meta_kept",
            write_json=False,
        )
        assert (out / "00_meta.json").is_file()

    def test_default_writes_json(self, tmp_path: Path):
        """Default behaviour (no `write_json` flag) writes JSON
        sub-files — back-compat with existing callers."""
        p = _persist()
        out = p.burst_run(
            out_dir=tmp_path,
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            deliberation_log=_delib_log(),
            artefacts=_artefact_bundle(),
            run_id="test_default_json",
        )
        assert (out / "01_deliberation" / "interaction_log.json").is_file()
        assert (out / "02_strategy_documents" / "CEO_strategy.json").is_file()


# ---------------------------------------------------------------------------
# 2. Concurrent-only burst — drafts become strategy documents
# ---------------------------------------------------------------------------

class TestBurstConcurrent:
    def test_drafts_become_strategy_documents(self, tmp_path: Path):
        p = _persist()
        payload = _concurrent_payload()
        payload_path = tmp_path / "concurrent.json"
        payload_path.write_text(json.dumps(payload))
        out = p.burst_concurrent_log(
            out_dir=tmp_path,
            payload_path=payload_path,
            run_id="test_concurrent",
        )
        ceo_md = (out / "02_strategy_documents" / "CEO_strategy.md").read_text()
        assert "CEO concurrent draft" in ceo_md
        assert "A full strategy memo here" in ceo_md

    def test_scratchpads_isolated_per_role(self, tmp_path: Path):
        p = _persist()
        payload = _concurrent_payload()
        payload_path = tmp_path / "concurrent.json"
        payload_path.write_text(json.dumps(payload))
        out = p.burst_concurrent_log(
            out_dir=tmp_path,
            payload_path=payload_path,
            run_id="test_scratchpad",
        )
        ceo_notes = (out / "01_deliberation" / "role_scratchpads" / "CEO_scratchpad.md").read_text()
        cto_notes = (out / "01_deliberation" / "role_scratchpads" / "CTO_scratchpad.md").read_text()
        assert "CTO seemed cautious" in ceo_notes
        assert "watch for safety pushback" in ceo_notes
        # CTO's scratchpad is empty — placeholder message.
        assert "no private notes recorded" in cto_notes
        # CTO's private notes must NOT appear in CEO's scratchpad, vice versa.
        assert "no private notes" not in ceo_notes
        assert "CTO seemed cautious" not in cto_notes


# ---------------------------------------------------------------------------
# 3. Partial captures — missing phases produce a sensible layout
# ---------------------------------------------------------------------------

class TestPartialCapture:
    def test_only_deliberation_no_other_folders(self, tmp_path: Path):
        p = _persist()
        out = p.burst_run(
            out_dir=tmp_path,
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            deliberation_log=_delib_log(),
            run_id="test_partial",
        )
        assert (out / "01_deliberation").is_dir()
        # No artefacts → no strategy documents folder.
        assert not (out / "02_strategy_documents").exists()
        assert not (out / "03_researcher").exists()
        assert not (out / "04_interview").exists()
        meta = json.loads((out / "00_meta.json").read_text())
        assert meta["phases_captured"]["strategy_documents"] is False

    def test_observation_summary_only(self, tmp_path: Path):
        p = _persist()
        out = p.burst_run(
            out_dir=tmp_path,
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            observation_summary=_observation(),
            run_id="test_obs_only",
        )
        assert (out / "03_researcher" / "observation_summary.md").is_file()
        md = (out / "03_researcher" / "observation_summary.md").read_text()
        assert "decision A" in md
        assert "inference API" in md
        # Loaded vocabulary section rendered.
        assert "strategic" in md


# ---------------------------------------------------------------------------
# 4. burst_run_from_files convenience
# ---------------------------------------------------------------------------

class TestBurstFromFiles:
    def test_session_pointer_expands_to_all_phases(self, tmp_path: Path):
        p = _persist()
        # Build a mini-session that looks like ResearchSessionOutputs.
        session = {
            "company": "Anthropic",
            "industry_context": "Stable",
            "product_type": "Incremental",
            "research_question": "How does Claude position?",
            "started_at": "2026-01-01T00:00:00",
            "finished_at": "2026-01-01T00:10:00",
            "deliberation_log": _delib_log(),
            "artefacts": _artefact_bundle(),
            "observation_summary": _observation(),
            "debriefing_transcript": _debrief(),
        }
        session_path = tmp_path / "session.json"
        session_path.write_text(json.dumps(session))

        out = p.burst_run_from_files(
            out_dir=tmp_path,
            session_path=session_path,
            run_id="test_session_burst",
        )
        meta = json.loads((out / "00_meta.json").read_text())
        assert meta["company"] == "Anthropic"
        assert meta["industry_context"] == "Stable"
        assert meta["product_type"] == "Incremental"
        # Every core Phase-1-to-4 stream is captured. The private
        # channel (CONCURRENT mode only) and any registered extra
        # phase handlers are opt-in and not part of this fixture.
        for phase, captured in meta["phases_captured"].items():
            if phase in ("private_channel", "field_notes"):
                continue
            assert captured, f"phase {phase} should be captured"
