"""End-of-deliberation artefact collection.

After the TMT deliberation concludes, each of the six role agents is
asked one more turn: 'Now produce your role's strategic document based
on the deliberation we just had.' Each agent emits one
`StrategicArtefact` (Pydantic-validated structured output). The six
together form the `ArtefactBundle` consumed by the qualitative
researcher and by you as principal investigator.

Key design points
-----------------
* The artefact agents are built ON TOP OF the existing `create_*_agent`
  factories so all the role-specific prompt content (functional
  portrait, scenario context, behavioural framing) carries through.
  We only add a thin instruction layer that asks for the structured
  document and constrains the output to `StrategicArtefact`.
* Schema is minimal (per user direction): `key_challenges`,
  `main_decisions`, `key_tensions` are the only structured lists; the
  rest of the document is free-form markdown the role authors itself.
* Each agent receives a *summary* of the deliberation log + the CEO's
  final synthesis, not the raw event stream — keeps prompt size bounded
  and lets each role focus on its own perspective.
* Runs are sequential by default to keep API rate-limit pressure low;
  switch to `asyncio.gather` if you need to parallelise on a higher
  tier of quota.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable, List, Optional

from google.adk.agents import LlmAgent

try:
    from ..providers import build_structured_agent, get_model
    from ..roles.artefact_schemas import ArtefactBundle, ArtefactRole, StrategicArtefact
    from ..data_capture import DeliberationLog
    from ..rag.schemas import RetrievedSnippet
    from ..rag.prompt_inject import format_retrieved_context
    from ..rag.queries import build_artefact_query
    from ..rag.runtime import RagSession
    from .role_memory import build_role_memory
except (ImportError, ValueError):  # pragma: no cover  (script-style execution)
    from providers import build_structured_agent, get_model  # type: ignore[no-redef]
    from roles.artefact_schemas import ArtefactBundle, ArtefactRole, StrategicArtefact  # type: ignore[no-redef]
    from data_capture import DeliberationLog  # type: ignore[no-redef]
    from rag.schemas import RetrievedSnippet  # type: ignore[no-redef]
    from rag.prompt_inject import format_retrieved_context  # type: ignore[no-redef]
    from rag.queries import build_artefact_query  # type: ignore[no-redef]
    from rag.runtime import RagSession  # type: ignore[no-redef]
    from orchestrator.role_memory import build_role_memory  # type: ignore[no-redef]

log = logging.getLogger(__name__)


# Description of what each role's document should *be about* (not what
# fields it must contain — the schema enforces those). Lets each role
# write a document that reads as authentic for its function.
#
# All framings ask for ELABORATE, COMPREHENSIVE documents in whatever
# depth the role's function demands — without leading the role toward
# a specific named approach (deliberate planning vs. agile vs. lean
# vs. design-science etc.) and WITHOUT enumerating a fixed list of
# strategic dimensions to address. Epistemic honesty is the binding
# rule: better to flag uncertainty than fabricate confidence.

_DEPTH_REMINDER = (
    "Write elaborately and comprehensively, in whatever depth YOUR "
    "role and the situation demand. Be specific where you have "
    "conviction; flag what you don't know and how you plan to find "
    "out (\"we don't know X yet — we plan to discover it by Y\") "
    "rather than fabricating confidence. Describe your team's "
    "strategic approach IN YOUR OWN WORDS — do not borrow a named "
    "methodology off the shelf."
)


_ROLE_DOC_FRAMING: dict[ArtefactRole, str] = {
    "CEO": (
        "A company strategy memo from the CEO. Document the firm's "
        "overall strategic position on this deliberation: where the "
        "firm should head, what choices the firm is making and why, "
        "how the firm intends to position itself, "
        "and (crucially) what the firm is choosing NOT to do. "
        "Surface the trade-offs and the uncertainties candidly. "
        "Write this as a memo you would circulate to your board "
        "knowing it will be read by skeptical directors.\n\n"
        + _DEPTH_REMINDER
    ),
    "CTO": (
        "A technology strategy document from the CTO. Document the "
        "technical position: the technical choices, the architectural "
        "reasoning, the engineering bets, and the technical risks. Be "
        "specific about what the architecture commits the firm to "
        "and what it leaves undecided. Write this as a technical strategy "
        "document for your engineering leads.\n\n"
        + _DEPTH_REMINDER
    ),
    "COO": (
        "An operations strategy document from the COO. Document the "
        "operational reality: resources, governance, scale-up plan, "
        "organisational implications, operational risks, and the "
        "decisions that need re-examination as the product matures. "
        "Be honest about what your operating model is good at and "
        "what it would struggle with. Write this as an operations "
        "plan for your functional leads.\n\n"
        + _DEPTH_REMINDER
    ),
    "CMO": (
        "A marketing & go-to-market document from the CMO. Document "
        "the customer and market reasoning: positioning, segmentation, "
        "GTM motion, brand implications, market risks, and the "
        "competitive picture as you currently understand it. Name "
        "your assumptions about the customer and how you plan to "
        "validate (or falsify) them. Write this as a market-strategy "
        "brief for your marketing team.\n\n"
        + _DEPTH_REMINDER
    ),
    "Product_Strategist": (
        "A product strategy document from the Product Strategist. "
        "Document the product thesis: who it is for, what it does, "
        "why now, why this firm, what shape it should take, and how "
        "product choices interact with the firm's broader direction. "
        "Articulate the product's evolution over time as you see it — "
        "knowing the picture will shift. Write this as a product "
        "strategy memo for your product team.\n\n"
        + _DEPTH_REMINDER
    ),
    "Product_Designer": (
        "A product / system design document from the Product Designer. "
        "Document the architecture and design choices: how components "
        "are arranged, the design "
        "principles guiding those choices, design trade-offs, and the "
        "user-facing implications of internal architectural decisions. "
        "Be explicit about what your design optimises for and what it "
        "trades away. Write this as a design document for your design "
        "and engineering peers.\n\n"
        + _DEPTH_REMINDER
    ),
}


def _build_artefact_prompt(
    role: ArtefactRole,
    company: str,
    industry_context: str,
    product_type: str,
    deliberation_summary: str,
    ceo_final_synthesis: str,
    retrieved_snippets: Optional[List[RetrievedSnippet]] = None,
    memory: str = "",
) -> str:
    """The user-turn prompt asking the role to author its artefact.

    `memory` is the whole discussion plus the role's own notes and draft.
    Without it the prompt falls back to `deliberation_summary` alone.

    `retrieved_snippets` is the RAG retrieval result for this role's
    artefact-authoring turn. When None or empty (the no-RAG default),
    the helper returns the empty string and the prompt is unchanged.
    `collect_role_artefacts` populates this from the role's per-turn
    Vertex retrieval when `--rag` was passed.
    """
    framing = _ROLE_DOC_FRAMING[role]
    reference_block = format_retrieved_context(role=role, snippets=retrieved_snippets)
    discussion_block = memory or (
        "THE TEAM'S DISCUSSION\n"
        "---------------------\n"
        f"{deliberation_summary}\n\n"
    )
    return f"""The TMT deliberation has concluded. As {role} of {company},
