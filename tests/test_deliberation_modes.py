"""Stubbed tests for orchestrator.deliberation — modes + convergence.

These tests exercise the four discussion modes
(`ceo_led`, `random_initiator`, `parallel_then_discuss`, `round_robin`)
and the three convergence criteria
(`time_boxed`, `stability`, `synthesiser`) without spinning up any
real LLM. The runner is a stub that returns canned text per agent
name; convergence YES/NO for the synthesiser mode is controlled by
a counter.

Coverage focus
--------------
- Default config dispatches to `parallel_then_discuss` + `time_boxed`.
- D2 produces a structured log with the expected phases:
  initial_position (6 events, one per role) → round_N (per role,
  contributions + passes) → convergence (1 event, CEO synthesis).
- D3 produces shuffled-per-round events with passes recognised.
- `random_initiator` uses `random_seed` to be reproducible.
- Convergence modes stop the loop when their criteria fire.
- `[PASS]` (and near-misses) are dropped from the discussion
  transcript but recorded as `kind="other"` events.
"""

from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass
from typing import Callable

import pytest

PKG = "open-innovation-strategy"


def _deliberation():
    return importlib.import_module(f"{PKG}.orchestrator.deliberation")


def _data_capture():
    return importlib.import_module(f"{PKG}.data_capture")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ROLES = ("CEO", "CTO", "COO", "CMO", "Product_Strategist", "Product_Designer")


@dataclass
class _StubAgent:
    """Minimal LlmAgent stand-in. Tests look at `name` only."""

    name: str
    instruction: str = ""
    model: str = "stub-model"


def _make_role_agents() -> dict:
    return {role: _StubAgent(name=role) for role in ROLES}


def _runner_canned(template: Callable[[str, str], str], record: list | None = None):
    """Build a runner that returns a canned text per call.

    Args:
        template: `(agent_name, prompt) -> text`. The test specifies
            how each agent responds.
        record: Optional list captured in closure; each entry is
            `(agent_name, prompt_excerpt)` for assertion-on-call-order.
    """
    async def runner(*, agent, prompt):
        out = template(agent.name, prompt)
        if record is not None:
            record.append((agent.name, prompt[:80]))
        return out

    return runner


def _always_text(text: str):
    """Runner: every agent returns the same text."""
    async def runner(*, agent, prompt):
        return text
    return runner


# ---------------------------------------------------------------------------
# 1. Default config
# ---------------------------------------------------------------------------

class TestDefaultConfig:
    def test_default_is_concurrent_with_time_boxed_convergence_for_round_modes(self):
        """Default discussion mode is CONCURRENT (closest to real TMT).

        CONCURRENT ignores `convergence` — it uses ConcurrentConfig
        caps instead — but the field still defaults to time_boxed(5)
        so switching to a round-based mode just works.
        """
        d = _deliberation()
        cfg = d.DeliberationConfig()
        assert cfg.discussion_mode == d.DiscussionMode.CONCURRENT
        assert cfg.convergence.mode == d.ConvergenceMode.TIME_BOXED
        assert cfg.convergence.max_rounds == 5

    def test_parallel_then_discuss_still_reachable_via_flag(self):
        d = _deliberation()
        cfg = d.DeliberationConfig(
            discussion_mode=d.DiscussionMode.PARALLEL_THEN_DISCUSS,
        )
        assert cfg.discussion_mode == d.DiscussionMode.PARALLEL_THEN_DISCUSS


# ---------------------------------------------------------------------------
# 2. ceo_led mode falls through to the ceo_led_fallback when supplied
# ---------------------------------------------------------------------------

