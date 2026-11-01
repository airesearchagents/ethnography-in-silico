"""Unit tests for orchestrator.rate_limit.

Covers:
  * TokenBucket refill rate (balance increases by elapsed * tpm / 60).
  * TokenBucket capacity cap (refill never exceeds the configured tpm/rpm).
  * Single-call acquire fast-path (no wait when balance suffices).
  * Wait path (acquire blocks until refill).
  * Concurrent acquires serialise correctly under asyncio (no double-spend).
  * Oversized-request edge case (request > tpm cap).
  * Env-var overrides (TMT_RATELIMIT_<PROVIDER>_TPM/RPM).
  * Env-var disable ("off" / "none" / "0").
  * Provider detection from string and LiteLlm wrapper.
  * Public `acquire_for_call` end-to-end with provider mapping.
  * Ollama / unknown providers are no-ops.

Tests use an injected `now_fn` clock that advances explicitly, so we
never actually sleep wall-clock time. Each test that touches the
global registry calls `reset_buckets()` to keep them isolated.
"""

from __future__ import annotations

import asyncio
import os
from typing import List

import pytest

from orchestrator import rate_limit as rl


# ---------------------------------------------------------------------------
# Test clock — list-of-floats driven monotonic-style fake.
# ---------------------------------------------------------------------------

class FakeClock:
    """Test clock that returns the head of a list and advances on tick().

    Each call to `__call__` returns `self.t`. `tick(seconds)` advances
    it. Used as `now_fn=` on TokenBucket. Also patches asyncio.sleep
    so it advances the clock and yields control without real wait.
    """
    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def tick(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def patched_sleep(monkeypatch, clock):
    """Replace asyncio.sleep with a fake that advances the clock."""
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds: float, result=None):
        # Advance the clock so the next refill sees elapsed time.
        clock.tick(seconds)
        # Still yield to the event loop with zero-delay so other
        # awaitables in this test's gather() run.
        await real_sleep(0)
        return result

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return fake_sleep


@pytest.fixture(autouse=True)
def isolated_buckets():
    """Each test gets a fresh bucket registry."""
    rl.reset_buckets()
    yield
    rl.reset_buckets()


# ---------------------------------------------------------------------------
# TokenBucket — primitives
# ---------------------------------------------------------------------------

class TestTokenBucketRefill:
    """The bucket refills at tpm/60 tokens per second up to the capacity."""

    @pytest.mark.asyncio
    async def test_starts_full(self, clock):
        b = rl.TokenBucket(tpm=60_000, rpm=60, now_fn=clock)
        # Should not block — bucket starts at full capacity.
        wait = await b.acquire(1000)
        assert wait == 0.0
        assert b.token_balance == pytest.approx(60_000 - 1000)
        assert b.request_balance == pytest.approx(59.0)

    @pytest.mark.asyncio
    async def test_refill_proportional_to_elapsed_time(self, clock):
        b = rl.TokenBucket(tpm=60_000, rpm=60, now_fn=clock)
        # Drain partially.
        await b.acquire(50_000)
        assert b.token_balance == pytest.approx(10_000)
        # Advance 30 seconds — should refill 30k tokens.
        clock.tick(30.0)
        await b.acquire(0 + 1)  # tiny request triggers refill on the way in
        # Should be at min(60_000, 10_000 + 30_000) - 1 = 39_999
        assert b.token_balance == pytest.approx(39_999)

    @pytest.mark.asyncio
    async def test_refill_never_exceeds_capacity(self, clock):
        b = rl.TokenBucket(tpm=60_000, rpm=60, now_fn=clock)
        await b.acquire(10_000)
        # Advance way more time than needed for full refill.
        clock.tick(3600.0)
        await b.acquire(1)
        # Should be capped at 60_000, then minus 1.
        assert b.token_balance == pytest.approx(59_999)


class TestTokenBucketWait:
    """When capacity isn't immediately available, acquire blocks."""

    @pytest.mark.asyncio
    async def test_waits_when_token_balance_insufficient(
        self, clock, patched_sleep,
    ):
        # 60k tpm = 1k tokens per second.
        b = rl.TokenBucket(tpm=60_000, rpm=600, now_fn=clock)
        # Drain it.
        await b.acquire(60_000)
        assert b.token_balance == pytest.approx(0.0)
        # Next request for 10k tokens should wait ~10 seconds.
        wait = await b.acquire(10_000)
        assert wait == pytest.approx(10.0, abs=0.5)
        # Balance should be ~0 after the acquire.
        assert b.token_balance == pytest.approx(0.0, abs=10)

    @pytest.mark.asyncio
    async def test_waits_when_request_balance_insufficient(
        self, clock, patched_sleep,
    ):
        # Big TPM but tight RPM — RPM should be the binding constraint.
        b = rl.TokenBucket(tpm=4_000_000, rpm=60, now_fn=clock)
        # Drain all request capacity.
        for _ in range(60):
            await b.acquire(100)
        assert b.request_balance == pytest.approx(0.0, abs=0.001)
        # Token balance is still high; only the RPM should force a wait.
        # 60 rpm = 1 request per second, so next acquire waits ~1s.
        wait = await b.acquire(100)
        assert wait == pytest.approx(1.0, abs=0.2)


