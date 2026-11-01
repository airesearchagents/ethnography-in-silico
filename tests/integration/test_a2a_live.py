"""Live verifier for the rewritten `agent.py` A2A bidirectional delegation.

Targeted, cheap (~£0.01-0.02), ~2-3 minutes. Calls
`TMTSystemWithA2A.run_strategic_discussion(...)` on ONE cell and prints
the conversation_log so we can see whether ADK's `transfer_to_agent`
machinery is firing.

What "success" looks like
-------------------------
The deliberation log should contain at least one event of `kind=
"delegation"` OR multiple consecutive events authored by different
agents (CEO → CTO → CEO → ...). If every event is authored by the CEO,
the delegation pattern isn't working.

Usage
-----
    GOOGLE_API_KEY=… python3 verify_a2a.py

Optional env vars (same as smoke_test.py):
  SMOKE_MODEL              defaults to gemini-2.5-flash
  TMT_GEMINI_PRO_MODEL     defaults to SMOKE_MODEL
  TMT_GEMINI_FLASH_MODEL   defaults to SMOKE_MODEL

This file is research/diagnostic only; it is NOT imported by any test.
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

COMPANY = "OpenAI"
INDUSTRY = "Dynamic"
PRODUCT = "Novel"

# Smaller / simpler than smoke_test.py's question to keep the run short.
PRODUCT_DESCRIPTION = (
    "Next-generation multimodal AI model with advanced reasoning capabilities"
)
STRATEGIC_QUESTION = (
    "Should we release this model with open weights or as a closed API? "
    "Consult the team — get input from technical, operational, and market "
    "perspectives — then make the call."
)


def _patch_role_models(system: TMTSystemWithA2A) -> None:
    """Override hardcoded gemini-2.0-flash on every base role agent.

    (Task A2 will move role factories to providers.get_model() and
    remove this workaround.)
    """
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

    print(f"=== verify_a2a: {COMPANY} / {INDUSTRY} / {PRODUCT} ===")
    print(f"Model: {SMOKE_MODEL}\n")

    system = TMTSystemWithA2A(
        company=COMPANY,
        current_year=2030,
        industry_context=INDUSTRY,
        product_type=PRODUCT,
    )
    _patch_role_models(system)

    print("Calling run_strategic_discussion...")
    result = await system.run_strategic_discussion(
        product_description=PRODUCT_DESCRIPTION,
        strategic_question=STRATEGIC_QUESTION,
    )

    print(f"\nReturned {result['events_count']} events, "
          f"{len(result['conversation_log'])} non-trivial log entries.")
    print(f"CEO synthesis length: {len(result['ceo_decision'])} chars")
    print()

    # Per-author count.
    authors = Counter(e["role"] for e in result["conversation_log"])
    print("Events per author:")
    for author, n in authors.most_common():
        print(f"  {author}: {n}")
    print()

    # Per-kind count.
    kinds = Counter(e["kind"] for e in result["conversation_log"])
    print("Events per kind:")
    for kind, n in kinds.most_common():
        print(f"  {kind}: {n}")
    print()

    delegations = [e for e in result["conversation_log"] if e["kind"] == "delegation"]
    print(f"Delegation events: {len(delegations)}")
    for d in delegations[:5]:
        print(f"  {d['role']} → {d['addressed_to']}: {d['text'][:120]}")
    if len(delegations) > 5:
        print(f"  ... ({len(delegations) - 5} more)")
    print()

    distinct_authors = set(authors.keys())
    if len(distinct_authors) <= 1:
        print("⚠ Only one author across the log — A2A delegation may not have fired.")
    elif len(delegations) == 0 and len(distinct_authors) > 1:
        print("ℹ Multiple authors but no explicit 'delegation' events captured. "
              "Likely the model is producing text-only responses through "
              "transfer_to_agent without emitting a dedicated event class. "
              "Bidirectional transfer is still working if author rotates.")
    else:
        print("✓ A2A bidirectional delegation appears to be working.")

    out_path = Path("results/smoke/verify_a2a_log.json")
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
