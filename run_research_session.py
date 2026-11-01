"""Top-level driver for one full research session.

This is the file you run to produce one simulated meeting and debrief. It sets up
the team of agents (language models given a name, a role and instructions), runs
each stage in order and saves the records.

A *session* = one (company, industry_context, product_type) scenario
(the setting of a run) run end-to-end. It produces FOUR research data streams:

  1. DeliberationLog          (data_capture.DeliberationLog)
       — every inter-agent utterance from the TMT (top management team: the six
         simulated executives) discussion, with
         author, addressee, kind, and order preserved.

  2. ArtefactBundle           (roles.artefact_schemas.ArtefactBundle)
       — six per-role strategic documents (CEO company strategy,
         CTO tech strategy, COO operations plan, CMO marketing brief,
         Product Strategist product memo, Product Designer design doc).

  3. ObservationSummary       (roles.researcher_schemas.ObservationSummary)
       — the qualitative researcher's (the researcher agent: the seventh agent, which
         watches and questions the team) structured field notes after
         silently observing the deliberation (the team's discussion) + reading
         the artefacts (the strategy documents above).

  4. DebriefingTranscript     (orchestrator.panel_debriefing.DebriefingTranscript)
       — the panel debriefing (the researcher agent questioning the six roles
         together) exchange-by-exchange (one question and the replies to it),
         with cross-talk (a role joining in after a first reply)
         markers and forbidden-vocab violation count (uses of words the
         researcher agent must not write unless quoting a panelist).

This entrypoint (the program's starting point) runs one session. A batch runner,
which will start many runs in one go, is planned (see `ROADMAP.md`).

Design
------
- The runner is provider-agnostic (it works with any provider, the company or
  service that supplies a model): it uses the existing TMT system
  (`TMTSystemWithA2A`) and the new orchestrator modules (the code that runs
  each stage), all of which
  honour `TMT_PROVIDER` (the setting that chooses the provider) / per-call `model` overrides.
- The observer (the researcher agent when it consolidates what it saw into one
  summary) is pinned (always set) to Gemini Pro, a Google model (see `providers.get_observer_model`)
  regardless of which provider ran the TMT; field notes must be
  produced by a stable model for cross-provider comparability.
- All four data streams are returned in a single Pydantic model (a record template, not
  a language model; Pydantic is a Python tool that checks records against templates) so
  the caller can JSON-dump (save as plain text with named fields) the entire dataset
  for one replicate.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

try:
    from .agent import TMTSystemWithA2A
    from .data_capture import DeliberationEvent, DeliberationLog
    from .orchestrator.artefact_collection import collect_role_artefacts
    from .orchestrator.deliberation import DeliberationConfig
    from .orchestrator.llm_retry import safe_run_with_capture
    from .orchestrator.role_memory import build_researcher_memory, build_role_memory
    from .orchestrator.panel_debriefing import (
        DEFAULT_RESEARCH_QUESTION,
        DebriefingTranscript,
        run_panel_debriefing,
    )
    from .providers import OBSERVER_PROVIDER, get_model, get_observer_model, snapshot_role_model_ids
    from .roles.artefact_schemas import ArtefactBundle, ArtefactRole
    from .roles.qualitative_researcher_agent import create_observer_agent
    from .roles.researcher_schemas import ObservationSummary
    from .studies import StudyConfig, load_study, DEFAULT_STUDY_SLUG
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from agent import TMTSystemWithA2A  # type: ignore[no-redef]
    from data_capture import DeliberationEvent, DeliberationLog  # type: ignore[no-redef]
    from orchestrator.artefact_collection import collect_role_artefacts  # type: ignore[no-redef]
    from orchestrator.deliberation import DeliberationConfig  # type: ignore[no-redef]
    from orchestrator.llm_retry import safe_run_with_capture  # type: ignore[no-redef]
    from orchestrator.role_memory import (  # type: ignore[no-redef]
        build_researcher_memory,
        build_role_memory,
    )
    from orchestrator.panel_debriefing import (  # type: ignore[no-redef]
        DEFAULT_RESEARCH_QUESTION,
        DebriefingTranscript,
        run_panel_debriefing,
    )
    from providers import OBSERVER_PROVIDER, get_model, get_observer_model, snapshot_role_model_ids  # type: ignore[no-redef]
    from roles.artefact_schemas import ArtefactBundle, ArtefactRole  # type: ignore[no-redef]
    from roles.qualitative_researcher_agent import create_observer_agent  # type: ignore[no-redef]
    from studies import StudyConfig, load_study, DEFAULT_STUDY_SLUG  # type: ignore[no-redef]
    from roles.researcher_schemas import ObservationSummary  # type: ignore[no-redef]

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Failure reporting
# ---------------------------------------------------------------------------

async def _run_observer(
    runner: RunnerFn, observer: Any, prompt: str, errors: list[str],
) -> Any:
    """Run the Phase 3 observer, retrying transient errors.

    Phases are the numbered stages of a run: 1 deliberation, 2 strategy
    documents, 3 observation summary, 4 debrief. Retrying means sending a failed
    call again after a transient (temporary) error.

    Phase 4 cannot run without the observer's summary, so one rate-limit
    error (a provider's cap on how much a customer may send per minute) here
    would otherwise lose the debrief. Only the first line of a
    failure goes into `errors`, because they are saved in `00_meta.json`
    (the run's summary file) and the traceback (the program's report of where it
    failed) carries local paths.
    """
    raw, error_text = await safe_run_with_capture(
        runner, observer, prompt, provider="observer",
    )
    if error_text is not None:
        errors.append(f"observation_failed: {error_text.splitlines()[0]}")
        log.error("Observation failed: %s", error_text)
    return raw


def _code_commit() -> Optional[str]:
    """The checked-out commit (one saved change in the project's history, naming
    the exact code version), marked if the tree (the project's files) has changes.
    None outside git (the tool that keeps that history)."""
    root = Path(__file__).resolve().parent
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        changed = subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return f"{commit}-modified" if changed else commit


def _active_phase_handlers(study: Optional[Any], run_judges: bool) -> list:
    """The extra phases this run should attempt.

    Registering the judging phase makes it available; `--judge` (a flag: an
    option added to the command) asks for
    it. Judges (models that score a finished run) score a rubric (a scoring guide
    saying what to rate and how), so they stay out of a default run.
    """
    handlers = list(study.extra_phases or []) if study is not None else []
    if not run_judges:
        return [h for h in handlers if getattr(h, "name", None) != "construct_judging"]
    if study is not None and study.judgment_rubric is not None:
        # If `--judge` was passed but no construct-judging handler (the code for the
        # judges' phase) is
        # already registered, inject the default. Prevents the legacy
        # CLI (command-line interface: using a program by typing commands) flag
        # from silently doing nothing on a study (a folder under `studies/`
        # supplying the research question, decision task and debrief topics) that has a
        # rubric but no extra_phases entry.
        if not any(getattr(h, "name", None) == "construct_judging" for h in handlers):
            try:
                from .orchestrator.construct_judging import ConstructJudgingPhase
            except (ImportError, ValueError):  # pragma: no cover
                from orchestrator.construct_judging import ConstructJudgingPhase  # type: ignore[no-redef]
            handlers.append(ConstructJudgingPhase())
    return handlers


def _lost_panel_answers(transcript: Optional[DebriefingTranscript]) -> list[str]:
    """Name each panel answer lost to a failed call, e.g. 'exchange 3: CTO'."""
    if transcript is None:
        return []
    return [
        f"exchange {i}: {role}"
        for i, exchange in enumerate(transcript.exchanges, 1)
        for role in exchange.lost_roles
    ]


def _missing_artefact_roles(
    expected_roles: list[str], artefacts: Optional[ArtefactBundle],
) -> list[str]:
    """Roles with no strategy document. Phase 2 skips a role that fails."""
    written = {a.role for a in artefacts.artefacts} if artefacts else set()
    return [role for role in expected_roles if role not in written]


def _exit_code(errors: list[str]) -> int:
    """Process exit code: 1 if anything in the run failed."""
    return 1 if errors else 0


# ---------------------------------------------------------------------------
# Session-key normalisation
# ---------------------------------------------------------------------------
#
# Each ADK (Agent Development Kit: Google's ready-made software for building
# agents) `LlmAgent` (ADK's agent type) instance is bound to one logical persona — the CEO,
# the researcher, etc. — but the pipeline builds several *shells* per
# persona (e.g. the CEO's deliberation agent, the CEO's artefact agent;
# the researcher's observer agent, the researcher's debriefer agent).
# These shells exist because ADK requires `output_schema` (a template of the
# fields a reply must hold) at agent
# construction and each shell needs a different output type. A persona's
# shells are filed under one key:
#
#   CEO / CEO_Concurrent / CEO_Artefact                       → role_CEO
#   CTO / CTO_Concurrent / CTO_Artefact                       → role_CTO
#   COO / COO_Concurrent / COO_Artefact                       → role_COO
#   CMO / CMO_Concurrent / CMO_Artefact                       → role_CMO
#   Product_Strategist / *_Concurrent / *_Artefact            → role_Product_Strategist
#   Product_Designer   / *_Concurrent / *_Artefact            → role_Product_Designer
#   QualitativeResearcher_Observer / QualitativeResearcher_Debriefer
#                                                             → researcher
#   <anything else>                                           → <verbatim>
#
# These only name sessions (in ADK, a session is a stored conversation re-sent to
# the model with each new prompt, unlike the research session above). Each model
# call (one prompt, the text sent to a model, and one reply back) has its own,
# and what an agent
# remembers goes in its prompt (`orchestrator/role_memory.py`).

_ROLE_NAMES: tuple[str, ...] = (
    "CEO", "CTO", "COO", "CMO", "Product_Strategist", "Product_Designer",
)


def _session_key_for(agent_name: str) -> str:
    """Return the name a persona's ADK sessions are filed under.

    Multi-shell personas (e.g. the CTO's deliberation agent and the
    CTO's artefact agent) share a key. It only names sessions: each
    call has its own, so nothing carries over between calls.

    Unknown agent names pass through verbatim.
    """
    if agent_name.startswith("QualitativeResearcher_"):
        return "researcher"
    for role in _ROLE_NAMES:
        if agent_name == role:
            return f"role_{role}"
        # `<role>_<suffix>` — e.g. `CEO_Concurrent`, `CEO_Artefact`.
        # Match the longest role prefix first by iterating in
        # declaration order (Product_Strategist / Product_Designer are
        # already longer than any bare role, so prefix collisions are
        # impossible).
        if agent_name.startswith(role + "_"):
            return f"role_{role}"
    return agent_name


# ---------------------------------------------------------------------------
# Private channel snapshot (each role's notes, draft and inbox, hidden from other roles)
# ---------------------------------------------------------------------------

def _deliberation_failures(system: Any) -> list[str]:
    """Failed model calls during deliberation, as entries for the run's errors."""
    shared = getattr(system, "_last_concurrent_shared_state", None)
    failures = getattr(shared, "llm_failures", None)
    if not failures:
        return []
    stopped = [
        role for role, state in shared.role_states.items()
        if state.finished_reason == "llm_failures"
    ]
    entries = [f"deliberation_model_calls_failed: {len(failures)}"]
    if stopped:
        entries.append(f"deliberation_roles_stopped: {', '.join(stopped)}")
    return entries


def _snapshot_private_channel(shared_state: Any) -> Optional[dict[str, Any]]:
    """Snapshot the per-role private state from a concurrent-mode SharedState.

    Concurrent mode is the default deliberation mode, in which all six roles act
    at once. SharedState is its record of the discussion.

    Returns a dict keyed by role with the fields needed by the
    sub-dimensional measurement layer (which scores narrow items within a rubric,
    by counting words from fixed lists):

        {
            "CEO": {
                "scratchpad": ["note 1", "note 2", ...],
                "draft": "the latest DRAFT text",
                "inbox": [
                    {
                        "id": "...", "sender": "CTO", "recipient": "CEO",
                        "kind": "ASK", "text": "...", "visibility": "public",
                        ...
                    },
                ],
                "action_count": 17,
                "done": True,
                "finished_reason": "DONE_action",
            },
            ...
        }

    Returns None if no SharedState was captured (deliberation didn't
    run in CONCURRENT mode, or it crashed before producing one).
    """
    if shared_state is None:
        return None
    role_states = getattr(shared_state, "role_states", None)
    if not role_states:
        return None
    dump: dict[str, Any] = {}
    for role, rs in role_states.items():
        # `rs` is a RoleState (pydantic). Convert to dict so the
        # private_state field on ResearchSessionOutputs stays
        # serialisable without importing the orchestrator's
        # internal types.
        try:
            dump[role] = rs.model_dump(mode="json")
        except Exception:  # noqa: BLE001  (best-effort dump)
            dump[role] = {
                "scratchpad": list(getattr(rs, "scratchpad", []) or []),
                "draft": getattr(rs, "draft", "") or "",
                "inbox": [],
                "action_count": getattr(rs, "action_count", 0),
                "done": getattr(rs, "done", False),
                "finished_reason": getattr(rs, "finished_reason", ""),
            }
    return dump


# ---------------------------------------------------------------------------
# Output container
# ---------------------------------------------------------------------------

class ResearchSessionOutputs(BaseModel):
    """All data streams from one research session.

    Streams 1-4 are produced by every run. Additional streams (Phase
    5+) come from `PhaseHandler` instances (code a study adds for an extra
    stage) registered in
    `StudyConfig.extra_phases`. Each handler's result is stored in
    `extra_phase_results` keyed by `handler.name`. The framework
    (the shared software in this repository) has a
    default rubric-anchored construct-judging handler, which is one such
    extra phase; future studies can register others without touching
    framework code.
    """

    company: str
    industry_context: str
    product_type: str
    research_question: str
    started_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    finished_at: Optional[str] = None

    # Stream 1
    deliberation_log: Optional[DeliberationLog] = None

    # Stream 2
    artefacts: Optional[ArtefactBundle] = None

    # Stream 3
    observation_summary: Optional[ObservationSummary] = None

    # Stream 4
    debriefing_transcript: Optional[DebriefingTranscript] = None

    # Streams 5+ — outputs of `PhaseHandler` instances registered in
    # `study.extra_phases`. Keys are handler `name` values (e.g.
    # `"construct_judging"`); values are whatever the handler's
    # `run()` returned. The framework treats each value as opaque
    # and hands it back to the handler at persistence time.
    extra_phase_results: dict[str, Any] = Field(default_factory=dict)

    # Field notes from `researcher_stream` — passed through to
    # `PhaseHandler.run()` via this attribute so handlers don't need
    # a separate parameter for them.
    researcher_stream_field_notes: Optional[list[str]] = None

    # Private channel — populated from the concurrent-mode SharedState
    # after Phase 1. Dict shape: `{role: {scratchpad: [str], draft: str,
    # inbox: [{...}], action_count: int, done: bool, finished_reason: str}}`.
    # Carries the firm's internal deliberation state (scratchpads,
    # working drafts, inbox messages) which is NOT part of the public
    # transcript the LLM (large language model: a program trained on vast amounts
    # of text to write likely continuations) judges see. Used by the sub-dimensional
    # measurement layer to score the private channel separately from
    # the public channel. None when the deliberation didn't run in
    # CONCURRENT mode (no SharedState to dump from).
    private_state: Optional[dict[str, Any]] = None

    # Researcher channel — the FieldNoter's running prose notes,
    # produced during Phase 1 by a researcher-role agent. Not the
    # firm's commitment; the researcher's interpretation. Used by
    # the sub-dimensional measurement layer as a third channel
    # alongside public and private. None / [] when no field notes
    # were captured.
    field_notes: Optional[list[str]] = None

    # RagSession instance when --rag was set (RAG, retrieval-augmented generation:
    # searching a document collection and adding the passages found to a model's
    # prompt). Carries the corpus (document collection)
    # resource name, retrieval log (record of the searches), and per-document SHAs
    # (SHA-256 hashes: short fingerprints computed from a file's contents). Persisted
    # to `07_rag/` and to the manifest's (`manifest.json`, a file listing what
    # produced the run) `rag_config` field by the
    # CLI's burst_run path. None for no-RAG runs.
    rag_session: Optional[Any] = None

    # Tokens (small pieces of text, often about three-quarters of a word, that
    # models read and write and providers charge by) per model call, the question the
    # team was asked, and the
    # system itself, which the CLI's manifest reads. Not part of the record.
    usage_log: Optional[Any] = Field(None, exclude=True)
    strategic_question: str = ""
    system: Optional[Any] = Field(None, exclude=True)

    # Diagnostics
    errors: list[str] = Field(default_factory=list)

    # Pydantic v2: allow arbitrary types (for phase results which are
    # separate Pydantic models imported lazily by their handlers).
    model_config = {"arbitrary_types_allowed": True}

    # ----- Back-compat alias (a second name, kept so older code still works) for the
    # headline construct-judging
    # result. Old callers expected `outputs.construct_judgment`; new
    # callers should use `outputs.extra_phase_results["construct_judging"]`.
    # The alias is read-only — handlers always write into the dict.
    @property
    def construct_judgment(self) -> Optional[Any]:
        """Convenience accessor for the default construct-judging
        handler's result. Equivalent to
        `self.extra_phase_results.get("construct_judging")`."""
        return self.extra_phase_results.get("construct_judging")

    def to_json_files(self, out_dir: Path) -> dict[str, Path]:
        """Persist each stream as its own JSON file under `out_dir`.

        Returns a map of stream name → file path so the simulation
        runner can index them in the Excel results.
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = f"{self.company}_{self.industry_context}_{self.product_type}"
        paths: dict[str, Path] = {}

        def _dump(name: str, model: Optional[BaseModel]) -> None:
            if model is None:
                return
            p = out_dir / f"{slug}_{name}.json"
            p.write_text(model.model_dump_json(indent=2))
            paths[name] = p

        _dump("deliberation_log", self.deliberation_log)
        _dump("artefacts", self.artefacts)
        _dump("observation_summary", self.observation_summary)
        _dump("debriefing_transcript", self.debriefing_transcript)

        # Top-level pointer for convenience.
        index = out_dir / f"{slug}_session.json"
        index.write_text(self.model_dump_json(indent=2))
        paths["session"] = index
        return paths


# ---------------------------------------------------------------------------
# Per-agent runner factories
# ---------------------------------------------------------------------------

# A `RunnerFn` is an async callable (a function that can wait for a reply while
# others run): `await fn(agent=..., prompt=...)`
# that runs the agent against the prompt and returns its structured /
# textual output. The orchestrator modules accept this abstraction so
# tests (small automatic checks of the code) can inject a stub (a simple stand-in
# giving set replies, so tests run free) and production can wrap ADK's Runner
# (the part that hands a prompt to an agent and collects the reply).
RunnerFn = Callable[..., Awaitable]


def _build_default_runner(system: TMTSystemWithA2A) -> RunnerFn:
    """Wrap ADK `Runner` into a flat `(agent, prompt) -> output` call.

    Under ADK each `Runner` binds to exactly one agent at
    construction time, so we instantiate a fresh Runner per call. The
    runner is connected to `system.session_service`; each call creates
    its own empty session.

    The return value is the concatenated text from every event in the
    stream. For agents with `output_schema` set the LLM emits a single
    JSON object as the text payload; the orchestrator coerces that via
    Pydantic. Plain-text agents return free-form text.
    """
    from google.adk.runners import Runner  # local import, ADK is heavy
    from google.genai import types  # local import — see agent.py note

    # One empty session per call. A shared session re-sends every earlier
    # prompt on every call, and each prompt already carries what the agent
    # needs (`orchestrator.role_memory`), so by the end of a long debrief a
    # call carried over ten times the text it needed.
    call_counts: dict[str, int] = {}
    usage_log = getattr(system, "usage_log", None)

    async def _new_session_id(agent_name: str) -> str:
        key = _session_key_for(agent_name)
        call_counts[key] = call_counts.get(key, 0) + 1
        sess_id = f"{system.base_session_id}_{key}_{call_counts[key]}"
        await system.session_service.create_session(
            app_name="tmt_research_session",
            user_id="researcher",
            session_id=sess_id,
        )
        return sess_id

    # Lazy import — keeps the orchestrator dependency optional for the
    # CLI's --help path and matches the script-style import fallback
    # convention used elsewhere in this module.
    try:
        from orchestrator.rate_limit import acquire_for_call
    except (ImportError, ValueError):  # pragma: no cover
        from .orchestrator.rate_limit import acquire_for_call  # type: ignore[no-redef]

    # Per-call wall-clock (real elapsed time) timeout (giving up on a model call
    # after waiting too long). Mirrors `agent.py:_run_one_agent`.
    # The Meta-2032 cell post-mortem (review after a run) caught a single Vertex AI
    # (Google's paid cloud service offering models) HTTP (web)
    # request hanging indefinitely without raising; `asyncio.wait_for`
    # converts the hang into a `TimeoutError`, which downstream retry
    # logic in `orchestrator/llm_retry.py` and `agent._parse_retry_
    # delay` treats as transient. Override via `TMT_LLM_CALL_TIMEOUT_S`
    # env var (environment variable: a named setting held outside the code) if a
    # particular run needs a longer or shorter ceiling.
    _LLM_CALL_TIMEOUT_S = float(os.environ.get(
        "TMT_LLM_CALL_TIMEOUT_S", "180"
    ))

    async def _run(*, agent, prompt):
        runner = Runner(
            agent=agent,
            app_name="tmt_research_session",
            session_service=system.session_service,
        )
        session_id = await _new_session_id(agent.name)
        new_message = types.Content(
            role="user",
            parts=[types.Part(text=prompt)],
        )
        # Throttle against the provider's TPM/RPM (tokens per minute and requests
        # per minute, the two usual rate limits) bucket (the allowance left for
        # now) before issuing
        # the call. No-op (it does nothing) for ollama (software that runs models
        # on your own computer) / unknown specs / providers without
        # a rate-limit config. See `orchestrator/rate_limit.py` for the
        # rationale (storm prevention for tier-limited providers).
        # `getattr` so the test seam's stub agents (which only carry
        # `.name`) don't blow up here.
        await acquire_for_call(getattr(agent, "model", None), prompt)

        async def _consume_runner() -> str:
            text_parts: list[str] = []
            async for event in runner.run_async(
                user_id="researcher",
                session_id=session_id,
                new_message=new_message,
            ):
                if usage_log is not None:
                    usage_log.record(agent, getattr(event, "usage_metadata", None))
                content = getattr(event, "content", None)
                if content is None or not hasattr(content, "parts"):
                    continue
                for part in content.parts or []:
                    t = getattr(part, "text", None)
                    if t:
                        text_parts.append(t)
            return "\n".join(text_parts).strip()

        return await asyncio.wait_for(
            _consume_runner(), timeout=_LLM_CALL_TIMEOUT_S,
        )

    # Expose these so callers (tests, the replay tools, which run one later stage
    # again from a saved run) can see what ran.
    _run.call_counts = call_counts  # type: ignore[attr-defined]
    _run.usage_log = usage_log  # type: ignore[attr-defined]
    return _run


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

async def run_research_session(
    *,
    company: str,
    industry_context: str = "Dynamic",
    product_type: str = "Novel",
    current_year: int = 2030,
    research_question: Optional[str] = None,
    product_description: Optional[str] = None,
    strategic_question: Optional[str] = None,
    max_debriefing_exchanges: int = 60,
    runner_fn: Optional[RunnerFn] = None,
    deliberation_config: Optional[DeliberationConfig] = None,
    study: Optional[StudyConfig] = None,
    run_judges: bool = False,
    use_rag: bool = False,
    on_phase_complete: Optional[Callable[["ResearchSessionOutputs"], None]] = None,
) -> ResearchSessionOutputs:
    """Run one full research session and return all four data streams.

    Args:
        company: Firm under simulation.
        industry_context: 'Dynamic' or 'Stable'.
        product_type: 'Novel' or 'Incremental'.
        current_year: Year for the scenario context.
        research_question: Override the default research question
            wording from the active study config.
        product_description: Free-form product framing for the
            deliberation. Defaults are set per product_type.
        strategic_question: The decision the TMT is asked to make.
            Defaults to the question template defined by the active
            study's `strategic_question_template`.
        max_debriefing_exchanges: Safety ceiling for the debriefing.
        runner_fn: Override the per-agent runner (for tests).
        on_phase_complete: Called with the outputs so far after each phase
            and each debrief exchange, so a late crash keeps earlier work.

    Returns:
        A `ResearchSessionOutputs` containing the four data streams,
        plus any errors encountered.
    """
    # Resolve the study. Explicit `study` wins; otherwise load the
    # framework's default (currently "openness_maneuvering"). All
    # subsequent researcher framing is driven by this config.
    if study is None:
        study = load_study(DEFAULT_STUDY_SLUG)

    # Effective research question for the transcript metadata + the
    # legacy `research_question` field on ResearchSessionOutputs.
    effective_rq = research_question or study.research_question

    out = ResearchSessionOutputs(
        company=company,
        industry_context=industry_context,
        product_type=product_type,
        research_question=effective_rq,
    )

    # Resolve the RAG session. None when `use_rag=False`, the study
    # has no `rag_corpus_loader`, or the loader returns None for this
    # company. The orchestrators handle a None session transparently
    # (every retrieve_for_role short-circuits).
    rag_session = None
    if use_rag:
        try:
            from .rag.runtime import build_rag_session_for_company
        except (ImportError, ValueError):  # pragma: no cover  (script-style)
            from rag.runtime import build_rag_session_for_company  # type: ignore[no-redef]
        rag_session = build_rag_session_for_company(study=study, company=company)
        if rag_session is None:
            # A grounded run (one with --rag, in which roles receive and cite
            # passages) that quietly goes ungrounded costs a full run
            # and yields the wrong condition, so stop before spending.
            raise RuntimeError(
                f"--rag was set but no corpus could be opened for {company} under "
                f"study {study.slug}. Check RAG_LOCATION and that the corpus exists "
                "(python -m rag.corpus_build --list)."
            )
        out.rag_session = rag_session

    log.info(
        "research_session.start company=%s industry=%s product=%s year=%s study=%s rag=%s",
        company, industry_context, product_type, current_year, study.slug,
        bool(rag_session and rag_session.enabled),
    )

    # ----- Phase 0: build the TMT system + the runner ----------------
    system = TMTSystemWithA2A(
        company=company,
        current_year=current_year,
        industry_context=industry_context,
        product_type=product_type,
    )
    runner = runner_fn or _build_default_runner(system)
    usage_log = system.usage_log
    out.usage_log = usage_log
    out.system = system

    def _phase_done() -> None:
        """Save what the run has so far, so a late crash keeps earlier work."""
        if on_phase_complete is None:
            return
        try:
            on_phase_complete(out)
        except Exception:  # noqa: BLE001
            log.exception("Could not save the run after this step")

    # Build the live-ethnographer: every public deliberation event and
    # every authored artefact is fed to the stream, which periodically
    # invokes the FieldNoter (the researcher agent during Phases 1 and 2) to record
    # a short field note. The notes then
    # go to the Observer and the Debriefer (the researcher agent in Phase 4), so the
    # Observer's final
    # ObservationSummary call becomes a consolidation rather than a cold
    # first read.
    try:
        from .roles.qualitative_researcher_agent import create_field_noter_agent
        from .orchestrator.researcher_stream import ResearcherStream
    except (ImportError, ValueError):  # pragma: no cover  (script-style)
        from roles.qualitative_researcher_agent import create_field_noter_agent  # type: ignore[no-redef]
        from orchestrator.researcher_stream import ResearcherStream  # type: ignore[no-redef]
    field_noter = create_field_noter_agent(
        company=company,
        current_year=current_year,
        industry_context=industry_context,
        product_type=product_type,
        study=study,
    )
    researcher_stream = ResearcherStream(
        run_agent=runner,
        field_noter_agent=field_noter,
        synth_every=10,
    )
    log.info("research_session.phase0_complete system_built field_noter_ready")

    # ----- Phase 1: deliberation + structured log -------------------
    #
    # NOTE: `product_description` is deliberately left at None by default
    # so the TMT *first* decides what to build. Pre-filling this field
    # with a concrete product spec (e.g. "Next-generation multimodal AI
    # model with advanced reasoning capabilities") turned the
    # deliberation into a release-strategy meeting — the WHAT was
    # already decided, the team only argued about HOW. Leaving it None
    # forces the team to surface candidate product directions, evaluate
    # them, and converge on one before deliberating on
    # development/governance/release.
    #
    # A caller who deliberately wants a controlled experiment with a
    # fixed product can still pass `product_description=...`.
    if strategic_question is None:
        # `product_type` is a scenario constraint (Novel = novel
        # product direction; Enhancement = enhancement of the existing
        # pipeline). The team still has to choose the specific direction.
        if product_type.lower().startswith("nov") or product_type.lower().startswith("break"):
            direction_hint = (
                "a novel AI product direction — something the firm "
                "does not already offer"
            )
        else:
            direction_hint = (
                "an enhancement of the firm's existing AI offering"
            )

        # Prefer the study's template if it specifies one; otherwise
        # fall back to the framework's built-in default. The template
        # may reference {product_type} and {direction_hint}.
        if study.strategic_question_template:
            try:
                strategic_question = study.strategic_question_template.format(
                    product_type=product_type,
                    direction_hint=direction_hint,
                )
            except (KeyError, IndexError):
                # Template references a placeholder we don't supply;
                # fall back to literal-format.
                strategic_question = study.strategic_question_template
        else:
            strategic_question = (
                "What should we, as a leadership team, "
                "develop and bring to market next? "
                f"The scope is {direction_hint}. "
                "Surface the directions worth considering given our "
                "industry context and firm position, evaluate them, "
                "converge on a recommendation, and then propose how "
                "to take it forward."
            )

    log.info("research_session.phase1_start deliberation")
    out.strategic_question = strategic_question
    usage_log.phase = "phase_1_deliberation"
    try:
        decision = await system.run_strategic_discussion(
            product_description=product_description,
            strategic_question=strategic_question,
            product_type=product_type,
            deliberation_config=deliberation_config,
            researcher_stream=researcher_stream,
            scenario_brief=study.scenario_brief,
            rag_session=rag_session,
        )
        # Build the structured deliberation log from the dicts that
        # `TMTSystemWithA2A.run_strategic_discussion` populated.
        # Each entry is already DeliberationEvent-compatible (see the
        # `_event_to_log_entry` helper in agent.py) — we just need to
        # Pydantic-validate.
        raw_log: list = decision.get("conversation_log", []) or []
        out.deliberation_log = DeliberationLog(
            company=company,
            industry_context=industry_context,
            product_type=product_type,
            events=[DeliberationEvent.model_validate(e) for e in raw_log],
        )
        # Always append the CEO's final synthesis as the closing event
        # so downstream consumers (observer, debriefer) see the headline
        # text without having to parse the stream themselves.
        ceo_final_synthesis = decision.get("ceo_decision", "")
        if ceo_final_synthesis:
            out.deliberation_log.events.append(
                DeliberationEvent(
                    index=len(out.deliberation_log.events),
                    role="CEO",
                    kind="text",
                    text=ceo_final_synthesis,
                    raw_type="FinalSynthesis",
                )
            )
        out.deliberation_log.finished_at = datetime.utcnow().isoformat()
        log.info(
            "research_session.phase1_complete events=%d",
            len(out.deliberation_log.events),
        )
    except Exception as exc:  # noqa: BLE001
        out.errors.append(f"deliberation_failed: {exc}")
        log.exception("Deliberation failed for %s", company)
        out.field_notes = list(researcher_stream.field_notes)
        return out

    # Force-flush the researcher stream at the phase-1 boundary so any
    # tail-end events that didn't reach the synth threshold (the number of events that
    # prompts a note) still
    # produce a closing field note before phase 2 begins.
    await researcher_stream.flush_if_due(force=True)

    # Snapshot the private channel from SharedState. The deliberation
    # populated `system._last_concurrent_shared_state` (when running in
    # CONCURRENT mode) with the per-role scratchpads, working drafts,
    # and inboxes. We dump it now — before Phase 2 — so we have a
    # frozen record of the private state at the deliberation's natural
    # end. Subsequent phases (artefact collection, debriefing) operate
    # on this state but the snapshot here is what gets persisted.
    out.private_state = _snapshot_private_channel(
        getattr(system, "_last_concurrent_shared_state", None)
    )
    out.errors.extend(_deliberation_failures(system))
    out.field_notes = list(researcher_stream.field_notes)
    _phase_done()

    # ----- Phase 2: per-role artefact collection -------------------
    log.info("research_session.phase2_start artefact_collection")
    usage_log.phase = "phase_2_documents"
    try:
        out.artefacts = await collect_role_artefacts(
            role_agents={
                role: system.agents[role]
                for role in (
                    "CEO", "CTO", "COO", "CMO",
                    "Product_Strategist", "Product_Designer",
                )
                if role in system.agents
            },  # type: ignore[arg-type]
            deliberation_log=out.deliberation_log,
            ceo_final_synthesis=ceo_final_synthesis,
            company=company,
            industry_context=industry_context,
            product_type=product_type,
            run_agent=runner,
            researcher_stream=researcher_stream,
            rag_session=rag_session,
            role_states=out.private_state,
        )
        log.info(
            "research_session.phase2_complete artefacts=%d",
            len(out.artefacts.artefacts) if out.artefacts else 0,
        )
        missing_roles = _missing_artefact_roles(
            [
                role for role in (
                    "CEO", "CTO", "COO", "CMO",
                    "Product_Strategist", "Product_Designer",
                )
                if role in system.agents
            ],
            out.artefacts,
        )
        if missing_roles:
            out.errors.append(f"artefacts_missing: {', '.join(missing_roles)}")
    except Exception as exc:  # noqa: BLE001
        out.errors.append(f"artefact_collection_failed: {exc}")
        log.exception("Artefact collection failed for %s", company)

    # Force-flush the researcher stream at the phase-2 boundary so any
    # tail-end artefacts still produce a closing field note before the
    # Observer's consolidation pass.
    await researcher_stream.flush_if_due(force=True)
    out.field_notes = list(researcher_stream.field_notes)
    _phase_done()

    # ----- Phase 3: silent observer → observation summary -----------
    log.info(
        "research_session.phase3_start observation field_notes=%d",
        len(researcher_stream.field_notes),
    )
    usage_log.phase = "phase_3_observation"
    try:
        observer = create_observer_agent(
            company=company,
            current_year=current_year,
            industry_context=industry_context,
            product_type=product_type,
            study=study,
        )
        observer_prompt = _build_observer_prompt(
            company=company,
            industry_context=industry_context,
            product_type=product_type,
            deliberation_log=out.deliberation_log,
            artefacts=out.artefacts,
            concurrent_shared_state=getattr(
                system, "_last_concurrent_shared_state", None
            ),
            field_notes=researcher_stream.field_notes,
        )
        raw = await _run_observer(runner, observer, observer_prompt, out.errors)
        out.observation_summary = _coerce_observation_summary(raw)
        log.info(
            "research_session.phase3_complete observation_summary=%s",
            "ok" if out.observation_summary is not None else "missing",
        )
    except Exception as exc:  # noqa: BLE001
        out.errors.append(f"observation_failed: {exc}")
        log.exception("Observation failed for %s", company)

    if out.observation_summary is None:
        out.errors.append("observation_summary_missing — skipping debriefing")
        out.field_notes = list(researcher_stream.field_notes)
        out.finished_at = datetime.utcnow().isoformat()
        log.warning("research_session.phase4_skipped reason=no_observation")
        return out

    _phase_done()

    # ----- Phase 4: panel debriefing → transcript ------------------
    log.info(
        "research_session.phase4_start debriefing max_exchanges=%d",
        max_debriefing_exchanges,
    )
    usage_log.phase = "phase_4_debrief"

    def _exchange_done(transcript: DebriefingTranscript) -> None:
        out.debriefing_transcript = transcript
        _phase_done()

    discussion = out.deliberation_log.as_plain_transcript()
    try:
        out.debriefing_transcript = await run_panel_debriefing(
            company=company,
            observation_summary=out.observation_summary,
            artefacts=out.artefacts,
            panel_agents={
                role: system.agents[role]
                for role in (
                    "CEO", "CTO", "COO", "CMO",
                    "Product_Strategist", "Product_Designer",
                )
                if role in system.agents
            },
            industry_context=industry_context,
            product_type=product_type,
            research_question=effective_rq,
            max_exchanges=max_debriefing_exchanges,
            run_agent=runner,
            concurrent_shared_state=getattr(
                system, "_last_concurrent_shared_state", None
            ),
            study=study,
            rag_session=rag_session,
            role_memory=build_role_memory(
                list(system.agents), discussion, out.private_state, out.artefacts,
            ),
            researcher_memory=build_researcher_memory(
                discussion, researcher_stream.field_notes, out.artefacts,
            ),
            on_exchange=_exchange_done,
        )
        log.info(
            "research_session.phase4_complete exchanges=%d",
            len(out.debriefing_transcript.exchanges)
            if out.debriefing_transcript else 0,
        )
        if (
            out.debriefing_transcript is not None
            and out.debriefing_transcript.ended_reason == "error"
        ):
            out.errors.append(
                "debriefing_incomplete: researcher turn failed after "
                f"{len(out.debriefing_transcript.exchanges)} exchanges"
            )
        lost_answers = _lost_panel_answers(out.debriefing_transcript)
        if lost_answers:
            out.errors.append(f"panel_answers_lost: {'; '.join(lost_answers)}")
    except Exception as exc:  # noqa: BLE001
        out.errors.append(f"debriefing_failed: {exc}")
        log.exception("Debriefing failed for %s", company)

    # ----- Phase 5+ : study-registered extra phase handlers ----------
    #
    # The framework runs Phases 0-4 unconditionally. Phases 5+ come
    # from `PhaseHandler` instances in `study.extra_phases`. Each
    # handler decides for itself whether to run (`should_run`) and
    # how to persist its output (`persist`, called later by the
    # burst-run layer). The handler's result is stored in
    # `out.extra_phase_results[handler.name]`.
    #
    # The CLI `--judge` flag (legacy) auto-injects the default
    # construct-judging handler if the study didn't register one but
    # has a `judgment_rubric` — so old `--judge` invocations keep
    # working without the study having to opt in explicitly.
    out.researcher_stream_field_notes = list(researcher_stream.field_notes)
    handlers = _active_phase_handlers(study, run_judges)
    usage_log.phase = "extra_phases"

    for handler in handlers:
        name = getattr(handler, "name", type(handler).__name__)
        if not handler.should_run(study=study, outputs=out):
            log.info("research_session.phase_%s_skipped", name)
            continue
        log.info("research_session.phase_%s_start", name)
        try:
            result = await handler.run(
                study=study,
                outputs=out,
                run_agent=runner,
                company=company,
                industry_context=industry_context,
                product_type=product_type,
            )
            out.extra_phase_results[name] = result
            log.info("research_session.phase_%s_complete", name)
        except Exception as exc:  # noqa: BLE001
            out.errors.append(f"phase_{name}_failed: {exc}")
            log.exception("Phase %s failed for %s", name, company)

    # Surface the researcher's running field notes so downstream
    # consumers (e.g. the sub-dimensional measurement layer's
    # researcher channel) can read them.
    try:
        out.field_notes = list(researcher_stream.field_notes)
    except Exception:  # noqa: BLE001  (best-effort)
        out.field_notes = None

    if rag_session is not None:
        failed = sum(1 for record in rag_session.retrieval_log if record.get("error"))
        if failed:
            out.errors.append(
                f"retrievals_failed: {failed} of {len(rag_session.retrieval_log)}"
            )

    out.finished_at = datetime.utcnow().isoformat()
    log.info(
        "research_session.end company=%s errors=%d",
        company, len(out.errors),
    )
    return out


# ---------------------------------------------------------------------------
# Observer prompt + coercion
# ---------------------------------------------------------------------------

def _build_observer_prompt(
    *,
    company: str,
    industry_context: str,
    product_type: str,
    deliberation_log: DeliberationLog,
    artefacts: Optional[ArtefactBundle],
    concurrent_shared_state: Optional[object] = None,
    field_notes: Optional[list[str]] = None,
) -> str:
    artefact_block = ""
    if artefacts and artefacts.artefacts:
        sections: list[str] = []
        for a in artefacts.artefacts:
            sections.append(
                f"### {a.role} — {a.title}\n"
                f"Key challenges:\n  - " + "\n  - ".join(a.key_challenges or []) + "\n"
                f"Main decisions:\n  - " + "\n  - ".join(a.main_decisions or []) + "\n"
                f"Key tensions:\n  - " + "\n  - ".join(a.key_tensions or []) + "\n"
                f"---\n{a.body}\n"
            )
        artefact_block = (
            "\nSTRATEGIC ARTEFACTS PRODUCED BY THE PANEL\n"
            "------------------------------------------\n"
            + "\n\n".join(sections)
        )

    # Render per-role scratchpads if the deliberation was concurrent.
    # The researcher has privileged access to these — panellists do not
    # share their private notebooks with each other.
    scratchpad_block = _render_scratchpads_for_researcher(
        concurrent_shared_state
    )

    # When the FieldNoter has been running through phases 1+2, this call is
    # a CONSOLIDATION pass. It gets the full transcript + artefacts +
    # scratchpads, so the structured summary is anchored on ground truth
    # and not just on the researcher's own paraphrases, plus the notes.
    notes_block = ""
    if field_notes:
        notes_block = (
            "\nYOUR RUNNING FIELD NOTES\n"
            "------------------------\n"
            + "\n\n".join(field_notes)
            + "\n"
        )
        task_block = (
            "TASK — CONSOLIDATE YOUR OBSERVATIONS\n"
            "------------------------------------\n"
            "You have been observing this deliberation live and your "
            "running field notes are above. Now "
            "consolidate everything you have seen — the transcript, "
            "the artefacts, the private scratchpads, AND your own "
            "running notes — into a single ObservationSummary JSON "
            "object capturing:\n"
            "  - decisions the TMT made (in their own words),\n"
            "  - components / products / assets discussed (panel's terminology),\n"
            "  - disagreements observed,\n"
            "  - what each role pushed for / pushed back on / was quiet on,\n"
            "  - alternatives considered but not pursued,\n"
            "  - unprompted use of the listed vocabulary by panelists.\n\n"
            "Your prior field notes already capture nuance; the "
            "consolidation tightens them into the structured schema. "
            "Cite panellists' own phrasing verbatim where it sharpens "
            "an observation."
        )
    else:
        task_block = (
            "TASK\n"
            "----\n"
            "Produce a single ObservationSummary JSON object capturing:\n"
            "  - decisions the TMT made (in their own words),\n"
            "  - components / products / assets discussed (panel's terminology),\n"
            "  - disagreements observed,\n"
            "  - what each role pushed for / pushed back on / was quiet on,\n"
            "  - alternatives considered but not pursued,\n"
            "  - unprompted use of the listed vocabulary by panelists.\n\n"
            "When the role agents kept private scratchpads (concurrent "
            "mode), the contents are reproduced above. They reveal what "
            "each role was thinking but did NOT say out loud. Treat them "
            "as ethnographic field-note material: cite verbatim where "
            "helpful; do not paraphrase into your analytical categories."
        )

    return f"""SCENARIO
--------
Firm: {company}
Industry context: {industry_context}
Product type: {product_type}

DELIBERATION TRANSCRIPT (every inter-agent utterance, in order)
---------------------------------------------------------------
{deliberation_log.as_plain_transcript()}
{artefact_block}
{scratchpad_block}
{notes_block}
{task_block}

Return ONLY the JSON object. No prose, no markdown.
"""


def _render_scratchpads_for_researcher(
    concurrent_shared_state: Optional[object],
) -> str:
    """Render private per-role scratchpads + drafts for the researcher.

    Returns an empty string if the deliberation did not produce a
    SharedState (i.e. CONCURRENT mode wasn't used). Otherwise dumps
    every role's notebook + working draft, prefixed with a header that
    makes their privileged provenance (where they came from) explicit.
    """
    if concurrent_shared_state is None:
        return ""
    role_states_attr = getattr(concurrent_shared_state, "role_states", None)
    if role_states_attr is None:
        return ""
    lines: list[str] = [
        "",
        "PRIVATE PER-ROLE SCRATCHPADS (researcher-only access)",
        "------------------------------------------------------",
        "The role agents kept these private notes during the concurrent",
        "deliberation. Other panellists never saw them. The researcher",
        "may use them to triangulate against the public transcript and",
        "to surface things panellists thought but did not say.",
        "",
    ]
    for role, rs in role_states_attr.items():
        scratchpad = getattr(rs, "scratchpad", []) or []
        draft = getattr(rs, "draft", "") or ""
        lines.append(f"### {role}")
        if scratchpad:
            lines.append("Private notes:")
            for n in scratchpad:
                lines.append(f"  - {n}")
        else:
            lines.append("Private notes: (none)")
        if draft:
            lines.append(f"Working draft (length: {len(draft)} chars):")
            lines.append(f"  {draft[:400]}{'...' if len(draft) > 400 else ''}")
        else:
            lines.append("Working draft: (empty)")
        lines.append("")
    return "\n".join(lines)


def _coerce_observation_summary(raw: object) -> Optional[ObservationSummary]:
    if raw is None:
        return None
    if isinstance(raw, ObservationSummary):
        return raw
    if isinstance(raw, dict):
        try:
            return ObservationSummary.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            log.error("ObservationSummary validation failed: %s", exc)
            return None
    if isinstance(raw, str):
        try:
            return ObservationSummary.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001
            log.error("ObservationSummary JSON parse failed: %s", exc)
            return None
    return None


# ---------------------------------------------------------------------------
# CLI smoke (single session, prints to stdout + writes JSON)
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Run one research session.")
    parser.add_argument("--company", default="OpenAI")
    parser.add_argument("--industry-context", default="Dynamic", choices=("Dynamic", "Stable"))
    parser.add_argument("--product-type", default="Novel", choices=("Novel", "Enhancement"))
    parser.add_argument(
        "--out-dir",
        default="./results/runs",
        help=(
            "Parent directory for the per-run output folder. The CLI "
            "creates a markdown-first folder at "
            "`<out-dir>/<run_id>/` with `00_meta.json` + `01_deliberation/` "
            "+ `02_strategy_documents/` + `03_researcher/` + "
            "`04_interview/` + `README.md`. Default `results/runs/`."
        ),
    )
    parser.add_argument("--max-exchanges", type=int, default=20,
                        help="Lower default for the CLI smoke than for production.")
    parser.add_argument(
        "--current-year",
        type=int,
        default=2030,
        help=(
            "Year the scenario is framed in. Threads through to "
            "the role JD prompts and the scenario brief; 2030 keeps "
            "things near-future, push it forward to test how role "
            "agents reason about a more speculative horizon."
        ),
    )
    parser.add_argument(
        "--study",
        default=DEFAULT_STUDY_SLUG,
        help=(
            "Study slug (sub-package under `studies/`). Picks the "
            "research question, theoretical lens, construct-specific "
            "forbidden vocabulary, and scenario brief for this run. "
            "See `studies/<slug>/__init__.py`."
        ),
    )
    parser.add_argument(
        "--no-json",
        action="store_true",
        help=(
            "Skip the per-phase JSON sub-files (interaction_log.json, "
            "transcript.json, etc.). Markdown sub-files are still "
            "written; the top-level 00_meta.json is also still written "
            "so the per-run folder has a stable machine-readable "
            "identity. Use this when you only want the qualitative-"
            "review artefacts and don't need the structured data for "
            "downstream tooling."
        ),
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help=(
            "Run Phase 5 — the optional construct-judge ensemble. Four "
            "LLM judges score the run against the study's rubric, which "
            "adds to the run's cost and time; measure it on your setup. "
            "Requires the "
            "active study to have a `judgment_rubric` set in its "
            "StudyConfig (the `openness_maneuvering` study does)."
        ),
    )
    parser.add_argument(
        "--subdimension-scores",
        action="store_true",
        help=(
            "Compute Method A (anchored dictionary) sub-dimensional "
            "openness scores across three channels (public / private "
            "/ researcher) and 21 sub-dimensions. Writes four CSVs + "
            "a markdown summary to <run_folder>/06_subdimension_scores/. "
            "Pure text scoring; no LLM calls; adds ~1 second of "
            "wall-clock. Independent of --judge."
        ),
    )
    parser.add_argument(
        "--rag",
        action="store_true",
        help=(
            "Retrieval-augmented mode. Resolves the active study's "
            "`rag_corpus_loader` for this company at session start, "
            "threads a RagSession through Phases 1 / 2 / 4 so each "
            "role agent sees ~5 retrieved excerpts from the firm's "
            "Vertex AI RAG corpus before its LLM call. The role's "
            "structured output then carries `citations[]` for any "
            "excerpt it leaned on; the persistence layer renders them "
            "as inline Markdown footnotes throughout the per-run "
            "outputs. Writes 07_rag/ subfolder (corpus manifest + "
            "retrieval log) and the manifest's `rag_config` field. "
            "Requires the active study to have `rag_corpus_loader` "
            "set, and stops with an error if the loader returns None "
            "for this firm."
        ),
    )
    parser.add_argument(
        "--max-actions-per-role",
        type=int,
        default=None,
        help=(
            "Cap each role's actions in the deliberation. With a low "
            "--max-exchanges this makes a short run, which tests the whole "
            "pipeline for a few dollars. Not for data: meta records the caps."
        ),
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "INFO"),
        help=(
            "Logger level: DEBUG / INFO / WARNING / ERROR. INFO emits "
            "one line per phase transition so a live CLI run shows "
            "progress instead of going silent until the end."
        ),
    )
    parser.add_argument(
        "--vertex",
        action="store_true",
        help=(
            "Route Gemini calls through Vertex AI instead of AI Studio. "
            "Use this if you're spending Google Cloud credits (e.g. EDU "
            "grants) rather than an AI Studio key. Requires "
            "GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_LOCATION env vars "
            "and `gcloud auth application-default login`. Non-Gemini "
            "providers (Claude, OpenAI, DeepSeek, Groq, Ollama) are "
            "unaffected; they continue to use their own APIs."
        ),
    )
    parser.add_argument(
        "--vertex-project",
        default=None,
        help=(
            "Override GOOGLE_CLOUD_PROJECT for this run (only honoured "
            "with --vertex). If omitted, the env var must already be set."
        ),
    )
    parser.add_argument(
        "--vertex-location",
        default=None,
        help=(
            "Override GOOGLE_CLOUD_LOCATION for this run (only honoured "
            "with --vertex). If omitted, the env var must already be set. "
            "Typical values: us-central1, europe-west4, asia-northeast1."
        ),
    )
    args = parser.parse_args()

    # Wire a root logging handler. Without this the module-level
    # `log.info(...)` calls go to a null handler and the CLI looks
    # frozen during the deliberation + debriefing phases (which run
    # for many minutes each on real Gemini calls).
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Vertex AI routing for Gemini. The --vertex flag flips the
    # standard GOOGLE_GENAI_USE_VERTEXAI env var and validates that
    # the required project/location are set. Failing fast here beats
    # discovering the misconfiguration 30s into a Phase 1 LLM call.
    if args.vertex:
        try:
            from .providers import enable_vertex, snapshot_vertex_config
        except (ImportError, ValueError):  # pragma: no cover  (script-style)
            from providers import enable_vertex, snapshot_vertex_config  # type: ignore[no-redef]
        enable_vertex(
            project=args.vertex_project,
            location=args.vertex_location,
        )
        vertex_cfg = snapshot_vertex_config()
        log.info(
            "Vertex AI routing enabled: project=%s location=%s",
            vertex_cfg["project"], vertex_cfg["location"],
        )

    # Resolve the study config from the CLI slug (a short name with no spaces, such as
    # `openness_maneuvering`).
    study_config = load_study(args.study)
    log.info("Using study: %s (v%s)", study_config.slug, study_config.version)

    # Markdown-first output (Markdown is plain text with simple marks for headings
    # and lists): burst (split) the phase outputs into a per-run folder
    # with both `.md` (human-readable, always) and `.json` (machine-readable,
    # optional via --no-json) sub-files. The per-run folder is browseable in
    # any file manager or markdown viewer, which matches how the qualitative
    # researcher actually consumes the artefacts.
    try:
        from .analysis.persist_artefacts import _default_run_id, burst_run
        from .analysis.replication_package import capture_from_system, write_manifest
        from .orchestrator.concurrent_mode import ConcurrentConfig
    except (ImportError, ValueError):  # pragma: no cover  (script-style)
        from analysis.persist_artefacts import _default_run_id, burst_run  # type: ignore[no-redef]
        from analysis.replication_package import capture_from_system, write_manifest  # type: ignore[no-redef]
        from orchestrator.concurrent_mode import ConcurrentConfig  # type: ignore[no-redef]

    # Named once, so each save during the run updates the same folder. A
    # folder whose meta says `run_complete: false` stopped early.
    run_id = _default_run_id(args.company, args.industry_context, args.product_type)
    code_commit = _code_commit()

    def _save(session: ResearchSessionOutputs) -> Path:
        return burst_run(
            out_dir=Path(args.out_dir),
            company=args.company,
            industry_context=args.industry_context,
            product_type=args.product_type,
            deliberation_log=(
                session.deliberation_log.model_dump(mode="json")
                if session.deliberation_log is not None else None
            ),
            artefacts=(
                session.artefacts.model_dump(mode="json")
                if session.artefacts is not None else None
            ),
            observation_summary=(
                session.observation_summary.model_dump(mode="json")
                if session.observation_summary is not None else None
            ),
            debriefing_transcript=(
                session.debriefing_transcript.model_dump(mode="json")
                if session.debriefing_transcript is not None else None
            ),
            extra_phase_handlers={
                getattr(h, "name", type(h).__name__): h
                for h in (study_config.extra_phases or [])
            },
            extra_phase_results=session.extra_phase_results,
            role_states=session.private_state,
            research_question=session.research_question,
            run_id=run_id,
            extra_meta={
                "study_slug": study_config.slug,
                "study_version": study_config.version,
                "started_at": session.started_at,
                "finished_at": session.finished_at,
                "run_complete": session.finished_at is not None,
                "errors": session.errors,
                "embedded_observation": study_config.embedded_observation,
                "role_models": snapshot_role_model_ids(),
                "researcher_provider": OBSERVER_PROVIDER,
                "code_commit": code_commit,
                "max_exchanges": args.max_exchanges,
                "max_actions_per_role": args.max_actions_per_role,
            },
            write_json=not args.no_json,
            rag_session=session.rag_session,
            field_notes=session.field_notes,
            usage_log=session.usage_log,
        )

    out = asyncio.run(run_research_session(
        company=args.company,
        industry_context=args.industry_context,
        product_type=args.product_type,
        current_year=args.current_year,
        max_debriefing_exchanges=args.max_exchanges,
        study=study_config,
        run_judges=args.judge,
        use_rag=args.rag,
        deliberation_config=(
            DeliberationConfig(
                concurrent=ConcurrentConfig(max_actions_per_role=args.max_actions_per_role)
            )
            if args.max_actions_per_role is not None else None
        ),
        on_phase_complete=_save,
    ))
    run_folder = _save(out)
    if out.system is not None:
        try:
            write_manifest(
                capture_from_system(
                    out.system,
                    run_id=run_id,
                    started_at=out.started_at,
                    finished_at=out.finished_at,
                    research_question=out.research_question,
                    strategic_question=out.strategic_question,
                    rag_session=out.rag_session,
                    study_slug=study_config.slug,
                    study_version=study_config.version,
                ),
                run_folder,
            )
        except Exception:  # noqa: BLE001
            log.exception("Could not write manifest.json for %s", run_id)

    # Optional: Method A (anchored dictionary: counting words from a fixed list tied to a
    # concept) sub-dimensional scoring.
    # Runs after burst_run so it can write into the freshly-created
    # run folder. Pure text scoring; no LLM calls.
    if args.subdimension_scores:
        try:
            from .analysis.text_measures import score_run as _score_run
        except (ImportError, ValueError):  # pragma: no cover  (script-style)
            from analysis.text_measures import score_run as _score_run  # type: ignore[no-redef]
        scores_dir = _score_run(
            out_dir=run_folder,
            artefacts=(
                out.artefacts.model_dump(mode="json")
                if out.artefacts is not None else None
            ),
            deliberation_log=(
                out.deliberation_log.model_dump(mode="json")
                if out.deliberation_log is not None else None
            ),
            observation_summary=(
                out.observation_summary.model_dump(mode="json")
                if out.observation_summary is not None else None
            ),
            debriefing_transcript=(
                out.debriefing_transcript.model_dump(mode="json")
                if out.debriefing_transcript is not None else None
            ),
            field_notes=out.field_notes,
            private_state=out.private_state,
        )
        print(f"  Sub-dimension scores: {scores_dir}/README.md")

    print(f"Run folder: {run_folder}")
    print(f"  Markdown index: {run_folder}/README.md")
    if out.usage_log is not None and out.usage_log.calls:
        usage = out.usage_log.summary()
        print(
            f"  Tokens: {usage['input_tokens']:,} input ({usage['cached_tokens']:,} cached), "
            f"{usage['output_tokens']:,} output; largest call "
            f"{usage['largest_call_input_tokens']:,}; list cost "
            f"{'unknown' if usage['list_cost_usd'] is None else '$%.2f' % usage['list_cost_usd']}"
        )
    if not args.no_json:
        print(f"  JSON sub-files: included (pass --no-json to skip)")
    if out.errors:
        print("ERRORS:")
        for e in out.errors:
            print(f"  - {e}")
    sys.exit(_exit_code(out.errors))