class TestTokenBucketOversized:
    """A request larger than the per-minute cap is satisfied at full capacity."""

    @pytest.mark.asyncio
    async def test_oversized_request_eventually_succeeds(
        self, clock, patched_sleep, caplog,
    ):
        b = rl.TokenBucket(tpm=30_000, rpm=600, now_fn=clock)
        await b.acquire(30_000)  # drain
        # 38k tokens > 30k cap.
        with caplog.at_level("WARNING"):
            wait = await b.acquire(38_000)
        # Should have logged the oversized warning.
        assert any("oversized" in r.message.lower() for r in caplog.records)
        # Should have eventually succeeded (capped at 30k).
        assert wait > 0


class TestTokenBucketConcurrent:
    """Concurrent acquires must serialise — no double-spend."""

    @pytest.mark.asyncio
    async def test_concurrent_acquires_do_not_double_spend(
        self, clock, patched_sleep,
    ):
        b = rl.TokenBucket(tpm=10_000, rpm=600, now_fn=clock)
        # Six concurrent role agents each asking for 2k tokens.
        # Total demand = 12k, capacity = 10k. Two will wait.
        async def one_acquire():
            return await b.acquire(2000)

        waits = await asyncio.gather(*[one_acquire() for _ in range(6)])
        # At least 1 of them should have waited (the one that pushed over).
        assert any(w > 0 for w in waits)
        # Total tokens taken = 6 * 2000 = 12_000. After 5 successful
        # immediate acquires (5*2000=10000), the 6th had to wait.
        # Balance at end should not be negative.
        assert b.token_balance >= 0


class TestTokenBucketConstructor:
    """Validation."""

    def test_rejects_zero_tpm(self):
        with pytest.raises(ValueError):
            rl.TokenBucket(tpm=0, rpm=10)

    def test_rejects_negative_rpm(self):
        with pytest.raises(ValueError):
            rl.TokenBucket(tpm=1000, rpm=-1)


# ---------------------------------------------------------------------------
# Registry + env-var resolution
# ---------------------------------------------------------------------------

class TestResolveLimits:
    def test_defaults_returned_when_no_env_override(self, monkeypatch):
        monkeypatch.delenv("TMT_RATELIMIT_CLAUDE_TPM", raising=False)
        monkeypatch.delenv("TMT_RATELIMIT_CLAUDE_RPM", raising=False)
        limits = rl._resolve_limits("claude")
        assert limits == rl.PROVIDER_RATE_LIMITS["claude"]

    def test_env_tpm_override(self, monkeypatch):
        monkeypatch.setenv("TMT_RATELIMIT_CLAUDE_TPM", "80000")
        monkeypatch.delenv("TMT_RATELIMIT_CLAUDE_RPM", raising=False)
        limits = rl._resolve_limits("claude")
        assert limits["tpm"] == 80_000
        # RPM should fall back to default.
        assert limits["rpm"] == rl.PROVIDER_RATE_LIMITS["claude"]["rpm"]

    def test_env_rpm_override(self, monkeypatch):
        monkeypatch.delenv("TMT_RATELIMIT_CLAUDE_TPM", raising=False)
        monkeypatch.setenv("TMT_RATELIMIT_CLAUDE_RPM", "1000")
        limits = rl._resolve_limits("claude")
        assert limits["rpm"] == 1000
        assert limits["tpm"] == rl.PROVIDER_RATE_LIMITS["claude"]["tpm"]

    @pytest.mark.parametrize("disable_value", ["off", "none", "0", "false", "no", "OFF"])
    def test_env_disable_returns_none(self, monkeypatch, disable_value):
        monkeypatch.setenv("TMT_RATELIMIT_CLAUDE_TPM", disable_value)
        assert rl._resolve_limits("claude") is None

    def test_ollama_returns_none_by_default(self, monkeypatch):
        monkeypatch.delenv("TMT_RATELIMIT_OLLAMA_TPM", raising=False)
        monkeypatch.delenv("TMT_RATELIMIT_OLLAMA_RPM", raising=False)
        assert rl._resolve_limits("ollama") is None

    def test_ollama_can_be_enabled_via_env(self, monkeypatch):
        monkeypatch.setenv("TMT_RATELIMIT_OLLAMA_TPM", "50000")
        monkeypatch.setenv("TMT_RATELIMIT_OLLAMA_RPM", "100")
        limits = rl._resolve_limits("ollama")
        assert limits == {"tpm": 50_000, "rpm": 100}

    def test_unknown_provider_returns_none(self, monkeypatch):
        assert rl._resolve_limits("totally-fake-provider") is None

    def test_garbage_env_var_logs_and_returns_none(self, monkeypatch, caplog):
        monkeypatch.setenv("TMT_RATELIMIT_CLAUDE_TPM", "not-a-number")
        with caplog.at_level("WARNING"):
            limits = rl._resolve_limits("claude")
        assert limits is None
        assert any("non-integer" in r.message for r in caplog.records)


