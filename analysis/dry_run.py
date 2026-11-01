"""Run the whole pipeline on a stand-in model: no network, no cost.

Uses the real framework (the shared software in this repository) and the real
prompts (the text sent to a language model), with a stand-in for the model
that records what it was sent and returns text of a realistic length. It shows
how large each call (one prompt and one reply) is, what a run (one complete
simulated meeting and debrief) would cost at list prices (the published rates of
the company supplying the model), and whether any
call carries earlier messages. With --save-prompts you can read each prompt.
--rag adds stand-in passages to each call, and --max-exchanges caps the debrief's questions.

    python -m analysis.dry_run
    python -m analysis.dry_run --rag --max-exchanges 20 --save-prompts <folder>

It checks wiring (whether the parts connect) and size, not behaviour, because the
stand-in's text is filler.
Real text can run longer or shorter, so treat its cost as a rough guide.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import typing
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.models.registry import LLMRegistry
from google.genai import types
from pydantic import BaseModel

try:
    from .. import run_research_session as session_module
    from ..orchestrator import rate_limit
    from ..rag import runtime as rag_runtime
    from ..rag import vertex_corpus
    from ..rag.schemas import RetrievedSnippet
    from ..studies import DEFAULT_STUDY_SLUG, load_study
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    import run_research_session as session_module  # type: ignore[no-redef]
    from orchestrator import rate_limit  # type: ignore[no-redef]
    from rag import runtime as rag_runtime  # type: ignore[no-redef]
    from rag import vertex_corpus  # type: ignore[no-redef]
    from rag.schemas import RetrievedSnippet  # type: ignore[no-redef]
    from studies import DEFAULT_STUDY_SLUG, load_study  # type: ignore[no-redef]

# Lengths in characters, close to those in the saved runs.
SPEAK_CHARS = 900
NOTE_CHARS = 150
DRAFT_CHARS = 2500
ANSWER_CHARS = 700
FIELD_NOTE_CHARS = 800
DOCUMENT_CHARS = 7000
PASSAGE_CHARS = 4000
# About 2.7 of the six roles (simulated executives) answered each debrief question
# (asked when the researcher agent interviews the team) in run D (one of four test runs).
ANSWERS_PER_SEVEN_CALLS = 3
# Filler avoids every word on the study's list, so the question screen
# (the check of researcher questions against that list) passes.
FILLER = "the team weighed the plan and the cost and the customer and the timing again "


def _question(number: int) -> str:
    """Different enough each time to pass the repeat check, as real questions do."""
    words = ("pricing", "staffing", "launch", "legal", "support", "hiring", "partners", "budget",
             "security", "training", "sales", "design", "testing", "vendors", "roadmap", "risk",
             "metrics", "regions", "contracts", "reflection")
    first = words[number % len(words)]
    second = words[(number * 7 + 3) % len(words)]
    return f"Question {number}: how did {first} shape the choice on {second}?"


def _filler(chars: int, seed: int = 0) -> str:
    return (f"Point {seed}: " + FILLER * (chars // len(FILLER) + 1))[:chars]


def _fill(model: Any, overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Valid JSON (plain-text structured data) for a schema (a template of required fields): every required
    field, with short filler."""
    values: Dict[str, Any] = {}
    for name, field in model.model_fields.items():
        if name in overrides:
            values[name] = overrides[name]
        elif field.is_required():
            values[name] = _value_for(field.annotation)
    return values


def _value_for(annotation: Any) -> Any:
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is typing.Literal:
        return args[0]
    if origin in (list, List):
        return [_value_for(args[0])] if args else []
    if origin is typing.Union:
        return _value_for(next(a for a in args if a is not type(None)))
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _fill(annotation, {})
    if annotation is bool:
        return False
    if annotation is int:
        return 0
    return "Stand-in text."


def _kind_of_call(schema: Any, prompt: str) -> str:
    """A readable name for one model call, for the saved prompt's file name."""
    if schema is None:
        return "field_note" if "LIVE OBSERVATION" in prompt else "panel_answer"
    return {
        "AgentAction": "deliberation",
        "StrategicArtefact": "document",
        "ObservationSummary": "observation",
        "PanelUtterance": "researcher_question",
    }.get(getattr(schema, "__name__", ""), "other")


