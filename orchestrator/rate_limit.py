"""Provider-scoped token-bucket rate limiting for LLM calls.

A provider (the company that supplies a model) caps how much a customer may send
per minute, which is its rate limit. This file holds calls to the large language
models (LLMs) back so the agents (models given a name, a role and instructions) stay
under that cap. A token-bucket keeps a stock
of allowed tokens (small pieces of text that providers charge by) that refills over
time; a call normally goes out only when the stock covers it.

Why this exists
---------------
The existing per-call retry (trying a failed call again) loop
in `agent.py:_run_one_agent` (and the
mirror in `run_research_session.py:_run`) handles a single 429 (the error code for a
rate-limit failure) cleanly:
it parses the suggested `retryDelay` from the provider's error message,
sleeps, and retries. That works when one role agent hits the rate
limit in isolation.

What it does NOT handle is the **synchronised retry storm**. In
CONCURRENT deliberation (team discussion) mode (the default, in which all roles act at once) six
TMT (top management team) role agents, the simulated executives, fire
LLM calls concurrently. Under a tier-limited provider — Anthropic tier
1 (a tier is an account level with its own cap; here 30k, meaning 30,000, TPM, tokens
per minute), Groq's (a company that hosts other firms' models) free tier (12k TPM) — those six requests
collectively blow the TPM bucket. All six get a 429. All six parse a
similar `retryDelay`. All six sleep ~the same amount. All six retry
at the same instant. The storm repeats and ~30% of wall-clock (real elapsed time) is
burned waiting for buckets that keep getting blown the moment they
refill.

A global token-bucket throttle prevents the storm at the source.
Before each LLM call, the caller `await`s capacity from a provider-
scoped bucket. The bucket has two reservoirs — tokens-per-minute and
requests-per-minute (RPM) — both refilling at the provider's documented
tier rate. When the bucket is empty, callers queue serially instead
of pile-driving the provider's 429 path.

This module is a complement to the per-call retry loop, not a
replacement. The retry loop still handles transient 5xx (error codes for a temporary server failure) and the
occasional rate-limit overshoot (estimation isn't exact). The bucket
just keeps the steady-state load under the provider's documented
ceiling.

What does NOT need the bucket
-----------------------------
* Sequential single-cell (cell: one combination of firm, industry context and
  product type) runs against Gemini Pro on Vertex AI (Google's language model on its
  paid cloud service; ~4M TPM)
  — the bucket is a no-op (it does nothing) there.
* Local Ollama (software for running models on your own computer; no rate limit at
  all).
* Phase 5 judge (a model that scores a finished run against a rubric) runs across a
  sweep (a planned set of runs) — each cell only fires one Claude (Anthropic's
  language model) judge call, and cells run sequentially in `scripts/run_frontier_
  sweep.sh`, so consecutive Claude judge calls are minutes apart.

What DOES benefit
-----------------
* CONCURRENT mode against Anthropic tier 1 (Claude as a TMT driver).
* CONCURRENT mode against Groq's free tier (Llama 4 Maverick, Meta's language model, as
  TMT).
* Any future tier-limited provider added under tighter constraints.

Configuration
-------------
Defaults are conservative — sized for each provider's entry / free
tier. Operators on higher tiers override via env vars (environment variables: named
settings held outside the code):

  TMT_RATELIMIT_<PROVIDER>_TPM    tokens per minute  (int)
  TMT_RATELIMIT_<PROVIDER>_RPM    requests per minute (int)

Setting either to `off`, `none`, or `0` disables the throttle for
that provider — useful when you've manually tier-upped and want to
let the per-call retry loop be the only safety net.

Limitations
-----------
* Token estimation is a 4-chars-per-token heuristic + a configurable
  output budget. It's within ~20% across all the providers in
  `_DEFAULTS`, which is plenty for budgeting against TPM ceilings.
  Precise tokenizers, which count tokens exactly (tiktoken /
  google-cloud-aiplatform), would add dependencies (extra packages of ready-made
  code) for marginal benefit.
* Process-local (each running copy of the program keeps its own count). Multiple
  concurrent Python processes hitting the
  same provider share no state. `scripts/run_frontier_sweep.sh` runs
  one cell at a time, so this matters only when the operator parallel-
  launches multiple sweep processes — in which case the per-process
  buckets each need a TPM divided by the parallelism factor.
* A single request larger than the per-minute bucket cap can never
  be satisfied as-is (e.g. a 38k-token judge prompt, the text sent to a model, against Claude
  tier 1's 30k-TPM cap). The bucket logs a warning and lets the call
  go through with a partial reservation; the provider will reject it
  with a hard 429 and the per-call retry loop will see the error and
  surface it. This is the "tier up" signal — there's no software fix
  for it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider tier defaults
# ---------------------------------------------------------------------------
# Conservative — sized for each provider's documented entry tier as of
# the May-2026 frontier-sweep (a set of runs on the newest, most capable models)
# planning. Operators on higher tiers
# override via env vars.
#
# `None` = no throttle for this provider (e.g. local Ollama).
#
# Note on Gemini Pro: the default is sized for Vertex preview-tier
# (an early release the provider may still change; gemini-3.x-pro-preview etc.),
# which is much tighter than the GA (generally available: finished and fully
# supported) 2.5 family. The framework's `_DEFAULTS["gemini_pro"]` is the
# preview model and live runs against it surface 429s well before
# the GA-tier ceilings. Operators on the GA 2.5 family can override
# safely via:
#   TMT_RATELIMIT_GEMINI_PRO_TPM=4000000
#   TMT_RATELIMIT_GEMINI_PRO_RPM=1000
# A future fix could split the bucket key into `gemini_pro_preview`
# vs `gemini_pro_ga`; left for when a study runs both tiers in the
# same process. The conservative default is the right trade-off today,
# because waiting in the queue costs less than hitting the provider's limit.
PROVIDER_RATE_LIMITS: dict[str, Optional[dict[str, int]]] = {
    "claude":       {"tpm":    30_000, "rpm":   50},   # Anthropic tier 1
    "openai":       {"tpm":   500_000, "rpm":  500},   # GPT tier 2
    "gemini_pro":   {"tpm":   100_000, "rpm":   60},   # Vertex preview-tier
    "gemini_flash": {"tpm":   400_000, "rpm":  200},   # Vertex flash tier
    "deepseek":     {"tpm": 2_000_000, "rpm": 1000},
    "groq":         {"tpm":    12_000, "rpm":   30},   # Groq free tier
    "ollama":       None,                              # local — no throttle
}


# ---------------------------------------------------------------------------
# Token-bucket primitive
# ---------------------------------------------------------------------------

# Minimum wait granularity. Even if the computed wait is sub-50ms we
# sleep this long before re-checking — otherwise a contended bucket
# spins the event loop (the part of Python that schedules tasks) in tight ~0ms re-checks.
_MIN_TICK_SECONDS = 0.05

# Default output-token budget added to every estimate. The frontier
# artefacts are ~2k-3k tokens; the judges' assessments are ~1k-2k;
# 2000 is a reasonable single default. Caller can override per-call.
_DEFAULT_OUTPUT_BUDGET = 2000

# Roughly: GPT/Claude/DeepSeek tokenizers average ~4 chars per token
# on English prose. Within ~20% — fine for budgeting.
_CHARS_PER_TOKEN = 4.0


class TokenBucket:
    """Async-safe dual-reservoir token bucket.

    One reservoir for tokens-per-minute, one for requests-per-minute.
    Both refill at their respective rates; `acquire(tokens)` blocks
    until both reservoirs can satisfy the request.

    Test-friendly: the `now_fn` parameter lets unit tests (small automatic
    checks) inject a
    fake clock that advances on demand.
    """

    def __init__(
        self,
        *,
        tpm: int,
        rpm: int,
        now_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if tpm <= 0 or rpm <= 0:
            raise ValueError(
                f"TokenBucket requires positive tpm/rpm; got tpm={tpm} rpm={rpm}"
            )
        self.tpm = tpm
        self.rpm = rpm
        self._now = now_fn
        self.token_balance: float = float(tpm)
        self.request_balance: float = float(rpm)
        self.last_refill: float = self._now()
        # Lazy lock (a lock lets one task at a time change the count) — created on
        # first acquire so module-load order
        # doesn't require a running event loop.
        self._lock: Optional[asyncio.Lock] = None

    def _ensure_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _refill(self) -> None:
        now = self._now()
        elapsed = max(0.0, now - self.last_refill)
        self.last_refill = now
        self.token_balance = min(
            float(self.tpm),
            self.token_balance + elapsed * self.tpm / 60.0,
        )
        self.request_balance = min(
            float(self.rpm),
            self.request_balance + elapsed * self.rpm / 60.0,
        )

    def _compute_wait(self, requested_tokens: float) -> float:
        """How long until both reservoirs satisfy this request."""
        token_deficit = max(0.0, requested_tokens - self.token_balance)
        request_deficit = max(0.0, 1.0 - self.request_balance)
        token_wait = (token_deficit * 60.0 / self.tpm) if self.tpm > 0 else 0.0
        request_wait = (request_deficit * 60.0 / self.rpm) if self.rpm > 0 else 0.0
        return max(token_wait, request_wait, _MIN_TICK_SECONDS)

    async def acquire(self, tokens: int) -> float:
        """Block until capacity is available; return total seconds waited.

        Args:
            tokens: How many tokens this call needs. Caller's estimate
                of input + reserved output budget.

        Returns:
            Total seconds spent waiting (0.0 if capacity was immediately
            available).

        Edge case — request larger than per-minute capacity: A single
        call requesting more than `tpm` tokens (e.g. a 38k judge prompt
        against 30k tpm) cannot be satisfied as-is. The bucket logs a
        warning, waits until balance is at maximum capacity, and lets
        the request go through. The provider will reject with a hard
        429 and the caller's retry loop will surface it.
        """
        if tokens <= 0:
            tokens = 1  # don't let a zero/negative slip past

        oversized = tokens > self.tpm
        if oversized:
            log.warning(
                "rate_limit oversized request: requested=%d > tpm_cap=%d. "
                "Will wait for full bucket, but provider may still reject. "
                "Consider tier-upping or shortening the prompt.",
                tokens, self.tpm,
            )

        # Cap effective request size at capacity so we don't deadlock
        # waiting for capacity that the bucket can never hold.
        requested = min(float(tokens), float(self.tpm))
        total_wait = 0.0

        while True:
            lock = self._ensure_lock()
            async with lock:
                self._refill()
                if (self.token_balance >= requested
                        and self.request_balance >= 1.0):
                    self.token_balance -= requested
                    self.request_balance -= 1.0
                    if total_wait > 0:
                        log.info(
                            "rate_limit acquired after %.2fs wait "
                            "(tokens=%d, balance_after=%.0f tpm / %.2f rpm)",
                            total_wait, tokens,
                            self.token_balance, self.request_balance,
                        )
                    return total_wait
                wait = self._compute_wait(requested)
            # Outside the lock — sleep without holding it so other
            # acquirers can re-evaluate when their turn arrives.
            log.info(
                "rate_limit waiting %.2fs (need=%d tok, have %.0f tpm / "
                "%.2f rpm)",
                wait, tokens, self.token_balance, self.request_balance,
            )
            total_wait += wait
            await asyncio.sleep(wait)


# ---------------------------------------------------------------------------
# Module-global registry
# ---------------------------------------------------------------------------
# One bucket per provider key, built lazily on first `get_bucket(provider)`.
# `reset_buckets()` clears the registry — used by tests and by anyone
# who wants to pick up env-var changes mid-process.

_BUCKETS: dict[str, Optional[TokenBucket]] = {}


def _resolve_limits(provider: str) -> Optional[dict[str, int]]:
    """Resolve effective TPM/RPM for `provider` honouring env-var overrides.

    Returns None if the throttle is disabled for this provider (either
    no default config, or the operator explicitly disabled it via
    `TMT_RATELIMIT_<PROVIDER>_TPM=off`).
    """
    defaults = PROVIDER_RATE_LIMITS.get(provider)
    tpm_env = os.environ.get(f"TMT_RATELIMIT_{provider.upper()}_TPM")
    rpm_env = os.environ.get(f"TMT_RATELIMIT_{provider.upper()}_RPM")

    # Explicit disable: any of the env vars set to off / none / 0.
    _DISABLE_TOKENS = {"off", "none", "0", "false", "no"}
    if tpm_env and tpm_env.strip().lower() in _DISABLE_TOKENS:
        return None
    if rpm_env and rpm_env.strip().lower() in _DISABLE_TOKENS:
        return None

    if defaults is None and not (tpm_env or rpm_env):
        return None

    try:
        tpm = int(tpm_env) if tpm_env else (defaults["tpm"] if defaults else 0)
        rpm = int(rpm_env) if rpm_env else (defaults["rpm"] if defaults else 0)
    except (TypeError, ValueError):
        log.warning(
            "rate_limit ignoring non-integer env override for %s "
            "(tpm=%r rpm=%r)", provider, tpm_env, rpm_env,
        )
        return None

    if tpm <= 0 or rpm <= 0:
        return None
    return {"tpm": tpm, "rpm": rpm}


def get_bucket(provider: str) -> Optional[TokenBucket]:
    """Return the bucket for `provider`, building it lazily.

    Returns `None` if the throttle is disabled for this provider.
    """
    if provider in _BUCKETS:
        return _BUCKETS[provider]
    limits = _resolve_limits(provider)
    if limits is None:
        _BUCKETS[provider] = None
        return None
    bucket = TokenBucket(tpm=limits["tpm"], rpm=limits["rpm"])
    _BUCKETS[provider] = bucket
    log.info(
        "rate_limit bucket initialised provider=%s tpm=%d rpm=%d",
        provider, limits["tpm"], limits["rpm"],
    )
    return bucket


def reset_buckets() -> None:
    """Clear the bucket registry. Test helper + env-var reload entry point."""
    _BUCKETS.clear()


# ---------------------------------------------------------------------------
# Token estimation + provider detection
# ---------------------------------------------------------------------------

def estimate_tokens(text: str, *, output_budget: int = _DEFAULT_OUTPUT_BUDGET) -> int:
    """Estimate the token cost of one LLM call.

    Char-count / 4 is the canonical OpenAI heuristic and within ~20%
    across GPT-4/5, Claude 3.x/4.x, DeepSeek V3/V4, Llama 3.x/4, and
    Gemini 1.5/2.x/3.x for English prose. Within budgeting tolerance —
    we don't need exact counts.

    Args:
        text: Prompt text. Caller should pass everything that will be
            sent (system + user prompt, meaning the standing instructions and the
            request, + any RAG snippets; RAG, retrieval-augmented generation,
            adds passages from documents to a prompt).
        output_budget: How many output tokens to reserve in the
            estimate. Defaults to 2000 (large enough for an artefact;
            judges can request more).
    """
    return int(len(text) / _CHARS_PER_TOKEN) + max(0, output_budget)


# Mapping from a LiteLLM (software that reaches many providers' models in the
# same way) model-ID prefix to a provider key in
# `PROVIDER_RATE_LIMITS`. Anything not in this map is unknown — caller
# skips throttling rather than guessing.
_LITELLM_PREFIX_TO_PROVIDER: dict[str, str] = {
    "anthropic":   "claude",
    "openai":      "openai",
    "deepseek":    "deepseek",
    "groq":        "groq",
    "ollama_chat": "ollama",
    "ollama":      "ollama",
}


def provider_for_model(model_spec: Any) -> Optional[str]:
    """Classify an ADK (Agent Development Kit: Google's software for building agents)
    model spec (string or LiteLlm wrapper) to a provider.

    Returns `None` when the spec can't be mapped — the caller should
    skip throttling rather than apply a wrong bucket.
    """
    if model_spec is None:
        return None
    if isinstance(model_spec, str):
        # Native Gemini path. Both `gemini-2.5-pro` and `gemini-3.1-pro`
        # match. Flash variants get their own bucket.
        if model_spec.startswith("gemini"):
            return "gemini_flash" if "flash" in model_spec else "gemini_pro"
        return None
    model_id = getattr(model_spec, "model", None) or ""
    prefix = model_id.split("/", 1)[0] if "/" in model_id else model_id
    return _LITELLM_PREFIX_TO_PROVIDER.get(prefix)


# ---------------------------------------------------------------------------
# Public acquire helper
# ---------------------------------------------------------------------------

async def acquire_for_call(
    model_spec: Any,
    prompt: str,
    *,
    output_budget: int = _DEFAULT_OUTPUT_BUDGET,
) -> float:
    """Acquire bucket capacity for one LLM call against `model_spec`.

    No-op (returns 0.0) if the model spec can't be mapped to a provider
    or the provider has no throttle config. Otherwise blocks until the
    provider's bucket can satisfy the estimated token cost; returns the
    seconds waited.

    This is the single seam (connection point) call sites use. Both `agent.py:_run_one_
    agent` and `run_research_session.py:_run` call this once per
    attempt, inside the retry loop, so each retry burns fresh capacity
    (matching what the provider will actually count).
    """
    provider = provider_for_model(model_spec)
    if provider is None:
        return 0.0
    bucket = get_bucket(provider)
    if bucket is None:
        return 0.0
    tokens = estimate_tokens(prompt, output_budget=output_budget)
    return await bucket.acquire(tokens)