class TestGetBucket:
    def test_returns_bucket_for_configured_provider(self):
        b = rl.get_bucket("claude")
        assert b is not None
        assert b.tpm == rl.PROVIDER_RATE_LIMITS["claude"]["tpm"]

    def test_returns_none_for_ollama_default(self):
        assert rl.get_bucket("ollama") is None

    def test_caches_bucket_instance(self):
        b1 = rl.get_bucket("claude")
        b2 = rl.get_bucket("claude")
        assert b1 is b2

    def test_caches_none_for_ollama(self):
        rl.get_bucket("ollama")
        # Second call should return None from cache, not rebuild.
        assert rl.get_bucket("ollama") is None
        assert "ollama" in rl._BUCKETS

    def test_reset_buckets_clears_cache(self):
        rl.get_bucket("claude")
        assert "claude" in rl._BUCKETS
        rl.reset_buckets()
        assert "claude" not in rl._BUCKETS


# ---------------------------------------------------------------------------
# estimate_tokens + provider_for_model
# ---------------------------------------------------------------------------

class TestEstimateTokens:
    def test_zero_text_returns_just_output_budget(self):
        assert rl.estimate_tokens("", output_budget=500) == 500

    def test_default_output_budget_is_2000(self):
        assert rl.estimate_tokens("") == 2000

    def test_text_contribution_is_chars_over_four(self):
        # 4000 chars = 1000 tokens (heuristic) + 2000 budget = 3000.
        assert rl.estimate_tokens("a" * 4000) == 3000

    def test_negative_output_budget_clamps_to_zero(self):
        assert rl.estimate_tokens("a" * 400, output_budget=-100) == 100


class _FakeLiteLlm:
    """Stand-in for google.adk.models.lite_llm.LiteLlm — just needs `.model`."""
    def __init__(self, model: str) -> None:
        self.model = model


class TestProviderForModel:
    def test_none_returns_none(self):
        assert rl.provider_for_model(None) is None

    def test_native_gemini_pro_string(self):
        assert rl.provider_for_model("gemini-3.1-pro") == "gemini_pro"
        assert rl.provider_for_model("gemini-2.5-pro") == "gemini_pro"

    def test_native_gemini_flash_string(self):
        assert rl.provider_for_model("gemini-3.5-flash") == "gemini_flash"

    def test_non_gemini_string_returns_none(self):
        assert rl.provider_for_model("o1-preview") is None

    def test_litellm_anthropic_prefix(self):
        spec = _FakeLiteLlm(model="anthropic/claude-opus-4-7")
        assert rl.provider_for_model(spec) == "claude"

    def test_litellm_openai_prefix(self):
        spec = _FakeLiteLlm(model="openai/gpt-5.4")
        assert rl.provider_for_model(spec) == "openai"

    def test_litellm_deepseek_prefix(self):
        spec = _FakeLiteLlm(model="deepseek/deepseek-chat-v4")
        assert rl.provider_for_model(spec) == "deepseek"

    def test_litellm_groq_prefix(self):
        spec = _FakeLiteLlm(model="groq/llama-4-maverick")
        assert rl.provider_for_model(spec) == "groq"

    def test_litellm_ollama_chat_prefix(self):
        spec = _FakeLiteLlm(model="ollama_chat/qwen3.5:9b")
        assert rl.provider_for_model(spec) == "ollama"

    def test_unknown_litellm_prefix_returns_none(self):
        spec = _FakeLiteLlm(model="bedrock/anthropic.claude-v2")
        assert rl.provider_for_model(spec) is None


# ---------------------------------------------------------------------------
# acquire_for_call — the public entry point
# ---------------------------------------------------------------------------

