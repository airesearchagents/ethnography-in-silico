"""Live-streaming researcher (the agent, a language model given a role, that watches and
questions the team): feeds deliberation (the team's discussion) + artefact (strategy
document) events to the QualitativeResearcher_FieldNoter (the researcher agent while it
writes notes without intervening) in batches as they happen.

This file gathers what happens during the simulated meeting and, every so often,
hands it to the researcher agent to write a short field note.

Why
---
Earlier behaviour invoked the researcher exactly once, AFTER phase 1
and phase 2 (the first two numbered stages of a run, one complete simulated
meeting and debrief) had completed, with the full transcript pasted into a
single prompt (the text sent to a model to get one reply). That
made the researcher a post-hoc reader of
artefacts rather than an in-room ethnographer.

This module implements the live-ethnography pattern asked for:

  * Every public deliberation event and every role-authored artefact
    is *silently* added to a buffer (a temporary holding list) via
    `observe(text)` — no LLM (large language model) call yet.
  * Every `synth_every` events (default 10) — or when explicitly
    flushed — the buffer is handed to the FieldNoter, which writes a
    short free-form field note. Each call shows it its notes so far.
  * Phase 3's Observer (the researcher agent summing up what it saw)
    receives the notes with the transcript, so its
    job is consolidation rather than a cold first read.
  * Phase 4's Debriefer (the researcher agent questioning the team) receives them too.

Cost shape
----------
For a typical run (e.g. ~100 phase-1 actions, meaning moves by a role, + 6 phase-2 artefacts),
synth_every=10 yields ~10 mid-phase researcher calls. Each prompt is
small (the latest batch of events + a 'write a short note' ask) and
each reply is ~100–150 words. Cheap relative to the deliberation
itself.

Constructor inputs
------------------
* `run_agent` — same callable (a function passed in) the orchestrators (the
  files that run each phase) already accept
  (returns the agent's reply as a string).
* `field_noter_agent` — built once at session start (the start of the run) via
  `roles.create_field_noter_agent(...)`. Its session_id (session: a stored
  conversation held by the agent software) resolves
  to the `researcher` key via `_session_key_for` in
  `run_research_session.py`.
* `synth_every` — flush threshold. 10 is a reasonable default; lower
  values mean more granular notes (and more LLM calls).
* `enabled` — letting the orchestrator turn streaming off without
  changing call sites (e.g. for a regression test, a check that older behaviour still
  works, that needs the old single-shot Observer behaviour).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional

from google.adk.agents import LlmAgent

log = logging.getLogger(__name__)


# Same shape the orchestrators use: `await run_agent(agent=..., prompt=...)`.
RunnerFn = Callable[..., Awaitable]


@dataclass
class ResearcherStream:
    """Live-streaming ethnographer.

    Two operations:
      * `observe(event_text)` — append to the buffer (no LLM call).
      * `flush_if_due(force=False)` — if the buffer has reached
        `synth_every` items (or `force=True` and the buffer is
        non-empty), invoke the FieldNoter with the buffered events
        and clear the buffer. The note text is captured in
        `field_notes` for downstream consolidation.
    """

    run_agent: RunnerFn
    field_noter_agent: LlmAgent
    synth_every: int = 10
    enabled: bool = True

    buffer: List[str] = field(default_factory=list)
    field_notes: List[str] = field(default_factory=list)
    # In-flight flag prevents two role loops (running concurrently)
    # from both passing the threshold check, both clearing the buffer,
    # and both calling the LLM on overlapping batches. The check +
    # assignment is synchronous (no await between them), so this is
    # race-free (two tasks cannot collide here) under asyncio (Python's tool for
    # running tasks side by side).
    _flushing: bool = field(default=False, init=False, repr=False)

    def observe(self, event_text: str) -> None:
        """Silently capture an event. Cheap — no LLM call."""
        if not self.enabled:
            return
        if not event_text:
            return
        self.buffer.append(event_text)

    async def flush_if_due(self, force: bool = False) -> Optional[str]:
        """Invoke the FieldNoter if a synthesis is due.

        Returns the new note text, or `None` if no synthesis fired
        (buffer empty, threshold not reached, currently flushing, or
        `enabled=False`).
        """
        if not self.enabled:
            return None
        if self._flushing:
            # Another role loop is already running a flush; let it
            # absorb this batch on its next call.
            return None
        if not self.buffer:
            return None
        if not force and len(self.buffer) < self.synth_every:
            return None

        # Take the batch + clear synchronously (no await between
        # these two lines, so no race window).
        batch = list(self.buffer)
        self.buffer.clear()
        self._flushing = True
        try:
            prompt = self._render_prompt(batch)
            try:
                note = await self.run_agent(
                    agent=self.field_noter_agent, prompt=prompt,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "researcher_stream.field_note_failed events=%d exc=%s",
                    len(batch), exc,
                )
                return None
            note_text = (note or "").strip() if isinstance(note, str) else str(note).strip()
            if note_text:
                self.field_notes.append(note_text)
            log.info(
                "researcher_stream.field_note batch=%d total_notes=%d",
                len(batch), len(self.field_notes),
            )
            return note_text
        finally:
            self._flushing = False

    # ------------------------------------------------------------------
    # Prompt rendering
    # ------------------------------------------------------------------

    def _render_prompt(self, batch: List[str]) -> str:
        prior_note_block = ""
        if self.field_notes:
            # Model calls (one prompt, one reply) share no session, so this is the FieldNoter's
            # only memory of its own journal.
            prior_note_block = (
                "YOUR NOTES SO FAR\n"
                "-----------------\n"
                + "\n\n".join(f"  > {n}" for n in self.field_notes)
                + "\n\n"
            )
        return (
            "LIVE OBSERVATION — new events since your last note\n"
            "==================================================\n"
            f"{prior_note_block}"
            "Events this batch:\n"
            + "\n".join(f"  - {e}" for e in batch)
            + "\n\nWrite a SHORT field note (under ~150 words) capturing "
              "anything noteworthy about THIS batch — patterns, position "
              "shifts, contested decisions, anything surprising or "
              "puzzling. Quote panel "
              "phrases verbatim when they sharpen the observation. "
              "Stay in your researcher voice. Prose only — no JSON, no "
              "markdown headers."
        )

    # ------------------------------------------------------------------
    # Helpers for downstream consolidation
    # ------------------------------------------------------------------

    def consolidated_notes(self) -> str:
        """Return all field notes concatenated, separated by blank
        lines. Used by the Observer's consolidation prompt at the end
        of phase 2."""
        return "\n\n".join(self.field_notes)


# Convenience formatters so call sites stay clean.

def format_transcript_entry(entry) -> str:
    """Render one transcript entry from a SharedState transcript into
    a one-line observation event the FieldNoter can read."""
    role = getattr(entry, "role", "?")
    kind = getattr(entry, "kind", "?")
    text = (getattr(entry, "text", "") or "").strip().replace("\n", " ")
    if len(text) > 320:
        text = text[:320] + "…"
    addressed_to = getattr(entry, "addressed_to", None)
    addr = f" → {addressed_to}" if addressed_to else ""
    return f"[{role} {kind}{addr}] {text}"


def format_artefact(role: str, artefact) -> str:
    """Render a StrategicArtefact into a multi-line observation event."""
    title = getattr(artefact, "title", "") or ""
    decisions = getattr(artefact, "main_decisions", []) or []
    tensions = getattr(artefact, "key_tensions", []) or []
    challenges = getattr(artefact, "key_challenges", []) or []
    lines = [f"[ARTEFACT {role}] {title}"]
    if challenges:
        lines.append(
            "  key_challenges: "
            + "; ".join(challenges[:3])
            + ("…" if len(challenges) > 3 else "")
        )
    if decisions:
        lines.append(
            "  main_decisions: "
            + "; ".join(decisions[:3])
            + ("…" if len(decisions) > 3 else "")
        )
    if tensions:
        lines.append(
            "  key_tensions: "
            + "; ".join(tensions[:3])
            + ("…" if len(tensions) > 3 else "")
        )
    return "\n".join(lines)
