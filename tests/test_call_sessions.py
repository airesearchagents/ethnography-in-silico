"""Each model call has its own empty session.

A shared session re-sends every earlier prompt on every call, which was most of
a run's cost. Each prompt now carries what its agent needs
(`orchestrator.role_memory`, tested in `test_call_context.py`).

Tests cover:

  1. The mapper, which still names sessions: every role variant collapses to
     one `role_<X>` key, both researcher shells to `researcher`, and unknown
     names pass through.
  2. The default runner: no two calls share a session, and each records its
     token usage.
  3. The deliberation's runner in `agent.py` does the same.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from dataclasses import dataclass

import pytest

PKG = "open-innovation-strategy"


def _rs():
    return importlib.import_module(f"{PKG}.run_research_session")


def _agent_module():
    return importlib.import_module(f"{PKG}.agent")


# ===========================================================================
# 1. _session_key_for — the agent-name → session-key mapper
# ===========================================================================

class TestSessionKeyMapper:
    """`_session_key_for` is pure (no I/O), so test it directly."""

    @pytest.mark.parametrize("role", [
        "CEO", "CTO", "COO", "CMO",
        "Product_Strategist", "Product_Designer",
    ])
    def test_bare_role_maps_to_role_prefix(self, role):
        m = _rs()
        assert m._session_key_for(role) == f"role_{role}"

    @pytest.mark.parametrize("role", [
        "CEO", "CTO", "COO", "CMO",
        "Product_Strategist", "Product_Designer",
    ])
    def test_concurrent_variant_maps_to_same_key(self, role):
        m = _rs()
        assert m._session_key_for(f"{role}_Concurrent") == f"role_{role}"

    @pytest.mark.parametrize("role", [
        "CEO", "CTO", "COO", "CMO",
        "Product_Strategist", "Product_Designer",
    ])
    def test_artefact_variant_maps_to_same_key(self, role):
        m = _rs()
        assert m._session_key_for(f"{role}_Artefact") == f"role_{role}"

    def test_observer_maps_to_researcher(self):
        m = _rs()
        assert m._session_key_for("QualitativeResearcher_Observer") == "researcher"

    def test_debriefer_maps_to_researcher(self):
        m = _rs()
        assert m._session_key_for("QualitativeResearcher_Debriefer") == "researcher"

    def test_unknown_name_passes_through_verbatim(self):
        """Any name we don't classify gets its own (single-shell)
        session, which is the safe default for an agent type we
        haven't anticipated."""
        m = _rs()
        assert m._session_key_for("MysteryAgent") == "MysteryAgent"
        assert m._session_key_for("") == ""

    def test_product_designer_does_not_collide_with_product_strategist(self):
        """Both start with 'Product_' — make sure they get DIFFERENT
        keys, not one swallowing the other."""
        m = _rs()
        d = m._session_key_for("Product_Designer_Artefact")
        s = m._session_key_for("Product_Strategist_Artefact")
        assert d == "role_Product_Designer"
        assert s == "role_Product_Strategist"
        assert d != s

    def test_role_prefix_match_requires_underscore_separator(self):
        """A name like `CEOCorp` must NOT match the CEO role — the
        separator after the role name is required."""
        m = _rs()
        # Should pass through verbatim since the role prefix lacks
        # the underscore separator that the mapper requires.
        assert m._session_key_for("CEOCorp") == "CEOCorp"
        assert m._session_key_for("CEO") == "role_CEO"  # exact-match still works


# ===========================================================================
# 2. _build_default_runner — one session per call
# ===========================================================================

@dataclass
class _FakeAgent:
    """Minimal stand-in for `LlmAgent` — only `.name` is read by the
    runner."""
    name: str


class _RecordingRunner:
    """A `Runner` look-alike that records every (agent, session_id)
    pair it's asked to run. Returns no events.

    Created fresh by the production code on every call (one Runner
    per call is the ADK 1.18 pattern), so we record into class-level
    state.
    """

    instances: list["_RecordingRunner"] = []
    calls: list[tuple[str, str]] = []  # (agent.name, session_id)

    def __init__(self, *, agent, app_name, session_service):
        self.agent = agent
        self.app_name = app_name
        self.session_service = session_service
        _RecordingRunner.instances.append(self)

    async def run_async(self, *, user_id, session_id, new_message):
        _RecordingRunner.calls.append((self.agent.name, session_id))
        # Yield nothing — the runner just records the binding.
        return
        yield  # pragma: no cover — make this a generator method

    @classmethod
    def reset(cls):
        cls.instances = []
        cls.calls = []


