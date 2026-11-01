"""Rerun only the debrief on a finished run's saved deliberation.

The debrief is Phase 4 of a run (one complete simulated meeting and debrief), when
the researcher agent interviews the team.

Skips the deliberation (the team's discussion), documents and observer (the
researcher agent's summary step), and starts Phase 4 from what the run saved.
Because the deliberation stays the same, a difference
between the two debriefs comes from the debrief, not from a different
team. That also suits comparing two debrief protocols (sets of
rules and topics) on identical input.

Usage
-----
    python -m analysis.replay_debrief --run-dir <path> --vertex

    Optional:
      --max-exchanges 5        Stop the debrief early, to spend less (an exchange
                               is one question and its replies)
      --roles CEO,CTO,COO      Seat only some of the panel (the roles questioned)
      --rag                    Retrieve from the firm's corpus (document collection),
                               as in a grounded run (roles cite firm documents)

`--vertex` reaches Gemini (Google's language model) through Vertex AI (Google's paid
cloud service). The source run is never changed. Output goes to
`results/debrief_replays/<run>_<timestamp>/`.

Agents (language models given a role and instructions) get the same memory (earlier
records copied into each prompt) as in a full run, built from the saved files.
Runs saved before field notes (the researcher agent's running notes) were kept have
none. A grounded run must be
replayed with --rag, or its panel would answer without its documents. Keep
grounded output out of git (the tool that keeps the code's shared history), because
its log holds source text.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from ..agent import TMTSystemWithA2A
    from ..orchestrator.panel_debriefing import DebriefingTranscript, run_panel_debriefing
    from .persist_artefacts import _write_debriefing_transcript, _write_rag_folder
    from .saved_run import (
        CallCounter,
        SavedRun,
        SavedRunError,
        load_saved_run,
        new_session_runner,
    )
    from ..orchestrator.deliberation import ROLE_ORDER
    from ..orchestrator.role_memory import build_researcher_memory, build_role_memory
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from agent import TMTSystemWithA2A  # type: ignore[no-redef]
    from orchestrator.deliberation import ROLE_ORDER  # type: ignore[no-redef]
    from orchestrator.role_memory import (  # type: ignore[no-redef]
        build_researcher_memory,
        build_role_memory,
    )
    from orchestrator.panel_debriefing import (  # type: ignore[no-redef]
        DebriefingTranscript,
        run_panel_debriefing,
    )
    from analysis.persist_artefacts import _write_debriefing_transcript, _write_rag_folder  # type: ignore[no-redef]
    from analysis.saved_run import (  # type: ignore[no-redef]
        CallCounter,
        SavedRun,
        SavedRunError,
        load_saved_run,
        new_session_runner,
    )

log = logging.getLogger(__name__)

LIMIT_NOTE = (
    "This is a replay of the debrief on a saved deliberation, not a full run. "
    "Agents get the same memory as in a full run, built from the saved files; "
    "runs saved before field notes were kept have none."
)


def panel_memory(run: SavedRun) -> Dict[str, str]:
    """What each role remembers, built from the saved run as a full run builds it."""
    if not run.deliberation_text:
        raise SavedRunError(f"{run.run_dir} has no saved deliberation to replay.")
    return build_role_memory(
        run.role_states or ROLE_ORDER, run.deliberation_text, run.role_states, run.artefacts,
    )


def _measures(transcript: dict, words: List[str]) -> dict:
    exchanges = transcript.get("exchanges", []) or []
    answers = " ".join(
        r.get("text", "") for e in exchanges for r in e.get("responses", []) or []
    )
    return {
        "exchanges": len(exchanges),
        "follow_ups": sum(bool(e["utterance"].get("is_followup")) for e in exchanges),
        "new_questions": sum(bool(e["utterance"].get("emerging_question")) for e in exchanges),
        "area_order": " ".join(e["utterance"].get("area_id", "?") for e in exchanges),
        "ended": transcript.get("ended_reason", ""),
        "forbidden_word_violations": transcript.get("forbidden_vocab_violations", 0),
        "panel_words": len(answers.split()),
        "watch_list_words_in_answers": {
            word: count
            for word in words
            if (count := len(re.findall(rf"(?<!\w){re.escape(word)}(?!\w)", answers, re.I)))
        },
    }


def render_comparison(original: Optional[dict], replay: dict, words: List[str]) -> str:
    """A side-by-side of the saved debrief and the replay."""
    new = _measures(replay, words)
    old = _measures(original, words) if original else {}
    rows = [
        ("Exchanges", "exchanges"),
        ("Follow-ups", "follow_ups"),
        ("New questions recorded", "new_questions"),
        ("Area order", "area_order"),
        ("How it ended", "ended"),
        ("Forbidden-word violations", "forbidden_word_violations"),
        ("Words in panel answers", "panel_words"),
        ("Watch-list words in panel answers", "watch_list_words_in_answers"),
    ]
    lines = [
        "# Debrief replay compared with the saved debrief",
        "",
        f"_{LIMIT_NOTE}_",
        "",
        "| | Saved debrief | Replay |",
        "|---|---|---|",
    ]
    for label, key in rows:
        lines.append(f"| {label} | {old.get(key, 'n/a')} | {new[key]} |")
    questions = [
        (i, e["utterance"]["emerging_question"])
        for i, e in enumerate(replay.get("exchanges", []) or [], 1)
        if e["utterance"].get("emerging_question")
    ]
    if questions:
        lines += ["", "## New questions in the replay", ""]
        lines += [f"- Exchange {i}: {question}" for i, question in questions]
    return "\n".join(lines) + "\n"


def _panel_agents(run: SavedRun, roles: Optional[List[str]], current_year: int) -> dict:
    system = TMTSystemWithA2A(
        company=run.company,
        current_year=current_year,
        industry_context=run.industry_context,
        product_type=run.product_type,
    )
    wanted = roles or list(system.agents)
    unknown = [role for role in wanted if role not in system.agents]
    if unknown:
        raise SavedRunError(f"Unknown roles: {', '.join(unknown)}.")
    return {role: system.agents[role] for role in wanted}


async def replay_debrief(
    run: SavedRun,
    *,
    max_exchanges: int = 20,
    roles: Optional[List[str]] = None,
    current_year: int = 2030,
    make_runner: Callable[[], Any] = new_session_runner,
    debriefer_model: Optional[str] = None,
    rag_session: Any = None,
) -> tuple[DebriefingTranscript, CallCounter]:
    """Run Phase 4 on the saved records. Never writes to the source run."""
    if run.grounded and rag_session is None:
        raise SavedRunError(
            "This is a grounded run. Replay it with --rag, or its panel would "
            "answer without the documents the original had."
        )
    counter = CallCounter(make_runner())
    if counter.usage_log is not None:
        counter.usage_log.phase = "phase_4_debrief"
    transcript = await run_panel_debriefing(
        company=run.company,
        observation_summary=run.observation_summary,
        artefacts=run.artefacts,
        panel_agents=_panel_agents(run, roles, current_year),
        industry_context=run.industry_context,
        product_type=run.product_type,
        research_question=run.study.research_question,
        debriefer_model=debriefer_model,
        max_exchanges=max_exchanges,
        run_agent=counter,
        concurrent_shared_state=run.shared_state,
        study=run.study,
        rag_session=rag_session,
        role_memory=panel_memory(run),
        researcher_memory=build_researcher_memory(
            run.deliberation_text, run.field_notes, run.artefacts,
        ),
    )
    return transcript, counter


def write_replay(
    run: SavedRun, transcript: DebriefingTranscript, counter: CallCounter,
    out_dir: Path, *, roles: Optional[List[str]], max_exchanges: int,
    rag_session: Any = None,
) -> Path:
    if out_dir.resolve().is_relative_to(run.run_dir.resolve()):
        raise SavedRunError("Output must not go inside the source run.")
    out_dir.mkdir(parents=True, exist_ok=True)
    replay = transcript.model_dump(mode="json")
    _write_debriefing_transcript(out_dir, replay)
    original = run.transcript.model_dump(mode="json") if run.transcript else None
    (out_dir / "comparison.md").write_text(
        render_comparison(original, replay, list(run.study.flagged_vocabulary))
    )
    (out_dir / "replay_meta.json").write_text(json.dumps({
        "kind": "debrief_replay",
        "source_run": run.meta.get("run_id", run.run_dir.name),
        "study_slug": run.study.slug,
        "study_version": run.study.version,
        "roles": roles or "all",
        "max_exchanges": max_exchanges,
        "model_calls": counter.calls,
        "prompt_chars": counter.prompt_chars,
        "reply_chars": counter.reply_chars,
        "token_usage": counter.usage_log.summary() if counter.usage_log is not None else None,
        "grounded": rag_session is not None,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "limits": LIMIT_NOTE,
    }, indent=2))
    if counter.usage_log is not None and counter.usage_log.calls:
        usage_dir = out_dir / "08_usage"
        usage_dir.mkdir(exist_ok=True)
        counter.usage_log.write_jsonl(usage_dir / "token_usage.jsonl")
    if rag_session is not None:
        _write_rag_folder(out_dir, rag_session)
    return out_dir


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--max-exchanges", type=int, default=20)
    parser.add_argument("--roles", default=None, help="Comma-separated roles. Default: all six.")
    parser.add_argument("--current-year", type=int, default=2030)
    parser.add_argument("--model", default=None, help="Provider key. Default: TMT_PROVIDER.")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--allow-version-mismatch", action="store_true")
    parser.add_argument("--vertex", action="store_true", help="Route Gemini through Vertex AI.")
    parser.add_argument("--rag", action="store_true", help="Retrieve from the firm's corpus.")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.WARNING)
    args = _parse_args(argv)
    if args.vertex:
        try:
            from ..providers import enable_vertex
        except (ImportError, ValueError):  # pragma: no cover  (script-style)
            from providers import enable_vertex  # type: ignore[no-redef]
        enable_vertex(project=None, location=None)
    roles = [r.strip() for r in args.roles.split(",")] if args.roles else None
    try:
        run = load_saved_run(args.run_dir, allow_version_mismatch=args.allow_version_mismatch)
        rag_session = None
        if args.rag:
            try:
                from ..rag.runtime import build_rag_session_for_company
            except (ImportError, ValueError):  # pragma: no cover  (script-style)
                from rag.runtime import build_rag_session_for_company  # type: ignore[no-redef]
            rag_session = build_rag_session_for_company(study=run.study, company=run.company)
            if rag_session is None:
                raise SavedRunError(
                    f"--rag was set but no corpus could be opened for {run.company}."
                )
        transcript, counter = asyncio.run(replay_debrief(
            run,
            max_exchanges=args.max_exchanges,
            roles=roles,
            current_year=args.current_year,
            debriefer_model=args.model,
            rag_session=rag_session,
        ))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_dir = args.out_dir or Path("results/debrief_replays") / (
            f"{run.meta.get('run_id', run.run_dir.name)}_{stamp}"
        )
        write_replay(
            run, transcript, counter, out_dir,
            roles=roles, max_exchanges=args.max_exchanges, rag_session=rag_session,
        )
    except SavedRunError as exc:
        print(f"Cannot replay this run: {exc}", file=sys.stderr)
        return 2
    print((out_dir / "comparison.md").read_text())
    print(f"Saved to {out_dir}")
    return 1 if transcript.ended_reason == "error" else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
