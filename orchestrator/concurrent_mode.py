"""Concurrent multi-agent deliberation — supercharged-humans model.

The previous modes (CEO_LED, RANDOM_INITIATOR, PARALLEL_THEN_DISCUSS,
ROUND_ROBIN) are all turn-based: someone speaks, then someone else
speaks, in a fixed cadence. Real TMTs don't work that way. People
work on their own piece simultaneously, ask each other for inputs
mid-stream, get answers back asynchronously, and finish when their
own work is done. Six people, working in parallel, with a shared
public conversation thread and private notebooks.

This module implements that. Each role agent runs as its own
`asyncio.Task`, calling its LLM continuously (no sleep, no idle wait)
until it declares its own deliverable complete. Coordination happens
through a `SharedState` with locked mutations and a directed-message
inbox per role.

Public surface
--------------
- `SharedState`               — concurrent-safe state container.
- `AgentAction`               — what each role emits per LLM call.
- `DirectedMessage`           — inbox payload for ASK/ANSWER.
- `RoleTaskSpec`              — the artefact the role is trying to
                                 produce; determines DONE.
- `ConcurrentConfig`          — caps + flags (max_actions_per_role,
                                 max_wall_clock_seconds, etc.).
- `run_concurrent_mode(...)` — entry point. Returns a
                                       `DeliberationOutcome` matching
                                       the existing schema PLUS the
                                       per-role scratchpads, drafts,
                                       and inboxes for the researcher.

Design constraints (from the user's spec)
-----------------------------------------
* No sleep / wake. Each agent calls its LLM repeatedly until DONE.
* Shared transcript visible to all roles.
* Private per-role scratchpad NOT visible to peers (only to the
  researcher).
* Directed Q&A: an agent can ASK a specific peer; the peer sees the
  question in their inbox; they answer in their own time; the asker
  picks up the answer next time they read state.
* Non-deterministic ordering — true asyncio concurrency.
* Deadlock safety — no agent waits indefinitely. Stale inboxes (no
  ANSWER returned within K actions of the ASK) get a synthetic
  '[NO ANSWER]' marker so the asker can move on.
* Budget caps to bound worst-case LLM spend.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

from google.adk.agents import LlmAgent
from pydantic import BaseModel, Field

try:
    from ..data_capture import DeliberationEvent, DeliberationLog
    from ..providers import build_structured_agent
    from ..rag.schemas import Citation, RetrievedSnippet
    from ..rag.prompt_inject import format_retrieved_context
    from ..rag.queries import build_role_turn_query
    from ..rag.runtime import RagSession
    from .researcher_stream import ResearcherStream
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from data_capture import DeliberationEvent, DeliberationLog  # type: ignore[no-redef]
    from providers import build_structured_agent  # type: ignore[no-redef]
    from rag.schemas import Citation, RetrievedSnippet  # type: ignore[no-redef]
    from rag.prompt_inject import format_retrieved_context  # type: ignore[no-redef]
    from rag.queries import build_role_turn_query  # type: ignore[no-redef]
    from rag.runtime import RagSession  # type: ignore[no-redef]
    from orchestrator.researcher_stream import ResearcherStream  # type: ignore[no-redef]

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

LLM_FAILURES_REASON = "llm_failures"


class ConcurrentConfig(BaseModel):
    """Caps + flags for the concurrent deliberation runner."""

    max_actions_per_role: int = Field(
        30,
        description=(
            "Hard ceiling on the number of LLM-emitting actions a single "
            "role may take. After this the agent is forced to DONE on "
            "its next iteration. Bounds worst-case cost to "
            "6 * max_actions_per_role LLM calls."
        ),
    )
    max_consecutive_llm_failures: int = Field(
        5,
        description=(
            "A role whose model calls fail this many times in a row stops. "
            "Retired models and missing keys fail instantly and would "
            "otherwise spin until the wall-clock cap."
        ),
    )
    llm_failure_backoff_seconds: float = Field(
        2.0,
        description="First wait after a failed model call; doubles each time.",
    )
    max_wall_clock_seconds: int = Field(
        30 * 60,
        description=(
            "Hard ceiling on the total wall-clock duration of the "
            "deliberation. After this the orchestrator force-completes "
            "any still-running role agents and returns. Default 30 min: "
            "leaves room for the Gemini 429-retry sleeps (each retry "
            "naps for the provider's suggested delay, often 30-46s), "
            "while still bounding worst-case latency per run."
        ),
    )
    stale_question_threshold: int = Field(
        3,
        description=(
            "If an inbox ASK is not ANSWERed within this many actions "
            "of the addressee, the orchestrator stuffs a '[NO ANSWER]' "
            "marker into the asker's inbox so they can move on. "
            "Prevents one role indefinitely waiting on another."
        ),
    )
    poll_interval_seconds: float = Field(
        0.5,
        description=(
            "How often the orchestrator wakes to check global timing / "
            "deadlock state. Each role's own loop is independent; this "
            "only governs the outer monitor."
        ),
    )
    max_retries_per_call: int = Field(
        5,
        description=(
            "Number of times to retry a single LLM call on Gemini 429 "
            "RESOURCE_EXHAUSTED. Retries sleep for the suggested "
            "retryDelay from the error and do NOT consume an action "
            "slot (the action only counts after the call succeeds or "
            "exhausts retries). Caps total per-action wall-clock spent "
            "in throttling to roughly max_retries × suggested delay."
        ),
    )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ActionKind(str, Enum):
    SPEAK = "SPEAK"           # add to the public transcript
    ASK = "ASK"               # send a directed question to a peer
    ANSWER = "ANSWER"         # answer a peer's question (private or public)
    SCRATCHPAD = "SCRATCHPAD" # write a private note (no public effect)
    DRAFT = "DRAFT"           # update working draft of the role's artefact
    DONE = "DONE"             # the role has completed its task


class AgentAction(BaseModel):
    """A single action emitted by a role agent on one LLM call.

    Pydantic-validated so we can constrain the output. Each action
    corresponds to exactly one state mutation in the orchestrator.
    """

    kind: ActionKind = Field(
        ...,
        description="What the agent wants to do this step.",
    )
    text: Optional[str] = Field(
        None,
        description=(
            "SPEAK: the public utterance, ~120-180 words. Make three "
            "things visible: (a) your position — the call you are making; "
            "(b) your reasoning — the assumptions, trade-offs, and "
            "evidence behind it (why this and not the alternative; what "
            "are you trusting that you cannot yet verify?); (c) any open "
            "questions — what you do not yet know, what you would need "
            "to find out next, where you would want peers to push back. "
            "ANSWER: the reply text, ~80-120 words — directly answer the "
            "question, surface the reasoning behind your answer, flag "
            "caveats or follow-ups. SCRATCHPAD: the private note (no "
            "length target). DRAFT: the updated draft (length governed "
            "by the artefact schema, not by this field). DONE: optional "
            "final remark. Unused for ASK and the addressee field — "
            "carry the question text via ask_question instead."
        ),
    )
    ask_recipient: Optional[str] = Field(
        None,
        description=(
            "ASK only. The role-name of the agent the question is "
            "addressed to."
        ),
    )
    ask_question: Optional[str] = Field(
        None,
        description=(
            "ASK only. The question text, ~80-120 words. State (a) the "
            "context that prompted you to ask — what you were thinking "
            "through when the gap appeared; (b) the specific decision "
            "or value you need from the peer; (c) any constraints they "
            "should weigh in answering. A bare one-line question is "
            "almost always too thin — peers cannot answer well without "
            "the framing that produced the question."
        ),
    )
    answer_to_question_id: Optional[str] = Field(
        None,
        description=(
            "ANSWER only. The id of the inbox question this answers. "
            "Use this exactly as it appears in your inbox."
        ),
    )
    answer_visibility: Optional[str] = Field(
        "public",
        description=(
            "ANSWER only. 'public' echoes the answer to the shared "
            "transcript; 'private' sends it only to the asker's inbox."
        ),
    )
    citations: List[Citation] = Field(
        default_factory=list,
        description=(
            "Optional. Populate ONLY if you drew on excerpts from the "
            "REFERENCE MATERIAL block in your prompt. One entry per "
            "excerpt you leaned on: doc_id + chunk_id copied verbatim "
            "from the excerpt header, quote copied verbatim from the "
            "excerpt text, supports = a short tag for which claim of "
            "yours this backs. If you didn't use any excerpt, leave "
            "this as an empty list. Every quote is later substring-"
            "verified against its excerpt; fabrications are flagged."
        ),
    )


class DirectedMessage(BaseModel):
    """One inbox entry — either a question to answer or an answer to a question."""

    id: str
    sender: str
    recipient: str
    kind: str = Field(..., description="'ASK' or 'ANSWER'")
    text: str
    answer_to_question_id: Optional[str] = None
    visibility: str = "public"  # only meaningful for ANSWERs
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    age_actions: int = Field(
        0,
        description=(
            "How many addressee-actions have passed since this message "
            "was delivered. Used by the stale-question detector."
        ),
    )


class RoleTaskSpec(BaseModel):
    """The deliverable a single role is working toward.

    Each role's goal is to produce its strategic document for the
    deliberation. The discussion is the means to refine it; DONE is
    declared when the role believes their document is complete.
    """

    role: str
    company: str
    industry_context: str
    product_type: str
    strategic_question: str
    # Optional — empty / None means the team decides the product
    # themselves (the PRODUCT block is then omitted from the prompt
    # via the truthiness check in `_compose_role_prompt`).
    product_description: Optional[str] = ""
    # The study's one-line description of the firm's domain, if any.
    scenario_brief: Optional[str] = ""
    doc_framing: str = Field(
        ...,
        description=(
            "A short description of what the role's final document "
            "needs to cover. Same content as orchestrator/"
            "artefact_collection.py::_ROLE_DOC_FRAMING."
        ),
    )


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

class TranscriptEntry(BaseModel):
    """One entry in the public shared transcript."""

    index: int
    role: str
    kind: str  # 'speak', 'ask_public_echo', 'answer_public', 'system'
    text: str
    addressed_to: Optional[str] = None
    answer_to_question_id: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    citations: List[Citation] = Field(
        default_factory=list,
        description=(
            "Citations the authoring role attached to this entry "
            "via its `AgentAction.citations`. Copied across from "
            "`_apply_action` so the deliberation log persists which "
            "retrieved snippets the role drew on for this utterance. "
            "Default empty list for no-RAG runs."
        ),
    )


class RoleState(BaseModel):
    """Per-role state held by the orchestrator."""

    role: str
    scratchpad: List[str] = Field(default_factory=list)
    draft: str = ""
    inbox: List[DirectedMessage] = Field(default_factory=list)
    action_count: int = 0
    done: bool = False
    finished_reason: str = ""


class SharedState:
    """Concurrent-safe container for the deliberation.

    All mutations are guarded by an asyncio.Lock. Reads return
    snapshots (deep-copied Pydantic objects) so the agent's view of
    the world is stable across one LLM call.
    """

    def __init__(self, roles: List[str]):
        self._lock = asyncio.Lock()
        self.transcript: List[TranscriptEntry] = []
        self.role_states: Dict[str, RoleState] = {
            role: RoleState(role=role) for role in roles
        }
        self.llm_failures: List[str] = []
        self.started_at = datetime.utcnow()

    # ----- snapshot reads (lock held briefly) ------------------------

    async def snapshot_transcript(self) -> List[TranscriptEntry]:
        async with self._lock:
            return [e.model_copy() for e in self.transcript]

    async def snapshot_role(self, role: str) -> RoleState:
        async with self._lock:
            return self.role_states[role].model_copy(deep=True)

    async def snapshot_all_role_states(self) -> Dict[str, RoleState]:
        async with self._lock:
            return {
                r: rs.model_copy(deep=True)
                for r, rs in self.role_states.items()
            }

    # ----- mutations (lock held for full op) ------------------------

    async def append_transcript(self, entry: TranscriptEntry) -> None:
        async with self._lock:
            entry.index = len(self.transcript)
            self.transcript.append(entry)

    async def push_inbox(self, message: DirectedMessage) -> None:
        async with self._lock:
            if message.recipient not in self.role_states:
                log.warning("Inbox push to unknown recipient: %s", message.recipient)
                return
            self.role_states[message.recipient].inbox.append(message)

    async def pop_inbox_question(
        self, role: str, question_id: str
    ) -> Optional[DirectedMessage]:
        """Remove an answered question from the asker's inbox."""
        async with self._lock:
            inbox = self.role_states[role].inbox
            for i, m in enumerate(inbox):
                if m.kind == "ASK" and m.id == question_id:
                    inbox.pop(i)
                    return m
            return None

    async def append_scratchpad(self, role: str, note: str) -> None:
        async with self._lock:
            self.role_states[role].scratchpad.append(note)

    async def update_draft(self, role: str, draft: str) -> None:
        async with self._lock:
            self.role_states[role].draft = draft

    async def increment_action_count(self, role: str) -> int:
        async with self._lock:
            self.role_states[role].action_count += 1
            return self.role_states[role].action_count

    async def record_llm_failure(self, role: str, error: str) -> None:
        async with self._lock:
            self.llm_failures.append(f"{role}: {error}")

    async def mark_done(self, role: str, reason: str) -> None:
        async with self._lock:
            self.role_states[role].done = True
            self.role_states[role].finished_reason = reason

    async def age_inboxes(self, role_that_acted: str) -> None:
        """Bump the age_actions counter on every queued question in the
        acting role's inbox, so the orchestrator can detect stale
        questions (asked → never answered within threshold)."""
        async with self._lock:
            for m in self.role_states[role_that_acted].inbox:
                if m.kind == "ASK":
                    m.age_actions += 1

    async def insert_no_answer_marker(
        self, asker: str, question_id: str, original_question: str
    ) -> None:
        """Forcibly answer a stale question with a [NO ANSWER] marker.

        This unblocks the asker — they can proceed without the answer.
        """
        marker = DirectedMessage(
            id=str(uuid.uuid4()),
            sender="system",
            recipient=asker,
            kind="ANSWER",
            text=f"[NO ANSWER — original question: {original_question}]",
            answer_to_question_id=question_id,
        )
        await self.push_inbox(marker)

    # ----- introspection -------------------------------------------

    async def all_done(self) -> bool:
        async with self._lock:
            return all(rs.done for rs in self.role_states.values())

    async def stale_questions(
        self, threshold: int
    ) -> List[tuple[str, DirectedMessage]]:
        """Return (asker, question) pairs where age_actions >= threshold."""
        async with self._lock:
            stale: List[tuple[str, DirectedMessage]] = []
            for role, rs in self.role_states.items():
                for m in rs.inbox:
                    if m.kind == "ASK" and m.age_actions >= threshold:
                        stale.append((m.sender, m))
            return stale