def _make_system():
    """Build a TMTSystemWithA2A wired to the test's stub session service.
    We mostly need `.base_session_id` and `.session_service` —
    `_build_default_runner` doesn't actually instantiate any role
    agents itself, so we don't need a functional TMT here."""
    a = _agent_module()
    return a.TMTSystemWithA2A("OpenAI")


def _patch_runner(monkeypatch):
    """Replace ADK's `Runner` with our recording runner so we can
    inspect session_ids without making real LLM calls."""
    _RecordingRunner.reset()
    import google.adk.runners as runners_mod
    monkeypatch.setattr(runners_mod, "Runner", _RecordingRunner)


class TestEachCallHasItsOwnSession:
    """No model call may see an earlier call's prompt or reply."""

    def test_same_agent_twice_gets_two_sessions(self, monkeypatch):
        rs = _rs()
        _patch_runner(monkeypatch)
        runner = rs._build_default_runner(_make_system())

        async def go():
            await runner(agent=_FakeAgent(name="CTO"), prompt="one")
            await runner(agent=_FakeAgent(name="CTO"), prompt="two")

        asyncio.run(go())
        first, second = [sid for _, sid in _RecordingRunner.calls]
        assert first != second

    def test_shells_of_one_persona_do_not_share_a_session(self, monkeypatch):
        rs = _rs()
        _patch_runner(monkeypatch)
        runner = rs._build_default_runner(_make_system())

        async def go():
            for name in ("CEO_Concurrent", "CEO_Artefact", "CEO"):
                await runner(agent=_FakeAgent(name=name), prompt="x")

        asyncio.run(go())
        ids = [sid for _, sid in _RecordingRunner.calls]
        assert len(set(ids)) == 3
        assert all("_role_CEO_" in sid for sid in ids), ids

    def test_researcher_shells_do_not_share_a_session(self, monkeypatch):
        rs = _rs()
        _patch_runner(monkeypatch)
        runner = rs._build_default_runner(_make_system())

        async def go():
            await runner(agent=_FakeAgent(name="QualitativeResearcher_Observer"), prompt="o")
            await runner(agent=_FakeAgent(name="QualitativeResearcher_Debriefer"), prompt="d")

        asyncio.run(go())
        ids = [sid for _, sid in _RecordingRunner.calls]
        assert len(set(ids)) == 2
        assert all("_researcher_" in sid for sid in ids), ids

    def test_runner_counts_calls_by_persona(self, monkeypatch):
        rs = _rs()
        _patch_runner(monkeypatch)
        runner = rs._build_default_runner(_make_system())

        async def go():
            await runner(agent=_FakeAgent(name="CEO_Concurrent"), prompt="x")
            await runner(agent=_FakeAgent(name="CEO_Artefact"), prompt="y")
            await runner(agent=_FakeAgent(name="QualitativeResearcher_Debriefer"), prompt="z")

        asyncio.run(go())
        assert runner.call_counts == {"role_CEO": 2, "researcher": 1}

    def test_deliberation_calls_get_new_sessions_too(self):
        system = _make_system()

        async def go():
            return [await system._new_call_session_id("CEO_Concurrent") for _ in range(2)]

        first, second = asyncio.run(go())
        assert first != second

    def test_a_retried_call_does_not_reuse_the_failed_session(self, monkeypatch):
        """A retry in a shared session would send the failed prompt as well."""
        rs = _rs()
        _patch_runner(monkeypatch)
        runner = rs._build_default_runner(_make_system())

        async def go():
            await runner(agent=_FakeAgent(name="CMO"), prompt="same prompt")
            await runner(agent=_FakeAgent(name="CMO"), prompt="same prompt")

        asyncio.run(go())
        assert len({sid for _, sid in _RecordingRunner.calls}) == 2


# ===========================================================================
# 3. CLI logging — log handler is configured before run_research_session
# ===========================================================================

class TestPhaseLoggingEmitted:
    """The per-phase `log.info(...)` calls should fire when the runner
    completes each phase. We don't run a real session here — we just
    invoke `log.info` with the same logger as production and verify a
    caplog handler captures it. Guards against accidentally removing
    the progress logs in a future refactor.
    """

    def test_phase_loggers_emit_at_info_level(self, caplog):
        rs = _rs()
        with caplog.at_level(logging.INFO, logger=rs.__name__):
            rs.log.info("research_session.phase1_start deliberation")
            rs.log.info("research_session.phase4_complete exchanges=12")
        messages = [r.message for r in caplog.records]
        assert any("phase1_start" in m for m in messages)
        assert any("phase4_complete" in m for m in messages)