class TestCEOLedMode:
    def test_dispatches_to_fallback_when_supplied(self):
        d = _deliberation()
        fallback_called = []

        async def fake_fallback():
            fallback_called.append(True)
            return d.DeliberationOutcome(
                log=_data_capture().DeliberationLog(
                    company="OpenAI",
                    industry_context="Dynamic",
                    product_type="Novel",
                ),
                ceo_synthesis="CEO speaks.",
                ended_reason="transfer_chain_complete",
                discussion_mode=d.DiscussionMode.CEO_LED,
                rounds_completed=1,
            )

        cfg = d.DeliberationConfig(discussion_mode=d.DiscussionMode.CEO_LED)
        outcome = asyncio.run(d.run_deliberation(
            role_agents=_make_role_agents(),
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            product_description="X",
            strategic_question="Y",
            config=cfg,
            run_agent=_always_text("unused"),
            ceo_led_fallback=fake_fallback,
        ))
        assert fallback_called == [True]
        assert outcome.discussion_mode == d.DiscussionMode.CEO_LED
        assert outcome.ceo_synthesis == "CEO speaks."

    def test_falls_back_to_random_initiator_when_no_fallback_supplied(self):
        d = _deliberation()
        # When no fallback is provided, ceo_led emulates via random_initiator
        # with the CEO forced as root — semantically equivalent for tests.
        cfg = d.DeliberationConfig(discussion_mode=d.DiscussionMode.CEO_LED)
        outcome = asyncio.run(d.run_deliberation(
            role_agents=_make_role_agents(),
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            product_description="X",
            strategic_question="Y",
            config=cfg,
            run_agent=_always_text("CEO's call: do A and B."),
            ceo_led_fallback=None,
        ))
        # The single event in the log is authored by the CEO.
        assert len(outcome.log.events) == 1
        assert outcome.log.events[0].role == "CEO"


# ---------------------------------------------------------------------------
# 3. random_initiator — seeded reproducibility, root rotates across seeds
# ---------------------------------------------------------------------------

class TestRandomInitiator:
    def test_seed_makes_initiator_reproducible(self):
        d = _deliberation()
        record = []

        def runner_factory():
            return _runner_canned(
                lambda name, prompt: f"output from {name}", record
            )

        cfg = d.DeliberationConfig(
            discussion_mode=d.DiscussionMode.RANDOM_INITIATOR,
            random_seed=42,
        )
        outcome_a = asyncio.run(d.run_deliberation(
            role_agents=_make_role_agents(),
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            product_description="X",
            strategic_question="Y",
            config=cfg,
            run_agent=runner_factory(),
        ))
        record.clear()
        outcome_b = asyncio.run(d.run_deliberation(
            role_agents=_make_role_agents(),
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            product_description="X",
            strategic_question="Y",
            config=cfg,
            run_agent=runner_factory(),
        ))
        # Same seed → same root.
        assert outcome_a.log.events[0].role == outcome_b.log.events[0].role

    def test_different_seeds_can_pick_different_roots(self):
        d = _deliberation()
        roots_seen = set()
        for seed in range(20):
            cfg = d.DeliberationConfig(
                discussion_mode=d.DiscussionMode.RANDOM_INITIATOR,
                random_seed=seed,
            )
            outcome = asyncio.run(d.run_deliberation(
                role_agents=_make_role_agents(),
                company="OpenAI",
                industry_context="Dynamic",
                product_type="Novel",
                product_description="X",
                strategic_question="Y",
                config=cfg,
                run_agent=_always_text("ok"),
            ))
            roots_seen.add(outcome.log.events[0].role)
        # Across 20 seeds we should hit at least 3 distinct roles.
        assert len(roots_seen) >= 3, (
            f"random_initiator picked too narrow a set: {roots_seen}"
        )


# ---------------------------------------------------------------------------
# 4. parallel_then_discuss — phase shape and convergence
# ---------------------------------------------------------------------------

