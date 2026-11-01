"""Burst a run's JSON outputs into a human-browseable folder.

A run is one complete simulated meeting and debrief. JSON is a plain-text format
for records with named fields. This file writes a run's records
into numbered folders, with a readable copy of each, for human researchers to code.

Reads either:
  - A `ResearchSessionOutputs` JSON (full 4-phase run, a phase being a numbered
    stage, from
    `run_research_session.py`), OR
  - A `verify_concurrent.py` log (concurrent deliberation only, that is, the team's
    discussion with all six simulated executives acting at once, and no
    observer/debriefer phases, in which the researcher agent sums up and then
    questions the team).

Produces a per-run folder with the following layout — empty phases
are skipped so the layout shows you exactly what was captured:

    results/runs/<run-id>/
    ├── 00_meta.json              # company, cell (one mix of firm, industry context, product type), mode (how the team takes turns), timing
    ├── 01_deliberation/
    │   ├── interaction_log.json  # raw event stream (structured)
    │   ├── interaction_log.md    # readable transcript
    │   └── role_scratchpads/
    │       ├── CEO_scratchpad.md
    │       ├── CTO_scratchpad.md
    │       └── …                 # one per role (a scratchpad holds its private notes); empty file if no notes
    ├── 02_strategy_documents/
    │   ├── CEO_strategy.md       # human-readable
    │   ├── CEO_strategy.json     # machine-readable (StrategicArtefact)
    │   └── …
    ├── 03_researcher/
    │   ├── observation_summary.json
    │   └── observation_summary.md
    └── 04_interview/
        ├── transcript.json
        └── transcript.md

Each `.md` (Markdown: plain text with simple marks for headings) file is meant for you to read; each `.json` keeps the
original Pydantic-validated (Pydantic: a Python tool that checks records against a
template) structure for downstream analysis.

This module (a Python file with one job) is import-safe (no ADK, Google's Agent
Development Kit for building agents, / google-genai deps, the packages it would
otherwise need); the test suite can exercise it without spinning up the heavy SDKs
(software development kits, a company's toolkits for using its service).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .citation_rendering import CitationCounter
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from analysis.citation_rendering import CitationCounter  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def burst_run(
    *,
    out_dir: Path,
    company: str,
    industry_context: str,
    product_type: str,
    deliberation_log: Optional[dict] = None,
    artefacts: Optional[dict] = None,
    observation_summary: Optional[dict] = None,
    debriefing_transcript: Optional[dict] = None,
    construct_judgment: Optional[dict] = None,
    extra_phase_handlers: Optional[dict] = None,
    extra_phase_results: Optional[dict] = None,
    role_states: Optional[dict] = None,
    research_question: str = "",
    run_id: Optional[str] = None,
    extra_meta: Optional[dict] = None,
    write_json: bool = True,
    rag_session: Optional[Any] = None,
    field_notes: Optional[list] = None,
    usage_log: Optional[Any] = None,
) -> Path:
    """Write a run's artefacts (here, any saved record) to a per-run folder.

    Markdown is always produced: the folder is a human-readable
    qualitative-review artefact and the markdown is the source of
    truth. JSON sub-files (per-phase structured data) are written
    alongside the markdown by default but can be disabled via
    `write_json=False` for runs where only the markdown matters.
    `00_meta.json` is always written regardless — the per-run folder
    needs a single machine-readable identity file even in
    markdown-only mode.

    Every argument is optional except company / cell context — pass
    whichever phases were captured. Empty phases are simply skipped
    (their folder is created with a placeholder so the layout makes
    it obvious what's missing).

    `role_states` is the per-role state from CONCURRENT mode
    (`SharedState.role_states`). When supplied AND `artefacts` is
    not, the role `draft` fields are promoted to strategy documents
    (CONCURRENT mode rolls artefact authoring into the deliberation
    via DRAFT actions, moves that update a role's private document draft; full
    pipeline runs Phase 2 separately).

    Args:
        write_json: When True (default), each phase folder gets both
            a `.json` (structured) and a `.md` (human-readable)
            version of its content. When False, only the markdown
            files are written. The top-level `00_meta.json` is
            always written so the per-run folder has a machine-
            readable identity. Useful for qualitative-review-only
            runs where the JSON sub-files would just be noise.

    Returns the directory written to.
    """
    run_id = run_id or _default_run_id(company, industry_context, product_type)
    base = out_dir / run_id
    base.mkdir(parents=True, exist_ok=True)

    # Reconcile the legacy `construct_judgment` (scores from judges, the language models that rate a finished run) kwarg
    # (named input) with the new
    # generic `extra_phase_results` dict. The legacy kwarg wins (it's
    # what the old callers passed). The handler comes from
    # `extra_phase_handlers["construct_judging"]` if registered;
    # otherwise we fall back to a default-instantiated handler so the
    # persist path still works.
    extra_phase_results = dict(extra_phase_results or {})
    extra_phase_handlers = dict(extra_phase_handlers or {})
    if construct_judgment is not None and "construct_judging" not in extra_phase_results:
        extra_phase_results["construct_judging"] = construct_judgment
        if "construct_judging" not in extra_phase_handlers:
            try:
                from ..orchestrator.construct_judging import ConstructJudgingPhase
            except (ImportError, ValueError):  # pragma: no cover
                from orchestrator.construct_judging import ConstructJudgingPhase  # type: ignore[no-redef]
            extra_phase_handlers["construct_judging"] = ConstructJudgingPhase()

    # 00 — meta (always JSON; the per-run folder needs a stable
    # machine-readable identity file regardless of write_json).
    meta = {
        "run_id": run_id,
        "company": company,
        "industry_context": industry_context,
        "product_type": product_type,
        "research_question": research_question,
        "written_at": datetime.utcnow().isoformat(),
        "phases_captured": {
            "deliberation": bool(deliberation_log),
            "strategy_documents": bool(artefacts) or bool(role_states),
            "observation_summary": bool(observation_summary),
            "field_notes": bool(field_notes),
            "debriefing": bool(debriefing_transcript),
            # One entry per registered extra phase, keyed by handler name.
            **{
                name: name in extra_phase_results
                for name in extra_phase_handlers
            },
            # The private channel is a Phase-1 SharedState snapshot
            # (scratchpads, drafts, inboxes) — not a phase that runs,
            # so it lives outside the PhaseHandler protocol.
            "private_channel": bool(role_states),
        },
    }
    if extra_meta:
        meta.update(extra_meta)
    (base / "00_meta.json").write_text(json.dumps(meta, indent=2, default=str))

    # 01 — deliberation
    if deliberation_log is not None or role_states is not None:
        _write_deliberation(base, deliberation_log, role_states, write_json=write_json)

    # 02 — strategy documents
    if artefacts is not None or role_states is not None:
        _write_strategy_documents(
            base, company, industry_context, product_type,
            artefacts, role_states, write_json=write_json,
        )

    # 03 — researcher observation summary
    if observation_summary is not None:
        _write_observation_summary(base, observation_summary, write_json=write_json)
    if field_notes:
        _write_field_notes(base, field_notes, write_json=write_json)

    # 04 — interview transcript
    if debriefing_transcript is not None:
        _write_debriefing_transcript(base, debriefing_transcript, write_json=write_json)

    # 05+ — every registered PhaseHandler persists its own output.
    for name, handler in extra_phase_handlers.items():
        if name not in extra_phase_results:
            continue
        try:
            handler.persist(
                out_dir=base,
                result=extra_phase_results[name],
                write_json=write_json,
            )
        except Exception:  # noqa: BLE001
            # Persisting one phase shouldn't break the whole run folder.
            # Errors get logged but the burst continues.
            import logging
            logging.getLogger(__name__).exception(
                "burst_run: handler %s persist() raised", name,
            )

    # 06 — private channel (scratchpads, drafts, inbox final state).
    # The public-artefact side of role_states is already consumed by
    # `_write_strategy_documents` when artefacts is missing. Here we
    # persist the FULL private channel regardless of whether Phase 2
    # produced artefacts, because the sub-dimensional (a sub-dimension is one
    # narrow item in the openness rubric, a scoring guide) measurement
    # layer scores the private channel separately from the public
    # one (see `analysis/text_measures/dictionary.py`).
    if role_states:
        _write_private_channel(base, role_states, write_json=write_json)

    # 07 — RAG (retrieval-augmented generation: searching documents and adding the
    # passages found to a model's prompt) audit folder. Written when a rag_session was active
    # (even if disabled — the manifest then records that fact and the
    # retrieval log carries the skipped-retrieval markers).
    if rag_session is not None:
        _write_rag_folder(base, rag_session)
        meta["phases_captured"]["rag"] = bool(getattr(rag_session, "enabled", False))
        # Rewrite 00_meta with the rag flag included.
        (base / "00_meta.json").write_text(json.dumps(meta, indent=2, default=str))

    # 08 — tokens (small pieces of text that providers charge by) each model call
    # (one prompt and one reply) used. Written whenever a run has them.
    if usage_log is not None and usage_log.calls:
        usage_dir = base / "08_usage"
        usage_dir.mkdir(exist_ok=True)
        usage_log.write_jsonl(usage_dir / "token_usage.jsonl")
        meta["token_usage"] = usage_log.summary()
        (base / "00_meta.json").write_text(json.dumps(meta, indent=2, default=str))

    # Master index for browsing
    (base / "README.md").write_text(_render_index(meta, base))

    return base


def _write_rag_folder(base: Path, rag_session: Any) -> None:
    """Write `07_rag/` — corpus manifest, retrieval log, README.

    Idempotent (safe to repeat) — overwrites any existing files in the folder.
    """
    rag_dir = base / "07_rag"
    rag_dir.mkdir(parents=True, exist_ok=True)

    # Corpus manifest — which corpus (document collection), embedding model (turns text
    # into numbers standing for its meaning), top_k (passages per search), doc SHAs
    # (fingerprints of each document's contents).
    manifest = rag_session.manifest_dict() if hasattr(rag_session, "manifest_dict") else {}
    (rag_dir / "corpus_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str)
    )

    # Retrieval log — one record per retrieve_for_role call, as JSONL (one JSON record per line).
    retrieval_log = getattr(rag_session, "retrieval_log", []) or []
    with (rag_dir / "retrieval_log.jsonl").open("w") as f:
        for rec in retrieval_log:
            f.write(json.dumps(rec, default=str))
            f.write("\n")

    # Human-readable README.
    enabled = bool(getattr(rag_session, "enabled", False))
    corpus_name = getattr(rag_session, "corpus_name", None)
    n_docs = len(getattr(rag_session, "corpus_documents", []) or [])
    n_retrievals = sum(
        1 for r in retrieval_log if not r.get("skipped_reason") and not r.get("error")
    )
    n_skipped = sum(1 for r in retrieval_log if r.get("skipped_reason"))
    n_errors = sum(1 for r in retrieval_log if r.get("error"))
    readme = [
        "# RAG audit folder",
        "",
        f"**Enabled:** {'yes' if enabled else 'no'}",
        f"**Corpus resource name:** `{corpus_name or '(none)'}`",
        f"**Documents in corpus:** {n_docs}",
        f"**Retrievals run:** {n_retrievals}",
        f"**Retrievals skipped:** {n_skipped}",
        f"**Retrieval errors:** {n_errors}",
        "",
        "## Files",
        "- [corpus_manifest.json](corpus_manifest.json) — corpus + per-doc SHAs + embedding model",
        "- [retrieval_log.jsonl](retrieval_log.jsonl) — one record per LLM-call retrieval",
        "",
        "## Reproducibility",
        "The `corpus_manifest.json` pins which document content was in the corpus at run time",
        "(via per-doc SHA256). The corpus state itself lives in Google Vertex AI RAG Engine,",
        "not in this folder — a reviewer reconstructing the run uses the SHAs here to verify",
        "that the document content matches what was indexed.",
    ]
    (rag_dir / "README.md").write_text("\n".join(readme))


def burst_run_from_files(
    *,
    out_dir: Path,
    deliberation_log_path: Optional[Path] = None,
    artefacts_path: Optional[Path] = None,
    observation_summary_path: Optional[Path] = None,
    debriefing_transcript_path: Optional[Path] = None,
    session_path: Optional[Path] = None,
    run_id: Optional[str] = None,
    write_json: bool = True,
) -> Path:
    """Burst a full-pipeline run from its per-phase JSON files on disk.

    Convenient when you have the `OpenAI_Dynamic_Novel_*.json` set
    produced by `ResearchSessionOutputs.to_json_files()`. Pass either
    the individual files or just the `session_path` (master pointer)
    and the others get inferred.

    `write_json` is forwarded to `burst_run`; see that function for
    semantics (markdown is always produced; JSON sub-files are
    optional).
    """
    if session_path is not None:
        session = _load(session_path)
        # The session JSON may carry either:
        # * legacy `construct_judgment` field (older runs persisted
        #   under the previous schema), OR
        # * the new generic `extra_phase_results` dict.
        # We forward whichever is present; burst_run reconciles them.
        return burst_run(
            out_dir=out_dir,
            company=session.get("company", "unknown"),
            industry_context=session.get("industry_context", "unknown"),
            product_type=session.get("product_type", "unknown"),
            deliberation_log=session.get("deliberation_log"),
            artefacts=session.get("artefacts"),
            observation_summary=session.get("observation_summary"),
            debriefing_transcript=session.get("debriefing_transcript"),
            construct_judgment=session.get("construct_judgment"),
            extra_phase_results=session.get("extra_phase_results"),
            research_question=session.get("research_question", ""),
            run_id=run_id,
            extra_meta={
                "started_at": session.get("started_at"),
                "finished_at": session.get("finished_at"),
                "errors": session.get("errors", []),
            },
            write_json=write_json,
        )

    delib = _load(deliberation_log_path) if deliberation_log_path else None
    arts = _load(artefacts_path) if artefacts_path else None
    obs = _load(observation_summary_path) if observation_summary_path else None
    debrief = _load(debriefing_transcript_path) if debriefing_transcript_path else None

    company = (delib or arts or {}).get("company", "unknown")
    industry = (delib or arts or {}).get("industry_context", "unknown")
    product = (delib or arts or {}).get("product_type", "unknown")
    rq = (debrief or {}).get("research_question", "")

    return burst_run(
        out_dir=out_dir,
        company=company,
        industry_context=industry,
        product_type=product,
        deliberation_log=delib,
        artefacts=arts,
        observation_summary=obs,
        debriefing_transcript=debrief,
        research_question=rq,
        run_id=run_id,
        write_json=write_json,
    )


def burst_concurrent_log(
    *,
    out_dir: Path,
    payload_path: Path,
    run_id: Optional[str] = None,
) -> Path:
    """Burst the JSON dump from `verify_concurrent.py` (deliberation-only)."""
    payload = _load(payload_path)
    result = payload.get("result_dict", {})
    transcript = payload.get("transcript", [])
    role_states = payload.get("role_states", {})

    # Wrap the transcript so it matches `DeliberationLog` shape that
    # `_write_deliberation` expects.
    delib_log = {
        "company": result.get("company", "unknown"),
        "industry_context": result.get("industry_context", "unknown"),
        "product_type": result.get("product_type", "unknown"),
        "events": transcript,
    }

    return burst_run(
        out_dir=out_dir,
        company=result.get("company", "unknown"),
        industry_context=result.get("industry_context", "unknown"),
        product_type=result.get("product_type", "unknown"),
        deliberation_log=delib_log,
        role_states=role_states,
        research_question=result.get("strategic_question", ""),
        run_id=run_id,
        extra_meta={
            "discussion_mode": result.get("discussion_mode"),
            "ended_reason": result.get("ended_reason"),
            "rounds_completed": result.get("rounds_completed"),
            "events_count": result.get("events_count"),
            "timestamp": result.get("timestamp"),
        },
    )


# ---------------------------------------------------------------------------
# Private writers — one per phase
# ---------------------------------------------------------------------------

def _write_deliberation(
    base: Path,
    deliberation_log: Optional[dict],
    role_states: Optional[dict],
    *,
    write_json: bool = True,
) -> None:
    delib = base / "01_deliberation"
    delib.mkdir(exist_ok=True)

    # Raw structured log
    if deliberation_log is not None:
        if write_json:
            (delib / "interaction_log.json").write_text(
                json.dumps(deliberation_log, indent=2, default=str)
            )
        (delib / "interaction_log.md").write_text(
            _render_deliberation_md(deliberation_log)
        )

    # Per-role scratchpads (CONCURRENT mode only)
    if role_states:
        scratch = delib / "role_scratchpads"
        scratch.mkdir(exist_ok=True)
        for role, rs in role_states.items():
            notes: List[str] = rs.get("scratchpad", []) or []
            lines = [f"# {role} — private scratchpad", ""]
            if not notes:
                lines.append("_(no private notes recorded)_")
            else:
                for i, note in enumerate(notes, 1):
                    lines.append(f"## Note {i}")
                    lines.append(str(note))
                    lines.append("")
            (scratch / f"{role}_scratchpad.md").write_text("\n".join(lines))


def _write_strategy_documents(
    base: Path,
    company: str,
    industry_context: str,
    product_type: str,
    artefacts: Optional[dict],
    role_states: Optional[dict],
    *,
    write_json: bool = True,
) -> None:
    docs_dir = base / "02_strategy_documents"
    docs_dir.mkdir(exist_ok=True)

    if artefacts and artefacts.get("artefacts"):
        # Full pipeline: Phase-2 ArtefactBundle.
        for a in artefacts["artefacts"]:
            role = a.get("role", "Unknown")
            if write_json:
                (docs_dir / f"{role}_strategy.json").write_text(
                    json.dumps(a, indent=2, default=str)
                )
            (docs_dir / f"{role}_strategy.md").write_text(
                _render_artefact_md(a)
            )
        return

    if role_states:
        # CONCURRENT mode: drafts in role_states are the strategy docs.
        for role, rs in role_states.items():
            draft = rs.get("draft", "") or ""
            if write_json:
                structured = {
                    "role": role,
                    "company": company,
                    "industry_context": industry_context,
                    "product_type": product_type,
                    "title": f"{role} strategy (from CONCURRENT draft)",
                    "body": draft,
                    "_source": "concurrent_mode.role_states[draft]",
                }
                (docs_dir / f"{role}_strategy.json").write_text(
                    json.dumps(structured, indent=2, default=str)
                )
            (docs_dir / f"{role}_strategy.md").write_text(
                f"# {role} — Strategy Document\n"
                f"_From CONCURRENT-mode draft "
                f"({company} / {industry_context} / {product_type})_\n\n"
                "---\n\n"
                + (draft or "_(empty — role did not produce a draft)_")
                + "\n"
            )


def _write_observation_summary(
    base: Path, obs: dict, *, write_json: bool = True,
) -> None:
    researcher = base / "03_researcher"
    researcher.mkdir(exist_ok=True)
    if write_json:
        (researcher / "observation_summary.json").write_text(
            json.dumps(obs, indent=2, default=str)
        )
    (researcher / "observation_summary.md").write_text(
        _render_observation_summary_md(obs)
    )


def _write_field_notes(
    base: Path, field_notes: list, *, write_json: bool = True,
) -> None:
    researcher = base / "03_researcher"
    researcher.mkdir(exist_ok=True)
    if write_json:
        (researcher / "field_notes.json").write_text(
            json.dumps(field_notes, indent=2, default=str)
        )
    lines = ["# Researcher field notes", ""]
    for i, note in enumerate(field_notes, 1):
        lines += [f"## Note {i}", "", str(note), ""]
    (researcher / "field_notes.md").write_text("\n".join(lines))


def _write_debriefing_transcript(
    base: Path, debrief: dict, *, write_json: bool = True,
) -> None:
    interview = base / "04_interview"
    interview.mkdir(exist_ok=True)
    if write_json:
        (interview / "transcript.json").write_text(
            json.dumps(debrief, indent=2, default=str)
        )
    (interview / "transcript.md").write_text(
        _render_debriefing_md(debrief)
    )


# NOTE: the Phase-5 construct-judgment writer that used to live here
# moved to `orchestrator/construct_judging.py::ConstructJudgingPhase.persist()`
# as part of the PhaseHandler extension hook. The markdown renderers
# (`_render_judgment_aggregate_md`, `_render_judge_assessment_md`)
# stay here because they're reused by `burst_concurrent_log` and by
# any future handler that wants the same look.


def _write_private_channel(
    base: Path, role_states: dict, *, write_json: bool = True,
) -> None:
    """Write the per-role private-channel artefacts.

    The private channel is the firm's INTERNAL deliberation state —
    not visible to peers during Phase 1 and not part of what the
    LLM-judge ensemble (the group of language models that score a finished
    run) currently sees. We persist it so the
    sub-dimensional measurement layer can score the private channel
    separately from the public channel.

    Layout:
        06_private_channel/
          {ROLE}_scratchpad.md    ← all SCRATCHPAD notes for the role
          {ROLE}_draft.md         ← the final DRAFT text for the role
          inbox_final.md          ← every role's inbox at end-of-Phase-1
          private_state.json      ← machine-readable dump (optional)

    Args:
        role_states: dict of `role -> RoleState.model_dump(mode='json')`
            shape produced by `_snapshot_private_channel` in
            `run_research_session.py`.
        write_json: if True (default), also write the machine-readable
            `private_state.json` alongside the markdown.
    """
    pc = base / "06_private_channel"
    pc.mkdir(exist_ok=True)

    # Machine-readable dump (the measurement layer reads this).
    if write_json:
        (pc / "private_state.json").write_text(
            json.dumps(role_states, indent=2, default=str)
        )

    # Per-role scratchpad + draft markdown.
    for role, rs in sorted(role_states.items()):
        scratchpad = rs.get("scratchpad", []) or []
        draft = rs.get("draft", "") or ""
        action_count = rs.get("action_count", 0)
        done = rs.get("done", False)
        finished_reason = rs.get("finished_reason", "")

        (pc / f"{role}_scratchpad.md").write_text(
            _render_scratchpad_md(
                role=role,
                scratchpad=scratchpad,
                action_count=action_count,
                done=done,
                finished_reason=finished_reason,
            )
        )
        (pc / f"{role}_draft.md").write_text(
            _render_draft_md(role=role, draft=draft)
        )

    # Combined inbox view — one section per role, every inbox message.
    (pc / "inbox_final.md").write_text(_render_inbox_md(role_states))


# ---------------------------------------------------------------------------
# Markdown renderers
# ---------------------------------------------------------------------------

def _render_deliberation_md(deliberation_log: dict) -> str:
    company = deliberation_log.get("company", "unknown")
    industry = deliberation_log.get("industry_context", "unknown")
    product = deliberation_log.get("product_type", "unknown")
    events = deliberation_log.get("events", []) or []

    citation_counter = CitationCounter()

    lines = [
        "# Inter-agent deliberation transcript",
        f"**Company:** {company}",
        f"**Cell:** {industry} / {product}",
        f"**Events:** {len(events)}",
        "",
        "---",
        "",
    ]
    for e in events:
        role = e.get("role", "?")
        kind = e.get("kind", "?")
        text = (e.get("text") or "").strip()
        addressed_to = e.get("addressed_to")
        idx = e.get("index", "?")
        if kind == "ask_public_echo":
            header = f"### [{idx}] {role} → {addressed_to or '?'} (ASK)"
        elif kind == "answer_public":
            qid = e.get("answer_to_question_id", "?")
            header = f"### [{idx}] {role} (ANSWER — re q={qid})"
        elif kind == "delegation":
            header = f"### [{idx}] {role} → {addressed_to or '?'} (delegation)"
        elif kind == "other":
            header = f"### [{idx}] {role} _(other)_"
        else:
            header = f"### [{idx}] {role}"
        lines.append(header)
        lines.append("")
        # Append per-event citation markers right after the body so a
        # reviewer sees which sentences leaned on retrieved material.
        markers = citation_counter.register_all(e.get("citations", []) or [])
        body = text or "_(empty)_"
        lines.append(body + markers)
        lines.append("")
    # If any citations were registered, append a References block at the
    # bottom of the file. Markdown footnote references in the body
    # resolve to definitions here.
    footnotes = citation_counter.footnote_block()
    if footnotes:
        lines.append(footnotes)
    return "\n".join(lines)


def _render_artefact_md(a: dict) -> str:
    role = a.get("role", "?")
    title = a.get("title", "(untitled)")
    company = a.get("company", "?")
    industry = a.get("industry_context", "?")
    product = a.get("product_type", "?")

    counter = CitationCounter()

    lines = [
        f"# {role} — Strategy Document",
        f"## {title}",
        f"**Company:** {company}",
        f"**Cell:** {industry} / {product}",
        "",
        "---",
        "",
        "## Key challenges",
    ]
    for c in a.get("key_challenges", []) or []:
        lines.append(f"- {c}")
    lines.extend(["", "## Main decisions"])
    for d in a.get("main_decisions", []) or []:
        lines.append(f"- {d}")
    lines.extend(["", "## Key tensions"])
    for t in a.get("key_tensions", []) or []:
        lines.append(f"- {t}")
    body = a.get("body", "") or ""
    # `StrategicArtefact.citations` is a single list — there is no
    # per-statement attribution from the LLM (the role authored the
    # whole document with the same retrieval pool). The cleanest
    # rendering: register all citations at the end of the body so they
    # appear as a block of footnote markers right before the
    # References section.
    citations = a.get("citations", []) or []
    citation_markers = counter.register_all(citations)
    if citation_markers:
        body = body.rstrip() + " " + citation_markers
    lines.extend(["", "---", "", "## Body", "", body])
    footnotes = counter.footnote_block()
    if footnotes:
        lines.append(footnotes)
    return "\n".join(lines)


def _render_observation_summary_md(obs: dict) -> str:
    lines = ["# Researcher observation summary", "", "## Decisions"]
    for d in obs.get("decisions", []) or []:
        lines.append(f"- {d}")
    lines.extend(["", "## Components / assets discussed"])
    for c in obs.get("components", []) or []:
        lines.append(f"- {c}")
    disagreements = obs.get("disagreements", []) or []
    if disagreements:
        lines.extend(["", "## Disagreements"])
        for d in disagreements:
            topic = d.get("topic", "?")
            parties = ", ".join(d.get("parties", []) or [])
            resolution = d.get("resolution", "?")
            lines.append(f"- **{topic}** between {parties} → _{resolution}_")
    contributions = obs.get("role_contributions", []) or []
    if contributions:
        lines.extend(["", "## Role contributions"])
        for rc in contributions:
            role = rc.get("role", "?")
            lines.append(f"### {role}")
            if rc.get("pushed_for"):
                lines.append(f"- Pushed for: {', '.join(rc['pushed_for'])}")
            if rc.get("pushed_back_on"):
                lines.append(f"- Pushed back on: {', '.join(rc['pushed_back_on'])}")
            if rc.get("quiet_on"):
                lines.append(f"- Quiet on: {', '.join(rc['quiet_on'])}")
            lines.append("")
    alts = obs.get("alternatives_considered", []) or []
    if alts:
        lines.extend(["## Alternatives considered (but not pursued)"])
        for a in alts:
            lines.append(f"- {a}")
    # Accept either the new field name (`flagged_vocabulary_used`)
    # or the legacy one (`loaded_vocabulary_used`) so old persisted
    # JSON dumps still render.
    flagged = (
        obs.get("flagged_vocabulary_used")
        or obs.get("loaded_vocabulary_used")
        or []
    )
    if flagged:
        lines.extend(["", "## Spontaneous use of watch-listed vocabulary"])
        for v in flagged:
            lines.append(
                f"- **{v.get('role', '?')}** said _'{v.get('word', '')}'_ in: "
                f"{v.get('context', '')}"
            )
    return "\n".join(lines)


def _render_debriefing_md(debrief: dict) -> str:
    company = debrief.get("company", "?")
    rq = debrief.get("research_question", "?")
    ended = debrief.get("ended_reason", "?")
    violations = debrief.get("forbidden_vocab_violations", 0)
    exchanges = debrief.get("exchanges", []) or []

    counter = CitationCounter()

    lines = [
        f"# Researcher debriefing transcript",
        f"**Company:** {company}",
        f"**Exchanges:** {len(exchanges)}",
        f"**Ended:** {ended}",
        f"**Forbidden-vocab violations caught:** {violations}",
        "",
        f"## Research question",
        f"> {rq}",
        "",
        "---",
        "",
    ]
    for i, ex in enumerate(exchanges, 1):
        utt = ex.get("utterance", {})
        area = utt.get("area_id", "?")
        addressed = utt.get("addressed_to", "?")
        anchors = utt.get("anchor_refs", []) or []
        text = utt.get("text", "")
        lines.append(f"## Exchange {i} (area {area})")
        lines.append(f"**Researcher → {addressed}:** {text}")
        if anchors:
            lines.append("")
            lines.append("_Anchored on:_ " + ", ".join(f"`{a}`" for a in anchors))
        link = utt.get("research_question_link", "")
        if link:
            lines.append("")
            lines.append(f"_Link to the research question (researcher's note):_ {link}")
        lines.append("")
        for r in ex.get("responses", []) or []:
            role = r.get("role", "?")
            tag = " _(cross-talk)_" if r.get("is_cross_talk") else ""
            lines.append(f"### {role}{tag}")
            # Footnote markers right after the panellist's response, so
            # the citations attach to what they just said.
            markers = counter.register_all(r.get("citations", []) or [])
            lines.append((r.get("text", "") or "") + markers)
            lines.append("")
        lost = ex.get("lost_roles", []) or []
        if lost:
            lines.append(
                "_No answer recorded (model call failed, not silence):_ "
                + ", ".join(lost)
            )
            lines.append("")
        lines.append("---")
        lines.append("")
    emerging = [
        (i, ex.get("utterance", {}).get("emerging_question", ""))
        for i, ex in enumerate(exchanges, 1)
    ]
    emerging = [(i, q) for i, q in emerging if q]
    if emerging:
        lines.append("## Emerging questions")
        lines.append("")
        for i, q in emerging:
            lines.append(f"- Exchange {i}: {q}")
        lines.append("")
    footnotes = counter.footnote_block()
    if footnotes:
        lines.append(footnotes)
    return "\n".join(lines)


def _render_index(meta: dict, base: Path) -> str:
    phases = meta.get("phases_captured", {})
    company = meta.get("company")
    cell = f"{meta.get('industry_context')} / {meta.get('product_type')}"
    lines = [
        f"# Run: {meta.get('run_id')}",
        f"**Company:** {company}",
        f"**Cell:** {cell}",
        f"**Written:** {meta.get('written_at')}",
        "",
        "## Phases captured",
        f"- Deliberation: {'✅' if phases.get('deliberation') else '❌'}",
        f"- Strategy documents: {'✅' if phases.get('strategy_documents') else '❌'}",
        f"- Observer summary: {'✅' if phases.get('observation_summary') else '❌'}",
        f"- Interview transcript: {'✅' if phases.get('debriefing') else '❌'}",
    ]
    # Every key in `phases` beyond the four hardcoded Phase-1-to-4
    # entries is an extra phase registered by the study. Render each
    # with its captured/missing status.
    core_phases = {"deliberation", "strategy_documents", "observation_summary", "debriefing"}
    extra_phase_names = [p for p in phases if p not in core_phases]
    for name in extra_phase_names:
        # Convert snake_case to a display label.
        label = name.replace("_", " ").capitalize()
        lines.append(f"- {label}: {'✅' if phases.get(name) else '❌'}")

    lines += [
        "",
        "## Layout",
        "- [00_meta.json](00_meta.json) — run metadata",
        "- [01_deliberation/](01_deliberation/) — inter-agent transcript + role scratchpads",
        "- [02_strategy_documents/](02_strategy_documents/) — one strategy doc per role",
        "- [03_researcher/](03_researcher/) — observer summary and field notes",
        "- [04_interview/](04_interview/) — researcher-led debriefing transcript",
        "- [08_usage/](08_usage/) — tokens each model call used, where recorded",
    ]
    if phases.get("construct_judging"):
        lines.append(
            "- [05_judging/](05_judging/) — construct-judge ensemble: "
            "aggregate composite + α + per-judge assessments"
        )
    return "\n".join(lines)


def _render_judgment_aggregate_md(bundle: dict) -> str:
    """Render the aggregate bundle as a human-readable summary."""
    lines = ["# Construct Judgment — Aggregate", ""]
    judges = bundle.get("judges_used", []) or []
    lines.append(f"**Judges:** {', '.join(judges)}" if judges else "**Judges:** —")
    judge_errors = bundle.get("judge_errors") or {}
    if judge_errors:
        failed = ", ".join(sorted(judge_errors.keys()))
        lines.append(
            f"**Failed judges (excluded from α + composite):** {failed} — see "
            f"`<provider>_error.txt` alongside this file for the captured "
            f"`repr(exc)` + traceback."
        )
    # Quote-verification summary (v0.4). Surface per-judge fail rates
    # so the PI (principal investigator, the lead researcher) can spot a judge
    # whose evidence quotes drifted from
    # the source files without opening every audit file.
    qv_summary = bundle.get("quote_verification_summary") or {}
    if qv_summary:
        parts = []
        for jid in sorted(qv_summary.keys()):
            s = qv_summary[jid]
            parts.append(
                f"{jid} {s.get('n_passed', 0)}/{s.get('n_total', 0)} "
                f"passed ({(s.get('fail_rate', 0.0) * 100):.1f}% fail)"
            )
        lines.append(
            f"**Quote verification (v0.4):** {'; '.join(parts)} — see "
            f"`<provider>_quote_audit.md` for per-quote detail."
        )
    composite = bundle.get("mean_composite")
    if composite is not None:
        lines.append(f"**Composite score (mean across judges):** {composite:.2f} / 7")
    iraa = bundle.get("inter_rater_agreement") or {}
    overall_alpha = iraa.get("overall_alpha")
    if overall_alpha is not None:
        lines.append(
            f"**Inter-rater agreement (Krippendorff's α):** "
            f"{overall_alpha:.3f} {_alpha_interpretation(overall_alpha)}"
        )
    lines.append("")

    # Per-parent-dimension table
    lines.append("## Per-dimension scores (parent-level)")
    lines.append("")
    lines.append("| Dimension | Mean | Consensus | α |")
    lines.append("|---|---|---|---|")
    means = bundle.get("per_dimension_means") or {}
    consensus = bundle.get("consensus_dimension_scores") or {}
    per_dim_alpha = iraa.get("per_dimension_alpha") or {}
    for dim_key in means:
        m = means.get(dim_key)
        c = consensus.get(dim_key)
        a = per_dim_alpha.get(dim_key)
        m_str = f"{m:.2f}" if isinstance(m, (int, float)) and m == m else "—"
        c_str = str(c) if c is not None else "—"
        a_str = (
            f"{a:.2f}"
            if isinstance(a, (int, float)) and a == a
            else "—"
        )
        lines.append(f"| {dim_key} | {m_str} | {c_str} | {a_str} |")
    lines.append("")

    # Per-sub-dimension table (v0.4 only — empty under v0.3 back-compat)
    sub_pct = bundle.get("per_sub_dimension_means_pct") or {}
    sub_likert = bundle.get("per_sub_dimension_means_likert") or {}
    sub_alpha = iraa.get("per_sub_dimension_alpha") or {}
    if sub_pct:
        lines.append("## Per-sub-dimension scores (v0.4 fine-grained)")
        lines.append("")
        lines.append(
            "Mean across judges in both native percent (0-100) and "
            "Likert back-bin (1-7). The per-sub-dim α surfaces exactly "
            "where the construct contests across judges."
        )
        lines.append("")
        lines.append("| Sub-dimension | Mean % | Likert | α |")
        lines.append("|---|---|---|---|")
        for sub_key in sub_pct:
            mp = sub_pct.get(sub_key)
            ml = sub_likert.get(sub_key)
            sa = sub_alpha.get(sub_key)
            mp_str = (
                f"{mp:.1f}" if isinstance(mp, (int, float)) and mp == mp else "—"
            )
            ml_str = str(ml) if ml is not None else "—"
            sa_str = (
                f"{sa:.2f}"
                if isinstance(sa, (int, float)) and sa == sa
                else "—"
            )
            lines.append(f"| {sub_key} | {mp_str} | {ml_str} | {sa_str} |")
        lines.append("")

    # Caveats from each judge (if any)
    any_caveats = False
    for a in bundle.get("assessments", []) or []:
        caveat = (a.get("caveats") or "").strip()
        if caveat:
            if not any_caveats:
                lines.append("## Caveats from judges")
                lines.append("")
                any_caveats = True
            lines.append(f"### {a.get('judge_id', 'unknown')}")
            lines.append(caveat)
            lines.append("")

    lines.append("---")
    lines.append("Per-judge full assessments live alongside this file as "
                 "`<judge_id>_assessment.md`.")
    return "\n".join(lines)


def _render_judge_assessment_md(a: dict) -> str:
    """Render one judge's full ConstructAssessment as markdown."""
    judge_id = a.get("judge_id", "unknown")
    lines = [f"# Construct Assessment — judge: {judge_id}", ""]
    composite = a.get("composite_score")
    if composite is not None:
        lines.append(f"**Composite score:** {composite:.2f} / 7")
    overall_conf = a.get("overall_confidence")
    if overall_conf:
        lines.append(f"**Overall confidence:** {overall_conf}")
    lines.append("")

    summary = (a.get("qualitative_summary") or "").strip()
    if summary:
        lines.append("## Qualitative summary (Stage 1)")
        lines.append("")
        lines.append(summary)
        lines.append("")

    lines.append("## Per-dimension scores (Stage 2)")
    lines.append("")
    for d in a.get("dimension_scores", []) or []:
        lines.append(f"### {d.get('dimension')} — {d.get('score')} / 7")
        conf = d.get("confidence")
        if conf:
            lines.append(f"*Confidence: {conf}*")
        reasoning = (d.get("reasoning") or "").strip()
        if reasoning:
            lines.append("")
            lines.append(reasoning)
        ev = d.get("evidence") or []
        if ev:
            lines.append("")
            lines.append("**Evidence:**")
            for q in ev:
                lines.append(f"> {q}")
        lines.append("")

    caveats = (a.get("caveats") or "").strip()
    if caveats:
        lines.append("## Caveats")
        lines.append("")
        lines.append(caveats)
        lines.append("")
    return "\n".join(lines)


def _render_scratchpad_md(
    *,
    role: str,
    scratchpad: list,
    action_count: int,
    done: bool,
    finished_reason: str,
) -> str:
    """Render a role's accumulated SCRATCHPAD notes as markdown.

    The scratchpad is the role's private notebook — every `SCRATCHPAD`
    action during Phase 1 appended one note. Peers never saw any of
    this; the LLM-judge ensemble doesn't see it either. Persisted here
    for the sub-dimensional measurement layer.
    """
    lines = [
        f"# {role} — private scratchpad",
        "",
        f"- Total actions taken in Phase 1: **{action_count}**",
        f"- Declared DONE: **{'yes' if done else 'no'}**",
    ]
    if finished_reason:
        lines.append(f"- Reason: `{finished_reason}`")
    lines.append("")
    lines.append("## Scratchpad notes (chronological)")
    lines.append("")
    if not scratchpad:
        lines.append("*(no scratchpad notes)*")
    else:
        for i, note in enumerate(scratchpad, 1):
            lines.append(f"### Note {i}")
            lines.append("")
            lines.append(note)
            lines.append("")
    return "\n".join(lines)


def _render_draft_md(*, role: str, draft: str) -> str:
    """Render a role's final DRAFT text as markdown.

    The DRAFT is the role's working-document precursor to the Phase 2
    artefact. Only the final snapshot is preserved — every `DRAFT`
    action REPLACES the previous one, per the orchestrator
    instruction. The draft is private to the authoring role during
    Phase 1.
    """
    lines = [
        f"# {role} — final working draft (private)",
        "",
        "*This is the role's last DRAFT before Phase 2. It is the*",
        "*private precursor to the public artefact in*",
        "*`02_strategy_documents/`. Peers did not see this content*",
        "*during the deliberation.*",
        "",
    ]
    if not draft:
        lines.append("*(empty — the role never issued a DRAFT action)*")
    else:
        lines.append("---")
        lines.append("")
        lines.append(draft)
    return "\n".join(lines)


def _render_inbox_md(role_states: dict) -> str:
    """Render every role's end-of-Phase-1 inbox as a single markdown file.

    Includes both ASKs (questions to the role) and ANSWERs (responses
    in to the role). Private answers (`answer_visibility="private"`)
    are explicitly flagged — they went to the recipient's inbox but
    never to the public transcript.
    """
    lines = [
        "# Inbox state at end of Phase 1",
        "",
        "*Per role: every directed message that landed in the role's*",
        "*inbox during the deliberation. ASKs that were answered are*",
        "*shown here alongside the ANSWERs they received. Private*",
        "*answers were never echoed to the public transcript.*",
        "",
    ]
    for role, rs in sorted(role_states.items()):
        inbox = rs.get("inbox", []) or []
        lines.append(f"## {role}")
        lines.append("")
        if not inbox:
            lines.append("*(empty)*")
            lines.append("")
            continue
        for m in inbox:
            kind = m.get("kind", "?")
            sender = m.get("sender", "?")
            recipient = m.get("recipient", "?")
            text = m.get("text", "")
            visibility = m.get("visibility", "public")
            ans_to = m.get("answer_to_question_id")
            header_bits = [f"**{kind}**", f"from {sender} → {recipient}"]
            if kind == "ANSWER":
                if ans_to:
                    header_bits.append(f"(answering question `{ans_to}`)")
                if visibility == "private":
                    header_bits.append("*PRIVATE*")
            lines.append(f"- {' '.join(header_bits)}: {text}")
        lines.append("")
    return "\n".join(lines)


def _alpha_interpretation(alpha: float) -> str:
    """One-word interpretation banner for Krippendorff's α, here agreement among
    the judge models
    (Krippendorff 2004 thresholds)."""
    if alpha != alpha:  # NaN
        return "(undefined)"
    if alpha >= 0.80:
        return "(reliable)"
    if alpha >= 0.67:
        return "(tentative)"
    return "(not reliable — report as exploratory)"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_")


def _default_run_id(company: str, industry: str, product: str) -> str:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return f"{_slug(company)}_{_slug(industry)}_{_slug(product)}_{ts}"


# ---------------------------------------------------------------------------
# CLI (command-line interface: using a program by typing commands)
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(
        description="Burst run JSON into a per-run folder structure."
    )
    parser.add_argument(
        "--out", type=Path, default=Path("results/runs"),
        help="Top-level directory for the per-run folders.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sp_full = sub.add_parser("full", help="Burst a full-pipeline run.")
    sp_full.add_argument("--session", type=Path)
    sp_full.add_argument("--deliberation", type=Path)
    sp_full.add_argument("--artefacts", type=Path)
    sp_full.add_argument("--observation", type=Path)
    sp_full.add_argument("--debriefing", type=Path)
    sp_full.add_argument("--run-id", type=str, default=None)

    sp_conc = sub.add_parser("concurrent", help="Burst a verify_concurrent.py dump.")
    sp_conc.add_argument("--payload", type=Path, required=True)
    sp_conc.add_argument("--run-id", type=str, default=None)

    args = parser.parse_args()

    if args.cmd == "full":
        path = burst_run_from_files(
            out_dir=args.out,
            session_path=args.session,
            deliberation_log_path=args.deliberation,
            artefacts_path=args.artefacts,
            observation_summary_path=args.observation,
            debriefing_transcript_path=args.debriefing,
            run_id=args.run_id,
        )
    else:
        path = burst_concurrent_log(
            out_dir=args.out,
            payload_path=args.payload,
            run_id=args.run_id,
        )
    print(f"Wrote: {path}")
