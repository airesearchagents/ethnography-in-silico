"""Tests for memory / scratchpad / shared-state isolation.

  - `TMTSystemWithA2A._get_role_session_id` — used by the legacy
    CEO-led path only: stable per role, distinct across roles.
  - `_role_session_ids` cache — doesn't leak between instances.
  - `_last_concurrent_shared_state` — populated after a CONCURRENT
    deliberation; lets the researcher reach into per-role
    scratchpads.
  - Per-role drafts are private (not just scratchpads).
  - Scratchpad rendering helpers in `run_research_session` and
    `orchestrator.panel_debriefing` produce the privileged-access
    block for the researcher and empty otherwise.

Tests are stub-based — no live LLM, no real ADK runtime.
"""

from __future__ import annotations

import importlib

import pytest

PKG = "open-innovation-strategy"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _agent_module():
    return importlib.import_module(f"{PKG}.agent")


def _concurrent_module():
    return importlib.import_module(f"{PKG}.orchestrator.concurrent_mode")


def _panel_debriefing_module():
    return importlib.import_module(f"{PKG}.orchestrator.panel_debriefing")


def _run_research_session_module():
    return importlib.import_module(f"{PKG}.run_research_session")


def _make_system(company: str = "OpenAI"):
    agent_mod = _agent_module()
    return agent_mod.TMTSystemWithA2A(
        company=company,
        current_year=2030,
        industry_context="Dynamic",
        product_type="Novel",
    )


async def _amake_shared_state(with_drafts: bool = True, with_notes: bool = True):
    """Build a populated SharedState INSIDE an asyncio coroutine.

    `asyncio.Lock()` (created in SharedState.__init__) needs a running
    event loop on Python 3.9, so we construct inside `asyncio.run`.
    """
    c = _concurrent_module()
    roles = ["CEO", "CTO", "COO", "CMO", "Product_Strategist", "Product_Designer"]
    ss = c.SharedState(roles=roles)
    if with_notes:
        ss.role_states["CEO"].scratchpad = ["watch CTO on safety"]
        ss.role_states["CTO"].scratchpad = ["CMO seemed cautious"]
    if with_drafts:
        ss.role_states["CEO"].draft = "# CEO draft\nCompany strategy here."
        ss.role_states["CTO"].draft = "# CTO draft\nTech strategy here."
    return ss


def _make_shared_state(with_drafts: bool = True, with_notes: bool = True):
    """Sync helper that wraps the async constructor in asyncio.run.

    Returns a SharedState whose lock is bound to a now-closed loop —
    fine for read-only sync inspection of the role_states / transcript
    fields, but the snapshot_*() methods should NOT be called from
    sync test code on the returned instance. For those, use
    `_amake_shared_state` inside the same `asyncio.run`.
    """
    import asyncio
    return asyncio.run(_amake_shared_state(with_drafts=with_drafts, with_notes=with_notes))


# ===========================================================================
# 1. _get_role_session_id contract
# ===========================================================================

class TestRoleSessionIDStability:
    """The session ID for a role must be stable across calls in the
    same instance, and distinct between roles. This is the property
    that makes per-role ADK conversation history coherent across all
    four phases of one run."""

    def test_same_role_returns_same_id_across_calls(self):
        import asyncio
        system = _make_system()

        async def go():
            id_a = await system._get_role_session_id("CEO")
            id_b = await system._get_role_session_id("CEO")
            id_c = await system._get_role_session_id("CEO")
            return id_a, id_b, id_c

        id_a, id_b, id_c = asyncio.run(go())
        assert id_a == id_b == id_c

    def test_different_roles_return_distinct_ids(self):
        import asyncio
        system = _make_system()

        async def go():
            ids = {}
            for role in ("CEO", "CTO", "COO", "CMO",
                         "Product_Strategist", "Product_Designer"):
                ids[role] = await system._get_role_session_id(role)
            return ids

        ids = asyncio.run(go())
        assert len(set(ids.values())) == 6, (
            f"Expected 6 distinct session ids, got {len(set(ids.values()))}: {ids}"
        )

    def test_ids_do_not_leak_between_instances(self):
        """Two TMTSystemWithA2A instances must have non-overlapping
        session id pools — each run is hermetic."""
        import asyncio
        sys_a = _make_system("OpenAI")
        sys_b = _make_system("OpenAI")  # same company; different instance.

        async def go():
            id_a = await sys_a._get_role_session_id("CEO")
            id_b = await sys_b._get_role_session_id("CEO")
            return id_a, id_b

        id_a, id_b = asyncio.run(go())
        assert id_a != id_b, (
            "Two TMT systems produced the same session id for CEO — "
            "memory could leak between runs"
        )

    def test_role_session_ids_cache_survives_repeat_calls(self):
        """The internal cache (_role_session_ids dict) should be
        populated after the first lookup."""
        import asyncio
        system = _make_system()
        # Before any call: empty.
        assert system._role_session_ids == {}

        async def go():
            return await system._get_role_session_id("CTO")

        asyncio.run(go())
        assert "CTO" in system._role_session_ids


