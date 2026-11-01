"""TMT (Top Management Team) multi-agent system, rewritten for ADK
(Agent Development Kit: Google's ready-made software for building agents).

This file sets up the six simulated executives of one firm and runs their
meeting, which the project calls the deliberation. Each agent (a language
model given a name, a role and instructions) only writes text; this code sends
it each prompt (the text sent to a model to get one reply) and records the reply.

What changed vs. the original
-----------------------------
The original `TMTSystemWithA2A` used the `google.adk.a2a` network mode
(A2A, agent-to-agent: a method for agents to call each other over a network;
`to_a2a`, `RemoteA2aAgent`) to expose each role agent (one of the six simulated executives) as an HTTP server
(a program that answers requests over the web) and let other roles dial in via a local
URL. That subpackage is empty in
ADK; the network-A2A mechanism was removed.

The current ADK pattern for cross-agent delegation is in-process (all agents run
inside one program): an
`LlmAgent` (ADK's agent type, built on an LLM, or large language model: a program
trained on vast amounts of text to write likely continuations) that lists other
`LlmAgent`s in its `sub_agents` field
automatically gets a `transfer_to_agent(...)` tool (an action the model can
ask the software to carry out), and the receiving
agent can transfer back if its own `sub_agents` includes the caller.
This rewrite uses that pattern. Behaviour from the user's perspective
is unchanged: the CEO can delegate to any team member, team members
can answer or push the conversation to another role, including back to
the CEO. The only thing lost is the network hop — irrelevant for
research because the deliberation log (the running record of the meeting) is captured
in either case.

Public surface kept stable for existing tests
---------------------------------------------
The public surface is the set of names other code relies on. Tests are small
automatic checks of the code.

- `class TMTSystemWithA2A` (name retained for import-stability, so code that
  loads it by this name keeps working)
  - `self.company`, `self.current_year`,
    `self.industry_context`, `self.product_type`
  - `self.agents`           — dict[role_name → LlmAgent], all six roles
  - `self.conversation_log` — list[dict] populated by deliberation
  - `self.session_service`  — google.adk.sessions.InMemorySessionService
    (a session is a stored conversation re-sent to the model with each new
    prompt; here each call to a model gets its own empty one, outside
    the older CEO-led mode)
  - `self.base_session_id`  — string used to namespace sessions (keep their names apart)
  - `async run_strategic_discussion(...) -> dict`

Public surface removed
----------------------
- `self.ports`                    — networked-A2A artefact (a leftover of the removed
                                    network method), no replacement
- `self.runner`                   — Runner (the part that hands a prompt to an
                                    agent and collects the reply) is per-call
                                    now (it binds to
                                    a specific agent in ADK)
- `self.server_tasks`             — no servers any more
- `start_a2a_servers()`           — gone
- `shutdown_servers()`            — gone
- `create_agents_with_full_network()` — superseded by
                                    `_build_delegating_network()`
- `create_ceo_with_remote_team()` — same
- `conduct_ceo_interview()`       — superseded by
                                    `orchestrator.panel_debriefing`

One test, `test_ports_defined_for_all_roles`, asserts the removed
attribute; it is updated to assert the new architecture's contract
in the same commit (one saved change in the project's history) as this file.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

# `google.genai.types` is imported lazily (only when first needed) inside
# `run_strategic_discussion`
# so the module loads cleanly under test-time stubs (simple stand-ins for real
# software, so that tests run free; the project root
# conftest, the tests' shared setup file, stubs `google.adk` but not `google.genai`,
# and the existing
# unit tests only exercise __init__ (the setup step) — never the live deliberation path).

try:
    from .orchestrator.usage_log import UsageLog
    from .roles import (
        create_ceo_agent,
        create_cmo_agent,
        create_coo_agent,
        create_cto_agent,
        create_product_designer_agent,
        create_product_strategist_agent,
    )
except (ImportError, ValueError):  # pragma: no cover  (script-style execution)
    from orchestrator.usage_log import UsageLog  # type: ignore[no-redef]
    from roles import (  # type: ignore[no-redef]
        create_ceo_agent,
        create_cmo_agent,
        create_coo_agent,
        create_cto_agent,
        create_product_designer_agent,
        create_product_strategist_agent,
    )

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROLE_ORDER: tuple[str, ...] = (
    "CEO",
    "CTO",
    "COO",
    "CMO",
    "Product_Strategist",
    "Product_Designer",
)

# App name passed to the InMemorySessionService. Single value for now;
# every session lives under this app namespace.
_APP_NAME = "tmt_multi_agent"


# ---------------------------------------------------------------------------
# Generic provider-agnostic retry detection
# ---------------------------------------------------------------------------
#
# A retry means sending a failed model call (one prompt to a model and one
# reply back) again. Different LLM providers (the companies or services that
# supply models: Gemini, which is Google's, OpenAI, Anthropic, and Ollama, which
# runs models on your own computer, possibly via LiteLLM, software that reaches
# many providers' models in the same way) emit different exception types (the
# error reports a program raises) and messages for the same underlying
# transient (temporary) errors. We treat all of the following as retryable
# and parse a suggested delay where possible. The numbers are web error
# codes. A rate limit is a provider's cap on how much a customer may send
# per minute, and a timeout is giving up after waiting too long:
#
#   429  rate limit       (Gemini RESOURCE_EXHAUSTED, OpenAI RateLimitError,
#                          Anthropic RateLimitError)
#   500  internal error   (any provider; sometimes transient)
#   502  bad gateway      (any provider; transient)
#   503  unavailable      (Gemini UNAVAILABLE, OpenAI/Anthropic 503)
#   504  gateway timeout
#   529  overloaded       (Anthropic-specific overload signal)
#
# Plus transient network errors detected by exception type name:
#   ConnectionError, Timeout, TimeoutError, APIConnectionError,
#   APITimeoutError, ReadTimeout, etc.

# Status codes whose presence in the exception message or attributes
# triggers a retry.
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504, 529})

# Exception type names (case-insensitive substring match) treated as
# retryable transient network errors even when no status code is
# present. Covers Python's standard library (stdlib), httpx and requests (two
# packages for making web requests), and SDK-specific wrappers (an SDK, or
# software development kit, is a company's toolkit for using its service).
_RETRYABLE_EXC_NAMES: tuple[str, ...] = (
    "RateLimitError",
    "ServiceUnavailableError",
    "ServerError",
    "OverloadedError",
    "APIConnectionError",
    "APITimeoutError",
    "Timeout",
    "TimeoutError",
    "ConnectionError",
    "ConnectionResetError",
    "ReadTimeout",
    "RemoteProtocolError",
)

# Patterns that extract a "wait this long" hint from the error message.
# Ordered most-specific → most-general so we prefer structured fields
# over free-form text when both appear.
_RETRY_DELAY_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Gemini structured: "'retryDelay': '46s'"
    re.compile(r"['\"]retryDelay['\"]\s*:\s*['\"](\d+(?:\.\d+)?)s?['\"]"),
    # Generic retry-after header: 'retry-after': '46' or "retry-after: 46"
    re.compile(r"['\"]?retry[-_ ]after['\"]?\s*[:=]\s*['\"]?([\d.]+)['\"]?"),
    # Gemini free-form: 'Please retry in 46.163097919s.'
    re.compile(r"retry\s+in\s+([\d.]+)\s*s", re.IGNORECASE),
    # OpenAI variant: 'Please try again in 12.345s' / '12345ms'
    re.compile(r"try\s+again\s+in\s+([\d.]+)\s*s", re.IGNORECASE),
    re.compile(r"try\s+again\s+in\s+([\d.]+)\s*ms", re.IGNORECASE),
    # Anthropic variant: 'try again in 30 seconds'
    re.compile(r"try\s+again\s+in\s+([\d.]+)\s*second", re.IGNORECASE),
    # Generic "wait N seconds" hint
    re.compile(r"wait\s+([\d.]+)\s*second", re.IGNORECASE),
)


def _extract_status_code(exc: Exception) -> Optional[int]:
    """Best-effort status-code extraction from common SDK exception shapes."""
    # SDK exceptions often carry a status_code attribute directly (Anthropic,
    # OpenAI, LiteLLM, ADK).
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    # httpx / requests-based exceptions wrap a response.
    resp = getattr(exc, "response", None)
    if resp is not None:
        status = getattr(resp, "status_code", None)
        if isinstance(status, int):
            return status
    # Some SDKs put the code on a `code` attribute.
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    return None


def _detect_retryable_status(exc: Exception) -> Optional[int]:
    """Return a retryable status code if the exception warrants retry.

    Tries (in order):
      1. Attribute-based status code from the SDK exception.
      2. Numeric status code embedded in the message.
      3. Provider-specific string markers (RESOURCE_EXHAUSTED, UNAVAILABLE,
         OVERLOADED, rate_limit_error, etc.).
      4. Exception type name match against known transient errors
         (ConnectionError, Timeout, …).
    Returns the inferred status (or 429/503 surrogate for type-based
    matches) on hit, `None` otherwise.
    """
    status = _extract_status_code(exc)
    if status in _RETRYABLE_STATUS_CODES:
        return status

    msg = str(exc)
    msg_upper = msg.upper()

    # Numeric status in the message text.
    for code in _RETRYABLE_STATUS_CODES:
        # Use word boundaries to avoid '5290' matching 529.
        if re.search(rf"\b{code}\b", msg):
            return code

    # Provider-specific string markers → infer a status.
    if (
        "RESOURCE_EXHAUSTED" in msg_upper
        or "RATE_LIMIT_ERROR" in msg_upper
        or "RATE LIMIT" in msg_upper
        or "RATELIMIT" in msg_upper
        or "TOO MANY REQUESTS" in msg_upper
    ):
        return 429
    if "OVERLOADED" in msg_upper:
        return 529
    if (
        "SERVICE_UNAVAILABLE" in msg_upper
        or "UNAVAILABLE" in msg_upper
    ):
        return 503

    # Fallback: exception type name.
    type_name = type(exc).__name__
    for marker in _RETRYABLE_EXC_NAMES:
        if marker.lower() in type_name.lower():
            # Network / timeout / generic transient — surrogate as 503.
            return 503

    return None


def _parse_retry_delay(
    exc: Exception, attempt: int, max_delay: float = 60.0
) -> Optional[float]:
    """Return seconds to wait before retrying `exc`, or `None` if not retryable.

    Args:
        exc: The caught exception.
        attempt: 0-based attempt index, used for exponential backoff
            (waiting longer before each new attempt) when the provider didn't supply a retry hint.
        max_delay: Cap on the returned delay. Protects against
            adversarial / huge retry hints.

    Strategy:
      1. If the exception is not retryable, return None.
      2. Try to parse an explicit retry hint from the message
         (handles ms units by dividing by 1000).
      3. Otherwise, exponential backoff with jitter (a small random addition, so
         calls do not all retry together):
            2^attempt + random(0..1), capped at max_delay.
    """
    status = _detect_retryable_status(exc)
    if status is None:
        return None

    msg = str(exc)
    for pattern in _RETRY_DELAY_PATTERNS:
        m = pattern.search(msg)
        if not m:
            continue
        try:
            value = float(m.group(1))
        except (ValueError, IndexError):
            continue
        # If the matched pattern was the ms variant, convert.
        if "ms" in pattern.pattern:
            value = value / 1000.0
        return min(value, max_delay)

    # No explicit hint → exponential backoff with jitter.
    import random
    base = min(2.0 ** attempt, max_delay)
    jitter = random.uniform(0.0, 1.0)
    return min(base + jitter, max_delay)


def _parse_429_retry_delay(exc: Exception) -> Optional[float]:
    """Back-compat alias (a second name, kept so older code still works) for the original Gemini-only retry parser.

    Existing tests import this name and pass a single `exc` argument.
    The new generic implementation takes an `attempt` index; we pass
    0 so the test sees the provider's hint when present, or a tiny
    backoff (1.x s) when not.
    """
    return _parse_retry_delay(exc, attempt=0)


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

class TMTSystemWithA2A:
    """Top management team for one (company, scenario) tuple. A scenario is the
    setting of a run: one firm, one industry context and one product type.

    Name kept identical to the original class for import-stability
    with existing tests and downstream callers. The "A2A" suffix is
    historical — under ADK delegation is in-process via
    `transfer_to_agent`, not a network protocol.

    Lifecycle
    ---------
        system = TMTSystemWithA2A(company="OpenAI", ...)
        result = await system.run_strategic_discussion(...)
        # result['ceo_decision']        : str   (the CEO's final synthesis)
        # result['conversation_log']    : list  (one record per event,
        #                                        compatible with the
        #                                        DeliberationLog schema, a template
        #                                        for the fields each record holds)
        # result['events_count']        : int
    """

    def __init__(
        self,
        company: str,
        current_year: int = 2030,
        industry_context: str = "Dynamic",
        product_type: str = "Novel",
    ) -> None:
        self.company = company
        self.current_year = current_year
        self.industry_context = industry_context
        self.product_type = product_type

        # Six base role agents. These are the canonical agent instances
        # external callers index by role name. They have NO sub_agents
        # set on them — `self.agents['CEO']` is just the plain CEO.
        # Bidirectional delegation is set up at run-time inside
        # `run_strategic_discussion` by building shallow copies (light duplicates) that
        # link to each other (see `_build_delegating_network`).
        self.agents: Dict[str, LlmAgent] = {
            "CEO": create_ceo_agent(company, current_year, industry_context, product_type),
            "CTO": create_cto_agent(company, current_year, industry_context, product_type),
            "COO": create_coo_agent(company, current_year, industry_context, product_type),
            "CMO": create_cmo_agent(company, current_year, industry_context, product_type),
            "Product_Strategist": create_product_strategist_agent(
                company, current_year, industry_context, product_type
            ),
            "Product_Designer": create_product_designer_agent(
                company, current_year, industry_context, product_type
            ),
        }

        # Session service is shared across the runners that
        # `run_strategic_discussion` constructs per call. ADK's
        # Runner constructor takes both `agent` and `session_service`,
        # which is why we no longer hold a single `self.runner`.
        self.session_service = InMemorySessionService()
        # Per-run namespace for ADK sessions. Microsecond timestamp
        # PLUS a short uuid4 fragment (part of a random identifier) so two instances created in the
        # same second (e.g. a test harness, which is a small program that repeats
        # something under set conditions, or a simulation runner spawning
        # rapid back-to-back replicates, meaning repeat runs) never collide. Critical for
        # the "each run is hermetic" (sealed off from other runs) property documented in the
        # design notes.
        import uuid as _uuid
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        self.base_session_id = (
            f"{company}_{ts}_{_uuid.uuid4().hex[:8]}"
        )

        # Populated by `run_strategic_discussion`. Each entry mirrors
        # `data_capture.DeliberationEvent` field-for-field but stays as
        # a plain dict here to avoid a runtime dependency cycle (two files each
        # needing the other) between
        # `agent` and `data_capture`. The walker in
        # `data_capture.walk_events` can ingest these dicts unchanged.
        self.conversation_log: List[Dict[str, Any]] = []

        # Tokens (small pieces of text, often about three-quarters of a word, that
        # models read and write and providers charge by) used by every model call
        # this run.
        self.usage_log = UsageLog()

        # Numbers each model call's own session (see `_new_call_session_id`).
        self._call_counts: Dict[str, int] = {}

        # Session ids for the legacy CEO-led path only, whose agents hand
        # the conversation to each other within one session.
        self._role_session_ids: Dict[str, str] = {}
        # Track which (app_name, role) sessions have actually been
        # created so we don't try to re-create.
        self._created_sessions: set[tuple[str, str]] = set()

        # Pluggable for the concurrent_mode orchestrator (the code that runs the
        # default discussion mode, in which all six roles act at once)
        # which stores its SharedState (the discussion's record, including each
        # role's notes, draft and inbox of questions from colleagues) on the
        # deliberation outcome.
        # Held here for one run only.
        self._last_concurrent_shared_state: Any = None

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    async def _new_call_session_id(self, agent_name: str) -> str:
        """An empty session for one model call.

        A shared session re-sends every earlier prompt on every call. Each
        deliberation prompt already carries the transcript and the role's
        own notes, draft and inbox, so nothing needs to carry over.
        """
        count = self._call_counts.get(agent_name, 0) + 1
        self._call_counts[agent_name] = count
        sess_id = f"{self.base_session_id}_{agent_name}_{count}"
        await self.session_service.create_session(
            app_name=_APP_NAME,
            user_id="researcher",
            session_id=sess_id,
        )
        return sess_id

    async def _get_role_session_id(self, role_name: str) -> str:
        """Return the ADK session_id for `role_name` in the CEO-led path.

        On first call for a given role, creates a session in
        `self.session_service`. Subsequent calls return the same id.
        """
        existing = self._role_session_ids.get(role_name)
        if existing is not None:
            return existing
        sess_id = f"{self.base_session_id}_role_{role_name}"
        if (_APP_NAME, role_name) not in self._created_sessions:
            await self.session_service.create_session(
                app_name=_APP_NAME,
                user_id="researcher",
                session_id=sess_id,
            )
            self._created_sessions.add((_APP_NAME, role_name))
        self._role_session_ids[role_name] = sess_id
        return sess_id

    # ------------------------------------------------------------------
    # Network setup (in-process delegation, no servers)
    # ------------------------------------------------------------------

    def _build_delegating_network(self) -> Dict[str, LlmAgent]:
        """Build a tree-shaped agent network that supports bidirectional transfer.

        ADK represents inter-agent delegation as a TREE, not a
        graph. Each agent has at most one parent (`parent_agent`) and
        any number of children (`sub_agents`). Cross-references between
        peers via `sub_agents` create cycles in ADK's recursive
        `find_agent` lookup and crash the runner — so we don't do that.

        Bidirectional transfer is enabled by the default flag values:
          - `disallow_transfer_to_parent=False` → sub-agents can hand
            control back up to the parent.
          - `disallow_transfer_to_peers=False`  → sub-agents can hand
            control SIDEWAYS to a sibling under the same parent.

        Concretely we build:
              CEO  (root)
              ├── CTO
              ├── COO
              ├── CMO
              ├── Product_Strategist
              └── Product_Designer

        CEO can transfer to any of the five via its sub_agents. Each
        sub-agent can transfer (a) back to CEO (parent), (b) sideways
        to any peer (CTO ↔ CMO etc.) via ADK's peer-transfer mechanism,
        which uses the shared parent's sub_agent registry. No peer
        references in `sub_agents` are needed — peer transfer works
        through the tree.

        Behaviour from the user's perspective is identical to a fully
        connected graph. The implementation difference is what makes it
        not crash.
        """
        delegation_block_peer = (
            "\n\nNETWORK ACCESS — YOU ARE A TMT MEMBER\n"
            "------------------------------------\n"
            "You can transfer the conversation to another TMT role when "
            "their perspective would materially improve the decision. "
            "You can also transfer back to the CEO when you have given "
            "your input. Treat this as a natural, fluid discussion — "
            "role boundaries can blur on complex innovation problems, "
            "and that is part of the point.\n"
            "\nAvailable transfer targets:\n"
            "  - CEO (parent: transfer back when your input is complete)\n"
            "  - peers: CTO, COO, CMO, Product_Strategist, Product_Designer "
            "(transfer sideways for a different functional perspective)\n"
        )
        delegation_block_ceo = (
            "\n\nNETWORK ACCESS — YOU ARE THE CEO\n"
            "--------------------------------\n"
            "You have access to the rest of the TMT as sub-agents. When "
            "another role's perspective would materially improve the "
            "decision, transfer the conversation to them by name. They "
            "may transfer back to you when their input is complete, or "
            "transfer sideways to a peer. After you have enough input "
            "to commit, produce your synthesis and the call you are "
            "making.\n"
            "\nAvailable team members (transfer targets):\n"
            "  - CTO, COO, CMO, Product_Strategist, Product_Designer\n"
        )

        # Build the five peers first. They have NO sub_agents — ADK
        # will set their `parent_agent` automatically when the CEO is
        # constructed with them as sub_agents.
        peers: Dict[str, LlmAgent] = {}
        for role in ROLE_ORDER:
            if role == "CEO":
                continue
            base = self.agents[role]
            peers[role] = LlmAgent(
                name=base.name,
                model=base.model,
                instruction=(base.instruction or "") + delegation_block_peer,
                description=base.description,
            )

        # Build the CEO with the five peers as sub_agents.
        base_ceo = self.agents["CEO"]
        ceo = LlmAgent(
            name=base_ceo.name,
            model=base_ceo.model,
            instruction=(base_ceo.instruction or "") + delegation_block_ceo,
            description=base_ceo.description,
            sub_agents=list(peers.values()),
        )

        # Return a dict that includes the CEO root and all five peers.
        # Callers index by role name.
        network: Dict[str, LlmAgent] = {"CEO": ceo}
        network.update(peers)
        return network

    # ------------------------------------------------------------------
    # Strategic deliberation
    # ------------------------------------------------------------------

    async def run_strategic_discussion(
        self,
        product_description: Optional[str] = None,
        strategic_question: str = "",
        product_type: Optional[str] = None,
        context: Optional[str] = None,
        deliberation_config: Optional["DeliberationConfig"] = None,
        researcher_stream: Optional[Any] = None,
        scenario_brief: Optional[str] = None,
        rag_session: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Run one TMT deliberation and return the structured outputs.

        Args:
            product_description: OPTIONAL free-form context about a
                product the firm is already considering. When None
                (default, meaning no value is given) the team has to decide what to build as part
                of the deliberation — no PRODUCT block is added to the
                prompt. Pre-filling this turns the discussion into a
                release-strategy meeting; leave it None unless you want
                a controlled experiment with a fixed product.
            strategic_question: The question the CEO is asked to lead
                the team in answering.
            product_type: Optional override of the system's
                `product_type`. Carried through to the CEO prompt.
            context: Optional free-text description of the industry
                context. Used for prompt phrasing only; the structured
                `industry_context` ("Dynamic" / "Stable") still flows
                through to the role agents via their factory.
            deliberation_config: Which discussion pattern + convergence
                criterion (the stop rule: the condition that ends the discussion)
                to use. None ⇒ default `concurrent` mode, the mode the
                command line uses and the only one connected to retrieval
                during deliberation and to live field notes.
                Pass `DeliberationConfig(discussion_mode=
                DiscussionMode.CEO_LED)` to get the legacy ADK
                tree-based behaviour.

        Returns:
            ```
            {
                "company": str,
                "product_type": str,
                "industry_context": str,
                "context": str,
                "strategic_question": str,
                "ceo_decision": str,           # final synthesis text
                "conversation_log": list[dict] # one entry per event
                "events_count": int,
                "timestamp": str,              # ISO 8601
                "discussion_mode": str,
                "convergence_mode": str | None,
                "ended_reason": str,
                "rounds_completed": int,
            }
            ```
        """
        # Lazy import — heavy modules are imported here so plain
        # construction of TMTSystemWithA2A (what tests exercise) does
        # not pull them in.
        from google.genai import types

        try:
            from .orchestrator.deliberation import (
                DeliberationConfig as _Cfg,
                DiscussionMode,
                run_deliberation,
            )
        except (ImportError, ValueError):  # pragma: no cover  (script-style)
            from orchestrator.deliberation import (  # type: ignore[no-redef]
                DeliberationConfig as _Cfg,
                DiscussionMode,
                run_deliberation,
            )

        product_type = product_type or self.product_type
        context_text = context or (
            f"{self.industry_context} competitive environment"
        )
        config = deliberation_config or _Cfg()

        # Normalise `None` → `""` so downstream modules (orchestrator,
        # role-task builders, prompt formatters) can rely on a string
        # type. The empty-string case is handled by truthiness checks in
        # the prompt builders — no PRODUCT block is rendered.
        if product_description is None:
            product_description = ""

        log.info(
            "Strategic discussion: %s / %s / %s (mode=%s)",
            self.company, self.industry_context, product_type,
            config.discussion_mode.value,
        )

        # Resolve rate-limit retry policy from config.concurrent if set,
        # otherwise use safe defaults (works for all phases, the numbered stages of a run).
        retry_cfg = getattr(config, "concurrent", None)
        max_retries = (
            retry_cfg.max_retries_per_call
            if retry_cfg is not None and hasattr(retry_cfg, "max_retries_per_call")
            else 5
        )

        # ----- Build a per-agent runner. Each call has its own empty
        # session (see `_new_call_session_id`), because the prompt already
        # carries the transcript and the role's own notes, draft and inbox.
        #
        # Each call also retries on Gemini 429 RESOURCE_EXHAUSTED errors:
        # parses the suggested retryDelay from the error payload, sleeps
        # for it, and retries the SAME call. Retries do NOT consume the
        # caller's action slot (an action is one move by a role in the
        # deliberation; the orchestrator counts actions only
        # after this returns). Up to `max_retries` attempts per call.
        async def _run_one_agent(*, agent: LlmAgent, prompt: str) -> str:
            local_runner = Runner(
                agent=agent,
                app_name=_APP_NAME,
                session_service=self.session_service,
            )
            local_msg = types.Content(
                role="user", parts=[types.Part(text=prompt)],
            )

            # Provider-scoped rate-limit throttle (a deliberate pause before
            # sending). No-op (it does nothing) for providers
            # without a rate-limit config (ollama, unknown specs) and
            # for providers with very generous TPM (tokens per minute)
            # ceilings (Gemini on Vertex, Google's paid cloud service offering
            # models). Where it matters — Claude tier 1, Groq free (low-priced
            # plans with tight limits; Groq is a company that hosts models) —
            # this blocks the call until the bucket (the allowance left for
            # now) can satisfy the
            # estimated cost, preventing synchronised retry storms
            # when six concurrent role agents would otherwise all
            # blow the bucket and 429-loop together.
            try:
                from .orchestrator.rate_limit import acquire_for_call
            except (ImportError, ValueError):  # pragma: no cover  (script-style)
                from orchestrator.rate_limit import acquire_for_call  # type: ignore[no-redef]

            # Per-call wall-clock (real elapsed time) timeout. The Meta-2032 cell
            # (one combination of firm, industry context and product type)
            # post-mortem (review after a run)
            # caught a single Vertex AI HTTP request hanging indefinitely
            # without raising — the client just sat waiting for data
            # that never arrived. That silent hang killed the whole
            # phase because nothing in our retry path fires until an
            # exception lands. `asyncio.wait_for` converts the hang
            # into a `TimeoutError`, which the retry classifier below
            # treats as transient (see `_parse_retry_delay` +
            # `_RETRYABLE_TYPE_NAMES`).
            _LLM_CALL_TIMEOUT_S = float(os.environ.get(
                "TMT_LLM_CALL_TIMEOUT_S", "180"
            ))

            async def _consume_runner() -> str:
                """Drive run_async to completion; returns concatenated text."""
                chunks: List[str] = []
                # A new session for each attempt, so a retry does not send
                # the failed attempt's prompt as well.
                session_id = await self._new_call_session_id(agent.name)
                async for event in local_runner.run_async(
                    user_id="researcher",
                    session_id=session_id,
                    new_message=local_msg,
                ):
                    self.usage_log.record(agent, getattr(event, "usage_metadata", None))
                    content = getattr(event, "content", None)
                    if content is None or not hasattr(content, "parts"):
                        continue
                    for part in content.parts or []:
                        t = getattr(part, "text", None)
                        if t:
                            chunks.append(t)
                return "\n".join(chunks).strip()

            last_exc: Optional[Exception] = None
            for attempt in range(max_retries + 1):
                try:
                    # `getattr` so stub agents in tests (which only carry
                    # `.name`) don't blow up at the throttle call.
                    await acquire_for_call(getattr(agent, "model", None), prompt)
                    return await asyncio.wait_for(
                        _consume_runner(),
                        timeout=_LLM_CALL_TIMEOUT_S,
                    )
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    delay = _parse_retry_delay(exc, attempt=attempt)
                    if delay is None or attempt >= max_retries:
                        # Not retryable (or exhausted retries) — let
                        # caller handle. `_parse_retry_delay` returns
                        # None for non-transient errors (400, 401,
                        # 404, context-window (the most text a model can
                        # take in during one call), etc.).
                        raise
                    log.info(
                        "%s transient error (%s); sleeping %.1fs "
                        "(attempt %d/%d)",
                        agent.name, type(exc).__name__,
                        delay, attempt + 1, max_retries,
                    )
                    await asyncio.sleep(delay)
            # Unreachable in practice — the loop above always returns or raises.
            if last_exc is not None:
                raise last_exc
            return ""

        # ----- ceo_led_fallback: the existing ADK tree-based path ------
        async def _ceo_led_fallback():
            from .orchestrator.deliberation import (
                DeliberationOutcome, DiscussionMode as _M,
            )
            network = self._build_delegating_network()
            ceo = network["CEO"]
            ceo_prompt = self._compose_ceo_prompt(
                product_description=product_description,
                strategic_question=strategic_question,
                product_type=product_type,
                context_text=context_text,
                scenario_brief=scenario_brief,
            )
            runner = Runner(
                agent=ceo,
                app_name=_APP_NAME,
                session_service=self.session_service,
            )
            # One session, because this mode's agents hand the conversation
            # to each other within this single call.
            session_id = await self._get_role_session_id("CEO")
            class _S:
                id = session_id
            session = _S()
            new_message = types.Content(
                role="user", parts=[types.Part(text=ceo_prompt)],
            )

            try:
                from .data_capture import DeliberationEvent, DeliberationLog
            except (ImportError, ValueError):  # pragma: no cover
                from data_capture import DeliberationEvent, DeliberationLog  # type: ignore[no-redef]

            log_obj = DeliberationLog(
                company=self.company,
                industry_context=self.industry_context,
                product_type=product_type,
            )
            text_parts: List[str] = []
            async for event in runner.run_async(
                user_id="researcher",
                session_id=session.id,
                new_message=new_message,
            ):
                entry = self._event_to_log_entry(event, index=len(log_obj.events))
                if entry is not None:
                    log_obj.events.append(DeliberationEvent.model_validate(entry))
                if getattr(event, "content", None) is not None:
                    for part in event.content.parts or []:
                        t = getattr(part, "text", None)
                        if t:
                            text_parts.append(t)
            log_obj.finished_at = datetime.utcnow().isoformat()
            ceo_synth = self._extract_ceo_synthesis(text_parts)
            return DeliberationOutcome(
                log=log_obj,
                ceo_synthesis=ceo_synth,
                ended_reason="transfer_chain_complete",
                discussion_mode=_M.CEO_LED,
                rounds_completed=1,
            )

        # ----- Dispatch ------------------------------------------------
        outcome = await run_deliberation(
            role_agents=self.agents,
            company=self.company,
            industry_context=self.industry_context,
            product_type=product_type,
            product_description=product_description,
            strategic_question=strategic_question,
            config=config,
            run_agent=_run_one_agent,
            researcher_stream=researcher_stream,
            ceo_led_fallback=_ceo_led_fallback
            if config.discussion_mode == DiscussionMode.CEO_LED
            else None,
            rag_session=rag_session,
            scenario_brief=scenario_brief,
        )

        # Mirror the orchestrator's log into self.conversation_log
        # (compatible dict shape that downstream consumers expect).
        self.conversation_log = [e.model_dump() for e in outcome.log.events]
        ceo_decision = outcome.ceo_synthesis
        events_count = len(self.conversation_log)

        # If CONCURRENT mode populated a SharedState, stash it for the
        # researcher (the seventh agent, which watches and questions the team)
        # phase to read scratchpads (private notes) / drafts / inboxes.
        self._last_concurrent_shared_state = (
            outcome.__dict__.get("_concurrent_shared_state")
        )

        return {
            "company": self.company,
            "product_type": product_type,
            "industry_context": self.industry_context,
            "context": context_text,
            "strategic_question": strategic_question,
            "ceo_decision": ceo_decision,
            "conversation_log": self.conversation_log,
            "events_count": events_count,
            "timestamp": datetime.utcnow().isoformat(),
            "discussion_mode": outcome.discussion_mode.value,
            "convergence_mode": (
                outcome.convergence_mode.value
                if outcome.convergence_mode is not None
                else None
            ),
            "ended_reason": outcome.ended_reason,
            "rounds_completed": outcome.rounds_completed,
        }

    # ------------------------------------------------------------------
    # Prompt composition + event handling
    # ------------------------------------------------------------------

    def _compose_ceo_prompt(
        self,
        *,
        product_description: Optional[str],
        strategic_question: str,
        product_type: str,
        context_text: str,
        scenario_brief: Optional[str] = None,
    ) -> str:
        # PRODUCT block only included when the caller deliberately
        # passes a specific product to deliberate over. Default
        # behaviour (product_description is None) leaves it out so the
        # team has to choose the product direction themselves.
        product_block = ""
        if product_description:
            product_block = (
                "\n\nPRODUCT (context the caller has provided; the team "
                "may still question or change it):\n" + product_description
            )

        # `scenario_brief` comes from the study config (the settings of a study, a
        # folder under `studies/`; e.g. "An AI
        # firm operating in a competitive industry."). Bounds the
        # firm's domain without dictating a product.
        company_line = f"Company: {self.company}"
        if scenario_brief:
            company_line = f"Company: {self.company} ({scenario_brief.rstrip('.')})"

        return f"""STRATEGIC DECISION CONTEXT

{company_line}
Year: {self.current_year}
Product type: {product_type}
Industry context: {self.industry_context} ({context_text}){product_block}

STRATEGIC QUESTION
{strategic_question}

YOUR TASK
You lead the TMT through this decision. Consult the rest of the team
when their perspective would materially improve the outcome — transfer
the conversation to whichever role is best placed to answer, then
incorporate what they say. Team members may transfer back to you or
to each other; that is by design. When you have enough to commit,
produce your synthesis and the call you are making.
"""

    @staticmethod
    def _event_to_log_entry(event: Any, *, index: int) -> Optional[Dict[str, Any]]:
        """Convert one ADK event into a plain-dict log entry.

        The dict shape matches `data_capture.DeliberationEvent` so
        downstream consumers can either use it directly or hand it to
        `data_capture.walk_events` for re-validation. We do duck-typing
        (checking what an object offers, not its exact type)
        on `event` rather than importing concrete ADK event classes so
        small API (the agreed way one program asks another for a service) shifts
        between ADK minor versions don't break us.
        """
        type_name = type(event).__name__.lower()
        author = (
            getattr(event, "author", None)
            or getattr(event, "agent_name", None)
            or getattr(event, "role", None)
            or "unknown"
        )
        target = (
            getattr(event, "transfer_to_agent", None)
            or getattr(event, "delegate_to", None)
            or None
        )

        # Inspect content parts for function_call / function_response —
        # ADK emits transfer_to_agent as a regular function_call
        # part inside a content event (not a dedicated event subclass),
        # so we need part-level classification to surface delegations.
        text_parts: List[str] = []
        function_calls: List[Any] = []
        function_responses: List[Any] = []
        content = getattr(event, "content", None)
        if content is not None and hasattr(content, "parts"):
            for part in content.parts or []:
                t = getattr(part, "text", None)
                if t:
                    text_parts.append(t)
                fc = getattr(part, "function_call", None)
                if fc is not None:
                    function_calls.append(fc)
                fr = getattr(part, "function_response", None)
                if fr is not None:
                    function_responses.append(fr)

        # Classification, in priority order.
        if "tool" in type_name and "result" in type_name:
            kind = "tool_result"
        elif "tool" in type_name and ("call" in type_name or "request" in type_name):
            kind = "tool_call"
        elif "transfer" in type_name or "delegation" in type_name:
            kind = "delegation"
        elif function_calls:
            # Promote function_call events to "delegation" when the
            # tool name looks like a transfer; otherwise tool_call.
            for fc in function_calls:
                fc_name = getattr(fc, "name", "") or ""
                if "transfer" in fc_name.lower() or "delegate" in fc_name.lower():
                    kind = "delegation"
                    # Extract the target role from the call args if available.
                    fc_args = getattr(fc, "args", None) or {}
                    if isinstance(fc_args, dict):
                        target = (
                            fc_args.get("agent_name")
                            or fc_args.get("target_agent")
                            or fc_args.get("to")
                            or target
                        )
                    break
            else:
                kind = "tool_call"
        elif function_responses:
            kind = "tool_result"
        elif content is not None and hasattr(content, "parts"):
            kind = "text"
        else:
            kind = "other"

        text = "\n".join(text_parts).strip()

        # Drop events that have neither a role nor any content — they
        # are usually internal ADK bookkeeping and would pollute the log.
        if not text and kind == "other" and author == "unknown":
            return None

        return {
            "index": index,
            "role": str(author),
            "addressed_to": str(target) if target else None,
            "kind": kind,
            "text": text,
            "timestamp": datetime.utcnow().isoformat(),
            "raw_type": type(event).__name__,
        }

    @staticmethod
    def _extract_ceo_synthesis(text_parts: List[str]) -> str:
        """The CEO's synthesis is the last textual contribution.

        ADK's transfer_to_agent chain returns control to the originating
        agent when sub-calls finish, so the LAST text in the stream is
        the CEO closing out the deliberation. Falls back to the
        concatenation of everything if we can't isolate it.
        """
        if not text_parts:
            return ""
        # Heuristic (rule of thumb): the closing text is usually substantially longer
        # than transient transfer-glue text. Pick the longest tail-end
        # contribution: scan backwards for the first part > 200 chars.
        for tp in reversed(text_parts):
            if len(tp.strip()) >= 200:
                return tp.strip()
        # Otherwise just return the last part.
        return text_parts[-1].strip()


# ---------------------------------------------------------------------------
# Backwards-compatible alias kept temporarily.
#
# Some callers / future contributors may type the system as TMTSystem;
# expose that name in addition to the original.
# ---------------------------------------------------------------------------
TMTSystem = TMTSystemWithA2A
