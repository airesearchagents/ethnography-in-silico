"""Tests for private-channel persistence (Phase A of the
sub-dimensional measurement plan, docs/09).

The private channel is the firm's internal deliberation state held
in `SharedState.role_states[role]` during Phase 1 — scratchpads,
working drafts, and inbox messages that peers never saw. Before this
change the data was garbage-collected when the run ended; now it is
snapshot-ed into `ResearchSessionOutputs.private_state` and persisted
by `burst_run` to `06_private_channel/`.

These tests pin:
  * the snapshot helper produces the right shape, with role attribution
    preserved on every message;
  * `burst_run` writes every expected file under `06_private_channel/`;
  * private-channel persistence does NOT interfere with the existing
    strategy-documents behaviour (artefacts still take precedence when
    both are supplied);
  * the inbox renderer distinguishes private vs public answers — this
    is the methodological signal that the sub-dimensional measurement
    layer will key off.

No network, no real ADK.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

PKG = "open-innovation-strategy"


def _persist():
    return importlib.import_module(f"{PKG}.analysis.persist_artefacts")


def _run_session_module():
    return importlib.import_module(f"{PKG}.run_research_session")


# ===========================================================================
# Helper: a stubbed SharedState-like object that has the role_states
# shape `_snapshot_private_channel` expects. Keeps the test independent
# of the orchestrator's concurrent_mode internals.
# ===========================================================================

class _StubRoleState:
    """Quacks like `orchestrator.concurrent_mode.RoleState`."""

    def __init__(
        self,
        *,
        role: str,
        scratchpad: list,
        draft: str = "",
        inbox: list | None = None,
        action_count: int = 0,
        done: bool = False,
        finished_reason: str = "",
    ):
        self.role = role
        self.scratchpad = scratchpad
        self.draft = draft
        self.inbox = inbox or []
        self.action_count = action_count
        self.done = done
        self.finished_reason = finished_reason

    def model_dump(self, mode: str = "json"):  # pragma: no cover  trivial
        return {
            "role": self.role,
            "scratchpad": list(self.scratchpad),
            "draft": self.draft,
            "inbox": [dict(m) if isinstance(m, dict) else m.model_dump() for m in self.inbox],
            "action_count": self.action_count,
            "done": self.done,
            "finished_reason": self.finished_reason,
        }


class _StubSharedState:
    """Quacks like `orchestrator.concurrent_mode.SharedState`."""

    def __init__(self, role_states: dict):
        self.role_states = role_states


def _sample_role_states() -> dict:
    """Build a non-trivial private-channel sample with all the shapes the
    measurement layer needs to discriminate.

    Includes private vs public answers in the inbox (the key
    methodological signal that distinguishes the channels)."""
    return {
        "CEO": _StubRoleState(
            role="CEO",
            scratchpad=[
                "Push CTO on weights-release stance.",
                "CMO worried about competitive leak; pressure-test that.",
            ],
            draft="# CEO position\n\nWe release weights with a permissive license.",
            inbox=[
                {
                    "id": "q1", "sender": "CTO", "recipient": "CEO",
                    "kind": "ASK",
                    "text": "Do we open the eval harness or hold it back?",
                    "visibility": "public",
                },
                {
                    "id": "q2", "sender": "CMO", "recipient": "CEO",
                    "kind": "ANSWER",
                    "text": "I disagree with the open posture — competitive risk.",
                    "answer_to_question_id": "q1",
                    "visibility": "private",  # this is the methodological signal
                },
            ],
            action_count=14,
            done=True,
            finished_reason="DONE_action",
        ),
        "CTO": _StubRoleState(
            role="CTO",
            scratchpad=["Need clarity from CEO on commercial license terms."],
            draft="# CTO position\n\nRelease all weights; restrict eval harness.",
            inbox=[],
            action_count=9,
            done=True,
            finished_reason="DONE_action",
        ),
    }


# ===========================================================================
# 1. _snapshot_private_channel
# ===========================================================================

class TestSnapshotPrivateChannel:
    """The helper that converts a SharedState into a serialisable dict
    for `ResearchSessionOutputs.private_state`."""

    def test_returns_none_when_shared_state_is_none(self):
        rs = _run_session_module()
        assert rs._snapshot_private_channel(None) is None

    def test_returns_none_when_role_states_is_missing(self):
        rs = _run_session_module()

        class _Empty:
            pass
        assert rs._snapshot_private_channel(_Empty()) is None

    def test_dumps_every_role(self):
        rs = _run_session_module()
        dump = rs._snapshot_private_channel(_StubSharedState(_sample_role_states()))
        assert dump is not None
        assert set(dump.keys()) == {"CEO", "CTO"}

    def test_preserves_scratchpad_and_draft(self):
        rs = _run_session_module()
        dump = rs._snapshot_private_channel(_StubSharedState(_sample_role_states()))
        assert dump["CEO"]["draft"].startswith("# CEO position")
        assert len(dump["CEO"]["scratchpad"]) == 2

    def test_preserves_inbox_visibility(self):
        """Private-vs-public answer attribution must survive the dump —
        this is the methodological signal that distinguishes private
        from public channel content."""
        rs = _run_session_module()
        dump = rs._snapshot_private_channel(_StubSharedState(_sample_role_states()))
        inbox = dump["CEO"]["inbox"]
        # Find the private ANSWER and verify visibility persisted.
        private_answers = [m for m in inbox if m.get("visibility") == "private"]
        assert len(private_answers) == 1
        assert private_answers[0]["sender"] == "CMO"


# ===========================================================================
# 2. _write_private_channel
# ===========================================================================

class TestWritePrivateChannel:
    """Writing the per-role scratchpad, draft, and inbox files to
    06_private_channel/."""

    def test_writes_per_role_scratchpad_files(self, tmp_path):
        p = _persist()
        states = _persist_dump(_sample_role_states())
        p._write_private_channel(tmp_path, states)
        assert (tmp_path / "06_private_channel" / "CEO_scratchpad.md").exists()
        assert (tmp_path / "06_private_channel" / "CTO_scratchpad.md").exists()

    def test_writes_per_role_draft_files(self, tmp_path):
        p = _persist()
        states = _persist_dump(_sample_role_states())
        p._write_private_channel(tmp_path, states)
        assert (tmp_path / "06_private_channel" / "CEO_draft.md").exists()
        assert (tmp_path / "06_private_channel" / "CTO_draft.md").exists()

    def test_writes_combined_inbox_file(self, tmp_path):
        p = _persist()
        states = _persist_dump(_sample_role_states())
        p._write_private_channel(tmp_path, states)
        assert (tmp_path / "06_private_channel" / "inbox_final.md").exists()

    def test_writes_machine_readable_dump_when_json_enabled(self, tmp_path):
        p = _persist()
        states = _persist_dump(_sample_role_states())
        p._write_private_channel(tmp_path, states, write_json=True)
        payload = json.loads(
            (tmp_path / "06_private_channel" / "private_state.json").read_text()
        )
        assert set(payload.keys()) == {"CEO", "CTO"}
        assert payload["CEO"]["draft"].startswith("# CEO position")

    def test_skips_machine_readable_dump_when_json_disabled(self, tmp_path):
        """--no-json mode: only markdown, no JSON sub-files in this section."""
        p = _persist()
        states = _persist_dump(_sample_role_states())
        p._write_private_channel(tmp_path, states, write_json=False)
        assert not (tmp_path / "06_private_channel" / "private_state.json").exists()
        # Markdown sub-files still present.
        assert (tmp_path / "06_private_channel" / "CEO_scratchpad.md").exists()


# ===========================================================================
# 3. Inbox renderer — methodological signal
# ===========================================================================

class TestInboxRenderer:
    """The inbox renderer must distinguish private from public answers.
    This is the operational definition the measurement layer keys off."""

    def test_private_answer_flagged_with_marker(self, tmp_path):
        p = _persist()
        states = _persist_dump(_sample_role_states())
        p._write_private_channel(tmp_path, states)
        inbox_md = (tmp_path / "06_private_channel" / "inbox_final.md").read_text()
        assert "PRIVATE" in inbox_md, (
            "Inbox renderer must mark private answers — the measurement "
            "layer can't distinguish private from public answers without it."
        )

    def test_public_ask_is_present_without_private_marker(self, tmp_path):
        p = _persist()
        states = _persist_dump(_sample_role_states())
        p._write_private_channel(tmp_path, states)
        inbox_md = (tmp_path / "06_private_channel" / "inbox_final.md").read_text()
        # The public ASK from CTO → CEO is in the file.
        assert "Do we open the eval harness" in inbox_md
        # And the section for an empty inbox is also rendered (CTO has none).
        assert "*(empty)*" in inbox_md


# ===========================================================================
# 4. burst_run integration — private channel persists end-to-end
# ===========================================================================

class TestBurstRunIntegration:
    """`burst_run` must write the private channel when role_states is
    passed, regardless of whether artefacts are also supplied."""

    def test_private_channel_written_alongside_artefacts(self, tmp_path):
        """The methodologically important case: a full run has BOTH
        public artefacts (Phase 2 output) AND private state (Phase 1
        snapshot). Both should land in the run folder, not one or the
        other."""
        p = _persist()
        states = _persist_dump(_sample_role_states())
        artefacts = {
            "artefacts": [
                {
                    "role": "CEO", "company": "Test", "industry_context": "Dynamic",
                    "product_type": "Novel", "title": "CEO Strategy",
                    "key_challenges": ["c1"], "main_decisions": ["d1"],
                    "key_tensions": ["t1"], "body": "CEO public artefact body",
                },
            ],
        }
        run_folder = p.burst_run(
            out_dir=tmp_path,
            company="Test", industry_context="Dynamic", product_type="Novel",
            artefacts=artefacts,
            role_states=states,
            write_json=False,
        )
        # Public artefact present.
        assert (run_folder / "02_strategy_documents" / "CEO_strategy.md").exists()
        # Private channel present too.
        assert (run_folder / "06_private_channel" / "CEO_scratchpad.md").exists()
        assert (run_folder / "06_private_channel" / "CEO_draft.md").exists()

    def test_private_channel_skipped_when_no_role_states(self, tmp_path):
        """If role_states isn't supplied (e.g. a non-CONCURRENT run),
        we don't create an empty 06_private_channel/ folder."""
        p = _persist()
        run_folder = p.burst_run(
            out_dir=tmp_path,
            company="Test", industry_context="Dynamic", product_type="Novel",
            artefacts=None,
            role_states=None,
            write_json=False,
        )
        assert not (run_folder / "06_private_channel").exists()

    def test_meta_records_private_channel_was_captured(self, tmp_path):
        p = _persist()
        states = _persist_dump(_sample_role_states())
        run_folder = p.burst_run(
            out_dir=tmp_path,
            company="Test", industry_context="Dynamic", product_type="Novel",
            role_states=states,
            write_json=False,
        )
        meta = json.loads((run_folder / "00_meta.json").read_text())
        assert meta["phases_captured"]["private_channel"] is True


# ===========================================================================
# Helpers
# ===========================================================================

def _persist_dump(role_states: dict) -> dict:
    """Convert {role: _StubRoleState} → {role: dict} the way
    `_snapshot_private_channel` does at runtime."""
    return {r: rs.model_dump(mode="json") for r, rs in role_states.items()}
