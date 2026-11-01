"""Tests for the shared `orchestrator.llm_retry` helper.

Lifted from the inline Phase-4 retry helper at the time of the
Meta-2032 post-mortem. `llm_retry` is now the canonical home of the
transient-error classifier + retry-with-backoff loop; both Phase 2
(`artefact_collection`) and Phase 4 (`panel_debriefing`) use it.

Covers:
  * `is_transient_error` classifies 429, 5xx, RateLimitError patterns,
    asyncio.TimeoutError, and "timeout"/"timed out" string forms as
    transient. Auth, 400, 404, validation errors are non-transient.
  * `parse_retry_delay` honours provider-suggested retry hints
    (Gemini retryDelay, OpenAI/Anthropic retry-after) and falls
    back to exponential backoff capped at MAX_BACKOFF_SECONDS.
  * `safe_run` retries transient errors, surfaces None on non-
    transient errors, surfaces None after retries exhausted, and
    propagates asyncio.CancelledError uncaught.
"""

from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass

import pytest

PKG = "open-innovation-strategy"


def _llm_retry():
    return importlib.import_module(f"{PKG}.orchestrator.llm_retry")


@dataclass
class _StubAgent:
    name: str
    instruction: str = ""
    model: str = "stub-model"


# ---------------------------------------------------------------------------
# is_transient_error
# ---------------------------------------------------------------------------

class TestIsTransientError:
    def test_429_is_transient(self):
        m = _llm_retry()
        assert m.is_transient_error(RuntimeError("429 RESOURCE_EXHAUSTED"))

    def test_rate_limit_error_message_is_transient(self):
        m = _llm_retry()
        assert m.is_transient_error(RuntimeError("RateLimitError: ..."))

    def test_5xx_is_transient(self):
        m = _llm_retry()
        for code in (500, 502, 503, 504, 529):
            assert m.is_transient_error(RuntimeError(f"{code} server error")), code

    def test_unavailable_is_transient(self):
        m = _llm_retry()
        assert m.is_transient_error(RuntimeError("503 UNAVAILABLE"))

    def test_overloaded_capacity_messages_are_transient(self):
        m = _llm_retry()
        assert m.is_transient_error(RuntimeError("server overloaded"))
        assert m.is_transient_error(RuntimeError("capacity exceeded"))

    def test_asyncio_timeout_is_transient(self):
        """The whole point of the timeout addition: `asyncio.TimeoutError`
        raised by `wait_for` must be classified as transient so the retry
        loop catches it. This is the load-bearing test for the
        per-call-timeout fix."""
        m = _llm_retry()
        assert m.is_transient_error(asyncio.TimeoutError())

    def test_timeout_string_form_is_transient(self):
        """Some clients raise an Exception with 'timeout' in the message
        rather than asyncio.TimeoutError. Cover both."""
        m = _llm_retry()
        assert m.is_transient_error(RuntimeError("Request timed out"))
        assert m.is_transient_error(RuntimeError("TimeoutError: ..."))

    def test_auth_400_404_are_NOT_transient(self):
        m = _llm_retry()
        assert not m.is_transient_error(RuntimeError("400 invalid argument"))
        assert not m.is_transient_error(RuntimeError("401 AuthenticationError"))
        assert not m.is_transient_error(RuntimeError("403 Forbidden"))
        assert not m.is_transient_error(RuntimeError("404 NOT_FOUND"))

    def test_validation_errors_are_NOT_transient(self):
        m = _llm_retry()
        assert not m.is_transient_error(ValueError("schema validation failed"))


# ---------------------------------------------------------------------------
# parse_retry_delay
# ---------------------------------------------------------------------------

class TestParseRetryDelay:
    def test_gemini_retry_delay_hint(self):
        m = _llm_retry()
        exc = RuntimeError("429 RESOURCE_EXHAUSTED 'retryDelay': '12s'")
        assert m.parse_retry_delay(exc, attempt=0) == 12.0

    def test_openai_retry_after_hint(self):
        m = _llm_retry()
        exc = RuntimeError("RateLimitError: retry-after: 8")
        assert m.parse_retry_delay(exc, attempt=0) == 8.0

    def test_anthropic_retry_in_hint(self):
        m = _llm_retry()
        exc = RuntimeError("Please retry in 5.0s.")
        assert m.parse_retry_delay(exc, attempt=0) == 5.0

    def test_exponential_backoff_when_no_hint(self):
        m = _llm_retry()
        exc = RuntimeError("429 (no hint)")
        assert m.parse_retry_delay(exc, attempt=0) == 2.0
        assert m.parse_retry_delay(exc, attempt=1) == 4.0
        assert m.parse_retry_delay(exc, attempt=2) == 8.0
        assert m.parse_retry_delay(exc, attempt=3) == 16.0

    def test_backoff_capped_at_max(self):
        m = _llm_retry()
        exc = RuntimeError("429")
        # MAX_BACKOFF_SECONDS = 60
        assert m.parse_retry_delay(exc, attempt=10) == 60.0
        assert m.parse_retry_delay(exc, attempt=100) == 60.0

    def test_hint_also_capped_at_max(self):
        """A malformed hint of 99999s shouldn't park us for hours."""
        m = _llm_retry()
        exc = RuntimeError("'retryDelay': '99999s'")
        assert m.parse_retry_delay(exc, attempt=0) == 60.0


