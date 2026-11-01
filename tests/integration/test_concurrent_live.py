"""Live verifier for DiscussionMode.CONCURRENT.

Targeted, cheap (~£0.10-0.20), ~5-10 minutes. Runs one TMT
deliberation in CONCURRENT mode against Gemini Flash and dumps:

  - The shared transcript (with ASK/ANSWER markers).
  - Each role's private scratchpad.
  - Each role's working draft.
  - The DirectedMessage history (whether ASKs were answered, NO ANSWER
    markers injected, etc.).
  - Per-role action counts + finished_reason.

What "success" looks like
-------------------------
- More than one role authored each public utterance class
  (SPEAK, ASK_PUBLIC_ECHO, ANSWER_PUBLIC) — i.e. discussion is
  non-deterministic, not CEO-only.
- At least one role's private scratchpad is non-empty AND meaningfully
  different from what they said publicly.
- At least one ASK → ANSWER round-trip completed (or [NO ANSWER]
  injected, demonstrating the deadlock safety net).
- All six roles reached either DONE or action-cap.
- Wall clock under max_wall_clock_seconds.

Usage
-----
    GOOGLE_API_KEY=… python3 verify_concurrent.py

Cost is bounded by `max_actions_per_role` (15) × 6 roles + monitor.
Worst case ≈ 90 LLM calls on Gemini Flash ≈ £0.15-£0.25.
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
from orchestrator.concurrent_mode import ConcurrentConfig  # noqa: E402
from orchestrator.deliberation import (  # noqa: E402
    DeliberationConfig,
    DiscussionMode,
)

COMPANY = "OpenAI"
INDUSTRY = "Dynamic"
PRODUCT = "Novel"

PRODUCT_DESCRIPTION = (
    "Next-generation multimodal AI model with advanced reasoning capabilities"
)
STRATEGIC_QUESTION = (
    "Should we release this model with open weights, as a closed API, "
    "or with a tiered hybrid? Work concurrently — each of you on your "
    "own piece, asking each other for specific inputs as you need them, "
    "and converging on a recommendation when your draft is ready."
)


def _patch_role_models(system: TMTSystemWithA2A) -> None:
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

    print(f"=== verify_concurrent: {COMPANY} / {INDUSTRY} / {PRODUCT} ===")
    print(f"Model: {SMOKE_MODEL}\n")

    system = TMTSystemWithA2A(
        company=COMPANY,
        current_year=2030,
        industry_context=INDUSTRY,
        product_type=PRODUCT,
    )
    _patch_role_models(system)

    config = DeliberationConfig(
        discussion_mode=DiscussionMode.CONCURRENT,
        concurrent=ConcurrentConfig(
            max_actions_per_role=30,           # full default
            max_wall_clock_seconds=30 * 60,    # 30 min cap (allows for retry sleeps)
            stale_question_threshold=3,
            poll_interval_seconds=0.5,
        ),
    )

    print("Calling run_strategic_discussion (CONCURRENT)...")
    result = await system.run_strategic_discussion(
        product_description=PRODUCT_DESCRIPTION,
        strategic_question=STRATEGIC_QUESTION,
        deliberation_config=config,
    )

    print(f"\n[Result] discussion_mode={result['discussion_mode']} "
          f"ended_reason={result['ended_reason']} "
          f"rounds_completed={result['rounds_completed']} "
          f"events={result['events_count']}")

    # Inspect the SharedState stashed on the system.
    shared = getattr(system, "_last_concurrent_shared_state", None)
    if shared is None:
        print("⚠ No concurrent SharedState found on system. Aborting analysis.")
        return

    states = await shared.snapshot_all_role_states()
    transcript = await shared.snapshot_transcript()

    print("\nTranscript breakdown by author and kind:")
    authors = Counter(e.role for e in transcript)
    kinds = Counter(e.kind for e in transcript)
    for author, n in authors.most_common():
        print(f"  {author}: {n}")
    print(f"  kinds: {dict(kinds)}")

    print("\nPer-role state:")
    for role, rs in states.items():
        notes = len(rs.scratchpad)
        draft_len = len(rs.draft)
        inbox_remaining = len(rs.inbox)
        print(
            f"  {role}: action_count={rs.action_count} "
            f"done={rs.done} reason='{rs.finished_reason}' "
            f"scratchpad_notes={notes} draft_chars={draft_len} "
            f"inbox_remaining={inbox_remaining}"
        )

    # Q&A summary.
    asks = [e for e in transcript if e.kind == "ask_public_echo"]
    answers = [e for e in transcript if e.kind == "answer_public"]
    print(f"\nQ&A: {len(asks)} public ASKs, {len(answers)} public ANSWERs.")
    for a in asks[:5]:
        print(f"  ASK: {a.role} → {a.addressed_to}: {a.text[:100]}")
    print("...")

    # NO ANSWER markers.
    no_answer = sum(
        1
        for rs in states.values()
        for m in rs.inbox
        if m.kind == "ANSWER" and m.sender == "system" and "[NO ANSWER" in m.text
    )
    print(f"\n[NO ANSWER] markers injected: {no_answer}")

    # Dump everything.
    out_path = Path("results/smoke/verify_concurrent_log.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "result_dict": {
            k: v for k, v in result.items()
            if k not in {"conversation_log"}  # already dumped via shared
        },
        "transcript": [e.model_dump() for e in transcript],
        "role_states": {role: rs.model_dump() for role, rs in states.items()},
    }
    out_path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nFull dump written to: {out_path}")



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
