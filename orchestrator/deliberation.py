"""Deliberation dispatcher — multiple discussion patterns behind one API.

Deliberation is Phase 1 (the first numbered stage) of a run (one complete simulated
meeting and debrief), in which the team (six agents,
language models playing the executives) discusses the decision task. This file chooses
how that discussion is organised, and holds three of the five ways of running it.
API (application programming interface) here means the one way other code starts a
discussion.

This module is the orchestrator dispatch entry-point. It owns:

  * The `DiscussionMode` enum (a fixed list of choices) + `DeliberationConfig` +
    `DeliberationOutcome` Pydantic types (records checked by the tool Pydantic)
    — the configuration surface every caller uses.
  * `run_deliberation(...)` — the dispatcher that picks an
    implementation by `config.discussion_mode`.
  * The implementations of three alternative modes that don't need
    much state: `random_initiator`, `parallel_then_discuss`,
    `round_robin`, plus their helpers.

The CONCURRENT mode (the framework's default) is more involved — it
needs a SharedState (the record all roles read and write) + per-role asyncio (Python's
tool for running tasks side by side) task loops + a directed-message inbox (the
questions colleagues have sent a role privately) +
many more helpers. It lives in a sibling module:

    orchestrator/concurrent_mode.py

This file imports `run_concurrent_mode` from that module and
delegates to it inside `_run_concurrent`. The two files together
make up the framework's deliberation layer.

Modes
-----
- `ceo_led`              — legacy. ADK (Agent Development Kit: Google's software for
                           building agents) tree-based transfer_to_agent, in
                           which one agent passes the floor to another,
                           with CEO as root (the agent at the top). Kept for
                           backwards compatibility / ablation studies (removing
                           a part to see what changes).
- `random_initiator`     — same tree topology but a random role is
                           the root each run. Breaks the "CEO always
                           starts" bias.
- `parallel_then_discuss`— Phase A: all 6 roles emit initial
                           positions in parallel against the same
                           prompt, the text sent to the models (true
                           non-determinism in order, meaning no fixed order).
                           Phase B: discussion rounds where any
                           role can react, push back, or stay
                           silent. Phase C: collective convergence /
                           synthesis.
- `round_robin`          — each round, roles take turns in a shuffled
                           order; each may speak or pass. Lighter
                           than parallel_then_discuss.
- `concurrent`           — DEFAULT. See `orchestrator/concurrent_mode.py`
                           for the implementation. All six role
                           agents run as asyncio tasks against a
                           shared state, exchanging directed messages
                           via private inboxes and a public
                           transcript. Closest match to a real TMT (top management
                           team) working through a novel problem.

Convergence
-----------
- `time_boxed`           — DEFAULT. Stop after `max_rounds` discussion
                           rounds (Phase B for D2, which is parallel_then_discuss;
                           total turns for D3, which is round_robin).
                           Cheapest, deterministic.
- `stability`            — Stop when `quiet_rounds_threshold` consecutive
                           rounds produce no substantively new content.
- `synthesiser`          — A dedicated agent reads each round and
                           decides whether the team has converged.
                           Most faithful, one extra LLM (large language model)
                           call per round.

Convergence flags apply to discussion modes that have explicit rounds
(parallel_then_discuss and round_robin). The ceo_led and random_initiator
modes use ADK's transfer-driven flow — convergence happens when the
root agent stops transferring and emits a synthesis.

The orchestrator is decoupled from agent.py: it takes role agents and
a runner function (the part that hands a prompt to an agent and collects the reply)
as inputs. That keeps the deliberation patterns unit-testable (checkable by small
automatic tests) with stubs (simple stand-ins that give set replies).
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

from google.adk.agents import LlmAgent
from pydantic import BaseModel, Field

try:
    from ..data_capture import DeliberationEvent, DeliberationLog
    from ..providers import get_observer_model
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from data_capture import DeliberationEvent, DeliberationLog  # type: ignore[no-redef]
    from providers import get_observer_model  # type: ignore[no-redef]

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public config
# ---------------------------------------------------------------------------

class DiscussionMode(str, Enum):
    CEO_LED = "ceo_led"
    RANDOM_INITIATOR = "random_initiator"
    PARALLEL_THEN_DISCUSS = "parallel_then_discuss"
    ROUND_ROBIN = "round_robin"
    # Concurrent mode: each role runs its own asyncio task, calls the
    # LLM continuously until DONE, with directed Q&A via inbox and
    # private scratchpads (notes). Closest match to a real TMT meeting.
    CONCURRENT = "concurrent"


class ConvergenceMode(str, Enum):
    TIME_BOXED = "time_boxed"
    STABILITY = "stability"
    SYNTHESISER = "synthesiser"


class ConvergenceConfig(BaseModel):
    """How to decide a multi-round discussion has converged."""

    mode: ConvergenceMode = Field(
        ConvergenceMode.TIME_BOXED,
        description="Which convergence criterion to apply.",
    )
    max_rounds: int = Field(
        5,
        description=(
            "Hard ceiling on discussion rounds, used by every "
            "convergence mode as a safety cap. For TIME_BOXED this is "
            "also the target."
        ),
    )
    quiet_rounds_threshold: int = Field(
        2,
        description=(
            "STABILITY only. Stop after this many consecutive rounds "
            "in which fewer than `quiet_min_contributions` substantive "
            "contributions are made."
        ),
    )
    quiet_min_contributions: int = Field(
        1,
        description=(
            "STABILITY only. A round counts as 'quiet' if it produced "
            "strictly fewer than this many non-pass contributions."
        ),
    )
    synthesiser_model_override: Optional[str] = Field(
        None,
        description=(
            "SYNTHESISER only. Override the model used for the "
            "convergence-check agent. Defaults to `get_observer_model()` "
            "(Gemini Pro pinned for comparability)."
        ),
    )


class DeliberationConfig(BaseModel):
    """Knobs that control how the TMT deliberation unfolds.

    Defaults to `concurrent` mode, which most closely models a real
    TMT working a problem in parallel with directed Q&A and private
    notebooks. The other modes are available from Python by setting
    `discussion_mode`, not from the command line, and they are not connected
    to retrieval during deliberation or to live field notes.
    """

    discussion_mode: DiscussionMode = Field(
        DiscussionMode.CONCURRENT,
        description="Which discussion pattern to drive.",
    )
    convergence: ConvergenceConfig = Field(
        default_factory=ConvergenceConfig,
        description=(
            "How to decide the discussion is done. Only applies to "
            "modes with explicit rounds (PARALLEL_THEN_DISCUSS, "
            "ROUND_ROBIN). The transfer-based modes (CEO_LED, "
            "RANDOM_INITIATOR) and CONCURRENT ignore this — CEO_LED "
            "ends when the root agent stops transferring; CONCURRENT "
            "uses its own ConcurrentConfig caps."
        ),
    )
    random_seed: Optional[int] = Field(
        None,
        description=(
            "Seed for the per-run RNG used by RANDOM_INITIATOR (to "
            "pick the root role) and ROUND_ROBIN (to shuffle turn "
            "order each round). None → use OS entropy."
        ),
    )
    # Typed as Any to avoid a forward-ref dance / import cycle. At
    # runtime this is a `concurrent_mode.ConcurrentConfig` or
    # None; documented behaviour is enforced in `_run_concurrent`. The defaults
    # in ConcurrentConfig are 30 actions per role, a 30-minute wall clock and a
    # stale-question threshold of 3; the description below is older.
    concurrent: Optional[Any] = Field(
        None,
        description=(
            "CONCURRENT mode only. A ConcurrentConfig (from "
            "orchestrator.concurrent_mode) with caps + flags "
            "for the concurrent runner. None ⇒ defaults (15 actions "
            "per role, 20 min wall clock, stale-question threshold 3)."
        ),
    )

    # Allow non-pydantic objects (ConcurrentConfig is a BaseModel but
    # any future change should not break Pydantic validation).
    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Output container
# ---------------------------------------------------------------------------

class DeliberationOutcome(BaseModel):
    """Structured return value from `run_deliberation`."""

    log: DeliberationLog
    ceo_synthesis: str = Field(
        "",
        description=(
            "The closing synthesis text. For ceo_led / random_initiator "
            "this is the root agent's final utterance. For "
            "parallel_then_discuss it is the convergence-phase output. "
            "For round_robin it is the last round's content joined."
        ),
    )
    ended_reason: str = Field(
        "",
        description=(
            "Why the discussion ended: 'max_rounds', 'stable', "
            "'synthesiser_converged', 'transfer_chain_complete', or 'error'."
        ),
    )
    discussion_mode: DiscussionMode
    convergence_mode: Optional[ConvergenceMode] = None
    rounds_completed: int = 0


# ---------------------------------------------------------------------------
# Runner abstraction
# ---------------------------------------------------------------------------

# A `RunnerFn` runs an LlmAgent against a prompt and returns the
# concatenated text from its event stream. Same shape as the one used
# by orchestrator/artefact_collection.py — callers (production and
# tests) can supply either the real ADK-Runner-backed implementation
# or a stub returning canned text.
RunnerFn = Callable[..., Awaitable]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

ROLE_ORDER: tuple[str, ...] = (
    "CEO", "CTO", "COO", "CMO", "Product_Strategist", "Product_Designer",
)


async def run_deliberation(
    *,
    role_agents: Dict[str, LlmAgent],
    company: str,
    industry_context: str,
    product_type: str,
    product_description: str,
    strategic_question: str,
    config: DeliberationConfig,
    run_agent: RunnerFn,
    ceo_led_fallback: Optional[Callable[..., Awaitable]] = None,
    researcher_stream: Optional[Any] = None,
    rag_session: Optional[Any] = None,
    scenario_brief: Optional[str] = None,
) -> DeliberationOutcome:
    """Dispatch to the right discussion pattern.

    `ceo_led_fallback` lets `agent.py::TMTSystemWithA2A` plug its
    existing tree-based deliberation in for the CEO_LED mode without
    this module having to know about ADK Runner internals. If None,
    CEO_LED falls back to the random_initiator path with the CEO
    forced as the root — semantically equivalent for most purposes.
    """
    if config.discussion_mode == DiscussionMode.CEO_LED:
        if ceo_led_fallback is not None:
            return await ceo_led_fallback()
        # Fallback: emulate CEO_LED via the random_initiator path,
        # forcing the CEO. This is only used in tests / when callers
        # don't have access to the ADK runner.
        return await _run_random_initiator(
            role_agents=role_agents,
            company=company,
            industry_context=industry_context,
            product_type=product_type,
            product_description=product_description,
            strategic_question=strategic_question,
            run_agent=run_agent,
            forced_root="CEO",
        )

    if config.discussion_mode == DiscussionMode.RANDOM_INITIATOR:
        rng = random.Random(config.random_seed)
        root = rng.choice(list(ROLE_ORDER))
        return await _run_random_initiator(
            role_agents=role_agents,
            company=company,
            industry_context=industry_context,
            product_type=product_type,
            product_description=product_description,
            strategic_question=strategic_question,
            run_agent=run_agent,
            forced_root=root,
        )

    if config.discussion_mode == DiscussionMode.PARALLEL_THEN_DISCUSS:
        return await _run_parallel_then_discuss(
            role_agents=role_agents,
            company=company,
            industry_context=industry_context,
            product_type=product_type,
            product_description=product_description,
            strategic_question=strategic_question,
            convergence=config.convergence,
            run_agent=run_agent,
        )

    if config.discussion_mode == DiscussionMode.ROUND_ROBIN:
        return await _run_round_robin(
            role_agents=role_agents,
            company=company,
            industry_context=industry_context,
            product_type=product_type,
            product_description=product_description,
            strategic_question=strategic_question,
            convergence=config.convergence,
            run_agent=run_agent,
            random_seed=config.random_seed,
        )

    if config.discussion_mode == DiscussionMode.CONCURRENT:
        return await _run_concurrent(
            role_agents=role_agents,
            company=company,
            industry_context=industry_context,
            product_type=product_type,
            product_description=product_description,
            strategic_question=strategic_question,
            concurrent_config=config.concurrent,
            run_agent=run_agent,
            researcher_stream=researcher_stream,
            rag_session=rag_session,
            scenario_brief=scenario_brief,
        )

    raise ValueError(f"Unknown discussion_mode: {config.discussion_mode}")


async def _run_concurrent(
    *,
    role_agents: Dict[str, LlmAgent],
    company: str,
    industry_context: str,
    product_type: str,
    product_description: str,
    strategic_question: str,
    concurrent_config: Optional["ConcurrentConfig"],  # noqa: F821
    run_agent: RunnerFn,
    researcher_stream: Optional[Any] = None,
    rag_session: Optional[Any] = None,
    scenario_brief: Optional[str] = None,
) -> DeliberationOutcome:
    """Bridge from the deliberation dispatcher to the concurrent runner.

    The concurrent runner returns `(SharedState, DeliberationLog,
    ended_reason)`. We adapt that to the `DeliberationOutcome` shape
    the rest of the pipeline already consumes, and stash the
    `SharedState` on the outcome (via attribute) so callers that want
    the per-role scratchpads (e.g. the researcher) can reach them.
    """
    # Lazy import — keeps the orchestrator module loadable even if
    # someone strips concurrent_mode out.
    try:
        from .concurrent_mode import (
            ConcurrentConfig as _Cfg,
            run_concurrent_mode,
        )
        from .artefact_collection import _ROLE_DOC_FRAMING
    except (ImportError, ValueError):  # pragma: no cover  (script-style)
        from concurrent_mode import (  # type: ignore[no-redef]
            ConcurrentConfig as _Cfg,
            run_concurrent_mode,
        )
        from orchestrator.artefact_collection import _ROLE_DOC_FRAMING  # type: ignore[no-redef]

    cfg = concurrent_config or _Cfg()
    shared, delib_log, ended_reason = await run_concurrent_mode(
        role_agents=role_agents,
        company=company,
        industry_context=industry_context,
        product_type=product_type,
        product_description=product_description,
        strategic_question=strategic_question,
        role_doc_framing=dict(_ROLE_DOC_FRAMING),
        config=cfg,
        run_agent=run_agent,
        researcher_stream=researcher_stream,
        rag_session=rag_session,
        scenario_brief=scenario_brief,
    )

    # Build a synthesis text from the longest non-empty draft. CEO's
    # draft is the headline if present; otherwise pick the longest.
    all_states = await shared.snapshot_all_role_states()
    ceo_draft = all_states.get("CEO")
    if ceo_draft and ceo_draft.draft:
        synthesis = ceo_draft.draft
    else:
        non_empty = [s for s in all_states.values() if s.draft]
        synthesis = max(
            (s.draft for s in non_empty), key=len, default=""
        )

    outcome = DeliberationOutcome(
        log=delib_log,
        ceo_synthesis=synthesis,
        ended_reason=ended_reason,
        discussion_mode=DiscussionMode.CONCURRENT,
        rounds_completed=max(
            (s.action_count for s in all_states.values()), default=0
        ),
    )
    # Stash the shared state so the researcher phase can read scratchpads.
    outcome.__dict__["_concurrent_shared_state"] = shared
    return outcome


# ---------------------------------------------------------------------------
# Mode: random_initiator (uses a single LLM call to the root agent)
# ---------------------------------------------------------------------------

async def _run_random_initiator(
    *,
    role_agents: Dict[str, LlmAgent],
    company: str,
    industry_context: str,
    product_type: str,
    product_description: str,
    strategic_question: str,
    run_agent: RunnerFn,
    forced_root: str,
) -> DeliberationOutcome:
    """One-shot deliberation kicked off by `forced_root`.

    This mode does NOT replicate the ADK transfer chain — it's a
    deliberate simplification used when the caller doesn't have the
    ADK tree available (tests, modes that aren't ceo_led). The root
    agent gets a "lead the discussion and synthesise" prompt; the
    output is a single substantive response that may reference what
    the root believes each peer would contribute, plus their own
    synthesis.

    For the FULL transfer-chain version, use ceo_led_fallback in
    run_deliberation — that path drives ADK's Runner so peers
    actually get to speak.
    """
    log_obj = DeliberationLog(
        company=company,
        industry_context=industry_context,
        product_type=product_type,
    )
    root_agent = role_agents.get(forced_root)
    if root_agent is None:
        raise ValueError(f"Unknown root role: {forced_root}")

    product_block = (
        f"PRODUCT (context, not a decision)\n{product_description}\n\n"
        if product_description else ""
    )
    prompt = (
        f"You are the {forced_root} of {company}. You are leading a TMT "
        f"discussion on this strategic question:\n\n{strategic_question}\n\n"
        f"{product_block}"
        f"INDUSTRY CONTEXT\n{industry_context}\n\n"
        f"PRODUCT TYPE\n{product_type}\n\n"
        "Lead the TMT through this. Surface the perspectives that each "
        "other role would bring — CTO, COO, CMO, Product_Strategist, "
        "Product_Designer (those that are not you). For each, give "
        "their position in their own voice. Then synthesise and "
        "produce the decision. Keep your output under 1500 words."
    )
    text = await run_agent(agent=root_agent, prompt=prompt)
    log_obj.events.append(
        DeliberationEvent(
            index=0,
            role=forced_root,
            kind="text",
            text=str(text),
            raw_type="RandomInitiatorSynthesis",
            phase="convergence",
        )
    )
    log_obj.finished_at = datetime.utcnow().isoformat()

    return DeliberationOutcome(
        log=log_obj,
        ceo_synthesis=str(text),
        ended_reason="transfer_chain_complete",
        discussion_mode=DiscussionMode.RANDOM_INITIATOR,
        rounds_completed=1,
    )


# ---------------------------------------------------------------------------
# Mode: parallel_then_discuss (D2 — closest to a real TMT meeting)
# ---------------------------------------------------------------------------

async def _run_parallel_then_discuss(
    *,
    role_agents: Dict[str, LlmAgent],
    company: str,
    industry_context: str,
    product_type: str,
    product_description: str,
    strategic_question: str,
    convergence: ConvergenceConfig,
    run_agent: RunnerFn,
) -> DeliberationOutcome:
    """Three phases: parallel positions → discussion rounds → synthesis.

    Phase A (initial positions, parallel):
        All six roles see the same prompt and emit their initial
        position concurrently via asyncio.gather. True
        non-determinism in execution order (the asyncio scheduler
        decides; outputs are deterministic given the same model
        + temperature, the setting for how much chance affects word choice).

    Phase B (discussion rounds):
        Each round shows every role the *full* transcript so far. Each
        role decides whether to respond (add, push back, qualify) or
        pass. Roles are invited in a shuffled order each round to
        avoid a "CTO always first" pattern.

    Phase C (convergence / synthesis):
        Final round: the team's positions are sent to a synthesiser
        (default: CEO using the same model as the rest) who writes
        the collective decision.
    """
    log_obj = DeliberationLog(
        company=company,
        industry_context=industry_context,
        product_type=product_type,
    )

    # --- Phase A: parallel initial positions ---
    initial_product_block = (
        f"PRODUCT (context, not a decision)\n{product_description}\n\n"
        if product_description else ""
    )
    initial_prompt = (
        f"You are a member of the TMT at {company} ({industry_context} "
        f"industry, {product_type} product). The team is convening "
        "to discuss this strategic question:\n\n"
        f"{strategic_question}\n\n"
        f"{initial_product_block}"
        "Write your INITIAL POSITION on this question — what you think, "
        "what you would push for, what concerns you. Speak in your "
        "own voice as your role. ~150–250 words. Do not reference "
        "what other roles might say (they are writing theirs in "
        "parallel and you cannot see their drafts)."
    )

    async def _run_one(role: str) -> tuple[str, str]:
        agent = role_agents[role]
        text = await run_agent(agent=agent, prompt=initial_prompt)
        return role, str(text)

    initial_results = await asyncio.gather(
        *[_run_one(role) for role in ROLE_ORDER]
    )
    # Sort by ROLE_ORDER for deterministic logging — execution order
    # was non-deterministic, the log just gets a canonical sort.
    for i, (role, text) in enumerate(
        sorted(initial_results, key=lambda r: ROLE_ORDER.index(r[0]))
    ):
        log_obj.events.append(
            DeliberationEvent(
                index=len(log_obj.events),
                role=role,
                kind="text",
                text=text,
                raw_type="InitialPosition",
                phase="initial_position",
            )
        )

    # --- Phase B: discussion rounds ---
    quiet_count = 0
    converged = False
    rounds_completed = 0
    ended_reason = "max_rounds"

    for round_idx in range(1, convergence.max_rounds + 1):
        shuffled = list(ROLE_ORDER)
        random.Random(round_idx).shuffle(shuffled)
        round_contributions = 0
        for role in shuffled:
            transcript = _render_log_for_discussion(log_obj)
            prompt = (
                f"You are the {role} of {company}. The TMT is in "
                f"round {round_idx} of an open discussion about:\n\n"
                f"{strategic_question}\n\n"
                "DISCUSSION SO FAR\n"
                f"{transcript}\n\n"
                "You may now contribute. Choose ONE of:\n"
                "  (a) ADD: a new point that has not been made.\n"
                "  (b) PUSHBACK: object to or qualify something someone said. "
                "Quote them when you do.\n"
                "  (c) UPDATE: revise your own earlier position.\n"
                "  (d) PASS: stay silent — return EXACTLY the string "
                "'[PASS]' and nothing else. Silence is data. Do not "
                "say anything else.\n"
                "If you contribute, keep it under 200 words and speak "
                "in your own voice as your role."
            )
            text = await run_agent(agent=role_agents[role], prompt=prompt)
            text_str = str(text).strip()
            if _is_pass(text_str):
                # Record passes as kind='other' to mark abstentions
                # without polluting downstream consumers that scan
                # for substantive 'text' events.
                log_obj.events.append(
                    DeliberationEvent(
                        index=len(log_obj.events),
                        role=role,
                        kind="other",
                        text="[PASS]",
                        raw_type="DiscussionPass",
                        phase=f"round_{round_idx}",
                    )
                )
                continue
            round_contributions += 1
            log_obj.events.append(
                DeliberationEvent(
                    index=len(log_obj.events),
                    role=role,
                    kind="text",
                    text=text_str,
                    raw_type="DiscussionContribution",
                    phase=f"round_{round_idx}",
                )
            )

        rounds_completed = round_idx

        # Convergence check.
        if convergence.mode == ConvergenceMode.TIME_BOXED:
            # No early stop — keep going until max_rounds.
            pass
        elif convergence.mode == ConvergenceMode.STABILITY:
            if round_contributions < convergence.quiet_min_contributions:
                quiet_count += 1
            else:
                quiet_count = 0
            if quiet_count >= convergence.quiet_rounds_threshold:
                converged = True
                ended_reason = "stable"
                break
        elif convergence.mode == ConvergenceMode.SYNTHESISER:
            decision = await _ask_synthesiser_converged(
                log_obj=log_obj,
                company=company,
                strategic_question=strategic_question,
                round_idx=round_idx,
                config=convergence,
                run_agent=run_agent,
            )
            if decision:
                converged = True
                ended_reason = "synthesiser_converged"
                break

    if not converged and rounds_completed >= convergence.max_rounds:
        ended_reason = "max_rounds"

    # --- Phase C: convergence / synthesis ---
    transcript = _render_log_for_discussion(log_obj)
    synthesis_prompt = (
        f"You are the CEO of {company}. The TMT has just completed an "
        f"open discussion ({rounds_completed} rounds) on:\n\n"
        f"{strategic_question}\n\n"
        "DISCUSSION\n"
        f"{transcript}\n\n"
        "Write the team's COLLECTIVE synthesis — what was decided, "
        "what trade-offs were weighed, where consensus emerged, where "
        "tension remains. Reference roles by name where their input "
        "was decisive. ~400–600 words."
    )
    synthesis = await run_agent(
        agent=role_agents["CEO"], prompt=synthesis_prompt
    )
    log_obj.events.append(
        DeliberationEvent(
            index=len(log_obj.events),
            role="CEO",
            kind="text",
            text=str(synthesis),
            raw_type="CollectiveSynthesis",
            phase="convergence",
        )
    )
    log_obj.finished_at = datetime.utcnow().isoformat()

    return DeliberationOutcome(
        log=log_obj,
        ceo_synthesis=str(synthesis),
        ended_reason=ended_reason,
        discussion_mode=DiscussionMode.PARALLEL_THEN_DISCUSS,
        convergence_mode=convergence.mode,
        rounds_completed=rounds_completed,
    )


# ---------------------------------------------------------------------------
# Mode: round_robin (D3 — shuffled per round, abstention allowed)
# ---------------------------------------------------------------------------

async def _run_round_robin(
    *,
    role_agents: Dict[str, LlmAgent],
    company: str,
    industry_context: str,
    product_type: str,
    product_description: str,
    strategic_question: str,
    convergence: ConvergenceConfig,
    run_agent: RunnerFn,
    random_seed: Optional[int],
) -> DeliberationOutcome:
    """Shuffle the role order each round; each role gets one chance.

    Unlike parallel_then_discuss, every round starts cold (no parallel
    initial-position phase). Each round = one full pass through all
    six roles in a different order. Roles may pass; convergence
    follows the same flag rules as D2.
    """
    log_obj = DeliberationLog(
        company=company,
        industry_context=industry_context,
        product_type=product_type,
    )
    rng = random.Random(random_seed)

    quiet_count = 0
    converged = False
    rounds_completed = 0
    ended_reason = "max_rounds"

    round_product_block = (
        f"PRODUCT (context, not a decision)\n{product_description}\n\n"
        if product_description else ""
    )
    for round_idx in range(1, convergence.max_rounds + 1):
        order = list(ROLE_ORDER)
        rng.shuffle(order)
        round_contributions = 0
        for role in order:
            transcript = _render_log_for_discussion(log_obj)
            prompt = (
                f"You are the {role} of {company}. The TMT is discussing:\n\n"
                f"{strategic_question}\n\n"
                f"{round_product_block}"
                f"INDUSTRY CONTEXT\n{industry_context}\n\n"
                "DISCUSSION SO FAR\n"
                f"{transcript if transcript else '(round 1, no contributions yet)'}\n\n"
                "Your turn. Either contribute (state your position, react to "
                "what others said, or update yours) in under 200 words, OR "
                "return exactly the string '[PASS]' to stay silent. Silence "
                "is data. Speak in your own voice as your role."
            )
            text = await run_agent(agent=role_agents[role], prompt=prompt)
            text_str = str(text).strip()
            if _is_pass(text_str):
                log_obj.events.append(
                    DeliberationEvent(
                        index=len(log_obj.events),
                        role=role,
                        kind="other",
                        text="[PASS]",
                        raw_type="RoundRobinPass",
                        phase=f"round_{round_idx}",
                    )
                )
                continue
            round_contributions += 1
            log_obj.events.append(
                DeliberationEvent(
                    index=len(log_obj.events),
                    role=role,
                    kind="text",
                    text=text_str,
                    raw_type="RoundRobinContribution",
                    phase=f"round_{round_idx}",
                )
            )

        rounds_completed = round_idx

        if convergence.mode == ConvergenceMode.TIME_BOXED:
            pass
        elif convergence.mode == ConvergenceMode.STABILITY:
            if round_contributions < convergence.quiet_min_contributions:
                quiet_count += 1
            else:
                quiet_count = 0
            if quiet_count >= convergence.quiet_rounds_threshold:
                converged = True
                ended_reason = "stable"
                break
        elif convergence.mode == ConvergenceMode.SYNTHESISER:
            decision = await _ask_synthesiser_converged(
                log_obj=log_obj,
                company=company,
                strategic_question=strategic_question,
                round_idx=round_idx,
                config=convergence,
                run_agent=run_agent,
            )
            if decision:
                converged = True
                ended_reason = "synthesiser_converged"
                break

    if not converged and rounds_completed >= convergence.max_rounds:
        ended_reason = "max_rounds"

    # Synthesis: same as D2 — CEO writes the collective synthesis.
    transcript = _render_log_for_discussion(log_obj)
    synthesis_prompt = (
        f"You are the CEO of {company}. The TMT has discussed:\n\n"
        f"{strategic_question}\n\n"
        f"DISCUSSION\n{transcript}\n\n"
        "Write the team's COLLECTIVE synthesis — decisions, trade-offs, "
        "where consensus emerged, where tension remains. Reference roles "
        "by name. ~400–600 words."
    )
    synthesis = await run_agent(
        agent=role_agents["CEO"], prompt=synthesis_prompt
    )
    log_obj.events.append(
        DeliberationEvent(
            index=len(log_obj.events),
            role="CEO",
            kind="text",
            text=str(synthesis),
            raw_type="CollectiveSynthesis",
            phase="convergence",
        )
    )
    log_obj.finished_at = datetime.utcnow().isoformat()

    return DeliberationOutcome(
        log=log_obj,
        ceo_synthesis=str(synthesis),
        ended_reason=ended_reason,
        discussion_mode=DiscussionMode.ROUND_ROBIN,
        convergence_mode=convergence.mode,
        rounds_completed=rounds_completed,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_pass(text: str) -> bool:
    """Whether a contribution should be treated as an abstention.

    Recognises '[PASS]' alone (or surrounded by minimal whitespace /
    punctuation) and a few near-misses an LLM might emit.
    """
    if not text:
        return True
    cleaned = text.strip().strip(".").strip("'").strip('"').upper()
    return cleaned in {"[PASS]", "PASS", "(PASS)", "NO COMMENT", "[NO COMMENT]"}


def _render_log_for_discussion(log_obj: DeliberationLog) -> str:
    """Render the log so far as a discussion transcript.

    Used to inject prior contributions into each round's prompt.
    Passes are omitted to keep the transcript readable; the runtime
    log still records them.
    """
    lines: List[str] = []
    for ev in log_obj.events:
        if ev.kind == "other" and ev.text == "[PASS]":
            continue
        prefix = f"[{ev.phase or 'turn'}] {ev.role}"
        lines.append(f"{prefix}: {ev.text}")
    return "\n\n".join(lines)


async def _ask_synthesiser_converged(
    *,
    log_obj: DeliberationLog,
    company: str,
    strategic_question: str,
    round_idx: int,
    config: ConvergenceConfig,
    run_agent: RunnerFn,
) -> bool:
    """Ask a dedicated synthesiser agent whether the team has converged.

    Returns True iff the synthesiser thinks the discussion has reached
    a coherent strategy. Conservative: false-negative is fine (one more
    round) but a false-positive truncates the deliberation.
    """
    transcript = _render_log_for_discussion(log_obj)
    judge_prompt = (
        f"You are an external observer of a TMT deliberation at {company}.\n\n"
        f"Question on the table:\n{strategic_question}\n\n"
        f"DISCUSSION (rounds 1-{round_idx})\n{transcript}\n\n"
        "Has the team converged on a coherent strategy? A 'yes' means "
        "(a) the major substantive points have been raised and "
        "responded to, (b) explicit trade-offs have been weighed, "
        "(c) a recognisable direction has emerged that the team has "
        "not pushed back on in the last round. Be conservative — "
        "false 'yes' truncates the deliberation; false 'no' just adds "
        "another round.\n\n"
        "Reply with exactly one word: YES or NO."
    )
    # Use a Gemini Pro–like agent for the judgement. We construct a
    # one-shot LlmAgent here rather than reuse a role agent, so the
    # judge isn't biased by a role-specific persona.
    synthesiser_agent = LlmAgent(
        name="ConvergenceSynthesiser",
        model=config.synthesiser_model_override or get_observer_model(),
        instruction=(
            "You are a neutral external observer of a TMT meeting. You "
            "judge whether the deliberation has reached a coherent "
            "outcome. Reply YES or NO only."
        ),
        description="Convergence judge for the deliberation orchestrator.",
    )
    reply = await run_agent(agent=synthesiser_agent, prompt=judge_prompt)
    return str(reply).strip().upper().startswith("YES")
