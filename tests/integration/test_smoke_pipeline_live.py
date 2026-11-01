"""Live one-run smoke for the four-data-stream pipeline.

Runs OpenAI / Dynamic / Novel end-to-end against Gemini and writes the
four research data streams to `results/smoke/`. Uses a simplified
sequential deliberation (each TMT role responds once, CEO synthesises)
rather than the bidirectional A2A delegation in
`agent.py::TMTSystemWithA2A`. That keeps the smoke fast and isolates
verification to the artefact / observer / debriefer phases.

For verification of the new ADK 1.18 A2A delegation path in agent.py
itself, see the live `run_research_session` route — that exercises the
full TMT system end-to-end.

What this verifies
------------------
1. Each of the six TMT role agents produces a `StrategicArtefact`.
2. The qualitative researcher's observer produces an `ObservationSummary`
   from the deliberation log + the six artefacts.
3. The panel-debriefing orchestrator runs the researcher turn-by-turn,
   routes utterances, collects panel responses, runs the
   forbidden-vocabulary guard, and terminates cleanly.
4. All four JSON outputs land on disk.

Model overrides
---------------
The role files in `roles/*_agent.py` hardcode `model="gemini-2.0-flash"`,
which is not authorised on the current billing project for AI Studio.
This script monkey-patches every agent's `.model` to a working model
ID after construction. The proper fix (task A2) is to thread
`providers.get_model()` through the role factories.

Cost
----
Capped via `MAX_DEBRIEFING_EXCHANGES = 15`. Expected total: < $0.10 on
gemini-2.5-flash.
"""

from __future__ import annotations

import asyncio
import os
import pytest
import sys
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

# Tell ADK to use AI Studio rather than Vertex (key auth path).
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "0")

# Pin every Gemini family member to a model the smoke account has quota
# for, including the observer (normally gemini-2.5-pro). Env-driven so
# we never modify production defaults.
SMOKE_MODEL = os.environ.get("SMOKE_MODEL", "gemini-2.5-flash")
# NOTE: TMT_GEMINI_PRO_MODEL / TMT_GEMINI_FLASH_MODEL are set inside
# `main()` rather than at module import time, because pytest imports
# this module during collection and would otherwise leak the SMOKE_MODEL
# value into other tests' env (breaking per-role override tests).

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Worktree-relative imports — assumes the smoke is run from the
# worktree root (`python3 smoke_test.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from data_capture import DeliberationEvent, DeliberationLog  # noqa: E402
from orchestrator.artefact_collection import collect_role_artefacts  # noqa: E402
from orchestrator.panel_debriefing import (  # noqa: E402
    DEFAULT_RESEARCH_QUESTION,
    run_panel_debriefing,
)
from roles import (  # noqa: E402
    create_ceo_agent,
    create_cmo_agent,
    create_coo_agent,
    create_cto_agent,
    create_debriefer_agent,
    create_observer_agent,
    create_product_designer_agent,
    create_product_strategist_agent,
)
from run_research_session import (  # noqa: E402
    ResearchSessionOutputs,
    _build_observer_prompt,
    _coerce_observation_summary,
)

COMPANY = "OpenAI"
INDUSTRY = "Dynamic"
PRODUCT = "Novel"
MAX_DEBRIEFING_EXCHANGES = 15
APP_NAME = "tmt_smoke"

