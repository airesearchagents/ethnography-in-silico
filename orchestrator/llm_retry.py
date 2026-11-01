"""Shared transient-error retry helper for LLM-facing phases.

An LLM (large language model) call is one prompt sent to a model and one reply back.
When a call fails for a transient (temporary) reason, this file retries it (tries
again after a wait), so that a run (one complete simulated meeting and debrief) does
not lose the work. A phase is a numbered stage of a run. An agent is a language model given a name, a role and instructions.

Originally lived in `orchestrator/panel_debriefing.py` as `_safe_run` +
helpers, behind the Phase-4 hardening (changes to make it more robust) landed against the
Meta/Dynamic/Novel/2032 cell (one combination of firm, industry context and
product type; this one set in 2032) post-mortem. Lifted here so:

  * Phase 2 (`orchestrator/artefact_collection.py`) can use the same
    retry policy — Phase 2 was independently losing artefacts (the roles'
    strategy documents) to transient 429s (the rate-limit error code;
    the Product_Designer / CMO cases in two
    sequential Meta runs), the SAME failure mode the Phase-4 helper
    was designed to absorb.
  * Future phases that wrap an LLM call don't have to re-invent the
    transient-error classifier.

Contract
--------
A call site that wraps a single LLM invocation can replace::

    try:
        result = await run_agent(agent=agent, prompt=prompt)
    except Exception as exc:
        log.exception("...")
        return None

with::

    from .llm_retry import safe_run
    result = await safe_run(run_agent, agent, prompt)

`safe_run` retries on transient errors (429 / 5xx, a server failure /
RateLimitError / asyncio.TimeoutError) with provider-honoured backoff (waiting longer
before each new attempt, or as long as the provider, the company supplying the
model, asks). Non-transient errors (auth, a rejected key; 400 and 404, a request that cannot succeed;
validation, a reply with the wrong fields) return ``None`` immediately —
the existing caller's ``if result is None: continue`` path handles
that the same way it always did.

Default policy mirrors the Phase-4 hardening exactly:
    5 retries, 2s → 4s → 8s → 16s → 32s exponential backoff,
    capped at 60s, provider hints honoured.
"""

from __future__ import annotations

import asyncio
import logging
import re
import traceback
from typing import Any, Awaitable, Callable, Optional, Tuple

from google.adk.agents import LlmAgent

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Retry-policy constants
# ---------------------------------------------------------------------------

MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 60.0
BACKOFF_FACTOR = 2.0


# Transient-error signatures we retry on. Covers:
#   * Provider rate-limit codes (429, RESOURCE_EXHAUSTED, RateLimitError)
#   * 5xx server-side errors (5xx, UNAVAILABLE, ServerError,
#     InternalServerError as raised by LiteLLM, software that reaches many
#     providers' models in the same way)
#   * Capacity / overload signals ("overloaded", "capacity",
#     "temporarily unavailable")
#   * Network / timeout failures (asyncio.TimeoutError, "timeout",
#     "timed out", "DeadlineExceeded")
#   * Connection-level disconnects from the underlying HTTPX / aiohttp (tools
#     that carry web requests) transport (ServerDisconnected, ReadError, ConnectionError,
#     "Server disconnected"). These surface when a reasoning model's
#     thinking phase (when it writes working-out text before replying)
#     exceeds the HTTP client's (the part that sends web requests) first-byte
#     timeout (giving up after waiting too long for the first reply) —
#     aiohttp catches the silent connection drop and raises
#     `ServerDisconnectedError`, which LiteLLM re-wraps as an
#     `InternalServerError` with message "Server disconnected". The
#     Meta-2032 (a run simulating Meta, set in 2032) OpenAI judge (a model
#     that scores a finished run) replay (re-running a stage from a saved run)
#     hit exactly this case (3-minute
#     timeout on a 162K-char prompt to GPT-5.5-pro).
#
# `TimeoutError` is the critical addition over the original Phase-4
# helper. The Meta-2032 cell post-mortem caught the framework in a
# state where a single Vertex AI (Google's paid cloud service offering models)
# request hung indefinitely without
# raising — the python client just sat waiting. Adding a per-call
# timeout at the call sites (`asyncio.wait_for(..., timeout=N)`)
# converts that silent hang into an `asyncio.TimeoutError`, which
# this classifier treats as retryable.
_TRANSIENT_RE = re.compile(
    r"("
    r"\b429\b|\bRESOURCE_EXHAUSTED\b|\bRateLimitError\b|\brate.?limit\b|"
    r"\b5\d\d\b|\bUNAVAILABLE\b|\bDeadlineExceeded\b|\bServerError\b|"
    r"InternalServerError|"
    r"\bToo Many Requests\b|\btemporarily unavailable\b|"
    r"\boverloaded\b|\bcapacity\b|"
    r"\bTimeoutError\b|\btimeout\b|\btimed out\b|"
    r"ServerDisconnected|Server disconnected|"
    r"ReadError|ConnectionError|TransportError|"
    r"connection (?:reset|refused|aborted)"
    r")",
    re.IGNORECASE,
)