# ---------------------------------------------------------------------------
# Runner abstraction
# ---------------------------------------------------------------------------

# A `RunnerFn` runs an LlmAgent against a prompt and returns the
# concatenated text. Used by both the production wiring (ADK Runner)
# and the test stubs.
RunnerFn = Callable[..., Awaitable]


# ---------------------------------------------------------------------------
# Per-role agent loop
# ---------------------------------------------------------------------------

async def _role_loop(
    *,
    role: str,
    agent: LlmAgent,
    task: RoleTaskSpec,
    shared: SharedState,
    config: ConcurrentConfig,
    run_agent: RunnerFn,
    researcher_stream: Optional["ResearcherStream"] = None,
    rag_session: Optional["RagSession"] = None,
) -> None:
    """One role's continuous-action loop.

    Runs until the role emits DONE, hits the per-role action cap, or
    the outer wall-clock monitor cancels the task.

    When `researcher_stream` is provided, each applied action is fed
    to the stream (silent buffer append) and a periodic flush is
    triggered. The stream itself decides whether to call the
    FieldNoter LLM based on its `synth_every` threshold. See
    orchestrator/researcher_stream.py.

    When `rag_session` is provided AND enabled, the loop runs a
    retrieval against the firm's corpus before each LLM call using
    a query built from (role, task, recent transcript, scratchpad) —
    deliberately not from the study's RQ/lens (invariant I5). The
    retrieved snippets are threaded into `_compose_role_prompt` via
    the R2 seam.
    """
    consecutive_failures = 0
    while True:
        # Check own done / cap state before doing anything else.
        my_state = await shared.snapshot_role(role)
        if my_state.done:
            return
        if my_state.action_count >= config.max_actions_per_role:
            await shared.mark_done(role, reason="action_cap_reached")
            return

        # Build the prompt from the latest snapshots.
        transcript = await shared.snapshot_transcript()

        # RAG: retrieve before composing the prompt. Empty list if
        # disabled (no-RAG path); the prompt-inject helper then
        # returns "" and the prompt is unchanged.
        retrieved: List[RetrievedSnippet] = []
        if rag_session is not None and rag_session.enabled:
            query = build_role_turn_query(
                role=role, task=task, my_state=my_state, transcript=transcript,
            )
            retrieved = await rag_session.retrieve_for_role(
                role=role, query=query, phase="phase_1_deliberation",
            )

        prompt = _compose_role_prompt(
            role=role, task=task, my_state=my_state, transcript=transcript,
            retrieved_snippets=retrieved or None,
        )

        # Ask the LLM what to do.
        try:
            raw = await run_agent(agent=agent, prompt=prompt)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("role_loop[%s] LLM call failed: %s", role, exc)
            # Don't crash the whole deliberation. A failure isn't something
            # the role did, so it goes in the run's errors, not its notes.
            consecutive_failures += 1
            await shared.record_llm_failure(role, str(exc))
            if consecutive_failures >= config.max_consecutive_llm_failures:
                await shared.mark_done(role, reason=LLM_FAILURES_REASON)
                return
            await asyncio.sleep(
                config.llm_failure_backoff_seconds * 2 ** (consecutive_failures - 1)
            )
            continue

        consecutive_failures = 0
        action = _coerce_action(raw)
        if action is None:
            await shared.append_scratchpad(
                role, "[Could not parse LLM action; one step skipped]"
            )
            await shared.increment_action_count(role)
            continue

        await _apply_action(role=role, action=action, shared=shared)
        await shared.age_inboxes(role)
        await shared.increment_action_count(role)

        # Live ethnography hook: feed the action that just happened
        # to the researcher's running session. Cheap (no LLM call)
        # unless the buffer threshold trips, in which case the
        # FieldNoter is invoked once and the role loop briefly waits
        # on that note (acceptable — keeps the rhythm coherent).
        if researcher_stream is not None:
            event_line = _format_action_for_observer(role=role, action=action)
            if event_line:
                researcher_stream.observe(event_line)
            await researcher_stream.flush_if_due()

        # Cooperative yield so the outer monitor and peer role loops
        # get scheduled between actions. Real LLM calls have network
        # latency that does this naturally; tests with stub runners
        # need an explicit yield.
        await asyncio.sleep(0)