class TestParallelThenDiscuss:
    def test_phase_a_emits_one_initial_position_per_role(self):
        d = _deliberation()
        cfg = d.DeliberationConfig(
            discussion_mode=d.DiscussionMode.PARALLEL_THEN_DISCUSS,
            convergence=d.ConvergenceConfig(
                mode=d.ConvergenceMode.TIME_BOXED, max_rounds=1,
            ),
        )
        outcome = asyncio.run(d.run_deliberation(
            role_agents=_make_role_agents(),
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            product_description="X",
            strategic_question="Y",
            config=cfg,
            run_agent=_always_text("My position is X."),
        ))
        # Initial-position phase: 6 events, kind=text, phase=initial_position.
        initials = [e for e in outcome.log.events if e.phase == "initial_position"]
        assert len(initials) == 6
        assert sorted(e.role for e in initials) == sorted(ROLES)
        # Convergence phase: exactly 1 event from CEO.
        conv = [e for e in outcome.log.events if e.phase == "convergence"]
        assert len(conv) == 1
        assert conv[0].role == "CEO"

    def test_pass_marker_recorded_as_other_and_dropped_from_transcript(self):
        """Pass-detection applies only in discussion rounds, not initial-position.

        In Phase A (initial position) the role is asked to STATE a
        position; emitting '[PASS]' there is a degenerate position and
        gets recorded verbatim as kind='text' for transparency. In
        Phase B (rounds) `[PASS]` is the explicit abstention marker
        and gets recorded as kind='other'.
        """
        d = _deliberation()

        def template(name, prompt):
            # CTO emits [PASS] everywhere; everyone else contributes.
            if name == "CTO":
                return "[PASS]"
            return f"{name} says X"

        cfg = d.DeliberationConfig(
            discussion_mode=d.DiscussionMode.PARALLEL_THEN_DISCUSS,
            convergence=d.ConvergenceConfig(
                mode=d.ConvergenceMode.TIME_BOXED, max_rounds=2,
            ),
        )
        outcome = asyncio.run(d.run_deliberation(
            role_agents=_make_role_agents(),
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            product_description="X",
            strategic_question="Y",
            config=cfg,
            run_agent=_runner_canned(template),
        ))
        # Initial position: kind='text' (no pass-detection in Phase A).
        cto_initials = [
            e for e in outcome.log.events
            if e.role == "CTO" and e.phase == "initial_position"
        ]
        assert len(cto_initials) == 1
        assert cto_initials[0].kind == "text"
        assert cto_initials[0].text == "[PASS]"

        # Discussion rounds: kind='other' (pass-detection fires).
        cto_round_passes = [
            e for e in outcome.log.events
            if e.role == "CTO"
            and e.phase is not None
            and e.phase.startswith("round_")
        ]
        assert len(cto_round_passes) == 2  # one per round
        for e in cto_round_passes:
            assert e.kind == "other"
            assert e.text == "[PASS]"

    def test_time_boxed_runs_full_max_rounds(self):
        d = _deliberation()
        cfg = d.DeliberationConfig(
            discussion_mode=d.DiscussionMode.PARALLEL_THEN_DISCUSS,
            convergence=d.ConvergenceConfig(
                mode=d.ConvergenceMode.TIME_BOXED, max_rounds=3,
            ),
        )
        outcome = asyncio.run(d.run_deliberation(
            role_agents=_make_role_agents(),
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            product_description="X",
            strategic_question="Y",
            config=cfg,
            run_agent=_always_text("contribution"),
        ))
        assert outcome.rounds_completed == 3
        assert outcome.ended_reason == "max_rounds"

    def test_stability_stops_early_when_quiet_rounds_threshold_reached(self):
        d = _deliberation()
        # All roles pass → quiet from round 1.
        cfg = d.DeliberationConfig(
            discussion_mode=d.DiscussionMode.PARALLEL_THEN_DISCUSS,
            convergence=d.ConvergenceConfig(
                mode=d.ConvergenceMode.STABILITY,
                max_rounds=10,
                quiet_rounds_threshold=2,
                quiet_min_contributions=1,
            ),
        )
        outcome = asyncio.run(d.run_deliberation(
            role_agents=_make_role_agents(),
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            product_description="X",
            strategic_question="Y",
            config=cfg,
            run_agent=_always_text("[PASS]"),
        ))
        # 2 quiet rounds should trigger stability.
        assert outcome.ended_reason == "stable"
        assert outcome.rounds_completed == 2

    def test_synthesiser_stops_when_judge_says_yes(self):
        d = _deliberation()
        call_idx = {"n": 0}

        async def runner(*, agent, prompt):
            # Synthesiser agent: name is "ConvergenceSynthesiser".
            if agent.name == "ConvergenceSynthesiser":
                call_idx["n"] += 1
                # Say NO on round 1, YES on round 2.
                return "YES" if call_idx["n"] >= 2 else "NO"
            return "contribution"

        cfg = d.DeliberationConfig(
            discussion_mode=d.DiscussionMode.PARALLEL_THEN_DISCUSS,
            convergence=d.ConvergenceConfig(
                mode=d.ConvergenceMode.SYNTHESISER, max_rounds=10,
            ),
        )
        outcome = asyncio.run(d.run_deliberation(
            role_agents=_make_role_agents(),
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            product_description="X",
            strategic_question="Y",
            config=cfg,
            run_agent=runner,
        ))
        assert outcome.ended_reason == "synthesiser_converged"
        assert outcome.rounds_completed == 2