# ===========================================================================
# 2. _last_concurrent_shared_state hook
# ===========================================================================

class TestLastConcurrentSharedState:
    def test_initialised_to_none(self):
        """Fresh system has no SharedState until a CONCURRENT
        deliberation runs."""
        system = _make_system()
        assert system._last_concurrent_shared_state is None

    def test_attribute_is_writable(self):
        """The post-deliberation hook writes to this attribute; verify
        it can be set + read."""
        system = _make_system()
        ss = _make_shared_state()
        system._last_concurrent_shared_state = ss
        assert system._last_concurrent_shared_state is ss
        # And the SharedState is per-role-isolated.
        assert "watch CTO" in ss.role_states["CEO"].scratchpad[0]
        assert "CMO seemed cautious" in ss.role_states["CTO"].scratchpad[0]


# ===========================================================================
# 3. Per-role drafts are private (not just scratchpads)
# ===========================================================================

class TestDraftIsolation:
    def test_role_draft_visible_only_in_own_role_state(self):
        ss = _make_shared_state(with_drafts=True, with_notes=False)
        # CEO has a draft.
        assert "Company strategy" in ss.role_states["CEO"].draft
        # CTO has its own; doesn't leak.
        assert "Company strategy" not in ss.role_states["CTO"].draft
        assert "Tech strategy" in ss.role_states["CTO"].draft
        # Others empty.
        for role in ("COO", "CMO", "Product_Strategist", "Product_Designer"):
            assert ss.role_states[role].draft == ""

    def test_drafts_do_not_appear_in_shared_transcript(self):
        """DRAFT actions are private — they should never leak into the
        public transcript automatically."""
        ss = _make_shared_state(with_drafts=True, with_notes=False)
        # No transcript writes happened — transcript should be empty.
        assert ss.transcript == []


# ===========================================================================
# 4. Researcher's privileged access to scratchpads
# ===========================================================================

class TestResearcherScratchpadAccess:
    """The observer + debriefer have privileged read access to per-role
    private scratchpads (when CONCURRENT mode produced them).
    Panellists themselves DO NOT see each other's scratchpads."""

    def test_observer_renderer_emits_block_when_state_present(self):
        rrs = _run_research_session_module()
        ss = _make_shared_state(with_drafts=True, with_notes=True)
        block = rrs._render_scratchpads_for_researcher(ss)
        assert block, "Expected a non-empty privileged-access block"
        assert "PRIVATE PER-ROLE SCRATCHPADS" in block
        assert "watch CTO on safety" in block       # CEO's note appears
        assert "CMO seemed cautious" in block       # CTO's note appears
        assert "Company strategy" in block          # CEO's draft preview
        assert "Tech strategy" in block             # CTO's draft preview

    def test_observer_renderer_returns_empty_string_without_state(self):
        rrs = _run_research_session_module()
        assert rrs._render_scratchpads_for_researcher(None) == ""

    def test_debriefer_renderer_emits_block_when_state_present(self):
        pd = _panel_debriefing_module()
        ss = _make_shared_state(with_drafts=True, with_notes=True)
        block = pd._render_scratchpads_for_debriefer(ss)
        assert block, "Expected non-empty privileged-access block"
        assert "PRIVATE PER-ROLE SCRATCHPADS" in block
        # The debriefer block includes the instruction NOT to quote
        # scratchpads verbatim back to the panel.
        assert "do" in block.lower() and (
            "not quote" in block.lower() or "verbatim" in block.lower()
        )

    def test_debriefer_renderer_returns_empty_string_without_state(self):
        pd = _panel_debriefing_module()
        assert pd._render_scratchpads_for_debriefer(None) == ""


# ===========================================================================
# 5. SharedState mutation locking (concurrent-safety smoke)
# ===========================================================================

class TestSharedStateLocking:
    """A minimal sanity check that mutations under asyncio.gather don't
    corrupt state. The existing test suite covers SharedState
    semantics; this just verifies the lock holds under contention."""

    def test_concurrent_scratchpad_writes_are_all_recorded(self):
        import asyncio
        c = _concurrent_module()

        async def go():
            # SharedState() needs an event loop (asyncio.Lock); build it here.
            ss = c.SharedState(roles=["CEO", "CTO"])

            async def writer(role: str, n: int):
                await ss.append_scratchpad(role, f"{role} note {n}")

            # 50 concurrent writes split across 2 roles.
            tasks = []
            for i in range(25):
                tasks.append(writer("CEO", i))
                tasks.append(writer("CTO", i))
            await asyncio.gather(*tasks)
            return await ss.snapshot_all_role_states()

        states = asyncio.run(go())
        assert len(states["CEO"].scratchpad) == 25
        assert len(states["CTO"].scratchpad) == 25
        # And no cross-contamination.
        assert all(n.startswith("CEO") for n in states["CEO"].scratchpad)
        assert all(n.startswith("CTO") for n in states["CTO"].scratchpad)