def _compose_role_prompt(
    *,
    role: str,
    task: RoleTaskSpec,
    my_state: RoleState,
    transcript: List[TranscriptEntry],
    retrieved_snippets: Optional[List[RetrievedSnippet]] = None,
) -> str:
    """Build the per-turn prompt for one role.

    Modelled on how real TMTs actually work — no enforced phase
    split between gathering and writing; the role decides:

      - Roles ASK peers for the information they need.
      - They develop their own strategy in private (SCRATCHPAD / DRAFT).
      - They SPEAK their view publicly and seek consensus.
      - When peers disagree, anyone can escalate to the CEO via ASK.
      - The CEO is a facilitator and arbiter with final authority, but
        a SOFT rule: must consider all perspectives before deciding.

    Discussion and writing are INTERLEAVED — no enforced phase split.
    The orchestrator gates nothing; the prompt nudges via per-turn
    status hints (`_render_role_status`) so the agent sees its own
    discussion-vs-writing balance and can self-correct.
    """
    scratchpad_block = (
        "\n".join(f"  - {n}" for n in my_state.scratchpad)
        if my_state.scratchpad
        else "  (no private notes yet)"
    )
    draft_block = my_state.draft or "(empty — you have not started drafting yet)"
    inbox_block = _render_inbox(my_state.inbox)
    transcript_block = _render_transcript(transcript) or "(empty — no one has spoken yet)"

    place_block = _render_role_place_on_team(role)
    status_block = _render_role_status(role=role, my_state=my_state, transcript=transcript)
    guidance_block = _render_role_guidance(role=role, my_state=my_state, transcript=transcript)
    # RAG: empty string when no snippets (no-RAG runs). When snippets
    # are provided, the helper inserts a REFERENCE MATERIAL block +
    # populate-citations instruction here.
    reference_block = format_retrieved_context(role=role, snippets=retrieved_snippets)

    return f"""You are the {role} of {task.company}.

YOUR PLACE ON THE TEAM
----------------------
{place_block}

HOW THE TEAM WORKS (interleaved, asynchronous, non-deterministic)
-----------------------------------------------------------------
Real TMTs don't run "discussion phase, then writing phase". They
interleave:

  - Gathering information you need by ASKing relevant peers.
  - Developing your role's strategy privately (SCRATCHPAD for
    thinking; DRAFT to commit pieces of your final document).
  - Sharing your view publicly via SPEAK when it would help others.
  - Seeking and acknowledging consensus on the team's direction.
  - Escalating genuine disagreements to the CEO (the CEO arbitrates;
    they don't dictate).

Any of these can happen in any order. ASKing a peer mid-draft is
fine. SCRATCHPAD'ing while waiting for an answer is fine. SPEAKing
your position while you still have unanswered questions is fine.

SCENARIO
--------
Company: {task.company}{f" ({task.scenario_brief.rstrip('.')})" if task.scenario_brief else ""}
Industry conditions: {task.industry_context}
Product type: {task.product_type}
Strategic question on the table:

  {task.strategic_question}

{('PRODUCT (context, not a decision):' + chr(10) + task.product_description) if task.product_description else ''}

{reference_block}
YOUR DELIVERABLE
----------------
{task.doc_framing}

You keep working — taking actions, refining your draft, talking to
peers — until your deliverable holds together AND you have engaged
the team. Declare DONE only when both are true.

STRATEGIC DEPTH
---------------
This is an ideation-stage decision. You don't know everything yet,
and pretending you do is worse than admitting you don't. Engage
with the decision in whatever depth your role and the situation
demand — the aspects you surface, and the level of detail on each,
should reflect what THIS decision actually requires from YOUR
perspective. Be elaborate where you have conviction; flag what you
don't know and how you plan to find out ("we don't know X yet — we
plan to discover it by Y") rather than fabricating confidence.
Describe how your team is approaching this in your own words; do
not borrow a named methodology off a shelf.

REASONING DISCIPLINE (how to talk so the decision is auditable)
---------------------------------------------------------------
Every substantive utterance — whether you SPEAK to the room,
ANSWER a peer, ASK a question, or DRAFT a piece of your document —
should make three things visible:

  1. Your position. The call you are making, the answer you are
     giving, the gap you are flagging. State it directly.

  2. Your reasoning. The assumptions you are trusting, the
     trade-offs you weighed, the evidence that pushed you one way
     and not the other. "Why this and not the alternative?" should
     be answerable from your own words, not inferred. Where you
     are trusting something you cannot yet verify, say so explicitly.

  3. Your unanswered questions. What you do not yet know, what you would
     need to find out next, where you would want peers to push back
     or supply expertise you lack. The dependencies your reasoning
     rests on.

Be expressive but disciplined. On substantive turns target ~120-180
words; on ASK / ANSWER turns ~80-120 words. State the reasoning,
do not just signal it. "I agree with the CTO" is too thin. Say
which part of the CTO's view you agree with, the reason that
decides it over the alternative, the assumption you are trusting,
and the part that worries you. Concise but expressive — say what matters, say
why it matters, name what you don't yet know.

What NOT to do:
  - Don't state conclusions without reasoning. "We should do X"
    needs a "because" that engages with the alternatives.
  - Don't borrow named methodologies without articulating what you
    actually mean. "Agile pivot" / "lean rollout" / "land and expand"
    are flags for the reader that the speaker is not yet doing the
    work — describe what the team actually does in your own words.
  - Don't agree-with-everything without surfacing the specific part
    you agree with. Vague endorsement is uninformative; pointed
    endorsement (or pointed disagreement) is the signal.
  - Don't fabricate confidence. If you don't know a number, say
    "I don't know — we'd need to measure it" rather than asserting
    one.

YOUR DISCUSSION STATUS (so you can self-correct)
------------------------------------------------
{status_block}

GUIDANCE FOR THIS TURN
----------------------
{guidance_block}

YOUR PRIVATE SCRATCHPAD (visible only to you and the researcher)
----------------------------------------------------------------
{scratchpad_block}

YOUR CURRENT DRAFT (visible only to you and the researcher; refine via DRAFT actions)
------------------------------------------------------------------------------------
{draft_block}

YOUR INBOX (private — questions and answers addressed to you)
-------------------------------------------------------------
{inbox_block}

SHARED PUBLIC TRANSCRIPT (visible to all six roles)
---------------------------------------------------
{transcript_block}

ACTION MENU
-----------
On each turn you emit EXACTLY ONE action as a JSON object conforming
to the AgentAction schema. The valid `kind` values are:

  SPEAK        — add a substantive contribution to the public
                 transcript. Use this for points you want everyone
                 to see and react to, OR for explicitly acknowledging
                 consensus / agreement / disagreement with what
                 someone else said. `text` is the contribution.

  ASK          — pose a directed question to a specific peer
                 (including the CEO — escalate genuine conflicts to
                 the CEO this way). They see it in their inbox;
                 they answer when they get to it. `ask_recipient`
                 is the role name (CEO, CTO, COO, CMO,
                 Product_Strategist, Product_Designer). `ask_question`
                 is the question text. Asks are also echoed publicly
                 so the room knows what was asked.

  ANSWER       — respond to a question from your inbox.
                 `answer_to_question_id` MUST match a question id in
                 your inbox. `text` is your answer.
                 `answer_visibility` ∈ {{'public', 'private'}}:
                 'public' echoes to the transcript; 'private' goes
                 only to the asker's inbox.

  SCRATCHPAD   — write a private note (impressions, things to chase
                 up later, things you noticed but haven't said).
                 `text` is the note. Costs you one action.

  DRAFT        — update your draft. `text` is the entire new draft
                 (replace, not append). Use this when you've thought
                 through enough to commit to a piece of the document.

  DONE         — declare your deliverable complete. `text` is an
                 optional final remark for the transcript.

You will keep acting until you emit DONE or until your action cap
({task.role}'s per-role cap) is reached. There is no resting and no
sleeping. Work in the natural rhythm of a busy executive who has 20
minutes to deliver their part of a strategic decision.

Return ONLY the JSON object. No prose, no markdown."""


