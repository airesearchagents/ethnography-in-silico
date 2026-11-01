"""Ask a saved panel the same questions under different conditions.

The panel is the six role agents (simulated executives) when questioned in the
debrief, the interview that ends a run (one complete simulated meeting and debrief).

Tests whether different roles are really different voices. It takes group
questions from a finished ungrounded run (one without firm documents), gives each
role its saved memory (earlier records copied into its prompt, the text sent to a
language model), and records the answers, without running a researcher (the agent
that questions the team):

  baseline   every role answers each question twice, as independent samples,
             so differences between roles can be compared with differences
             a role has with itself
  isolated   as baseline, but each role sees only its own earlier debrief
             answers, not the other roles'
  mixed      as baseline, with the models set by `--mix`

Usage
-----
    python -m analysis.panel_probe --run-dir <path> --vertex \\
        --questions 4 --mix CTO=openai,COO=openai,CMO=deepseek,Product_Designer=deepseek

`--vertex` reaches Gemini (Google's language model) through Vertex AI (Google's paid
cloud service). Output goes to `results/panel_probes/`. The source run is never changed.

Limits: every condition still shares the saved deliberation (the team's discussion),
and retrieval (searching firm documents) is absent. One small sample per condition
shows direction, not an effect size.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from ..orchestrator import panel_debriefing as pd
    from ..roles.researcher_schemas import PanelExchange
    from .provenance import _mean, _vectors, cosine, role_similarity
    from .replay_debrief import _panel_agents, panel_memory
    from .saved_run import (
        CallCounter, SavedRun, SavedRunError, load_saved_run, new_session_runner,
    )
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from orchestrator import panel_debriefing as pd  # type: ignore[no-redef]
    from roles.researcher_schemas import PanelExchange  # type: ignore[no-redef]
    from analysis.provenance import _mean, _vectors, cosine, role_similarity  # type: ignore[no-redef]
    from analysis.replay_debrief import _panel_agents, panel_memory  # type: ignore[no-redef]
    from analysis.saved_run import (  # type: ignore[no-redef]
        CallCounter, SavedRun, SavedRunError, load_saved_run, new_session_runner,
    )

log = logging.getLogger(__name__)

LIMIT_NOTE = (
    "Every condition shares the saved deliberation, and retrieval is absent. "
    "One small sample per condition shows direction, not an effect size."
)


def choose_questions(run: SavedRun, count: int) -> List[int]:
    """Indexes of group questions most of the panel answered, evenly spread."""
    exchanges = run.transcript.exchanges if run.transcript else []
    eligible = [
        i for i, exchange in enumerate(exchanges)
        if exchange.utterance.addressed_to == "group" and len(exchange.responses) >= 4
    ]
    if len(eligible) <= count:
        return eligible
    step = (len(eligible) - 1) / max(count - 1, 1)
    return [eligible[round(step * i)] for i in range(count)]


def history_for(run: SavedRun, index: int, role: str, *, isolated: bool) -> str:
    """The saved debrief before this question, optionally without other roles' answers."""
    earlier = pd.DebriefingTranscript(company=run.company, research_question="")
    for exchange in run.transcript.exchanges[:index]:
        responses = [
            r for r in exchange.responses if not isolated or r.role == role
        ]
        earlier.exchanges.append(
            PanelExchange(utterance=exchange.utterance, responses=responses)
        )
    return pd._render_transcript_for_prompt(earlier)


async def probe_condition(
    run: SavedRun,
    questions: List[int],
    *,
    isolated: bool,
    repeats: int,
    make_runner: Callable[[], Any],
    agents: dict,
    pause: float = 0.0,
) -> tuple[List[dict], int, int]:
    """Ask each role each question. Failed calls are counted, never treated as silence."""
    answers: List[dict] = []
    memory = panel_memory(run)
    calls = 0
    lost = 0
    for repeat in range(repeats):
        # New sessions (a session is a stored conversation re-sent to the model, here starting empty),
        # so one sample cannot read the other.
        counter = CallCounter(make_runner())
        for index in questions:
            utterance = run.transcript.exchanges[index].utterance
            for role, agent in agents.items():
                addressed = utterance.model_copy(update={"addressed_to": role})
                lost_roles: List[str] = []
                response = await pd._single_panellist_response(
                    role=role, agent=agent, utterance=addressed,
                    history_block=history_for(run, index, role, isolated=isolated),
                    artefacts=run.artefacts, run_agent=counter,
                    is_cross_talk=False, lost_roles=lost_roles,
                    memory=memory.get(role, ""),
                )
                lost += len(lost_roles)
                if response is not None:
                    answers.append({
                        "question": index + 1, "repeat": repeat,
                        "role": role, "text": response.text,
                    })
                if pause:
                    await asyncio.sleep(pause)
        calls += counter.calls
    return answers, calls, lost


