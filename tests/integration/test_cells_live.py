"""End-to-end live tests across the 2x2 study design.

One test per cell. Each cell pairs a different company with a
different LLM provider so the four tests can run in parallel via
`pytest-xdist` (`-n 4`) without competing for the same provider's
rate-limit budget.

Cells
-----
+--------+-----------+-------------+-------------+-------------+------+
| Cell   | Company   | LLM         | Industry    | Product     | Year |
+--------+-----------+-------------+-------------+-------------+------+
| cell_1 | OpenAI    | gemini_pro  | Dynamic     | Novel       | 2030 |
| cell_2 | Anthropic | claude      | Stable      | Novel       | 2032 |
| cell_3 | Google    | openai      | Dynamic     | Enhancement | 2030 |
| cell_4 | Meta      | ollama      | Stable      | Enhancement | 2032 |
| cell_5 | Mistral   | deepseek    | Dynamic     | Novel       | 2030 |
| cell_6 | xAI       | groq        | Stable      | Enhancement | 2032 |
+--------+-----------+-------------+-------------+-------------+------+

Cells 1-4 are the canonical 2x2 study design (industry x product),
each pinned to a different premium provider. Cells 5-6 are low-cost
provider smoke tests — DeepSeek and Groq — added so the framework
can be exercised cheaply during development and CI without burning
the premium budget. They re-use design combinations from cells 1 and 4
respectively.

The observer is pinned to gemini_pro (per `providers.OBSERVER_PROVIDER`)
so every cell needs `GOOGLE_API_KEY` regardless of the TMT provider —
otherwise Phase 3 fails. Each cell additionally requires its TMT
provider's credentials:

  cell_1:  GOOGLE_API_KEY
  cell_2:  GOOGLE_API_KEY + ANTHROPIC_API_KEY
  cell_3:  GOOGLE_API_KEY + OPENAI_API_KEY
  cell_4:  GOOGLE_API_KEY + Ollama server running with the model pulled
           (default: qwen2.5:9b; override via TMT_OLLAMA_MODEL=ollama_chat/<name>)
  cell_5:  GOOGLE_API_KEY + DEEPSEEK_API_KEY
  cell_6:  GOOGLE_API_KEY + GROQ_API_KEY

A cell whose credentials are missing skips with a clear message rather
than failing.

Usage
-----
Sequential (one-by-one):

    pytest tests/integration/test_cells_live.py --run-live

Parallel (all four at once — requires `pip install pytest-xdist`):

    pytest tests/integration/test_cells_live.py -n 4 --run-live

A single cell:

    pytest tests/integration/test_cells_live.py::test_cell_2_anthropic_claude_stable_novel --run-live

What each test asserts
----------------------
- `run_research_session(...)` completes without exceptions.
- All four phase outputs are populated:
    * deliberation_log has at least one event,
    * artefacts bundle has at least one StrategicArtefact (CEO present),
    * observation_summary is non-empty (at least one decision OR component),
    * debriefing_transcript has at least one exchange.
- `out.errors` is empty (no per-phase failures swallowed).
- `out.finished_at` is set.

Cost ceiling per cell: ~$0.10–$0.40 depending on provider, bounded by
`max_debriefing_exchanges=10`. Ollama is free (local compute).
"""

from __future__ import annotations

import asyncio
import os
import sys
import urllib.error
import urllib.request
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

warnings.filterwarnings("ignore")

# Tell ADK to use AI Studio rather than Vertex for the Gemini-family
# keys. Safe to setdefault at module-load time — does not affect
# non-Gemini providers.
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "0")

# Worktree-relative imports — assumes pytest runs from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


# ===========================================================================
# Cell definitions
# ===========================================================================

@dataclass(frozen=True)
class Cell:
    """One scenario instance for the cross-cell live tests."""

    cell_id: str
    company: str
    provider: str          # 'gemini_pro' | 'claude' | 'openai' | 'ollama' | 'deepseek' | 'groq'
    industry_context: str  # 'Dynamic' | 'Stable'
    product_type: str      # 'Novel' | 'Enhancement'
    current_year: int


CELLS: tuple[Cell, ...] = (
    Cell("cell_1", "OpenAI",    "gemini_pro", "Dynamic", "Novel",       2030),
    Cell("cell_2", "Anthropic", "claude",     "Stable",  "Novel",       2032),
    Cell("cell_3", "Google",    "openai",     "Dynamic", "Enhancement", 2030),
    Cell("cell_4", "Meta",      "ollama",     "Stable",  "Enhancement", 2032),
    Cell("cell_5", "Mistral",   "deepseek",   "Dynamic", "Novel",       2030),
    Cell("cell_6", "xAI",       "groq",       "Stable",  "Enhancement", 2032),
)


# Cost ceiling: smaller exchanges cap keeps each cell ~10 min wall-clock
# even on slow providers. Override per-cell if a study needs more depth.
MAX_DEBRIEFING_EXCHANGES = 10