# ---------------------------------------------------------------------------
# Role-aware prompt fragments
# ---------------------------------------------------------------------------

_PLACE_PEER = (
    "You are an executive on the TMT, accountable for your function. "
    "Your peers — CEO, CTO, COO, CMO, Product Strategist, Product "
    "Designer — bring different perspectives. You ASK them for "
    "information you need. You answer their questions. You SPEAK to "
    "the room when your view matters. When you and a peer disagree "
    "and can't resolve it together, escalate to the CEO (via ASK "
    "with `ask_recipient='CEO'`)."
)

_PLACE_CEO = (
    "You are the CEO. You facilitate, integrate, and — when "
    "necessary — arbitrate. You are NOT a dictator: your authority "
    "is a SOFT rule. Use it sparingly. Before making any final call, "
    "consult relevant peers via ASK and surface the trade-offs "
    "publicly via SPEAK. Your peers will escalate genuine conflicts "
    "to you; resolve them by pulling together every perspective. "
    "When you SPEAK a decision, acknowledge whose views informed it. "
    "The team's strategy is the team's, not yours alone — but you "
    "are the one who closes the loop when consensus stalls."
)


def _render_role_place_on_team(role: str) -> str:
    if role == "CEO":
        return _PLACE_CEO
    return _PLACE_PEER