class Recorder:
    """What the stand-in model was sent, and what it should say next."""

    def __init__(self, save_to: Optional[Path], actions_per_role: int) -> None:
        self.save_to = save_to
        self.actions_per_role = actions_per_role
        self.calls = 0
        self.with_earlier_messages = 0
        self.actions: Dict[str, int] = {}
        self.panel_calls = 0
        self.questions = 0
        if save_to:
            save_to.mkdir(parents=True, exist_ok=True)

    def note(self, request: Any) -> str:
        """Count the call, save its prompt, and return its text."""
        self.calls += 1
        contents = request.contents or []
        if len(contents) > 1:
            self.with_earlier_messages += 1
        text = "\n\n".join(
            part.text for content in contents for part in (content.parts or []) if part.text
        )
        instruction = str(getattr(request.config, "system_instruction", "") or "")
        if self.save_to:
            kind = _kind_of_call(getattr(request.config, "response_schema", None), text)
            (self.save_to / f"{self.calls:04d}_{kind}.txt").write_text(
                f"=== SYSTEM INSTRUCTION ===\n{instruction}\n\n=== MESSAGE ===\n{text}\n"
            )
        return instruction + text

    def action(self, prompt: str) -> str:
        role = re.search(r"You are the (\w+) of", prompt)
        role = role.group(1) if role else "?"
        count = self.actions.get(role, 0)
        self.actions[role] = count + 1
        if count + 1 >= self.actions_per_role:
            return json.dumps({"kind": "DONE", "text": "Done."})
        kind = ("SPEAK", "SCRATCHPAD", "DRAFT")[count % 3]
        chars = {"SPEAK": SPEAK_CHARS, "SCRATCHPAD": NOTE_CHARS, "DRAFT": DRAFT_CHARS}[kind]
        return json.dumps({"kind": kind, "text": _filler(chars, count)})

    def utterance(self, model: Any) -> str:
        self.questions += 1
        return json.dumps(_fill(model, {
            "area_id": "A",
            "addressed_to": "group",
            "text": _question(self.questions),
            "research_question_link": "Stand-in link.",
        }))

    def plain(self, prompt: str) -> str:
        if "LIVE OBSERVATION" in prompt:
            return _filler(FIELD_NOTE_CHARS)
        self.panel_calls += 1
        if self.panel_calls % 7 < ANSWERS_PER_SEVEN_CALLS:
            return _filler(ANSWER_CHARS, self.panel_calls)
        return "[PASS]"

    def reply(self, schema: Any, prompt: str) -> str:
        name = getattr(schema, "__name__", "")
        if name == "AgentAction":
            return self.action(prompt)
        if name == "PanelUtterance":
            return self.utterance(schema)
        if name == "StrategicArtefact":
            role = re.search(r"As (\w+) of", prompt)
            return json.dumps(_fill(schema, {
                "role": role.group(1) if role else "CEO",
                "company": "Stand-in",
                "industry_context": "Dynamic",
                "product_type": "Novel",
                "title": "Stand-in document",
                "key_challenges": ["A challenge."],
                "main_decisions": ["A decision."],
                "key_tensions": ["A tension."],
                "body": _filler(DOCUMENT_CHARS),
            }))
        if schema is not None:
            return json.dumps(_fill(schema, {}))
        return self.plain(prompt)


def _stand_in_model(recorder: Recorder) -> type:
    class StandIn(BaseLlm):
        async def generate_content_async(
            self, llm_request: Any, stream: bool = False,
        ) -> AsyncGenerator[LlmResponse, None]:
            prompt = recorder.note(llm_request)
            reply = recorder.reply(getattr(llm_request.config, "response_schema", None), prompt)
            yield LlmResponse(
                content=types.Content(role="model", parts=[types.Part(text=reply)]),
                usage_metadata=types.GenerateContentResponseUsageMetadata(
                    prompt_token_count=len(prompt) // 4,
                    candidates_token_count=len(reply) // 4,
                ),
            )

    return StandIn