# ===========================================================================
# Provider availability — drive graceful skips
# ===========================================================================

def _gemini_available() -> bool:
    """Gemini is required for EVERY cell (observer is pinned).

    Accept either AI Studio auth (`GOOGLE_API_KEY`) or Vertex AI auth
    (`GOOGLE_GENAI_USE_VERTEXAI=true` + `GOOGLE_CLOUD_PROJECT` +
    `GOOGLE_CLOUD_LOCATION`). Vertex auth uses Application Default
    Credentials, not an env-var key, so we test for the routing flag
    + project + location rather than for the credentials themselves.
    """
    if os.environ.get("GOOGLE_API_KEY"):
        return True
    vertex_flag = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower()
    if vertex_flag in {"1", "true", "yes", "on"}:
        return bool(
            os.environ.get("GOOGLE_CLOUD_PROJECT")
            and os.environ.get("GOOGLE_CLOUD_LOCATION")
        )
    return False


def _claude_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _openai_available() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def _deepseek_available() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


def _groq_available() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))


def _ollama_available() -> bool:
    """Probe the Ollama server with a bounded HTTP GET to /api/version."""
    base = os.environ.get("TMT_OLLAMA_BASE", "http://localhost:11434")
    try:
        with urllib.request.urlopen(f"{base}/api/version", timeout=2.0) as r:
            return getattr(r, "status", 200) == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _skip_if_unavailable(cell: Cell) -> None:
    """Skip the test gracefully if any of the cell's prerequisites are
    missing. Caller invokes this at the top of each test."""
    if not _gemini_available():
        pytest.skip(
            "Gemini auth missing — required for every cell because the "
            "observer is pinned to gemini_pro. Set GOOGLE_API_KEY for "
            "AI Studio, or set GOOGLE_GENAI_USE_VERTEXAI=true + "
            "GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_LOCATION (and run "
            "`gcloud auth application-default login`) for Vertex AI."
        )
    if cell.provider == "claude" and not _claude_available():
        pytest.skip(f"ANTHROPIC_API_KEY not set — {cell.cell_id} skipped.")
    if cell.provider == "openai" and not _openai_available():
        pytest.skip(f"OPENAI_API_KEY not set — {cell.cell_id} skipped.")
    if cell.provider == "ollama" and not _ollama_available():
        base = os.environ.get("TMT_OLLAMA_BASE", "http://localhost:11434")
        pytest.skip(
            f"Ollama server not reachable at {base} — {cell.cell_id} "
            f"skipped. Start it with `ollama serve` and ensure the model "
            f"is pulled (default: qwen2.5:9b)."
        )
    if cell.provider == "deepseek" and not _deepseek_available():
        pytest.skip(f"DEEPSEEK_API_KEY not set — {cell.cell_id} skipped.")
    if cell.provider == "groq" and not _groq_available():
        pytest.skip(f"GROQ_API_KEY not set — {cell.cell_id} skipped.")


# ===========================================================================
# Cell execution
# ===========================================================================

async def _run_one_cell(cell: Cell, out_dir: Path) -> "ResearchSessionOutputs":  # noqa: F821
    """Drive run_research_session for one cell and persist outputs."""
    from run_research_session import run_research_session

    out_dir.mkdir(parents=True, exist_ok=True)

    out = await run_research_session(
        company=cell.company,
        industry_context=cell.industry_context,
        product_type=cell.product_type,
        current_year=cell.current_year,
        max_debriefing_exchanges=MAX_DEBRIEFING_EXCHANGES,
    )

    # Persist the four phase-JSON files + a session.json index so a
    # human reviewer can inspect any test that surfaced a failure.
    out.to_json_files(out_dir)
    return out


def _verify_cell_output(out, cell: Cell) -> None:
    """Common invariants across all four cells.

    Every assertion message includes `cell.cell_id` so a parallel test
    run with one failing cell reports the cell unambiguously.
    """
    # 1. No silent per-phase failure (errors are accumulated, not raised).
    assert out.errors == [], (
        f"[{cell.cell_id}] accumulated errors during run: {out.errors}"
    )

    # 2. Phase 1: deliberation produced events.
    assert out.deliberation_log is not None, (
        f"[{cell.cell_id}] deliberation_log is None"
    )
    assert len(out.deliberation_log.events) > 0, (
        f"[{cell.cell_id}] deliberation produced zero events"
    )

    # 3. Phase 2: artefact bundle populated; CEO at minimum.
    assert out.artefacts is not None, (
        f"[{cell.cell_id}] artefacts bundle is None"
    )
    assert len(out.artefacts.artefacts) >= 1, (
        f"[{cell.cell_id}] no artefacts produced"
    )
    roles_with_artefacts = {a.role for a in out.artefacts.artefacts}
    assert "CEO" in roles_with_artefacts, (
        f"[{cell.cell_id}] CEO produced no artefact "
        f"(roles seen: {roles_with_artefacts})"
    )

    # 4. Phase 3: observation summary non-empty.
    assert out.observation_summary is not None, (
        f"[{cell.cell_id}] observation_summary is None"
    )
    decisions = len(out.observation_summary.decisions)
    components = len(out.observation_summary.components)
    assert decisions > 0 or components > 0, (
        f"[{cell.cell_id}] observation_summary has no decisions or "
        f"components"
    )

    # 5. Phase 4: debriefing produced at least one exchange.
    assert out.debriefing_transcript is not None, (
        f"[{cell.cell_id}] debriefing_transcript is None"
    )
    assert len(out.debriefing_transcript.exchanges) >= 1, (
        f"[{cell.cell_id}] debriefing transcript has no exchanges"
    )

    # 6. Run timestamps are set.
    assert out.finished_at is not None, (
        f"[{cell.cell_id}] finished_at is None"
    )


