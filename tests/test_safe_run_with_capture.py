"""Tests for `orchestrator.llm_retry.safe_run_with_capture` — the
shared retry-with-backoff helper used by both
`orchestrator.construct_judging.run_construct_judging::_one_judge` AND
`analysis.replay_judges.replay_judges`.

Both paths use this one helper, so a replay retries the same errors as a
live run.

Contract: returns `(raw_or_None, error_text_or_None)`. Exactly one
is None. The error_text follows the audit-friendly format the judge
persistence layer expects (so `<provider>_error.txt` files have
consistent shape regardless of whether the failure happened in a
live run or a replay).
"""

from __future__ import annotations

import asyncio
import importlib

import pytest

PKG = "open-innovation-strategy"


def _llm_retry():
    return importlib.import_module(f"{PKG}.orchestrator.llm_retry")


# ===========================================================================
# Success path
# ===========================================================================

class TestSuccessPath:
    def test_success_returns_raw_no_error(self):
        ie = _llm_retry()

        async def runner(*, agent, prompt):
            return {"raw": "ok"}

        raw, err = asyncio.run(ie.safe_run_with_capture(
            runner, agent=object(), prompt="x", provider="test",
        ))
        assert raw == {"raw": "ok"}
        assert err is None

    def test_string_return_value_supported(self):
        """LiteLLM `json_object` mode providers return strings (the
        `_coerce_assessment` path parses them downstream); helper
        must preserve the raw shape."""
        ie = _llm_retry()

        async def runner(*, agent, prompt):
            return '{"judge_id":"test"}'

        raw, err = asyncio.run(ie.safe_run_with_capture(
            runner, agent=object(), prompt="x", provider="test",
        ))
        assert raw == '{"judge_id":"test"}'
        assert err is None


# ===========================================================================
# Retry-on-transient path
# ===========================================================================

class TestRetryOnTransient:
    def test_first_attempt_transient_then_success(self, monkeypatch):
        """First call raises a transient error; second succeeds. The
        helper must return the success without surfacing the
        transient blip as an error."""
        ie = _llm_retry()

        # Zero out backoff so the test runs instantly.
        async def _instant_sleep(seconds: float) -> None:
            return None
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

        attempts = {"n": 0}
        async def runner(*, agent, prompt):
            attempts["n"] += 1
            if attempts["n"] == 1:
                # Mirror the Meta-2032 OpenAI failure mode.
                raise Exception(
                    "litellm.InternalServerError: InternalServerError: "
                    "OpenAIException - Server disconnected"
                )
            return {"raw": "second-attempt-ok"}

        raw, err = asyncio.run(ie.safe_run_with_capture(
            runner, agent=object(), prompt="x", provider="openai",
        ))
        assert attempts["n"] == 2
        assert raw == {"raw": "second-attempt-ok"}
        assert err is None

    def test_repeated_transient_exhausts_returns_error_text(
        self, monkeypatch,
    ):
        """Every attempt raises the same transient error; helper
        returns `(None, error_text)` after MAX_RETRIES + 1 attempts.
        The error text includes attempt count + transient=True + the
        captured exception repr + traceback."""
        ie = _llm_retry()

        async def _instant_sleep(seconds: float) -> None:
            return None
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

        attempts = {"n": 0}
        async def runner(*, agent, prompt):
            attempts["n"] += 1
            raise Exception(
                "litellm.InternalServerError: InternalServerError: "
                "OpenAIException - Server disconnected"
            )

        raw, err = asyncio.run(ie.safe_run_with_capture(
            runner, agent=object(), prompt="x", provider="openai",
        ))
        assert raw is None
        assert err is not None
        # MAX_RETRIES + 1 attempts total (initial + 5 retries).
        assert attempts["n"] == ie.MAX_RETRIES + 1
        # Error text format contract.
        assert "openai:" in err
        assert "transient=True" in err
        assert f"attempts={ie.MAX_RETRIES + 1}/{ie.MAX_RETRIES + 1}" in err
        assert "Server disconnected" in err
        assert "Traceback" in err

    def test_max_retries_override(self, monkeypatch):
        """Caller can dial down the retry count for a less-permissive
        call site (e.g. a probe that should fail fast)."""
        ie = _llm_retry()

        async def _instant_sleep(seconds: float) -> None:
            return None
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

        attempts = {"n": 0}
        async def runner(*, agent, prompt):
            attempts["n"] += 1
            raise Exception("HTTP 429 Too Many Requests")

        raw, err = asyncio.run(ie.safe_run_with_capture(
            runner, agent=object(), prompt="x", provider="test",
            max_retries=2,
        ))
        assert attempts["n"] == 3  # initial + 2 retries
        assert err is not None
        assert "attempts=3/3" in err


