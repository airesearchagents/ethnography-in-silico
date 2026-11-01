"""Ask how the debrief researcher would respond at one saved moment.

Give it a finished run (one complete simulated meeting and debrief) and an exchange
number (an exchange is one researcher question and the replies to it). The researcher
(the agent that questions the team) sees the debrief up to that point and proposes
its next question, as many times as you ask, and nothing goes to the panel (the six
simulated executives). This shows in about a minute whether a prompt (the text sent
to a language model) change makes it probe or move on, and repeating the turn
gives a rate instead of one example.

Usage
-----
    python -m analysis.researcher_turn_test --run-dir <path> \\
        --after-exchange 9 --repeats 10 --vertex

`--vertex` reaches Gemini (Google's language model) through Vertex AI (Google's paid
cloud service).

Limit: this test does not load the researcher's live field notes (running notes made
during the run), so its memory (earlier records copied into its prompt) here is the
observation summary (its single account of the team's discussion), documents and
private notes. A
result is a quick check on behaviour, not evidence for a paper.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List, Optional

try:
    from ..orchestrator import panel_debriefing as pd
    from ..orchestrator.role_memory import build_researcher_memory
    from ..roles.qualitative_researcher_agent import (
        _apply_study_overlay,
        _load_protocol,
        closing_area_id,
    )
    from .saved_run import (
        CallCounter,
        SavedRun,
        SavedRunError,
        load_saved_run,
        new_session_runner,
    )
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from orchestrator import panel_debriefing as pd  # type: ignore[no-redef]
    from orchestrator.role_memory import build_researcher_memory  # type: ignore[no-redef]
    from roles.qualitative_researcher_agent import (  # type: ignore[no-redef]
        _apply_study_overlay,
        _load_protocol,
        closing_area_id,
    )
    from analysis.saved_run import (  # type: ignore[no-redef]
        CallCounter,
        SavedRun,
        SavedRunError,
        load_saved_run,
        new_session_runner,
    )

log = logging.getLogger(__name__)

LIMIT_NOTE = (
    "This is a quick check on behaviour from a saved moment, not evidence for "
    "a paper. Runs saved before field notes were kept give the researcher none."
)


@dataclass
class TurnAttempt:
    area_id: str = ""
    is_followup: bool = False
    closes: bool = False
    ends_debriefing: bool = False
    emerging_question: str = ""
    text: str = ""
    failed: bool = False


@dataclass
class TurnTestResult:
    run_id: str
    after_exchange: int
    last_question: str
    attempts: List[TurnAttempt] = field(default_factory=list)
    calls: int = 0
    prompt_chars: int = 0
    reply_chars: int = 0

    @property
    def completed(self) -> List[TurnAttempt]:
        return [a for a in self.attempts if not a.failed]


def _transcript_up_to(run: SavedRun, after_exchange: int) -> pd.DebriefingTranscript:
    saved = run.transcript
    if saved is None:
        raise SavedRunError(f"{run.run_dir} has no debrief transcript to start from.")
    if not 0 <= after_exchange <= len(saved.exchanges):
        raise SavedRunError(
            f"--after-exchange must be from 0 to {len(saved.exchanges)}; "
            f"got {after_exchange}."
        )
    return saved.model_copy(deep=True, update={
        "exchanges": [e.model_copy(deep=True) for e in saved.exchanges[:after_exchange]],
        "forbidden_vocab_violations": 0,
        "ended_reason": "",
    })


async def _one_attempt(
    run: SavedRun,
    after_exchange: int,
    make_runner: Callable[[], Any],
    counter_box: list,
    debriefer_model: Optional[str],
) -> TurnAttempt:
    transcript = _transcript_up_to(run, after_exchange)
    protocol = _apply_study_overlay(_load_protocol(), run.study)
    closing = closing_area_id(protocol)
    debriefer = pd._build_debriefer(
        company=run.company,
        observation_summary=run.observation_summary,
        artefacts=run.artefacts,
        industry_context=run.industry_context,
        product_type=run.product_type,
        model=debriefer_model,
        concurrent_shared_state=run.shared_state,
        study=run.study,
    )
    panel_format = protocol.get("panel_format", {})
    coverage = pd._render_coverage_map(
        transcript,
        all_areas=[a["id"] for a in protocol.get("thematic_areas", []) if a.get("id")] or None,
        closing_area=closing,
        traversal_mode=panel_format.get("area_traversal_mode", "free"),
        target_exchanges=panel_format.get("target_exchanges"),
    )
    counter = CallCounter(make_runner())
    counter_box.append(counter)
    utterance = await pd._next_researcher_utterance(
        debriefer=debriefer,
        history_block=pd._render_transcript_for_prompt(transcript),
        coverage_block=coverage,
        run_agent=counter,
        panelist_quotes_history=[
            r.text for e in transcript.exchanges for r in e.responses
        ],
        transcript=transcript,
        study=run.study,
        researcher_memory=build_researcher_memory(
            run.deliberation_text, run.field_notes, run.artefacts,
        ),
    )
    if utterance is None:
        return TurnAttempt(failed=True)
    return TurnAttempt(
        area_id=utterance.area_id,
        is_followup=utterance.is_followup,
        closes=utterance.area_id == closing,
        ends_debriefing=utterance.ends_debriefing,
        emerging_question=utterance.emerging_question,
        text=utterance.text,
    )


async def run_turn_test(
    run: SavedRun,
    *,
    after_exchange: int,
    repeats: int = 10,
    concurrency: int = 2,
    make_runner: Callable[[], Any] = new_session_runner,
    debriefer_model: Optional[str] = None,
) -> TurnTestResult:
    """Ask for the researcher's next question `repeats` times, independently."""
    transcript = _transcript_up_to(run, after_exchange)
    last = transcript.exchanges[-1].utterance.text if transcript.exchanges else ""
    gate = asyncio.Semaphore(concurrency)
    counters: list = []

    async def guarded() -> TurnAttempt:
        async with gate:
            return await _one_attempt(
                run, after_exchange, make_runner, counters, debriefer_model,
            )

    attempts = await asyncio.gather(*(guarded() for _ in range(repeats)))
    return TurnTestResult(
        run_id=run.meta.get("run_id", run.run_dir.name),
        after_exchange=after_exchange,
        last_question=last,
        attempts=list(attempts),
        calls=sum(c.calls for c in counters),
        prompt_chars=sum(c.prompt_chars for c in counters),
        reply_chars=sum(c.reply_chars for c in counters),
    )


