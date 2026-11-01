"""Tests for the judge-call resilience improvements that close the
Meta-2032 `ServerDisconnectedError` failure mode.

Background. On the Meta-2032 cell the OpenAI judge reproducibly hit
`litellm.InternalServerError: ... - Server disconnected` at exactly
3:01 minutes — the LiteLLM/HTTPX/aiohttp first-byte timeout firing
before GPT-5.5-pro's reasoning phase finished thinking on a 162K-char
prompt. The server wasn't actually disconnecting; aiohttp gave up
waiting. PR-A captured the error to `<provider>_error.txt` for the
first time; this commit fixes the root cause.

Three coordinated fixes:

1. **Transient-error classifier extension** — `orchestrator.llm_retry.
   _TRANSIENT_RE` now matches `Server disconnected` /
   `ServerDisconnected` / `ReadError` / `InternalServerError` /
   `ConnectionError`. Without this, the existing `safe_run` would
   refuse to retry the Meta-2032 case.

2. **Per-judge request timeout** — `providers.JUDGE_TIMEOUT_OVERRIDES`
   defaults OpenAI + DeepSeek to 600s (reasoning-model headroom). Env
   var `TMT_JUDGE_<PROVIDER>_TIMEOUT_S` overrides. The timeout kwarg
   threads through the LiteLlm wrapper into `litellm.acompletion`.

3. **`_one_judge` retry loop** — bare `run_agent` call in
   `orchestrator.construct_judging` replaced with a local retry loop
   that reuses `is_transient_error` + `parse_retry_delay` from
   `llm_retry`. NOT wrapped in `safe_run` because that helper swallows
   exceptions on exhaustion; we keep the captured `traceback.format_
   exc()` so PR-A's `<provider>_error.txt` audit trail stays
   diagnostic.
"""

from __future__ import annotations

import asyncio
import importlib

import pytest

PKG = "open-innovation-strategy"


def _llm_retry():
    return importlib.import_module(f"{PKG}.orchestrator.llm_retry")


def _providers():
    return importlib.import_module(f"{PKG}.providers")


def _judging():
    return importlib.import_module(f"{PKG}.orchestrator.construct_judging")


def _schemas():
    return importlib.import_module(f"{PKG}.roles.judge_schemas")


def _studies():
    return importlib.import_module(f"{PKG}.studies")


_RUBRIC_KEYS = (
    "component_disclosure",
    "process_openness",
    "boundary_permeability_inbound",
    "boundary_permeability_outbound",
    "ecosystem_orchestration",
    "value_capture_posture",
    "temporal_openness_maneuvering",
)


# ===========================================================================
# Fix 1 — transient-error classifier covers connection-level disconnects
# ===========================================================================