STRATEGIC_QUESTION = (
    "We need to decide how to release our next-generation multimodal AI "
    "model with advanced reasoning capabilities. Identify and reason "
    "through the most relevant strategic pathways for OpenAI in this "
    "dynamic industry context. Surface trade-offs and propose a "
    "recommended pathway."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_agent_model(agent: LlmAgent, model: str) -> LlmAgent:
    """Override an agent's model. LlmAgent is Pydantic; setattr works."""
    agent.model = model  # type: ignore[assignment]
    return agent


async def _run_one_agent(
    session_service: InMemorySessionService,
    agent: LlmAgent,
    prompt: str,
    user_id: str = "researcher",
) -> str:
    """Run one LlmAgent end-to-end and return the concatenated output text."""
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)
    sess = await session_service.create_session(app_name=APP_NAME, user_id=user_id)
    msg = types.Content(role="user", parts=[types.Part(text=prompt)])
    text_parts: list[str] = []
    async for event in runner.run_async(
        user_id=user_id, session_id=sess.id, new_message=msg
    ):
        if event.content and event.content.parts:
            for p in event.content.parts:
                t = getattr(p, "text", None)
                if t:
                    text_parts.append(t)
    return "\n".join(text_parts).strip()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    if not os.environ.get("GOOGLE_API_KEY"):
        print("ERROR: GOOGLE_API_KEY not set")
        sys.exit(1)

    # Apply the SMOKE_MODEL override now (deferred from module load — see
    # note above about pytest collection pollution).
    os.environ.setdefault("TMT_GEMINI_PRO_MODEL", SMOKE_MODEL)
    os.environ.setdefault("TMT_GEMINI_FLASH_MODEL", SMOKE_MODEL)

    started = datetime.utcnow()
    print(f"=== TMT smoke: {COMPANY} / {INDUSTRY} / {PRODUCT} ===")
    print(f"Model: {SMOKE_MODEL}")
    print(f"Started: {started.isoformat()}\n")

    session_service = InMemorySessionService()

    # Build the six TMT role agents and patch each to the working model.
    panel = {
        "CEO": _patch_agent_model(create_ceo_agent(COMPANY, 2030, INDUSTRY, PRODUCT), SMOKE_MODEL),
        "CTO": _patch_agent_model(create_cto_agent(COMPANY, 2030, INDUSTRY, PRODUCT), SMOKE_MODEL),
        "COO": _patch_agent_model(create_coo_agent(COMPANY, 2030, INDUSTRY, PRODUCT), SMOKE_MODEL),
        "CMO": _patch_agent_model(create_cmo_agent(COMPANY, 2030, INDUSTRY, PRODUCT), SMOKE_MODEL),
        "Product_Strategist": _patch_agent_model(
            create_product_strategist_agent(COMPANY, 2030, INDUSTRY, PRODUCT), SMOKE_MODEL
        ),
        "Product_Designer": _patch_agent_model(
            create_product_designer_agent(COMPANY, 2030, INDUSTRY, PRODUCT), SMOKE_MODEL
        ),
    }

    # -----------------------------------------------------------------
    # Phase 1: simplified deliberation (each role weighs in; CEO synthesises)
    # -----------------------------------------------------------------
    print("[Phase 1] Deliberation")
    log = DeliberationLog(
        company=COMPANY, industry_context=INDUSTRY, product_type=PRODUCT
    )

    for role, agent in panel.items():
        if role == "CEO":
            continue
        print(f"  → {role}")
        text = await _run_one_agent(
            session_service,
            agent,
            (
                f"As the {role} of {COMPANY}, share your perspective on this "
                f"strategic question:\n\n{STRATEGIC_QUESTION}\n\n"
                "Be specific about the decisions you would push for, the "
                "trade-offs you see, and the risks. Keep your response under "
                "250 words."
            ),
        )
        log.events.append(
            DeliberationEvent(
                index=len(log.events), role=role, kind="text", text=text
            )
        )

    print("  → CEO synthesis")
    history = "\n\n".join(f"{e.role}: {e.text}" for e in log.events)
    ceo_text = await _run_one_agent(
        session_service,
        panel["CEO"],
        (
            f"You are the CEO of {COMPANY}. Your team has weighed in on this "
            f"strategic question:\n\n{STRATEGIC_QUESTION}\n\n"
            f"Your team's input:\n{history}\n\n"
            "Synthesise and make the final call. Address the trade-offs "
            "explicitly. Keep your synthesis under 350 words."
        ),
    )
    log.events.append(
        DeliberationEvent(
            index=len(log.events), role="CEO", kind="text", text=ceo_text
        )
    )
    log.finished_at = datetime.utcnow().isoformat()
    print(f"  Deliberation events captured: {len(log.events)}")

    # -----------------------------------------------------------------
    # Runner adaptor used by the orchestrator modules
    # -----------------------------------------------------------------
    async def runner_fn(*, agent, prompt):
        # Patch any artefact-phase wrapper agents created by the
        # orchestrator (they inherit the base agent's model but were
        # constructed via get_model() which honours TMT_GEMINI_FLASH_MODEL,
        # so this is belt-and-braces).
        if isinstance(getattr(agent, "model", None), str):
            agent.model = SMOKE_MODEL  # type: ignore[assignment]
        return await _run_one_agent(session_service, agent, prompt)

    # -----------------------------------------------------------------
    # Phase 2: per-role artefact collection
    # -----------------------------------------------------------------
    print("\n[Phase 2] Artefact collection (6 roles)")
    artefacts = await collect_role_artefacts(
        role_agents=panel,
        deliberation_log=log,
        ceo_final_synthesis=ceo_text,
        company=COMPANY,
        industry_context=INDUSTRY,
        product_type=PRODUCT,
        run_agent=runner_fn,
    )
    produced = sorted(a.role for a in artefacts.artefacts)
    print(f"  Artefacts produced: {len(produced)}/6 — {produced}")

    # -----------------------------------------------------------------
    # Phase 3: silent observer → ObservationSummary
    # -----------------------------------------------------------------
    print("\n[Phase 3] Silent observer")
    observer = _patch_agent_model(
        create_observer_agent(COMPANY, 2030, INDUSTRY, PRODUCT),
        SMOKE_MODEL,
    )
    obs_prompt = _build_observer_prompt(
        company=COMPANY,
        industry_context=INDUSTRY,
        product_type=PRODUCT,
        deliberation_log=log,
        artefacts=artefacts,
    )
    obs_raw = await _run_one_agent(session_service, observer, obs_prompt)
    observation = _coerce_observation_summary(obs_raw)
    if observation is None:
        print("  ✗ Observation summary FAILED to parse")
        print(f"  Raw output (first 400 chars): {obs_raw[:400]}")
    else:
        print(
            f"  Observation summary OK: "
            f"{len(observation.decisions)} decisions, "
            f"{len(observation.components)} components, "
            f"{len(observation.disagreements)} disagreements"
        )

    # -----------------------------------------------------------------
    # Phase 4: panel debriefing
    # -----------------------------------------------------------------
    transcript = None
    if observation is not None:
        print(f"\n[Phase 4] Panel debriefing (cap = {MAX_DEBRIEFING_EXCHANGES} exchanges)")
        transcript = await run_panel_debriefing(
            company=COMPANY,
            observation_summary=observation,
            artefacts=artefacts,
            panel_agents=panel,
            industry_context=INDUSTRY,
            product_type=PRODUCT,
            research_question=DEFAULT_RESEARCH_QUESTION,
            max_exchanges=MAX_DEBRIEFING_EXCHANGES,
            run_agent=runner_fn,
        )
        print(
            f"  Debriefing exchanges: {len(transcript.exchanges)} "
            f"(stopped: {transcript.ended_reason})"
        )
        print(f"  Forbidden-vocab violations: {transcript.forbidden_vocab_violations}")

    # -----------------------------------------------------------------
    # Dump
    # -----------------------------------------------------------------
    out = ResearchSessionOutputs(
        company=COMPANY,
        industry_context=INDUSTRY,
        product_type=PRODUCT,
        research_question=DEFAULT_RESEARCH_QUESTION,
        deliberation_log=log,
        artefacts=artefacts,
        observation_summary=observation,
        debriefing_transcript=transcript,
    )
    out.finished_at = datetime.utcnow().isoformat()

    out_dir = Path("results/smoke")
    paths = out.to_json_files(out_dir)

    print("\n=== Files written ===")
    for name, p in paths.items():
        print(f"  {name}: {p}")

    elapsed = (datetime.utcnow() - started).total_seconds()
    print(f"\nElapsed: {elapsed:.1f}s")



@pytest.mark.live
def test_live_run() -> None:
    """Pytest wrapper around main(). Marked  so it is skipped by
    default; run with `pytest --run-live`. Standalone invocation via
    `python3 <file>` still works through the __main__ block below.
    """
    if not os.environ.get("GOOGLE_API_KEY"):
        pytest.skip("GOOGLE_API_KEY not set")
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