def _render_role_status(
    *,
    role: str,
    my_state: RoleState,
    transcript: List[TranscriptEntry],
) -> str:
    """Status summary the role can use to self-correct.

    Counts the role's own contributions and looks at the transcript
    to see which peers haven't engaged with the role yet. Prompts
    the LLM toward more discussion when the role has been heads-down
    on their own draft.
    """
    n_speak = sum(
        1 for e in transcript
        if e.role == role and e.kind == "speak"
    )
    n_ask_from_me = sum(
        1 for e in transcript
        if e.role == role and e.kind == "ask_public_echo"
    )
    n_answer_from_me = sum(
        1 for e in transcript
        if e.role == role and e.kind == "answer_public"
    )
    n_inbox_asks = sum(1 for m in my_state.inbox if m.kind == "ASK")
    n_inbox_answers = sum(1 for m in my_state.inbox if m.kind == "ANSWER")

    all_roles = {"CEO", "CTO", "COO", "CMO", "Product_Strategist", "Product_Designer"}
    other_roles = all_roles - {role}

    # Peers who have engaged with this role in any direction.
    engaged_with: set[str] = set()
    for e in transcript:
        if e.role == role and e.addressed_to:
            engaged_with.add(e.addressed_to)
        if e.addressed_to == role and e.role != role:
            engaged_with.add(e.role)

    not_yet_heard_from = sorted(other_roles - engaged_with)

    lines = [
        f"- Public contributions you've made (SPEAK): {n_speak}",
        f"- Questions you've asked peers (ASK from you): {n_ask_from_me}",
        f"- Answers you've given peers (ANSWER from you): {n_answer_from_me}",
        f"- Open ASKs in your inbox (waiting for your ANSWER): {n_inbox_asks}",
        f"- ANSWERs in your inbox (peers responding to you): {n_inbox_answers}",
        f"- Draft length so far: {len(my_state.draft)} chars",
    ]
    if not_yet_heard_from:
        lines.append(
            f"- Peers you have NOT yet exchanged with: {', '.join(not_yet_heard_from)}"
        )
    else:
        lines.append("- You have exchanged with every peer at least once. ✓")
    return "\n".join(lines)


