"""Checks that `agent.py` imports cleanly and keeps `os` and `asyncio` at
module level, because its per-call timeout and retry code use both names.
"""

from __future__ import annotations

import importlib

PKG = "open-innovation-strategy"


def test_agent_module_imports_cleanly():
    """The agent module itself must import without raising. A
    NameError or AttributeError surfaced here would mean a future
    refactor stripped a needed import — fail fast in tests rather
    than during a live run."""
    importlib.import_module(f"{PKG}.agent")


def test_agent_has_os_and_asyncio_at_module_level():
    """`agent._run_one_agent` reads `os.environ.get(
    'TMT_LLM_CALL_TIMEOUT_S', ...)` and calls
    `asyncio.wait_for(...)` + `asyncio.sleep(...)` from its closure
    body. Both modules must be importable as `os` / `asyncio` (not
    just `_os` / `_asyncio`) at the agent module's top level.
    """
    agent_mod = importlib.import_module(f"{PKG}.agent")
    assert hasattr(agent_mod, "os"), (
        "agent module must `import os` at top level — the per-call "
        "timeout `os.environ.get('TMT_LLM_CALL_TIMEOUT_S', ...)` "
        "inside _run_one_agent depends on the global `os` name."
    )
    assert hasattr(agent_mod, "asyncio"), (
        "agent module must `import asyncio` at top level — the "
        "per-call `asyncio.wait_for(...)` + retry-sleep "
        "`asyncio.sleep(...)` inside _run_one_agent depend on the "
        "global `asyncio` name."
    )
