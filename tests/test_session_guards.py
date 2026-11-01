"""Mistakes in starting a run must stop it before it spends anything."""

from __future__ import annotations

import asyncio
import importlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PKG = "open-innovation-strategy"
ROOT = Path(__file__).resolve().parent.parent


def _session():
    return importlib.import_module(f"{PKG}.run_research_session")


def test_grounded_run_with_no_corpus_stops(monkeypatch):
    runtime = importlib.import_module(f"{PKG}.rag.runtime")
    monkeypatch.setattr(runtime, "build_rag_session_for_company", lambda **_: None)
    with pytest.raises(RuntimeError, match="no corpus"):
        asyncio.run(_session().run_research_session(company="X", use_rag=True))


@pytest.mark.parametrize("flag, value", [
    ("--industry-context", "Dynmaic"), ("--product-type", "Nvel"),
])
def test_a_typo_in_a_condition_is_refused(flag, value):
    result = subprocess.run(
        [sys.executable, "run_research_session.py", flag, value],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_failed_model_calls_reach_the_errors():
    state = lambda reason: SimpleNamespace(finished_reason=reason)  # noqa: E731
    shared = SimpleNamespace(
        llm_failures=["CEO: 404"] * 5,
        role_states={"CEO": state("llm_failures"), "CTO": state("DONE_action")},
    )
    entries = _session()._deliberation_failures(SimpleNamespace(_last_concurrent_shared_state=shared))
    assert entries == ["deliberation_model_calls_failed: 5", "deliberation_roles_stopped: CEO"]
    assert _session()._deliberation_failures(SimpleNamespace()) == []