write your role's strategic document for this deliberation.

DELIBERATION CONTEXT
--------------------
- Firm: {company}
- Industry context: {industry_context}
- Product type: {product_type}

{discussion_block}CEO'S FINAL SYNTHESIS
---------------------
{ceo_final_synthesis}

{reference_block}
YOUR TASK
---------
{framing}

The structured fields below MUST be filled regardless of how you choose
to structure the body:
  - title             : a short title for your document.
  - key_challenges    : the problems you saw as needing solving.
  - main_decisions    : the calls you made or strongly recommended.
  - key_tensions      : the trade-offs you wrestled with.
  - body              : Markdown — your document. You choose the
                        sections and structure. Write it from YOUR
                        role's perspective, in your own voice.

Return ONLY the JSON object conforming to the StrategicArtefact schema.
"""


def _build_artefact_agent(
    base_agent: LlmAgent,
    role: ArtefactRole,
) -> LlmAgent:
    """Wrap an existing role agent so its next turn emits a StrategicArtefact.

    We inherit the base agent's `instruction` (the functional portrait)
    and `model` so the document reads in the role's voice, then pin the
    output schema. The agent's `name` is kept identical so logs remain
    coherent across deliberation and artefact phases.
    """
    base_instruction = getattr(base_agent, "instruction", "") or ""
    return build_structured_agent(
        name=f"{role}_Artefact",
        model=getattr(base_agent, "model", get_model()),
        instruction=(
            base_instruction
            + "\n\nARTEFACT PHASE\n"
              "You are now authoring a structured strategic document as "
              f"output for the deliberation that just concluded. Stay "
              f"in {role} voice. The schema is enforced — fill every "
              "required field."
        ),
        description=f"{role} artefact author — emits a StrategicArtefact.",
        output_schema=StrategicArtefact,
    )


# Type alias for the runner callable. Keeps `agent.py` and tests free
# to pass either ADK's Runner or a stub that returns canned events.
RunnerFn = Callable[..., Awaitable]


async def collect_role_artefacts(
    *,
    role_agents: dict[ArtefactRole, LlmAgent],
    deliberation_log: DeliberationLog,
    ceo_final_synthesis: str,
    company: str,
    industry_context: str,
    product_type: str,
    run_agent: RunnerFn,
    researcher_stream: Optional["object"] = None,
    rag_session: Optional["RagSession"] = None,
    role_states: Optional[dict] = None,
) -> ArtefactBundle:
    """Ask each of the six role agents to author its strategic document.

    Args:
        role_agents: Map from role name to the existing TMT `LlmAgent`
            (typically from `TMTSystemWithA2A.agents`).
        deliberation_log: The structured deliberation record.
        ceo_final_synthesis: The CEO's final text from
            `run_strategic_discussion`.
        company / industry_context / product_type: Scenario context.
        run_agent: Awaitable that runs an `LlmAgent` against a single
            prompt and returns its structured output (parsed
            `StrategicArtefact`). Injected so tests can supply a stub
            and production can use the real ADK Runner.
        researcher_stream: Optional ResearcherStream. When provided,
            each successfully-authored artefact is fed (silently) to
            the stream and a flush is triggered, so the live-
            ethnographer sees the artefacts as they are produced
            during the run.
        role_states: Each role's private notes and draft from the
            deliberation, in the shape `_snapshot_private_channel` writes.
            A role reads its own and no one else's.

    Returns:
        An `ArtefactBundle` containing one `StrategicArtefact` per role.
        Roles that fail to produce a valid artefact (validation error,
        rate limit, etc.) are logged and skipped; the bundle is still
        returned so partial failure doesn't lose the whole session.
    """
    deliberation_summary = deliberation_log.as_plain_transcript()
    memory = build_role_memory(role_agents, deliberation_summary, role_states)
    artefacts: list[StrategicArtefact] = []

    for role, base_agent in role_agents.items():
        if role not in _ROLE_DOC_FRAMING:
            log.warning("Unknown role %s — skipping artefact collection.", role)
            continue

        artefact_agent = _build_artefact_agent(base_agent, role)

        # RAG: retrieve before composing this role's artefact prompt.
        # Empty list when no rag_session — the prompt-inject helper
        # then returns "" and the prompt is unchanged.
        retrieved: List[RetrievedSnippet] = []
        if rag_session is not None and rag_session.enabled:
            query = build_artefact_query(
                role=role, company=company,
                deliberation_summary=deliberation_summary,
                industry_context=industry_context,
                product_type=product_type,
            )
            retrieved = await rag_session.retrieve_for_role(
                role=role, query=query, phase="phase_2_artefact",
            )

        prompt = _build_artefact_prompt(
            role=role,
            company=company,
            industry_context=industry_context,
            product_type=product_type,
            deliberation_summary=deliberation_summary,
            ceo_final_synthesis=ceo_final_synthesis,
            retrieved_snippets=retrieved or None,
            memory=memory[role],
        )

        # Run with transient-error retry-with-backoff. Phase 2 was
        # historically the SECOND phase (after Phase 4) to lose work
        # to transient 429s — the Meta-2032 cell post-mortem caught
        # CMO + Product_Designer artefacts being dropped here. The
        # shared `llm_retry.safe_run` returns None either on a non-
        # transient error (auth / 400 / 404) or once retries are
        # exhausted; the existing `continue` path handles None the
        # same way it always did.
        try:
            from .llm_retry import safe_run as _safe_run_with_retry
        except (ImportError, ValueError):  # pragma: no cover  (script-style)
            from orchestrator.llm_retry import safe_run as _safe_run_with_retry  # type: ignore[no-redef]

        result = await _safe_run_with_retry(run_agent, artefact_agent, prompt)
        if result is None:
            # safe_run already logged the failure context; continue to
            # the next role rather than dropping the whole bundle.
            log.warning(
                "Artefact collection for %s returned None after retries; "
                "skipping this role's artefact.",
                role,
            )
            continue

        # `run_agent` returns either a parsed StrategicArtefact, a dict, or a
        # JSON string. Normalise to a model instance.
        artefact = _coerce_artefact(result, role=role, company=company,
                                    industry_context=industry_context,
                                    product_type=product_type)
        if artefact is not None:
            artefacts.append(artefact)
            # Feed the freshly-authored artefact to the researcher
            # stream so the live-ethnographer's session sees what
            # each role committed to.
            if researcher_stream is not None:
                try:
                    from .researcher_stream import format_artefact
                except (ImportError, ValueError):  # pragma: no cover
                    from orchestrator.researcher_stream import format_artefact  # type: ignore[no-redef]
                researcher_stream.observe(format_artefact(role, artefact))
                await researcher_stream.flush_if_due()

    return ArtefactBundle(
        company=company,
        industry_context=industry_context,
        product_type=product_type,
        artefacts=artefacts,
    )


def _coerce_artefact(
    raw: object,
    *,
    role: ArtefactRole,
    company: str,
    industry_context: str,
    product_type: str,
) -> Optional[StrategicArtefact]:
    """Normalise the runner's return value into a StrategicArtefact.

    Accepts:
      - already-validated StrategicArtefact (passthrough)
      - dict
      - JSON string
    Logs and returns None if the value cannot be coerced.
    """
    if isinstance(raw, StrategicArtefact):
        return raw
    if isinstance(raw, dict):
        payload = dict(raw)
    elif isinstance(raw, str):
        # Strip ```json … ``` fences and any prose framing — providers in
        # `json_object` mode (DeepSeek, Ollama) are not schema-enforced
        # server-side, so the parser is the enforcement boundary.
        cleaned = _strip_json_envelope(raw)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            log.error("Artefact JSON parse failed for %s: %s", role, exc)
            return None
    else:
        log.error("Unexpected artefact return type for %s: %s", role, type(raw))
        return None

    # Ensure scenario context is set even if the model omitted it.
    payload.setdefault("role", role)
    payload.setdefault("company", company)
    payload.setdefault("industry_context", industry_context)
    payload.setdefault("product_type", product_type)

    try:
        return StrategicArtefact.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        log.error("Artefact validation failed for %s: %s", role, exc)
        return None


def _strip_json_envelope(text: str) -> str:
    """Strip ```json … ``` fences and any prose framing around a JSON object.

    Tolerates the two common quirks seen on `json_object`-mode providers
    (DeepSeek, Ollama) where the model returns either a fenced code
    block or a JSON object preceded/followed by a sentence of prose:

      ``` ```json
      {"foo": 1}
      ``` ```
      → '{"foo": 1}'

      Here is your artefact:
      {"foo": 1}
      → '{"foo": 1}'

    If no JSON-looking content is found, returns the input unchanged
    (caller will surface the resulting `JSONDecodeError`).
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()
    # Trim surrounding prose by slicing to the outermost {...}, if present.
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if 0 <= first_brace < last_brace:
        return stripped[first_brace : last_brace + 1]
    return stripped