def measure(answers: List[dict]) -> dict:
    """Compare different roles with a role's own second sample, on the same question."""
    first = [a for a in answers if a["repeat"] == 0]
    result = role_similarity([(a["question"], a["role"], a["text"]) for a in first])
    vectors = _vectors([a["text"] for a in answers])
    between: List[float] = []
    within: List[float] = []
    for i, j in combinations(range(len(answers)), 2):
        a, b = answers[i], answers[j]
        if a["question"] != b["question"]:
            continue
        if a["role"] == b["role"] and a["repeat"] != b["repeat"]:
            within.append(cosine(vectors[i], vectors[j]))
        elif a["role"] != b["role"] and a["repeat"] == b["repeat"]:
            between.append(cosine(vectors[i], vectors[j]))
    result["between_roles_same_sample"] = _mean(between)
    result["same_role_second_sample"] = _mean(within)
    return result


def parse_mix(text: Optional[str]) -> Dict[str, str]:
    if not text:
        return {}
    pairs = [item.split("=", 1) for item in text.split(",") if item.strip()]
    if any(len(pair) != 2 for pair in pairs):
        raise SavedRunError("--mix takes ROLE=provider pairs separated by commas.")
    return {role.strip(): provider.strip() for role, provider in pairs}


def _set_mix(mix: Dict[str, str]) -> Dict[str, Optional[str]]:
    previous = {}
    for role, provider in mix.items():
        key = f"TMT_PROVIDER_{role.upper()}"
        previous[key] = os.environ.get(key)
        os.environ[key] = provider
    return previous


def _restore_mix(previous: Dict[str, Optional[str]]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


async def run_probe(
    run: SavedRun, *, question_count: int, mix: Dict[str, str], current_year: int,
    make_runner: Callable[[], Any] = new_session_runner,
) -> dict:
    if run.grounded:
        raise SavedRunError("A probe has no retrieval, so it refuses grounded runs.")
    questions = choose_questions(run, question_count)
    if not questions:
        raise SavedRunError("No group question in this run was answered by most of the panel.")
    report: Dict[str, Any] = {"questions": [q + 1 for q in questions], "conditions": {}}
    plan = [("baseline", False, {}), ("isolated", True, {})]
    if mix:
        plan.append(("mixed", False, mix))
    for name, isolated, condition_mix in plan:
        previous = _set_mix(condition_mix)
        try:
            agents = _panel_agents(run, None, current_year)
            answers, calls, lost = await probe_condition(
                run, questions, isolated=isolated, repeats=2,
                make_runner=make_runner, agents=agents,
            )
        finally:
            _restore_mix(previous)
        report["conditions"][name] = {
            "mix": condition_mix, "calls": calls, "lost_answers": lost,
            "measures": measure(answers), "answers": answers,
        }
    return report


def render(report: dict) -> str:
    keys = (
        "between_roles_same_sample", "same_role_second_sample",
        "role_attribution_accuracy", "chance",
    )
    lines = [
        "# Panel probe", "", f"_{LIMIT_NOTE}_", "",
        f"Questions from exchanges {report['questions']}.", "",
        "| Measure | " + " | ".join(report["conditions"]) + " |",
        "|---|" + "---|" * len(report["conditions"]),
    ]
    for key in keys:
        cells = [str(c["measures"].get(key)) for c in report["conditions"].values()]
        lines.append(f"| {key.replace('_', ' ')} | " + " | ".join(cells) + " |")
    for row in ("calls", "lost_answers"):
        cells = [str(c[row]) for c in report["conditions"].values()]
        lines.append(f"| {row.replace('_', ' ')} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--questions", type=int, default=4)
    parser.add_argument("--mix", default=None, help="ROLE=provider pairs, comma separated.")
    parser.add_argument("--current-year", type=int, default=2030)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--allow-version-mismatch", action="store_true")
    parser.add_argument("--vertex", action="store_true", help="Route Gemini through Vertex AI.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    if args.vertex:
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
    try:
        run = load_saved_run(args.run_dir, allow_version_mismatch=args.allow_version_mismatch)
        report = asyncio.run(run_probe(
            run, question_count=args.questions, mix=parse_mix(args.mix),
            current_year=args.current_year,
        ))
    except (SavedRunError, ValueError) as exc:
        sys.exit(f"Cannot run the probe: {exc}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = args.out_dir or (
        Path(__file__).resolve().parent.parent / "results" / "panel_probes" / f"{args.run_dir.name}_{stamp}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "probe.json").write_text(json.dumps(report, indent=2))
    (out_dir / "probe.md").write_text(render(report))
    print(f"Wrote {out_dir / 'probe.md'}")


if __name__ == "__main__":
    main()
