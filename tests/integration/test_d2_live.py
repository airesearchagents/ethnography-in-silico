"""Live verifier for the D2 (parallel_then_discuss) deliberation mode.

Targeted, cheap (~£0.05), ~3-5 minutes. Calls
`TMTSystemWithA2A.run_strategic_discussion(...)` with
`discussion_mode=PARALLEL_THEN_DISCUSS` + `time_boxed(max_rounds=3)`
on Gemini Flash and prints the resulting deliberation log structure.

What "success" looks like
-------------------------
- Phase A: exactly 6 events tagged `phase="initial_position"`, one
  per role. Their text was generated in parallel.
- Phase B: per-round events tagged `phase="round_N"`, with mixed roles
  contributing or passing in shuffled order.
- Phase C: exactly 1 event tagged `phase="convergence"`, authored by
  the CEO.
- `ended_reason == "max_rounds"` (we set max_rounds=3 with time_boxed).
- `rounds_completed == 3`.

Usage
-----
    GOOGLE_API_KEY=… python3 verify_d2.py

This file is diagnostic only; it is NOT imported by any test.
"""

from __future__ import annotations

import asyncio
import json
import os
import pytest
import sys
import warnings
from collections import Counter
from pathlib import Path

warnings.filterwarnings("ignore")

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "0")
SMOKE_MODEL = os.environ.get("SMOKE_MODEL", "gemini-2.5-flash")
# NOTE: TMT_GEMINI_PRO_MODEL / TMT_GEMINI_FLASH_MODEL are set inside
# `main()` rather than at module import time, because pytest imports
# this module during collection and would otherwise leak the SMOKE_MODEL
# value into other tests' env (breaking per-role override tests).

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agent import TMTSystemWithA2A  # noqa: E402
from orchestrator.deliberation import (  # noqa: E402
    ConvergenceConfig,
    ConvergenceMode,
    DeliberationConfig,
    DiscussionMode,
)

COMPANY = "OpenAI"
INDUSTRY = "Dynamic"
PRODUCT = "Novel"

# A scoped strategic question — enough material for ~3 discussion
# rounds but not so broad that the deliberation balloons.
PRODUCT_DESCRIPTION = (
    "Next-generation multimodal AI model with advanced reasoning capabilities"
)
STRATEGIC_QUESTION = (
    "Should we release this model with open weights, as a closed API, or "
    "with a tiered hybrid? Discuss as a team — let any of you speak, push "
    "back, qualify each other — then converge on a recommendation."
)


def _patch_role_models(system: TMTSystemWithA2A) -> None:
    """Override hardcoded gemini-2.0-flash on every base role agent."""
    for agent in system.agents.values():
        agent.model = SMOKE_MODEL  # type: ignore[assignment]


async def main() -> None:
    if not os.environ.get("GOOGLE_API_KEY"):
        print("ERROR: GOOGLE_API_KEY not set")
        sys.exit(1)

    # Apply the SMOKE_MODEL override now (deferred from module load — see
    # note above about pytest collection pollution).
    os.environ.setdefault("TMT_GEMINI_PRO_MODEL", SMOKE_MODEL)
    os.environ.setdefault("TMT_GEMINI_FLASH_MODEL", SMOKE_MODEL)

    print(f"=== verify_d2: {COMPANY} / {INDUSTRY} / {PRODUCT} ===")
    print(f"Model: {SMOKE_MODEL}\n")

    system = TMTSystemWithA2A(
        company=COMPANY,
        current_year=2030,
        industry_context=INDUSTRY,
        product_type=PRODUCT,
    )
    _patch_role_models(system)

    config = DeliberationConfig(
        discussion_mode=DiscussionMode.PARALLEL_THEN_DISCUSS,
        convergence=ConvergenceConfig(
            mode=ConvergenceMode.TIME_BOXED,
            max_rounds=3,
        ),
    )

    print("Calling run_strategic_discussion (D2, time_boxed N=3)...")
    result = await system.run_strategic_discussion(
        product_description=PRODUCT_DESCRIPTION,
        strategic_question=STRATEGIC_QUESTION,
        deliberation_config=config,
    )

    print(f"\n[Result] discussion_mode={result['discussion_mode']} "
          f"convergence_mode={result['convergence_mode']} "
          f"rounds_completed={result['rounds_completed']} "
          f"ended_reason={result['ended_reason']}")
    print(f"[Result] events_count={result['events_count']} "
          f"ceo_synthesis_chars={len(result['ceo_decision'])}")

    # Group events by phase for inspection.
    by_phase: dict[str, list] = {}
    for e in result["conversation_log"]:
        by_phase.setdefault(e.get("phase") or "(none)", []).append(e)
    print("\nEvents per phase:")
    for phase in sorted(by_phase):
        counts = Counter(e["role"] for e in by_phase[phase])
        roles_summary = ", ".join(f"{r}×{n}" for r, n in counts.most_common())
        print(f"  {phase}: {len(by_phase[phase])} events  [{roles_summary}]")

    # Pass detection per round.
    print("\nPass markers per round:")
    rounds = sorted(p for p in by_phase if p.startswith("round_"))
    for r in rounds:
        passes = [e for e in by_phase[r] if e["text"].strip() == "[PASS]"]
        contribs = [e for e in by_phase[r] if e["text"].strip() != "[PASS]"]
        print(f"  {r}: {len(contribs)} contributions, {len(passes)} passes")

    # First 200 chars of the CEO synthesis.
    print("\nCEO synthesis (preview):")
    print(f"  {result['ceo_decision'][:300]}...")

    # Save the full result.
    out_path = Path("results/smoke/verify_d2_log.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, default=str))
    print(f"\nFull log written to: {out_path}")



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