class TestTransientErrorClassifier:
    """Verify the classifier now recognises the actual Meta-2032 error
    patterns. Without these patterns, `safe_run` would refuse to retry
    a connection-level disconnect even though it's exactly the kind of
    transient failure retry-with-backoff is designed for."""

    def test_server_disconnected_classified_transient(self):
        ie = _llm_retry()
        # The exact string from the Meta-2032 openai_error.txt.
        msg = (
            "litellm.InternalServerError: InternalServerError: "
            "OpenAIException - Server disconnected"
        )
        assert ie.is_transient_error(Exception(msg)), (
            "Meta-2032 OpenAI failure must classify as transient now"
        )

    def test_aiohttp_server_disconnected_error_class_name_matches(self):
        ie = _llm_retry()
        msg = (
            "aiohttp.client_exceptions.ServerDisconnectedError: "
            "Server disconnected"
        )
        assert ie.is_transient_error(Exception(msg))

    def test_httpx_read_error_classified_transient(self):
        """`httpx.ReadError: Server disconnected` is the wrapper layer
        between aiohttp and LiteLLM. Same root cause; must retry."""
        ie = _llm_retry()
        assert ie.is_transient_error(Exception("httpx.ReadError: Server disconnected"))

    def test_litellm_internal_server_error_classified_transient(self):
        """LiteLLM re-wraps various 5xx and connection failures as
        `litellm.InternalServerError`. Must retry regardless of the
        wrapped cause."""
        ie = _llm_retry()
        assert ie.is_transient_error(Exception(
            "litellm.exceptions.InternalServerError: Something went wrong"
        ))

    def test_connection_error_classified_transient(self):
        ie = _llm_retry()
        for msg in (
            "ConnectionError: TCP connection failed",
            "connection reset by peer",
            "connection refused",
            "connection aborted",
        ):
            assert ie.is_transient_error(Exception(msg)), (
                f"connection-level error must retry: {msg!r}"
            )

    # Sanity probes — pre-existing transient categories still classify.

    def test_429_still_classified_transient(self):
        ie = _llm_retry()
        assert ie.is_transient_error(Exception("HTTP 429 Too Many Requests"))

    def test_timeout_still_classified_transient(self):
        ie = _llm_retry()
        assert ie.is_transient_error(asyncio.TimeoutError())

    # Negative probes — non-transient errors must NOT retry.

    def test_400_bad_request_not_transient(self):
        """A 400 Bad Request (e.g. malformed schema, invalid model
        name) won't succeed on retry — must NOT match."""
        ie = _llm_retry()
        assert not ie.is_transient_error(Exception(
            "openai.BadRequestError: 400 invalid model name"
        ))

    def test_auth_error_not_transient(self):
        ie = _llm_retry()
        assert not ie.is_transient_error(Exception(
            "openai.AuthenticationError: invalid api key"
        ))


# ===========================================================================
# Fix 2 — per-judge timeout override
# ===========================================================================

class TestJudgeTimeoutResolution:
    def test_openai_judge_has_no_default_timeout(self):
        """OpenAI judge moved from gpt-5.5-pro (Responses API,
        reasoner, hit a server-side 3-min cap) to gpt-5.4 (Chat
        Completions, no cap) — see DECISIONS §32. The 600s timeout
        was a workaround for the cap; with gpt-5.4 the default
        LiteLLM/HTTPX timeout is fine. Result: OpenAI no longer
        appears in `JUDGE_TIMEOUT_OVERRIDES` and the resolver
        returns None."""
        p = _providers()
        assert p._resolve_judge_timeout("openai") is None

    def test_deepseek_judge_defaults_to_600s(self):
        """DeepSeek-R1 is reasoner-class — the 10-min headroom
        applies. DeepSeek-R1 succeeded on the Meta-2032 162K-char
        prompt in ~40s with this timeout, demonstrating the kwarg
        works at the SDK level (the OpenAI case that motivated this
        being added was structural, not a kwarg-plumbing issue)."""
        p = _providers()
        assert p._resolve_judge_timeout("deepseek") == 600

    def test_gemini_judge_has_no_default_timeout(self):
        """Native Gemini bypasses LiteLLM; the timeout kwarg wouldn't
        apply. Returns None so `get_judge_model` doesn't try to wrap
        the native model string."""
        p = _providers()
        assert p._resolve_judge_timeout("gemini_pro") is None

    def test_env_var_override_works_for_openai(self, monkeypatch):
        """Even though OpenAI is no longer in
        `JUDGE_TIMEOUT_OVERRIDES`, the env var path still works.
        Useful for the case where an operator pins the OpenAI judge
        back to gpt-5.5-pro and wants the old 600s ceiling."""
        p = _providers()
        monkeypatch.setenv("TMT_JUDGE_OPENAI_TIMEOUT_S", "900")
        assert p._resolve_judge_timeout("openai") == 900

    def test_malformed_env_var_falls_back_to_default(self, monkeypatch):
        """A typo'd timeout shouldn't crash the run — the resolver
        logs a warning and falls back to the override dict (or None
        when the provider isn't in the dict)."""
        p = _providers()
        monkeypatch.setenv("TMT_JUDGE_OPENAI_TIMEOUT_S", "not-a-number")
        # No override-dict entry for openai any more — falls back to None.
        assert p._resolve_judge_timeout("openai") is None
        # DeepSeek still has its override-dict entry as the fallback.
        monkeypatch.setenv("TMT_JUDGE_DEEPSEEK_TIMEOUT_S", "not-a-number")
        assert p._resolve_judge_timeout("deepseek") == 600

    def _extract_timeout(self, spec) -> object:
        """Read the `timeout` kwarg off a LiteLlm spec in a way that
        works against both the real `LiteLlm` (stores kwargs in
        `_additional_args`) and the test conftest's `_StubLiteLlm`
        (stores kwargs as direct attributes)."""
        if hasattr(spec, "_additional_args"):
            return spec._additional_args.get("timeout")
        return getattr(spec, "timeout", None)

    def test_get_judge_model_openai_has_no_timeout_kwarg(self):
        """The OpenAI judge spec no longer carries a timeout kwarg —
        gpt-5.4 on Chat Completions runs fast enough that the LiteLLM
        default first-byte ceiling is appropriate. DECISIONS §32 has
        the full rationale."""
        p = _providers()
        spec = p.get_judge_model("openai")
        assert self._extract_timeout(spec) is None

    def test_get_judge_model_deepseek_carries_timeout_kwarg(self):
        p = _providers()
        spec = p.get_judge_model("deepseek")
        assert self._extract_timeout(spec) == 600

    def test_get_judge_model_claude_has_no_timeout_override(self):
        """Only providers in `JUDGE_TIMEOUT_OVERRIDES` get the kwarg —
        Claude isn't in the override set, so no timeout is forwarded
        (LiteLLM default applies)."""
        p = _providers()
        spec = p.get_judge_model("claude")
        assert self._extract_timeout(spec) is None

    def test_get_judge_model_gemini_has_no_timeout_attribute(self):
        """Native Gemini returns a plain string (not a LiteLlm
        wrapper). Should not error; no timeout kwarg involved."""
        p = _providers()
        spec = p.get_judge_model("gemini_pro")
        # Either a string (native Gemini path) or an object — but
        # crucially the resolver should not have crashed.
        assert spec is not None