# ---------------------------------------------------------------------------
# 5. round_robin — shuffled per round, abstention recognised
# ---------------------------------------------------------------------------

class TestRoundRobin:
    def test_each_round_visits_every_role(self):
        d = _deliberation()
        record = []

        def template(name, prompt):
            return f"{name} says X"

        cfg = d.DeliberationConfig(
            discussion_mode=d.DiscussionMode.ROUND_ROBIN,
            convergence=d.ConvergenceConfig(
                mode=d.ConvergenceMode.TIME_BOXED, max_rounds=1,
            ),
            random_seed=1,
        )
        outcome = asyncio.run(d.run_deliberation(
            role_agents=_make_role_agents(),
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            product_description="X",
            strategic_question="Y",
            config=cfg,
            run_agent=_runner_canned(template, record),
        ))
        # In round 1 every role should have been called once.
        role_calls_in_round = [
            r for r, p in record
            if r != "ConvergenceSynthesiser" and r != "CEO_synthesis_only"
        ]
        # The CEO is called twice: once during the round, once for synthesis.
        # Filter out the synthesis call by deduplicating to first occurrences.
        first_calls = []
        seen = set()
        for r, p in record:
            if "COLLECTIVE synthesis" in p:
                # this is the synthesis call
                continue
            if r not in seen:
                first_calls.append(r)
                seen.add(r)
        assert sorted(first_calls) == sorted(ROLES)

    def test_shuffle_order_is_seeded(self):
        """Same seed → same shuffled order each run."""
        d = _deliberation()

        async def make_runner():
            calls = []

            async def runner(*, agent, prompt):
                if "COLLECTIVE synthesis" not in prompt:
                    calls.append(agent.name)
                return f"{agent.name} says X"

            return runner, calls

        cfg = d.DeliberationConfig(
            discussion_mode=d.DiscussionMode.ROUND_ROBIN,
            convergence=d.ConvergenceConfig(
                mode=d.ConvergenceMode.TIME_BOXED, max_rounds=1,
            ),
            random_seed=7,
        )

        runner_a, calls_a = asyncio.run(make_runner())
        asyncio.run(d.run_deliberation(
            role_agents=_make_role_agents(),
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            product_description="X",
            strategic_question="Y",
            config=cfg,
            run_agent=runner_a,
        ))

        runner_b, calls_b = asyncio.run(make_runner())
        asyncio.run(d.run_deliberation(
            role_agents=_make_role_agents(),
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            product_description="X",
            strategic_question="Y",
            config=cfg,
            run_agent=runner_b,
        ))

        # Same seed → same call order.
        assert calls_a == calls_b


# ---------------------------------------------------------------------------
# 6. _is_pass helper handles the common abstention forms
# ---------------------------------------------------------------------------

class TestPassDetection:
    @pytest.mark.parametrize("text", [
        "[PASS]",
        "  [PASS]  ",
        "[pass]",
        "PASS",
        "(PASS)",
        "no comment",
        "[NO COMMENT]",
        "",
    ])
    def test_recognised_as_pass(self, text):
        d = _deliberation()
        assert d._is_pass(text) is True

    @pytest.mark.parametrize("text", [
        "We should pass on this opportunity.",  # phrase, not abstention
        "I disagree.",
        "X is the right call.",
    ])
    def test_substantive_text_not_a_pass(self, text):
        d = _deliberation()
        assert d._is_pass(text) is False