# Patterns to extract a provider-suggested retry delay from the
# exception text. Provider conventions vary: Gemini emits
# `'retryDelay': '46s'`, OpenAI / Anthropic put it in `retry-after`
# headers (sometimes leaked into the error message string).
_RETRY_HINT_RES = [
    re.compile(r"['\"]?retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s?['\"]?"),
    re.compile(r"['\"]?retry[-_ ]after['\"]?\s*[:=]\s*['\"]?([\d.]+)['\"]?"),
    re.compile(r"retry\s+in\s+([\d.]+)\s*s", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Type alias for the run_agent callable. Matches the RunnerFn in
# `orchestrator/concurrent_mode.py` so any caller already using that
# alias can pass its `run_agent` straight through.
# ---------------------------------------------------------------------------

RunAgentFn = Callable[..., Awaitable]


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

def is_transient_error(exc: BaseException) -> bool:
    """Return True if `exc` looks like a transient provider error.

    Includes `asyncio.TimeoutError` and any match against the
    transient-error patterns, in the exception's class name or its
    message. The class name matters because `google.auth`'s
    `TransportError` carries only the failed request in its message.
    """
    if isinstance(exc, asyncio.TimeoutError):
        return True
    return bool(_TRANSIENT_RE.search(f"{type(exc).__name__}: {exc}"))


def parse_retry_delay(exc: BaseException, *, attempt: int) -> float:
    """Pick a wait duration before retrying `exc` on `attempt`.

    Honour an explicit provider-suggested delay if one is in the
    exception text; otherwise use exponential backoff capped at
    `MAX_BACKOFF_SECONDS`.

    Args:
        exc: The exception that triggered retry.
        attempt: 0-indexed retry attempt counter (0 = first retry,
            1 = second retry, ...). Used for exponential backoff.

    Returns:
        Wait duration in seconds, in `[INITIAL_BACKOFF_SECONDS,
        MAX_BACKOFF_SECONDS]`.
    """
    text = str(exc)
    for pat in _RETRY_HINT_RES:
        m = pat.search(text)
        if m:
            try:
                hint = float(m.group(1))
                # Sanity cap so a malformed hint doesn't park us forever.
                return min(hint, MAX_BACKOFF_SECONDS)
            except (TypeError, ValueError):
                pass
    backoff = INITIAL_BACKOFF_SECONDS * (BACKOFF_FACTOR ** attempt)
    return min(backoff, MAX_BACKOFF_SECONDS)


async def safe_run(
    run_agent: RunAgentFn,
    agent: LlmAgent,
    prompt: str,
    *,
    max_retries: int = MAX_RETRIES,
):
    """Run a single LLM call with transient-error retry-with-backoff.

    The wrapper around `run_agent(agent=..., prompt=...)` that both
    Phase 2 (`artefact_collection`) and Phase 4 (`panel_debriefing`)
    use. Retries transient errors (429 / 5xx / rate-limit / asyncio
    timeout) up to `max_retries` times with provider-honoured backoff;
    surfaces `None` for non-transient errors or once retries are
    exhausted.

    Non-transient errors (auth, 400, 404, schema-validation failures)
    still return `None` immediately — retrying them burns budget for
    no chance of success.

    Args:
        run_agent: An awaitable matching the framework's RunnerFn
            signature (``async def(agent: LlmAgent, prompt: str) ->
            Any``).
        agent: The `LlmAgent` (the agent object in Google's Agent Development
            Kit) to invoke.
        prompt: The user-message prompt to pass to the agent.
        max_retries: Override the default retry count. The default
            (5) matches the deliberation phase's per-call retry.

    Returns:
        Whatever `run_agent` returns on success; `None` if the call
        failed non-transiently or all retries were exhausted.
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(max_retries + 1):
        try:
            return await run_agent(agent=agent, prompt=prompt)
        except BaseException as exc:  # noqa: BLE001
            # We catch BaseException (not Exception) specifically so
            # `asyncio.CancelledError` would propagate cleanly if the
            # caller cancels — but in practice `wait_for`'s timeout
            # raises `TimeoutError` (Exception subclass), which we
            # DO want to catch and retry.
            if isinstance(exc, asyncio.CancelledError):
                raise
            last_exc = exc
            if not is_transient_error(exc) or attempt >= max_retries:
                log.exception(
                    "Agent run failed (attempt %d/%d, transient=%s): %s",
                    attempt + 1, max_retries + 1, is_transient_error(exc), exc,
                )
                return None
            delay = parse_retry_delay(exc, attempt=attempt)
            log.warning(
                "Agent run hit transient error (attempt %d/%d); "
                "sleeping %.1fs before retry. Error: %s",
                attempt + 1, max_retries + 1, delay, exc,
            )
            await asyncio.sleep(delay)
    # Unreachable in practice — the loop above always returns or logs.
    if last_exc is not None:
        log.exception("Agent run exhausted retries: %s", last_exc)
    return None


# ---------------------------------------------------------------------------
# Capturing variant for judge-like callers that need the audit trail
# ---------------------------------------------------------------------------
#
# `safe_run` above swallows exceptions (errors raised by the code) and returns `None` on failure.
# That's fine for Phase 1 / Phase 2 / Phase 4 callers where the
# orchestrator only needs a yes/no signal. But the Phase-5 judge path
# wants the captured exception text to land in
# `05_judging/<provider>_error.txt` (the audit trail from PR-A, where PR means
# pull request, a proposed set of changes) so post-mortem
# doesn't require re-running the LLM call. This helper provides that:
# same retry-with-backoff logic, but returns
# `(result_or_None, error_text_or_None)` so the caller can record the
# captured `repr(exc) + traceback.format_exc()` (the error and Python's record
# of where it arose).
#
# Used by both `orchestrator.construct_judging.run_construct_judging`
# (the live-run judge path) and `analysis.replay_judges.replay_judges`
# (the offline replay path). The two call sites used to have
# divergent retry behaviour — the live path had a local retry loop
# while the replay path did a single bare call — which is exactly how
# the Meta-2032 OpenAI failure slipped through without retrying. This
# helper consolidates the two into one code path.

async def safe_run_with_capture(
    run_agent: RunAgentFn,
    agent: LlmAgent,
    prompt: str,
    *,
    provider: str,
    max_retries: int = MAX_RETRIES,
) -> Tuple[Optional[Any], Optional[str]]:
    """Run a single LLM call with retry-with-backoff, returning either
    the raw response OR a captured error string.

    Exactly one of the returned tuple's two elements is `None`. The
    caller is expected to either use the raw result (success path) or
    record the error string in its audit trail (failure path —
    typically `<provider>_error.txt` for the judge ensemble).

    Retry semantics match `safe_run`: transient errors trigger
    backoff up to `max_retries`; non-transient errors short-circuit
    immediately. The difference is the failure return: where
    `safe_run` returns `None` and logs at exception level, this
    helper returns `(None, error_text)` with the captured
    `repr(exc) + traceback.format_exc()` so the caller can persist
    it.

    Args:
        run_agent: An awaitable matching ``async def(agent, prompt)
            -> Any``. Same shape that `safe_run` uses.
        agent: The `LlmAgent` to invoke.
        prompt: The user-message prompt.
        provider: Provider key (e.g. 'gemini_pro', 'openai',
            'deepseek') — used for log tagging and for the error
            text prefix. Keyword-only.
        max_retries: Override the default retry count.

    Returns:
        ``(raw_response, None)`` on success — the caller coerces /
        validates the raw response as it sees fit.

        ``(None, error_text)`` on failure — final attempt's
        ``repr(exc) + traceback`` formatted into the audit-friendly
        string the judge persistence layer expects:

            ``<provider>: <repr(exc)>\n
            transient=<bool>, attempts=<N>/<max_retries+1>\n\n
            <traceback>``

        The exception object is NOT raised — the caller never sees
        it directly, by design (consistent error handling across all
        call sites).
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(max_retries + 1):
        try:
            raw = await run_agent(agent=agent, prompt=prompt)
            return raw, None
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001
            last_exc = exc
            transient = is_transient_error(exc)
            if not transient or attempt >= max_retries:
                tb = traceback.format_exc()
                error_text = (
                    f"{provider}: {exc!r}\n"
                    f"transient={transient}, "
                    f"attempts={attempt + 1}/{max_retries + 1}\n\n{tb}"
                )
                log.warning(
                    "safe_run_with_capture failed provider=%s exc=%r "
                    "transient=%s attempts=%d/%d",
                    provider, exc, transient,
                    attempt + 1, max_retries + 1,
                )
                return None, error_text
            delay = parse_retry_delay(exc, attempt=attempt)
            log.warning(
                "safe_run_with_capture transient provider=%s exc=%r "
                "attempt=%d/%d sleep=%.1fs",
                provider, exc, attempt + 1, max_retries + 1, delay,
            )
            await asyncio.sleep(delay)
    # Unreachable in practice — the loop above always returns.
    assert last_exc is not None
    return None, f"{provider}: unreachable retry-loop exit ({last_exc!r})"