# ---------------------------------------------------------------------------
# safe_run
# ---------------------------------------------------------------------------

class TestSafeRun:
    def test_first_call_succeeds_no_retry(self):
        m = _llm_retry()
        agent = _StubAgent(name="X")
        calls = {"n": 0}

        async def happy_runner(*, agent, prompt):
            calls["n"] += 1
            return "OK"

        result = asyncio.run(m.safe_run(happy_runner, agent, "p"))
        assert result == "OK"
        assert calls["n"] == 1

    def test_retries_transient_then_succeeds(self):
        m = _llm_retry()
        agent = _StubAgent(name="X")
        calls = {"n": 0}

        async def flaky_runner(*, agent, prompt):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("429 RESOURCE_EXHAUSTED 'retryDelay': '0s'")
            return "OK"

        result = asyncio.run(m.safe_run(flaky_runner, agent, "p"))
        assert result == "OK"
        assert calls["n"] == 3

    def test_retries_on_asyncio_timeout(self):
        """The wait_for-timeout case: a hung HTTP call surfaces as
        asyncio.TimeoutError, which safe_run must classify as
        transient and retry."""
        m = _llm_retry()
        agent = _StubAgent(name="X")
        calls = {"n": 0}

        async def timing_out_runner(*, agent, prompt):
            calls["n"] += 1
            if calls["n"] == 1:
                raise asyncio.TimeoutError()
            return "OK"

        result = asyncio.run(m.safe_run(timing_out_runner, agent, "p"))
        assert result == "OK"
        assert calls["n"] == 2

    def test_returns_none_on_non_transient(self):
        m = _llm_retry()
        agent = _StubAgent(name="X")
        calls = {"n": 0}

        async def auth_failing_runner(*, agent, prompt):
            calls["n"] += 1
            raise RuntimeError("401 AuthenticationError invalid key")

        result = asyncio.run(m.safe_run(auth_failing_runner, agent, "p"))
        assert result is None
        assert calls["n"] == 1  # no retries on non-transient

    def test_returns_none_after_retries_exhausted(self):
        m = _llm_retry()
        agent = _StubAgent(name="X")
        calls = {"n": 0}

        async def always_429(*, agent, prompt):
            calls["n"] += 1
            raise RuntimeError("429 'retryDelay': '0s'")

        result = asyncio.run(
            m.safe_run(always_429, agent, "p", max_retries=2)
        )
        assert result is None
        assert calls["n"] == 3  # initial + 2 retries

    def test_cancelled_error_propagates(self):
        """asyncio.CancelledError must NOT be caught — it's not a
        provider error, it's a caller-initiated shutdown. Catching it
        would break orderly cancellation."""
        m = _llm_retry()
        agent = _StubAgent(name="X")

        async def cancelling_runner(*, agent, prompt):
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(m.safe_run(cancelling_runner, agent, "p"))


# ---------------------------------------------------------------------------
# Back-compat: panel_debriefing still re-exports the old names
# ---------------------------------------------------------------------------

class TestPanelDebriefingBackCompat:
    """`orchestrator/panel_debriefing.py` was previously the home of
    `_safe_run`, `_is_transient_error`, `_parse_phase4_retry_delay`,
    `_PHASE4_MAX_RETRIES`. After the lift to `llm_retry`, those names
    are re-exported so existing tests + imports still resolve."""

    def test_panel_debriefing_safe_run_still_resolvable(self):
        pd = importlib.import_module(f"{PKG}.orchestrator.panel_debriefing")
        assert callable(pd._safe_run)

    def test_panel_debriefing_is_transient_error_still_resolvable(self):
        pd = importlib.import_module(f"{PKG}.orchestrator.panel_debriefing")
        assert callable(pd._is_transient_error)

    def test_panel_debriefing_max_retries_still_resolvable(self):
        pd = importlib.import_module(f"{PKG}.orchestrator.panel_debriefing")
        assert isinstance(pd._PHASE4_MAX_RETRIES, int)
        assert pd._PHASE4_MAX_RETRIES >= 1

    def test_old_parse_phase4_retry_delay_signature(self):
        """The pre-lift tests called `_parse_phase4_retry_delay(exc,
        attempt=N)` — positional `exc`, keyword `attempt`. The
        compatibility wrapper preserves that signature."""
        pd = importlib.import_module(f"{PKG}.orchestrator.panel_debriefing")
        exc = RuntimeError("429 RESOURCE_EXHAUSTED 'retryDelay': '7s'")
        assert pd._parse_phase4_retry_delay(exc, attempt=0) == 7.0