def render_report(result: TurnTestResult) -> str:
    done = result.completed
    followups = sum(a.is_followup for a in done)
    closes = sum(a.closes for a in done)
    emerging = sum(bool(a.emerging_question) for a in done)
    lines = [
        "# Researcher turn test",
        f"**Run:** {result.run_id}",
        f"**After exchange:** {result.after_exchange}",
        f"**Last question asked:** {result.last_question or '(start of debrief)'}",
        "",
        f"- Follow-ups: {followups} of {len(done)}",
        f"- Moved to the closing area: {closes} of {len(done)}",
        f"- Recorded a new question: {emerging} of {len(done)}",
        f"- Failed attempts: {len(result.attempts) - len(done)}",
        f"- Model calls: {result.calls} ({result.prompt_chars:,} prompt characters, "
        f"{result.reply_chars:,} reply characters)",
        "",
        f"_{LIMIT_NOTE}_",
        "",
        "## Proposed questions",
        "",
    ]
    for i, a in enumerate(result.attempts, 1):
        if a.failed:
            lines.append(f"{i}. (failed)")
            continue
        tag = "follow-up" if a.is_followup else "new line"
        lines.append(f"{i}. **Area {a.area_id}, {tag}:** {a.text}")
        if a.emerging_question:
            lines.append(f"   - _New question:_ {a.emerging_question}")
    return "\n".join(lines) + "\n"


def _write(result: TurnTestResult, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(render_report(result))
    (out_dir / "result.json").write_text(json.dumps(asdict(result), indent=2))
    return out_dir


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--after-exchange", type=int, required=True,
                        help="Exchanges to keep before the researcher's turn; 0 is the opening.")
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--model", default=None, help="Provider key. Default: TMT_PROVIDER.")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--allow-version-mismatch", action="store_true")
    parser.add_argument("--vertex", action="store_true", help="Route Gemini through Vertex AI.")
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
    try:
        run = load_saved_run(args.run_dir, allow_version_mismatch=args.allow_version_mismatch)
        result = asyncio.run(run_turn_test(
            run,
            after_exchange=args.after_exchange,
            repeats=args.repeats,
            concurrency=args.concurrency,
            debriefer_model=args.model,
        ))
    except SavedRunError as exc:
        print(f"Cannot run this test: {exc}", file=sys.stderr)
        return 2
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = args.out_dir or Path("results/turn_tests") / (
        f"{result.run_id}_after{args.after_exchange}_{stamp}"
    )
    _write(result, out_dir)
    print(render_report(result))
    print(f"Saved to {out_dir}")
    return 0 if result.completed else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
