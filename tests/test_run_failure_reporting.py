"""A run that loses a phase must say so, and one 429 must not lose the debrief."""

from __future__ import annotations

import asyncio
import importlib
import inspect
from pathlib import Path
from types import SimpleNamespace

PKG = "open-innovation-strategy"


def _rs():
    return importlib.import_module(f"{PKG}.run_research_session")


def _retry():
    return importlib.import_module(f"{PKG}.orchestrator.llm_retry")


def _no_sleep(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(_retry().asyncio, "sleep", instant)


def test_observer_survives_a_rate_limit(monkeypatch):
    _no_sleep(monkeypatch)
    calls = []

    async def runner(*, agent, prompt):
        calls.append(prompt)
        if len(calls) == 1:
            raise RuntimeError("429 RESOURCE_EXHAUSTED. Resource exhausted.")
        return "summary"

    errors: list[str] = []
    raw = asyncio.run(_rs()._run_observer(runner, object(), "p", errors))
    assert raw == "summary"
    assert len(calls) == 2
    assert errors == []


def test_observer_error_is_recorded_without_the_traceback(monkeypatch):
    _no_sleep(monkeypatch)

    async def runner(*, agent, prompt):
        raise RuntimeError("401 UNAUTHENTICATED")

    errors: list[str] = []
    raw = asyncio.run(_rs()._run_observer(runner, object(), "p", errors))
    assert raw is None
    assert len(errors) == 1
    assert errors[0].startswith("observation_failed: observer: RuntimeError")
    assert "401 UNAUTHENTICATED" in errors[0]
    assert "Traceback" not in errors[0]
    assert "\n" not in errors[0]


def test_missing_artefact_roles():
    rs = _rs()
    bundle = SimpleNamespace(artefacts=[SimpleNamespace(role="CEO")])
    assert rs._missing_artefact_roles(["CEO", "CTO"], bundle) == ["CTO"]
    assert rs._missing_artefact_roles(["CEO"], bundle) == []
    assert rs._missing_artefact_roles(["CEO"], None) == ["CEO"]


def test_exit_code():
    rs = _rs()
    assert rs._exit_code([]) == 0
    assert rs._exit_code(["observation_failed: x"]) == 1


def test_command_line_exits_with_that_code():
    assert _rs().sys.exit is not None
    source = Path(inspect.getfile(_rs())).read_text()
    assert source.rstrip().endswith("sys.exit(_exit_code(out.errors))")
