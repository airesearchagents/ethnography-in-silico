"""Tokens (small pieces of text that models read and write and that the companies
supplying them charge by) each model call (one prompt sent to a model and one reply
back) used, so a run (one complete simulated meeting and debrief) can report what it
used and cost.

Run folders once recorded no token counts, so cost could only be worked out
afterwards from Google's monitoring, and cached tokens (repeated input text the provider
charges less for) not at all. The model's own `usage_metadata` (the counts returned
with each reply) gives input (text sent), cached and output (text returned) tokens
for every response.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

LONG_CONTEXT_TOKENS = 200_000

# USD per million tokens, from the pricing page of Google's Vertex AI (its paid cloud
# service offering models) on 31 Oct 2026, as (up to 200K, meaning 200,000, input
# tokens, above 200K). Above 200K the whole request moves to the
# higher rates. Other models get token counts but no cost.
LIST_PRICES: Dict[str, Dict[str, tuple]] = {
    "gemini-3.1-pro-preview": {
        "input": (2.00, 4.00),
        "cached": (0.20, 0.40),
        "output": (12.00, 18.00),
    },
}


def _model_name(agent: Any) -> str:
    spec = getattr(agent, "model", None)
    return spec if isinstance(spec, str) else str(getattr(spec, "model", spec) or "")


def list_cost(model: str, input_tokens: int, cached: int, output: int) -> Optional[float]:
    """Cost of one call at list prices (a provider's published rates), or
    None for a model not in the table."""
    prices = LIST_PRICES.get(model)
    if prices is None:
        return None
    tier = 1 if input_tokens > LONG_CONTEXT_TOKENS else 0
    fresh = max(0, input_tokens - cached)
    return (
        fresh * prices["input"][tier]
        + cached * prices["cached"][tier]
        + output * prices["output"][tier]
    ) / 1_000_000


class UsageLog:
    """One record per model response. `phase` (a numbered stage of the run) is set by the
    session (here, the run) as it moves on."""

    def __init__(self) -> None:
        self.phase = "setup"
        self.calls: List[Dict[str, Any]] = []

    def record(self, agent: Any, usage: Any) -> None:
        if usage is None:
            return
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        cached = getattr(usage, "cached_content_token_count", 0) or 0
        # Google bills reasoning (working-out text some models produce before replying) at
        # the output rate.
        output = (getattr(usage, "candidates_token_count", 0) or 0) + (
            getattr(usage, "thoughts_token_count", 0) or 0
        )
        model = _model_name(agent)
        self.calls.append({
            "phase": self.phase,
            "agent": getattr(agent, "name", ""),
            "model": model,
            "input_tokens": input_tokens,
            "cached_tokens": cached,
            "output_tokens": output,
            "list_cost_usd": list_cost(model, input_tokens, cached, output),
        })

    def _totals(self, calls: List[Dict[str, Any]]) -> Dict[str, Any]:
        costs = [c["list_cost_usd"] for c in calls]
        return {
            "calls": len(calls),
            "input_tokens": sum(c["input_tokens"] for c in calls),
            "cached_tokens": sum(c["cached_tokens"] for c in calls),
            "output_tokens": sum(c["output_tokens"] for c in calls),
            "largest_call_input_tokens": max((c["input_tokens"] for c in calls), default=0),
            "calls_over_200k": sum(c["input_tokens"] > LONG_CONTEXT_TOKENS for c in calls),
            "list_cost_usd": (
                round(sum(costs), 2) if costs and all(c is not None for c in costs) else None
            ),
        }

    def summary(self) -> Dict[str, Any]:
        phases = {}
        for call in self.calls:
            phases.setdefault(call["phase"], []).append(call)
        return {
            **self._totals(self.calls),
            "by_phase": {name: self._totals(calls) for name, calls in phases.items()},
        }

    def write_jsonl(self, path: Path) -> None:
        path.write_text("".join(json.dumps(call) + "\n" for call in self.calls))