def _render_role_guidance(
    *,
    role: str,
    my_state: RoleState,
    transcript: List[TranscriptEntry],
) -> str:
    """Per-turn nudge based on the role's discussion-vs-writing balance.

    Soft, not enforced. Tells the LLM what would be appropriate NEXT
    given what it's done so far. The orchestrator never blocks any
    action; we just bias the model's choice through these hints.
    """
    n_inbox_asks = sum(1 for m in my_state.inbox if m.kind == "ASK")
    n_ask_from_me = sum(
        1 for e in transcript
        if e.role == role and e.kind == "ask_public_echo"
    )
    n_speak = sum(
        1 for e in transcript
        if e.role == role and e.kind == "speak"
    )
    draft_chars = len(my_state.draft)

    nudges: list[str] = []

    # Highest-priority: inbox ASKs waiting on you.
    if n_inbox_asks > 0:
        nudges.append(
            f"- YOU HAVE {n_inbox_asks} OPEN QUESTION(S) IN YOUR INBOX. "
            "Answer them before doing other work — keeping peers waiting "
            "blocks the discussion."
        )

    # Drafting without having engaged.
    if draft_chars > 500 and n_ask_from_me == 0:
        nudges.append(
            "- Your draft is taking shape but you haven't ASKed any peer "
            "for input. Before declaring DONE, you should consult at "
            "least 2 relevant peers about questions only they can answer."
        )

    if draft_chars > 500 and n_speak == 0:
        nudges.append(
            "- Your draft is taking shape but you have NOT yet SPOKEN "
            "your view publicly. Consider sharing the part of your "
            "thinking that the team needs to react to (or agree with) "
            "before you commit further."
        )

    # CEO-specific: have they consulted before any synthesis?
    if role == "CEO" and draft_chars > 500 and n_ask_from_me < 3:
        nudges.append(
            "- As CEO, you should have consulted at least 3 peers via "
            "ASK before drafting a synthesis. Closing the loop requires "
            "you to have heard the room first."
        )

    # Otherwise: encouragement based on state.
    if not nudges:
        if n_speak == 0 and draft_chars == 0:
            nudges.append(
                "- Start by SPEAKing your initial take, or ASKing the "
                "peer whose perspective is most decision-relevant for "
                "your role. Don't go heads-down on a draft before "
                "engaging the team."
            )
        else:
            nudges.append(
                "- Continue in your natural rhythm: gather any more "
                "information you need, refine your draft, share where it "
                "helps the team. DONE when both are complete."
            )

    return "\n".join(nudges)


def _render_inbox(inbox: List[DirectedMessage]) -> str:
    if not inbox:
        return "(empty)"
    lines: List[str] = []
    for m in inbox:
        if m.kind == "ASK":
            lines.append(
                f"  [ASK id={m.id}] from {m.sender}: {m.text}"
            )
        else:  # ANSWER
            lines.append(
                f"  [ANSWER to your question {m.answer_to_question_id}] "
                f"from {m.sender}: {m.text}"
            )
    return "\n".join(lines)


def _render_transcript(transcript: List[TranscriptEntry]) -> str:
    if not transcript:
        return ""
    lines: List[str] = []
    for e in transcript:
        if e.kind == "ask_public_echo":
            lines.append(f"  [{e.index}] {e.role} → {e.addressed_to}: {e.text}")
        elif e.kind == "answer_public":
            lines.append(
                f"  [{e.index}] {e.role} answers (re q {e.answer_to_question_id}): {e.text}"
            )
        else:
            lines.append(f"  [{e.index}] {e.role}: {e.text}")
    return "\n".join(lines)


def _coerce_action(raw: object) -> Optional[AgentAction]:
    """Coerce LLM output into an AgentAction.

    Tolerant of two common LLM output quirks observed in the live smoke:

      1. **Markdown code fences.** Models sometimes wrap JSON in
         ```json … ``` even when asked for bare JSON. Strip the fences.

      2. **Action wrapper nesting.** Models sometimes return
         ``{"action": {"kind": "DONE", ...}}`` instead of the bare
         ``{"kind": "DONE", ...}``. Detect this exact shape and
         unwrap to the inner object.

    Belt-and-braces with `output_schema=AgentAction` on the role
    agents (which forces ADK to enforce structured output server-side);
    this parser tolerance is the fallback for cases ADK didn't catch.
    """
    if raw is None:
        return None
    if isinstance(raw, AgentAction):
        return raw

    if isinstance(raw, str):
        cleaned = _strip_markdown_fences(raw)
        try:
            parsed = json.loads(cleaned)
        except Exception as exc:  # noqa: BLE001
            log.error("AgentAction JSON decode failed: %s", exc)
            return None
        return _coerce_action(parsed)  # recurse with the dict

    if isinstance(raw, dict):
        # Unwrap {"action": {...}} nesting if that's the only top-level key.
        if (
            list(raw.keys()) == ["action"]
            and isinstance(raw["action"], dict)
        ):
            raw = raw["action"]
        try:
            return AgentAction.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            log.error("AgentAction validation failed: %s", exc)
            return None

    return None