def _install_stand_ins(recorder: Recorder) -> None:
    """Point the framework at the stand-in model, store (of firm documents to
    search) and rate limiter (which paces calls to stay under a provider's cap)."""
    model_class = _stand_in_model(recorder)
    LLMRegistry.new_llm = staticmethod(lambda model: model_class(model=model))  # type: ignore[assignment]

    async def _no_wait(*_: Any, **__: Any) -> float:
        return 0.0

    rate_limit.acquire_for_call = _no_wait  # type: ignore[assignment]

    def _retrieve(corpus: str, query: str, top_k: int = 5) -> List[RetrievedSnippet]:
        return [
            RetrievedSnippet(
                doc_id=f"document_{i}.txt",
                doc_display_name=f"document_{i}.txt",
                chunk_id=f"document_{i}.txt#{i}",
                text=_filler(PASSAGE_CHARS, i),
                score=0.3,
            )
            for i in range(top_k)
        ]

    vertex_corpus.retrieve = _retrieve  # type: ignore[assignment]
    rag_runtime.build_rag_session_for_company = (  # type: ignore[assignment]
        lambda *, study, company: rag_runtime.RagSession(corpus_name="dry-run")
    )


def report(out: Any, recorder: Recorder) -> str:
    usage = out.usage_log.summary()
    lines = [
        "| Phase | Calls | Input tokens | Largest call | List cost |",
        "|---|---|---|---|---|",
    ]
    for name, phase in usage["by_phase"].items():
        lines.append(
            f"| {name} | {phase['calls']} | {phase['input_tokens']:,} | "
            f"{phase['largest_call_input_tokens']:,} | ${phase['list_cost_usd'] or 0:.2f} |"
        )
    lines += [
        f"| All | {usage['calls']} | {usage['input_tokens']:,} | "
        f"{usage['largest_call_input_tokens']:,} | ${usage['list_cost_usd'] or 0:.2f} |",
        "",
        f"Calls carrying earlier messages: {recorder.with_earlier_messages}",
        f"Calls over 200,000 input tokens: {usage['calls_over_200k']}",
        f"Debrief exchanges: {len(out.debriefing_transcript.exchanges) if out.debriefing_transcript else 0}",
        f"Errors: {out.errors or 'none'}",
    ]
    return "\n".join(lines)


async def dry_run(args: argparse.Namespace) -> tuple[Any, Recorder]:
    try:
        from ..orchestrator.concurrent_mode import ConcurrentConfig
        from ..orchestrator.deliberation import DeliberationConfig
    except (ImportError, ValueError):  # pragma: no cover  (script-style)
        from orchestrator.concurrent_mode import ConcurrentConfig  # type: ignore[no-redef]
        from orchestrator.deliberation import DeliberationConfig  # type: ignore[no-redef]
    recorder = Recorder(args.save_prompts, args.max_actions_per_role)
    _install_stand_ins(recorder)
    out = await session_module.run_research_session(
        company=args.company,
        study=load_study(args.study),
        max_debriefing_exchanges=args.max_exchanges,
        use_rag=args.rag,
        deliberation_config=DeliberationConfig(
            concurrent=ConcurrentConfig(max_actions_per_role=args.max_actions_per_role + 1),
        ),
    )
    return out, recorder


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--study", default=DEFAULT_STUDY_SLUG)
    parser.add_argument("--company", default="OpenAI")
    parser.add_argument("--rag", action="store_true", help="Add stand-in passages to each call.")
    parser.add_argument("--max-exchanges", type=int, default=20)
    parser.add_argument("--max-actions-per-role", type=int, default=12)
    parser.add_argument("--save-prompts", type=Path, default=None, help="Save every prompt here.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.ERROR)
    out, recorder = asyncio.run(dry_run(args))
    print(report(out, recorder))
    return 1 if recorder.with_earlier_messages or out.errors else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
