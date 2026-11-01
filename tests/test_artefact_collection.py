"""Tests for the per-role artefact collection phase.

Covers:
- The StrategicArtefact / ArtefactBundle schemas round-trip.
- `collect_role_artefacts` calls the injected runner once per role,
  with a prompt that mentions the role's framing.
- Roles that emit valid JSON are captured in the bundle; roles that
  emit malformed JSON are skipped without aborting the whole bundle.
- `ArtefactBundle.by_role` returns the right artefact.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from dataclasses import dataclass

import pytest

PKG = "open-innovation-strategy"


def _artefact_schemas():
    return importlib.import_module(f"{PKG}.roles.artefact_schemas")


def _artefact_collection():
    return importlib.import_module(f"{PKG}.orchestrator.artefact_collection")


def _data_capture():
    return importlib.import_module(f"{PKG}.data_capture")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ROLES = ("CEO", "CTO", "COO", "CMO", "Product_Strategist", "Product_Designer")


@dataclass
class _StubAgent:
    name: str
    instruction: str = "Stub instruction."
    model: str = "stub-model"


def _make_log():
    dc = _data_capture()
    return dc.DeliberationLog(
        company="OpenAI",
        industry_context="Dynamic",
        product_type="Novel",
    )


def _valid_artefact_json(role: str) -> str:
    """A minimum valid StrategicArtefact for `role`, as JSON."""
    return json.dumps({
        "role": role,
        "company": "OpenAI",
        "industry_context": "Dynamic",
        "product_type": "Novel",
        "title": f"{role} doc",
        "key_challenges": ["c1"],
        "main_decisions": ["d1"],
        "key_tensions": ["t1"],
        "body": "# heading\nMarkdown body.",
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestArtefactSchema:
    def test_minimum_valid(self):
        s = _artefact_schemas()
        a = s.StrategicArtefact(
            role="CEO",
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            title="Doc",
            key_challenges=["c"],
            main_decisions=["d"],
            key_tensions=["t"],
            body="body",
        )
        assert a.role == "CEO"

    def test_roundtrip(self):
        s = _artefact_schemas()
        original = s.StrategicArtefact.model_validate_json(_valid_artefact_json("CEO"))
        blob = original.model_dump_json()
        revived = s.StrategicArtefact.model_validate_json(blob)
        assert revived.title == "CEO doc"

    def test_bundle_by_role(self):
        s = _artefact_schemas()
        a_ceo = s.StrategicArtefact.model_validate_json(_valid_artefact_json("CEO"))
        a_cto = s.StrategicArtefact.model_validate_json(_valid_artefact_json("CTO"))
        bundle = s.ArtefactBundle(
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            artefacts=[a_ceo, a_cto],
        )
        assert bundle.by_role("CEO").title == "CEO doc"  # type: ignore[union-attr]
        assert bundle.by_role("COO") is None


class TestCollectRoleArtefacts:
    def test_calls_runner_once_per_role(self):
        ac = _artefact_collection()
        calls: list[str] = []

        async def fake_runner(*, agent, prompt):
            calls.append(agent.name)
            # Each artefact agent is named '<Role>_Artefact'.
            role = agent.name.replace("_Artefact", "")
            return _valid_artefact_json(role)

        role_agents = {r: _StubAgent(name=r) for r in ROLES}

        bundle = asyncio.run(ac.collect_role_artefacts(
            role_agents=role_agents,
            deliberation_log=_make_log(),
            ceo_final_synthesis="The CEO's closing statement.",
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            run_agent=fake_runner,
        ))

        assert len(bundle.artefacts) == 6
        # Every role was called.
        assert sorted(set(calls)) == sorted([f"{r}_Artefact" for r in ROLES])
        # Each artefact is the right role.
        roles_in_bundle = sorted(a.role for a in bundle.artefacts)
        assert roles_in_bundle == sorted(ROLES)

    def test_malformed_json_role_is_skipped_others_retained(self):
        ac = _artefact_collection()

        async def fake_runner(*, agent, prompt):
            role = agent.name.replace("_Artefact", "")
            if role == "COO":
                return "not valid json"
            return _valid_artefact_json(role)

        role_agents = {r: _StubAgent(name=r) for r in ROLES}

        bundle = asyncio.run(ac.collect_role_artefacts(
            role_agents=role_agents,
            deliberation_log=_make_log(),
            ceo_final_synthesis="Closing.",
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            run_agent=fake_runner,
        ))

        # 5 of 6 roles succeed; COO is silently skipped.
        assert len(bundle.artefacts) == 5
        assert bundle.by_role("COO") is None
        assert bundle.by_role("CEO") is not None

    def test_runner_receives_role_framing(self):
        ac = _artefact_collection()
        prompts: dict[str, str] = {}

        async def fake_runner(*, agent, prompt):
            role = agent.name.replace("_Artefact", "")
            prompts[role] = prompt
            return _valid_artefact_json(role)

        role_agents = {r: _StubAgent(name=r) for r in ROLES}

        asyncio.run(ac.collect_role_artefacts(
            role_agents=role_agents,
            deliberation_log=_make_log(),
            ceo_final_synthesis="Closing.",
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            run_agent=fake_runner,
        ))

        # The CEO prompt mentions 'CEO of OpenAI'; the CTO prompt mentions
        # 'technology strategy'; the CMO prompt mentions 'GTM' or 'marketing'.
        assert "CEO of OpenAI" in prompts["CEO"]
        assert "tech" in prompts["CTO"].lower() or "technology" in prompts["CTO"].lower()
        assert "market" in prompts["CMO"].lower()

    def test_returns_bundle_even_with_no_successful_artefacts(self):
        ac = _artefact_collection()

        async def always_fail(*, agent, prompt):
            return "garbage"

        bundle = asyncio.run(ac.collect_role_artefacts(
            role_agents={r: _StubAgent(name=r) for r in ROLES},
            deliberation_log=_make_log(),
            ceo_final_synthesis="Closing.",
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            run_agent=always_fail,
        ))
        assert bundle.artefacts == []
        # Company / context still on the bundle so downstream consumers
        # don't blow up.
        assert bundle.company == "OpenAI"


class TestPhase2TransientErrorResilience:
    """Phase 2 was losing artefacts to transient 429s during the
    Meta-2032 cell runs (Product_Designer + CMO in two sequential
    attempts). The fix routes artefact-collection LLM calls through
    `llm_retry.safe_run` so transient 429 / 5xx / asyncio.TimeoutError
    failures get retried with backoff instead of dropping the role's
    artefact.
    """

    def test_artefact_collection_retries_transient_429(self):
        """A role that 429s on its first try, then succeeds on retry,
        produces a valid artefact. The bundle still has all 6 entries."""
        ac = _artefact_collection()
        call_counts: dict[str, int] = {r: 0 for r in ROLES}

        async def flaky_then_ok(*, agent, prompt):
            role = agent.name.replace("_Artefact", "")
            call_counts[role] += 1
            # CMO 429s on first try (with a 0s hint so the test isn't slow),
            # succeeds on retry. All other roles succeed first time.
            if role == "CMO" and call_counts[role] == 1:
                raise RuntimeError(
                    "429 RESOURCE_EXHAUSTED 'retryDelay': '0s'"
                )
            return _valid_artefact_json(role)

        bundle = asyncio.run(ac.collect_role_artefacts(
            role_agents={r: _StubAgent(name=r) for r in ROLES},
            deliberation_log=_make_log(),
            ceo_final_synthesis="Closing.",
            company="Meta",
            industry_context="Dynamic",
            product_type="Novel",
            run_agent=flaky_then_ok,
        ))

        # All 6 roles produce artefacts — CMO survived the retry.
        assert len(bundle.artefacts) == 6
        assert bundle.by_role("CMO") is not None
        # CMO required two runner calls; others required one.
        assert call_counts["CMO"] == 2
        for r in ROLES:
            if r != "CMO":
                assert call_counts[r] == 1, r

    def test_artefact_collection_skips_role_on_non_transient(self):
        """Non-transient errors (auth, schema) still result in the role
        being skipped — same behaviour as before, just routed through
        safe_run's None-return path now."""
        ac = _artefact_collection()

        async def auth_fail_for_coo(*, agent, prompt):
            role = agent.name.replace("_Artefact", "")
            if role == "COO":
                raise RuntimeError("401 AuthenticationError invalid key")
            return _valid_artefact_json(role)

        bundle = asyncio.run(ac.collect_role_artefacts(
            role_agents={r: _StubAgent(name=r) for r in ROLES},
            deliberation_log=_make_log(),
            ceo_final_synthesis="Closing.",
            company="Meta",
            industry_context="Dynamic",
            product_type="Novel",
            run_agent=auth_fail_for_coo,
        ))

        # 5 of 6 roles succeed; COO is silently skipped (non-transient).
        assert len(bundle.artefacts) == 5
        assert bundle.by_role("COO") is None
        assert bundle.by_role("CEO") is not None

    def test_artefact_collection_retries_on_asyncio_timeout(self):
        """The new per-call wait_for timeout converts a hung HTTP call
        into asyncio.TimeoutError, which safe_run must classify as
        transient and retry."""
        import asyncio as _asyncio_mod
        ac = _artefact_collection()
        call_counts: dict[str, int] = {r: 0 for r in ROLES}

        async def timeout_once(*, agent, prompt):
            role = agent.name.replace("_Artefact", "")
            call_counts[role] += 1
            if role == "Product_Strategist" and call_counts[role] == 1:
                raise _asyncio_mod.TimeoutError()
            return _valid_artefact_json(role)

        bundle = asyncio.run(ac.collect_role_artefacts(
            role_agents={r: _StubAgent(name=r) for r in ROLES},
            deliberation_log=_make_log(),
            ceo_final_synthesis="Closing.",
            company="Meta",
            industry_context="Dynamic",
            product_type="Novel",
            run_agent=timeout_once,
        ))

        assert len(bundle.artefacts) == 6
        assert bundle.by_role("Product_Strategist") is not None
        assert call_counts["Product_Strategist"] == 2