def _strip_markdown_fences(text: str) -> str:
    """Remove ```json … ``` or ``` … ``` wrappers if present.

    Returns the inner content. If no fence is detected, returns the
    original text unchanged.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    # Remove the opening fence (with optional language tag).
    first_newline = stripped.find("\n")
    if first_newline == -1:
        return text
    inner = stripped[first_newline + 1:]
    # Remove the trailing fence.
    if inner.endswith("```"):
        inner = inner[: -3]
    return inner.strip()


async def _apply_action(
    *, role: str, action: AgentAction, shared: SharedState
) -> None:
    """Dispatch one parsed action to the appropriate state mutation."""
    if action.kind == ActionKind.SPEAK:
        if action.text:
            await shared.append_transcript(
                TranscriptEntry(
                    index=0, role=role, kind="speak", text=action.text,
                    citations=list(action.citations),
                )
            )

    elif action.kind == ActionKind.ASK:
        if action.ask_recipient and action.ask_question:
            qid = str(uuid.uuid4())
            await shared.push_inbox(
                DirectedMessage(
                    id=qid,
                    sender=role,
                    recipient=action.ask_recipient,
                    kind="ASK",
                    text=action.ask_question,
                )
            )
            # Also echo publicly so the rest of the room is aware.
            await shared.append_transcript(
                TranscriptEntry(
                    index=0,
                    role=role,
                    kind="ask_public_echo",
                    text=action.ask_question,
                    addressed_to=action.ask_recipient,
                    citations=list(action.citations),
                )
            )

    elif action.kind == ActionKind.ANSWER:
        if action.answer_to_question_id and action.text:
            # Remove the answered question from our own inbox.
            await shared.pop_inbox_question(role, action.answer_to_question_id)
            # Send the answer to the asker. We need to look up the
            # asker — the answer's recipient is whoever sent the
            # original question. The asker is the original sender.
            # We don't have the sender directly here, so we walk the
            # transcript / role_states to find the original ASK.
            asker = await _find_asker_by_question_id(
                shared, action.answer_to_question_id
            )
            if asker is not None:
                await shared.push_inbox(
                    DirectedMessage(
                        id=str(uuid.uuid4()),
                        sender=role,
                        recipient=asker,
                        kind="ANSWER",
                        text=action.text,
                        answer_to_question_id=action.answer_to_question_id,
                        visibility=action.answer_visibility or "public",
                    )
                )
            if (action.answer_visibility or "public") == "public":
                await shared.append_transcript(
                    TranscriptEntry(
                        index=0,
                        role=role,
                        kind="answer_public",
                        text=action.text,
                        answer_to_question_id=action.answer_to_question_id,
                        citations=list(action.citations),
                    )
                )

    elif action.kind == ActionKind.SCRATCHPAD:
        if action.text:
            await shared.append_scratchpad(role, action.text)

    elif action.kind == ActionKind.DRAFT:
        if action.text:
            await shared.update_draft(role, action.text)

    elif action.kind == ActionKind.DONE:
        # Optional final remark to the transcript.
        if action.text:
            await shared.append_transcript(
                TranscriptEntry(
                    index=0, role=role, kind="speak", text=action.text,
                    citations=list(action.citations),
                )
            )
        await shared.mark_done(role, reason="agent_declared_done")


def _format_action_for_observer(*, role: str, action: AgentAction) -> str:
    """Render one action as a one-line event for the researcher stream.

    Returns "" for actions that aren't visible to a silent observer
    sitting in the public room (private SCRATCHPAD content, DRAFT
    edits) — the researcher reads scratchpads + drafts via the
    privileged channel later, not as live observations.
    """
    kind = action.kind.value if hasattr(action.kind, "value") else str(action.kind)
    text = (action.text or "").strip().replace("\n", " ")
    if len(text) > 320:
        text = text[:320] + "…"

    if kind == "SPEAK":
        return f"[{role} SPEAK] {text}"
    if kind == "ASK":
        recipient = action.ask_recipient or "?"
        q = (action.ask_question or "").strip().replace("\n", " ")
        if len(q) > 320:
            q = q[:320] + "…"
        return f"[{role} ASK → {recipient}] {q}"
    if kind == "ANSWER":
        vis = action.answer_visibility or "public"
        # Private answers are still part of the public-room dynamics
        # (an answer was given), so we surface the existence but not
        # the content for private answers.
        if vis == "private":
            return f"[{role} ANSWER (private)] (content not shown to room)"
        return f"[{role} ANSWER] {text}"
    if kind == "DONE":
        if text:
            return f"[{role} DONE] {text}"
        return f"[{role} DONE]"
    # SCRATCHPAD / DRAFT — not surfaced as live observations.
    return ""


async def _find_asker_by_question_id(
    shared: SharedState, question_id: str
) -> Optional[str]:
    """Walk the transcript to find who originally asked question_id.

    The ASK was echoed publicly as a TranscriptEntry of kind
    'ask_public_echo' with the same question content. We don't store
    the id on the public echo (clutter), so we approximate by
    scanning role_states: a question that has been answered is no
    longer in the addressee's inbox, but the *asker* recorded their
    ASK in their own action history. Simplest reliable signal:
    sweep every role's inbox for an ASK with this id — won't find
    it since it was just popped — but the popped DirectedMessage
    object still tells us the sender. We saved that mapping at
    pop_inbox_question time? Not currently — let's add a lookup.

    For correctness we'll cheat a little and store an internal
    map in SharedState. (Refactor below.)
    """
    return getattr(shared, "_asker_by_qid", {}).get(question_id)


# Patch SharedState to record asker_by_qid when pushing ASK messages.
# Doing this as a post-hoc augmentation keeps the SharedState class
# above readable; semantically the map is part of internal bookkeeping.
_original_push = SharedState.push_inbox  # type: ignore[assignment]


async def _push_inbox_with_asker_tracking(
    self: SharedState, message: DirectedMessage
) -> None:
    await _original_push(self, message)
    if message.kind == "ASK":
        if not hasattr(self, "_asker_by_qid"):
            self._asker_by_qid = {}  # type: ignore[attr-defined]
        self._asker_by_qid[message.id] = message.sender  # type: ignore[attr-defined]


SharedState.push_inbox = _push_inbox_with_asker_tracking  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Role-agent wrapper for concurrent mode
# ---------------------------------------------------------------------------

def _build_concurrent_role_agent(
    base_agent: LlmAgent, role: str
) -> LlmAgent:
    """Wrap a base role agent so its outputs are validated as AgentAction.

    Mirrors the pattern used in `orchestrator.artefact_collection.
    _build_artefact_agent`: keep the base persona/model, layer a small
    instruction note, request AgentAction structured output. The
    `providers.build_structured_agent` adapter picks the right
    enforcement strategy for the provider — strict json_schema for
    Gemini/Claude/OpenAI/Groq, schema-in-prompt + json_object for
    DeepSeek/Ollama. `_coerce_action` enforces on the client side
    regardless.

    Keeps the base agent in `system.agents[role]` untouched, so other
    phases (artefact collection with StrategicArtefact; panel
    debriefing with no schema) get the pristine agent.
    """
    base_instruction = getattr(base_agent, "instruction", "") or ""
    return build_structured_agent(
        name=f"{role}_Concurrent",
        model=getattr(base_agent, "model", "gemini-2.0-flash"),
        instruction=(
            base_instruction
            + "\n\nCONCURRENT MODE\n"
              f"You ({role}) are participating in a real-time TMT working "
              "session. On each turn you emit ONE AgentAction (the schema "
              "is enforced by the runtime). Read your inbox, the shared "
              "transcript, your private scratchpad, and your draft. Pick "
              "the action that best advances your role's deliverable."
        ),
        description=(
            f"{role} in concurrent-deliberation mode — emits AgentAction "
            f"per turn."
        ),
        output_schema=AgentAction,
    )


# ---------------------------------------------------------------------------
# Outer monitor — wall clock + stale question detection
# ---------------------------------------------------------------------------

async def _outer_monitor(
    *,
    shared: SharedState,
    config: ConcurrentConfig,
    role_tasks: Dict[str, asyncio.Task],
) -> str:
    """Background monitor — returns the reason the deliberation ended.

    Polls every `poll_interval_seconds` for:
      - all roles DONE → 'all_done'
      - wall-clock cap exceeded → 'wall_clock_cap'
      - stale questions present → inject [NO ANSWER] markers, continue
    """
    start = datetime.utcnow()
    while True:
        await asyncio.sleep(config.poll_interval_seconds)

        # All roles done?
        if await shared.all_done():
            return "all_done"

        # Wall clock?
        elapsed = (datetime.utcnow() - start).total_seconds()
        if elapsed >= config.max_wall_clock_seconds:
            # Force every still-running role task to cancel.
            for t in role_tasks.values():
                if not t.done():
                    t.cancel()
            return "wall_clock_cap"

        # Stale questions → inject [NO ANSWER] markers so askers move on.
        # Two conditions trigger this:
        #   (a) age_actions on the question has reached the threshold,
        #   (b) the addressee has gone DONE but the question is still
        #       unanswered — they can never answer it now.
        stale = await shared.stale_questions(config.stale_question_threshold)

        # Add condition (b): DONE-role with unanswered ASKs.
        all_states = await shared.snapshot_all_role_states()
        for role, rs in all_states.items():
            if rs.done:
                for m in rs.inbox:
                    if m.kind == "ASK":
                        # Already covered by `stale` if age threshold met,
                        # but we want immediate timeout regardless.
                        if (m.sender, m) not in stale and not any(
                            existing[1].id == m.id for existing in stale
                        ):
                            stale.append((m.sender, m))

        for asker, q in stale:
            log.info(
                "Stale question id=%s (asker=%s, addressee=%s, age=%d) → injecting [NO ANSWER]",
                q.id, q.sender, q.recipient, q.age_actions,
            )
            await shared.insert_no_answer_marker(
                asker=asker, question_id=q.id, original_question=q.text,
            )
            # Also remove the original ASK from the addressee's inbox
            # so they don't keep seeing it.
            await shared.pop_inbox_question(q.recipient, q.id)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_concurrent_mode(
    *,
    role_agents: Dict[str, LlmAgent],
    company: str,
    industry_context: str,
    product_type: str,
    product_description: Optional[str],
    strategic_question: str,
    role_doc_framing: Dict[str, str],
    config: Optional[ConcurrentConfig] = None,
    run_agent: RunnerFn,
    researcher_stream: Optional[ResearcherStream] = None,
    rag_session: Optional[RagSession] = None,
    scenario_brief: Optional[str] = None,
) -> tuple[SharedState, DeliberationLog, str]:
    """Run the concurrent deliberation to completion.

    Returns:
        (shared_state, deliberation_log, ended_reason)

        - shared_state contains the public transcript, the per-role
          scratchpads, drafts, and inboxes. The researcher reads
          scratchpads from here.
        - deliberation_log is the DeliberationLog the rest of the
          pipeline already consumes (one DeliberationEvent per
          transcript entry, phase-tagged 'concurrent').
        - ended_reason ∈ {'all_done', 'wall_clock_cap'}.
    """
    config = config or ConcurrentConfig()
    roles = list(role_agents.keys())
    shared = SharedState(roles=roles)

    # Build a RoleTaskSpec per role.
    tasks_by_role: Dict[str, RoleTaskSpec] = {
        role: RoleTaskSpec(
            role=role,
            company=company,
            industry_context=industry_context,
            product_type=product_type,
            strategic_question=strategic_question,
            product_description=product_description,
            scenario_brief=scenario_brief,
            doc_framing=role_doc_framing.get(role, "Produce your role's strategic document."),
        )
        for role in roles
    }

    # Wrap each base role agent with output_schema=AgentAction so ADK
    # enforces structured output server-side. Avoids the markdown-
    # fence-wrapping and {"action": …} nesting bugs we observed in
    # the first live smoke. The base role agents in self.agents stay
    # clean for other phases (artefact collection wants its own
    # output_schema=StrategicArtefact, etc.).
    action_agents: Dict[str, LlmAgent] = {
        role: _build_concurrent_role_agent(role_agents[role], role)
        for role in roles
    }

    # Launch each role loop as its own task.
    role_tasks: Dict[str, asyncio.Task] = {
        role: asyncio.create_task(_role_loop(
            role=role,
            agent=action_agents[role],
            task=tasks_by_role[role],
            shared=shared,
            config=config,
            run_agent=run_agent,
            researcher_stream=researcher_stream,
            rag_session=rag_session,
        ))
        for role in roles
    }

    # Outer monitor decides when to stop.
    monitor_task = asyncio.create_task(_outer_monitor(
        shared=shared, config=config, role_tasks=role_tasks,
    ))

    # Wait for the monitor (and therefore the deliberation) to end.
    ended_reason = await monitor_task

    # Drain still-running role tasks. They were cancelled by the
    # monitor if wall-clock fired; if all_done, they should be exiting
    # on their own. Give them a brief grace period.
    pending = [t for t in role_tasks.values() if not t.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    # Mark any role that wasn't already DONE as wall_clock_cap-ended.
    for role, t in role_tasks.items():
        rs = await shared.snapshot_role(role)
        if not rs.done:
            await shared.mark_done(role, reason="wall_clock_cap_or_cancelled")

    # Build the DeliberationLog.
    transcript = await shared.snapshot_transcript()
    delib_log = DeliberationLog(
        company=company,
        industry_context=industry_context,
        product_type=product_type,
    )
    for i, entry in enumerate(transcript):
        delib_log.events.append(DeliberationEvent(
            index=i,
            role=entry.role,
            kind=("delegation" if entry.kind == "ask_public_echo"
                  else "text"),
            text=entry.text,
            addressed_to=entry.addressed_to,
            raw_type=entry.kind,
            phase="concurrent",
            citations=list(entry.citations),
        ))
    delib_log.finished_at = datetime.utcnow().isoformat()

    return shared, delib_log, ended_reason