# ===========================================================================
# Non-transient path
# ===========================================================================

class TestNonTransientShortCircuits:
    def test_400_bad_request_no_retry(self, monkeypatch):
        """Non-transient errors burn budget for no chance of success.
        Single attempt; error_text records transient=False."""
        ie = _llm_retry()

        async def _instant_sleep(seconds: float) -> None:
            return None
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

        attempts = {"n": 0}
        async def runner(*, agent, prompt):
            attempts["n"] += 1
            raise Exception("openai.BadRequestError: 400 invalid request")

        raw, err = asyncio.run(ie.safe_run_with_capture(
            runner, agent=object(), prompt="x", provider="openai",
        ))
        assert attempts["n"] == 1
        assert raw is None
        assert "transient=False" in err
        assert "attempts=1/" in err

    def test_auth_error_no_retry(self, monkeypatch):
        ie = _llm_retry()
        async def _instant_sleep(seconds: float) -> None:
            return None
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

        attempts = {"n": 0}
        async def runner(*, agent, prompt):
            attempts["n"] += 1
            raise Exception("openai.AuthenticationError: invalid api key")

        raw, err = asyncio.run(ie.safe_run_with_capture(
            runner, agent=object(), prompt="x", provider="openai",
        ))
        assert attempts["n"] == 1
        assert "transient=False" in err


# ===========================================================================
# Behaviour contract — exception is captured, NOT re-raised
# ===========================================================================

class TestExceptionNotRaised:
    """`safe_run_with_capture` never re-raises an exception from
    `run_agent` (CancelledError is the lone exception — see below).
    Callers ALWAYS see `(raw, error_text)`. This invariant is what
    makes the helper usable by both call sites without per-call
    try/except blocks."""

    def test_arbitrary_exception_captured_not_raised(self, monkeypatch):
        ie = _llm_retry()
        async def _instant_sleep(seconds: float) -> None:
            return None
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

        class WeirdError(Exception):
            pass

        async def runner(*, agent, prompt):
            raise WeirdError("something unusual")

        # No try/except needed at the call site:
        raw, err = asyncio.run(ie.safe_run_with_capture(
            runner, agent=object(), prompt="x", provider="test",
        ))
        assert raw is None
        assert "WeirdError" in err

    def test_cancelled_error_propagates(self):
        """`asyncio.CancelledError` must propagate cleanly so the
        caller's cancel signal isn't swallowed — the only exception
        to the never-raise contract."""
        ie = _llm_retry()

        async def runner(*, agent, prompt):
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(ie.safe_run_with_capture(
                runner, agent=object(), prompt="x", provider="test",
            ))


# ===========================================================================
# Error text format — contract for `<provider>_error.txt`
# ===========================================================================

class TestErrorTextFormat:
    """The error text is written verbatim into
    `05_judging/<provider>_error.txt`. Format must be stable so
    grep / parse-friendly tooling can rely on it."""

    def test_starts_with_provider_colon(self, monkeypatch):
        ie = _llm_retry()
        async def _instant_sleep(seconds: float) -> None:
            return None
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

        async def runner(*, agent, prompt):
            raise Exception("400 Bad Request")

        _, err = asyncio.run(ie.safe_run_with_capture(
            runner, agent=object(), prompt="x", provider="my_provider",
        ))
        assert err.startswith("my_provider:"), (
            f"error text should start with `<provider>:`, got: {err[:40]!r}"
        )

    def test_carries_repr_not_just_str(self, monkeypatch):
        """The Meta-2032 silent-failure root cause was that
        `str(exc) == ""` for some LiteLLM exceptions, so `%s, exc`
        rendered as `exc=`. The error text MUST use repr so the
        exception class name lands."""
        ie = _llm_retry()
        async def _instant_sleep(seconds: float) -> None:
            return None
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

        class EmptyMessageError(Exception):
            def __str__(self) -> str:
                return ""

        async def runner(*, agent, prompt):
            raise EmptyMessageError()

        _, err = asyncio.run(ie.safe_run_with_capture(
            runner, agent=object(), prompt="x", provider="openai",
        ))
        # repr(exc) must put the class name in the audit text
        # regardless of how empty str(exc) is.
        assert "EmptyMessageError" in err