# ===========================================================================
# Fix 3 — `_one_judge` retries on transient + captures exception on exhaust
# ===========================================================================

class TestOneJudgeRetryLoop:
    """The judge-side retry loop. Verifies:

    * Transient errors trigger retry-with-backoff (with sleep
      time-multiplied at 0 so the test runs instantly).
    * Successful response after a transient blip lands in the bundle.
    * Exhausted retries on transient errors capture the LAST
      exception's traceback in `<provider>_error.txt` content.
    * Non-transient errors capture on the first attempt.
    """

    def _make_assessment_dict_for_provider(self, provider: str) -> dict:
        return {
            "judge_id": provider,
            "qualitative_summary": "auto",
            "dimension_scores": [
                {"dimension": k, "score": 4, "reasoning": "auto",
                 "evidence": [], "confidence": "medium"}
                for k in _RUBRIC_KEYS
            ],
            "composite_score": 4.0,
            "overall_confidence": "medium",
            "caveats": "",
        }

    def test_transient_error_then_success(self, monkeypatch):
        """First attempt raises a transient error; second succeeds.
        Final bundle must include the assessment + no judge_errors."""
        j = _judging()

        # Patch the judge factory to a sentinel so no LLM machinery is
        # built (the closure only uses `agent.name`-ish attrs).
        monkeypatch.setattr(
            j, "create_construct_judge_agent",
            lambda provider, study: type("FakeAgent", (), {"name": f"ConstructJudge_{provider}"})(),
        )
        # Zero out backoff so the test runs instantly.
        async def _instant_sleep(seconds: float) -> None:
            return None
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

        call_count = {"openai": 0}
        async def fake_run_agent(*, agent, prompt):
            call_count["openai"] += 1
            if call_count["openai"] == 1:
                # Mirror the Meta-2032 exact failure mode.
                raise Exception(
                    "litellm.InternalServerError: InternalServerError: "
                    "OpenAIException - Server disconnected"
                )
            return self._make_assessment_dict_for_provider("openai")

        s = _studies().load_study("openness_maneuvering")
        bundle = asyncio.run(j.run_construct_judging(
            study=s,
            company="Test", industry_context="Dynamic", product_type="Novel",
            deliberation_log=None, artefacts=None,
            observation_summary=None, debriefing_transcript=None,
            field_notes=None,
            run_agent=fake_run_agent,
            judge_providers=["openai"],
        ))
        # Retry succeeded — judge in the bundle, no error.
        assert call_count["openai"] == 2
        assert bundle.judges_used == ["openai"]
        assert "openai" not in bundle.judge_errors

    def test_transient_error_exhausts_after_max_retries(self, monkeypatch):
        """Every attempt raises the same transient error; the final
        error file captures `repr(exc)` + traceback + attempt count."""
        j = _judging()
        ie = _llm_retry()

        monkeypatch.setattr(
            j, "create_construct_judge_agent",
            lambda provider, study: type("FakeAgent", (), {"name": f"ConstructJudge_{provider}"})(),
        )
        async def _instant_sleep(seconds: float) -> None:
            return None
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

        call_count = {"openai": 0}
        async def always_fail(*, agent, prompt):
            call_count["openai"] += 1
            raise Exception(
                "litellm.InternalServerError: InternalServerError: "
                "OpenAIException - Server disconnected"
            )

        # claude succeeds so the bundle has at least one assessment
        # (otherwise run_construct_judging raises RuntimeError).
        async def routed(*, agent, prompt):
            if "openai" in (agent.name or ""):
                return await always_fail(agent=agent, prompt=prompt)
            return self._make_assessment_dict_for_provider("claude")

        s = _studies().load_study("openness_maneuvering")
        bundle = asyncio.run(j.run_construct_judging(
            study=s,
            company="Test", industry_context="Dynamic", product_type="Novel",
            deliberation_log=None, artefacts=None,
            observation_summary=None, debriefing_transcript=None,
            field_notes=None,
            run_agent=routed,
            judge_providers=["openai", "claude"],
        ))
        # MAX_RETRIES = 5 → 6 attempts total.
        assert call_count["openai"] == ie.MAX_RETRIES + 1
        # openai failure surfaces in judge_errors with the captured exc.
        assert "openai" in bundle.judge_errors
        err = bundle.judge_errors["openai"]
        assert "Server disconnected" in err
        assert "transient=True" in err
        assert f"attempts={ie.MAX_RETRIES + 1}/{ie.MAX_RETRIES + 1}" in err
        # claude succeeded.
        assert bundle.judges_used == ["claude"]

    def test_non_transient_error_no_retry(self, monkeypatch):
        """A 400 Bad Request should NOT retry — burns budget for no
        chance of success. Captured immediately."""
        j = _judging()

        monkeypatch.setattr(
            j, "create_construct_judge_agent",
            lambda provider, study: type("FakeAgent", (), {"name": f"ConstructJudge_{provider}"})(),
        )
        async def _instant_sleep(seconds: float) -> None:
            return None
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

        call_count = {"openai": 0}
        async def fake_run_agent(*, agent, prompt):
            if "openai" in (agent.name or ""):
                call_count["openai"] += 1
                raise Exception(
                    "openai.BadRequestError: 400 invalid request format"
                )
            return self._make_assessment_dict_for_provider("claude")

        s = _studies().load_study("openness_maneuvering")
        bundle = asyncio.run(j.run_construct_judging(
            study=s,
            company="Test", industry_context="Dynamic", product_type="Novel",
            deliberation_log=None, artefacts=None,
            observation_summary=None, debriefing_transcript=None,
            field_notes=None,
            run_agent=fake_run_agent,
            judge_providers=["openai", "claude"],
        ))
        # Just one attempt — non-transient.
        assert call_count["openai"] == 1
        err = bundle.judge_errors["openai"]
        assert "transient=False" in err
        assert "attempts=1/" in err