class TestAcquireForCall:
    @pytest.mark.asyncio
    async def test_noop_for_unknown_model_spec(self):
        wait = await rl.acquire_for_call(None, "hi")
        assert wait == 0.0

    @pytest.mark.asyncio
    async def test_noop_for_ollama(self):
        spec = _FakeLiteLlm(model="ollama_chat/qwen3.5:9b")
        wait = await rl.acquire_for_call(spec, "hello")
        assert wait == 0.0

    @pytest.mark.asyncio
    async def test_acquires_for_claude(self):
        spec = _FakeLiteLlm(model="anthropic/claude-opus-4-7")
        wait = await rl.acquire_for_call(spec, "hi")
        # First call should not wait — bucket starts full.
        assert wait == 0.0
        bucket = rl.get_bucket("claude")
        # Some tokens should have been consumed.
        assert bucket.token_balance < bucket.tpm

    @pytest.mark.asyncio
    async def test_blocks_under_storm(self, monkeypatch, patched_sleep, clock):
        """Six concurrent Claude-tier-1-sized calls serialise without
        starving any caller. Sized so that some fit immediately and
        some wait — the bucket's job is exactly to enforce that
        ordering instead of letting all six 429 in parallel."""
        # Replace the registry entry with a bucket driven by our fake clock.
        rl._BUCKETS["claude"] = rl.TokenBucket(
            tpm=30_000, rpm=50, now_fn=clock,
        )
        spec = _FakeLiteLlm(model="anthropic/claude-opus-4-7")
        # Each prompt: 20_000 chars → 5k input-token estimate. With the
        # default 2k output budget the per-call estimate is 7k tokens.
        # 6 callers × 7k = 42k tokens demand vs a 30k tpm cap → 4
        # immediate (28k), 2 must wait.
        prompt = "x" * 20_000

        async def one_call():
            return await rl.acquire_for_call(spec, prompt)

        waits = await asyncio.gather(*[one_call() for _ in range(6)])

        # The throttle's job under storm: SOME callers must wait
        # (otherwise it isn't preventing the synchronised retry storm).
        # We don't pin the exact count — the fake clock advances inside
        # asyncio.sleep, so a "delayed" task's sleep can opportunistically
        # refill the bucket for tasks the event loop scheduled after it.
        # That's a quirk of the test harness, not production behaviour.
        # The real contract is: under demand exceeding capacity, at least
        # one caller blocks instead of all six 429-storming in parallel.
        bucket = rl.get_bucket("claude")
        assert len(waits) == 6
        assert any(w > 0 for w in waits), (
            f"expected at least one caller to wait under storm; got {waits}"
        )
        assert bucket.token_balance >= 0, (
            f"token_balance went negative: {bucket.token_balance}"
        )
        assert bucket.request_balance >= 0, (
            f"request_balance went negative: {bucket.request_balance}"
        )


# ---------------------------------------------------------------------------
# Smoke — module imports cleanly
# ---------------------------------------------------------------------------

def test_module_constants_present():
    """Imports + sanity for the public surface."""
    assert "claude" in rl.PROVIDER_RATE_LIMITS
    assert rl.PROVIDER_RATE_LIMITS["ollama"] is None
    # Constants stay positive.
    for provider, cfg in rl.PROVIDER_RATE_LIMITS.items():
        if cfg is None:
            continue
        assert cfg["tpm"] > 0, f"non-positive tpm for {provider}"
        assert cfg["rpm"] > 0, f"non-positive rpm for {provider}"


def test_gemini_pro_default_sized_for_preview_tier():
    """The `gemini_pro` default in PROVIDER_RATE_LIMITS is sized
    for Vertex preview-tier (gemini-3.x-pro-preview). The GA 2.5
    family has much higher ceilings; operators on GA can override
    via TMT_RATELIMIT_GEMINI_PRO_TPM / _RPM env vars.

    This test pins the conservative default so a future refactor
    can't silently bump it back to GA-tier limits and re-introduce
    the 429-storm during Phase 4 that the Meta-2032 cell hit."""
    cfg = rl.PROVIDER_RATE_LIMITS["gemini_pro"]
    assert cfg is not None
    # Preview-tier sanity bounds. Anything above ~500k TPM would
    # be GA-tier and re-introduce the under-throttling that cost
    # us Phase 4 in the Meta cell.
    assert cfg["tpm"] <= 500_000, (
        f"gemini_pro tpm={cfg['tpm']} looks GA-tier; preview is ~100k. "
        "Under-throttling here will 429-storm Phase 4 again."
    )
    assert cfg["rpm"] <= 200
