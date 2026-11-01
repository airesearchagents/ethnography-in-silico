"""Load a finished run's saved records so a later phase can be tested cheaply.

A run is one complete simulated meeting and debrief, and a phase is one numbered
stage of it. `analysis.researcher_turn_test` and `analysis.replay_debrief` both start
from a run folder instead of paying for a new deliberation (the team's discussion).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Optional

try:
    from ..data_capture import DeliberationLog
    from ..orchestrator.panel_debriefing import DebriefingTranscript
    from ..orchestrator.usage_log import UsageLog
    from ..roles.artefact_schemas import ArtefactBundle, StrategicArtefact
    from ..roles.researcher_schemas import ObservationSummary
    from ..studies import StudyConfig, load_study
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from data_capture import DeliberationLog  # type: ignore[no-redef]
    from orchestrator.panel_debriefing import DebriefingTranscript  # type: ignore[no-redef]
    from orchestrator.usage_log import UsageLog  # type: ignore[no-redef]
    from roles.artefact_schemas import ArtefactBundle, StrategicArtefact  # type: ignore[no-redef]
    from roles.researcher_schemas import ObservationSummary  # type: ignore[no-redef]
    from studies import StudyConfig, load_study  # type: ignore[no-redef]


class SavedRunError(ValueError):
    """The run folder cannot be used for this test. The message says why."""


@dataclass
class SavedRun:
    run_dir: Path
    meta: dict
    study: StudyConfig
    observation_summary: ObservationSummary
    artefacts: Optional[ArtefactBundle]
    transcript: Optional[DebriefingTranscript]
    role_states: dict
    grounded: bool
    deliberation_text: str = ""
    field_notes: List[str] = field(default_factory=list)

    @property
    def company(self) -> str:
        return self.meta["company"]

    @property
    def industry_context(self) -> str:
        return self.meta["industry_context"]

    @property
    def product_type(self) -> str:
        return self.meta["product_type"]

    @property
    def shared_state(self) -> Optional[object]:
        """The shape `_render_scratchpads_for_debriefer` reads, or None."""
        if not self.role_states:
            return None
        return SimpleNamespace(role_states={
            role: SimpleNamespace(
                scratchpad=state.get("scratchpad") or [],
                draft=state.get("draft") or "",
            )
            for role, state in self.role_states.items()
        })


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        raise SavedRunError(
            f"{path} is missing. These tools need the run's JSON files, so "
            "the run cannot have used --no-json."
        ) from None


def load_saved_run(run_dir: Path, *, allow_version_mismatch: bool = False) -> SavedRun:
    """Read a run folder. Raises `SavedRunError` if it cannot be used."""
    run_dir = Path(run_dir)
    meta = _read_json(run_dir / "00_meta.json")
    study = load_study(meta["study_slug"])
    saved_version = meta.get("study_version")
    if saved_version != study.version and not allow_version_mismatch:
        raise SavedRunError(
            f"Run used study version {saved_version}, but the code is at "
            f"{study.version}. Pass allow_version_mismatch to use it anyway."
        )
    summary = ObservationSummary.model_validate(
        _read_json(run_dir / "03_researcher" / "observation_summary.json")
    )
    documents = [
        StrategicArtefact.model_validate(json.loads(path.read_text()))
        for path in sorted((run_dir / "02_strategy_documents").glob("*_strategy.json"))
    ]
    artefacts = ArtefactBundle(
        company=meta["company"],
        industry_context=meta["industry_context"],
        product_type=meta["product_type"],
        artefacts=documents,
    ) if documents else None
    transcript_path = run_dir / "04_interview" / "transcript.json"
    transcript = (
        DebriefingTranscript.model_validate(json.loads(transcript_path.read_text()))
        if transcript_path.exists() else None
    )
    state_path = run_dir / "06_private_channel" / "private_state.json"
    role_states = json.loads(state_path.read_text()) if state_path.exists() else {}
    log_path = run_dir / "01_deliberation" / "interaction_log.json"
    deliberation_text = (
        DeliberationLog.model_validate(json.loads(log_path.read_text())).as_plain_transcript()
        if log_path.exists() else ""
    )
    notes_path = run_dir / "03_researcher" / "field_notes.json"
    field_notes = json.loads(notes_path.read_text()) if notes_path.exists() else []
    return SavedRun(
        run_dir=run_dir,
        meta=meta,
        study=study,
        observation_summary=summary,
        artefacts=artefacts,
        transcript=transcript,
        role_states=role_states,
        grounded=(run_dir / "07_rag").exists(),
        deliberation_text=deliberation_text,
        field_notes=field_notes,
    )


def new_session_runner() -> Any:
    """A runner (the software part that hands a prompt to an agent and collects the
    reply) with its own log of tokens, the small pieces of text providers charge by. Calls do not share memory."""
    from google.adk.sessions import InMemorySessionService  # noqa: PLC0415  (heavy)

    try:
        from ..run_research_session import _build_default_runner
    except (ImportError, ValueError):  # pragma: no cover  (script-style)
        from run_research_session import _build_default_runner  # type: ignore[no-redef]

    return _build_default_runner(SimpleNamespace(
        session_service=InMemorySessionService(),
        base_session_id=f"saved_run_{uuid.uuid4().hex}",
        usage_log=UsageLog(),
    ))


class CallCounter:
    """Counts model calls and characters, as a rough guide to what a test cost."""

    def __init__(self, run_agent: Any) -> None:
        self._run_agent = run_agent
        self.usage_log = getattr(run_agent, "usage_log", None)
        self.calls = 0
        self.prompt_chars = 0
        self.reply_chars = 0

    async def __call__(self, *, agent: Any, prompt: str) -> Any:
        self.calls += 1
        self.prompt_chars += len(prompt)
        reply = await self._run_agent(agent=agent, prompt=prompt)
        self.reply_chars += len(str(reply))
        return reply