# ===========================================================================
# Tests — one per cell. Each test is independent of the others; pytest-
# xdist (`-n 4`) runs them in separate worker processes, each with its
# own env vars (so `monkeypatch.setenv("TMT_PROVIDER", ...)` does not
# race across workers).
# ===========================================================================

@pytest.mark.live
def test_cell_1_openai_gemini_dynamic_novel(monkeypatch, tmp_path):
    """OpenAI / gemini_pro / Dynamic / Novel / 2030."""
    cell = CELLS[0]
    _skip_if_unavailable(cell)
    monkeypatch.setenv("TMT_PROVIDER", cell.provider)

    out = asyncio.run(_run_one_cell(cell, tmp_path / cell.cell_id))
    _verify_cell_output(out, cell)


@pytest.mark.live
def test_cell_2_anthropic_claude_stable_novel(monkeypatch, tmp_path):
    """Anthropic / claude / Stable / Novel / 2032."""
    cell = CELLS[1]
    _skip_if_unavailable(cell)
    monkeypatch.setenv("TMT_PROVIDER", cell.provider)

    out = asyncio.run(_run_one_cell(cell, tmp_path / cell.cell_id))
    _verify_cell_output(out, cell)


@pytest.mark.live
def test_cell_3_google_openai_dynamic_enhancement(monkeypatch, tmp_path):
    """Google / openai / Dynamic / Enhancement / 2030."""
    cell = CELLS[2]
    _skip_if_unavailable(cell)
    monkeypatch.setenv("TMT_PROVIDER", cell.provider)

    out = asyncio.run(_run_one_cell(cell, tmp_path / cell.cell_id))
    _verify_cell_output(out, cell)


@pytest.mark.live
def test_cell_4_meta_ollama_stable_enhancement(monkeypatch, tmp_path):
    """Meta / ollama / Stable / Enhancement / 2032.

    Defaults to `qwen2.5:9b` running on a local Ollama server at
    `http://localhost:11434`. Override either with environment vars:
        TMT_OLLAMA_MODEL=ollama_chat/<name>
        TMT_OLLAMA_BASE=http://<host>:<port>
    """
    cell = CELLS[3]
    _skip_if_unavailable(cell)
    monkeypatch.setenv("TMT_PROVIDER", cell.provider)
    # Default to qwen2.5:9b (smaller than the providers.py default of
    # qwen2.5:32b — faster on a typical local machine). The user can
    # override by setting TMT_OLLAMA_MODEL before running.
    monkeypatch.setenv(
        "TMT_OLLAMA_MODEL",
        os.environ.get("TMT_OLLAMA_MODEL", "ollama_chat/qwen2.5:9b"),
    )

    out = asyncio.run(_run_one_cell(cell, tmp_path / cell.cell_id))
    _verify_cell_output(out, cell)


@pytest.mark.live
def test_cell_5_mistral_deepseek_dynamic_novel(monkeypatch, tmp_path):
    """Mistral / deepseek / Dynamic / Novel / 2030.

    Low-cost smoke test — DeepSeek-Chat is roughly 1/10th the cost of
    GPT-5 / Claude Sonnet. Requires `DEEPSEEK_API_KEY` in the env.
    """
    cell = CELLS[4]
    _skip_if_unavailable(cell)
    monkeypatch.setenv("TMT_PROVIDER", cell.provider)

    out = asyncio.run(_run_one_cell(cell, tmp_path / cell.cell_id))
    _verify_cell_output(out, cell)


@pytest.mark.live
def test_cell_6_xai_groq_stable_enhancement(monkeypatch, tmp_path):
    """xAI / groq / Stable / Enhancement / 2032.

    Low-cost smoke test — Groq serves open-weight Llama 3.3 70B at
    sub-second latency. Requires `GROQ_API_KEY` in the env.
    """
    cell = CELLS[5]
    _skip_if_unavailable(cell)
    monkeypatch.setenv("TMT_PROVIDER", cell.provider)

    out = asyncio.run(_run_one_cell(cell, tmp_path / cell.cell_id))
    _verify_cell_output(out, cell)
