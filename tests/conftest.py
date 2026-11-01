"""Pytest configuration shared by all tests in this package.

Two responsibilities:

1. Make the repository root importable as a package under the alias in
   `PKG_NAME` (it has hyphens). Tests load the code through
   `importlib.import_module` with this alias.

2. Stub `google.adk` (and submodules) before any production code is
   imported, so tests can run without the heavy SDK installed. Real ADK
   classes are not exercised here — the tests only need `LlmAgent` to
   accept its constructor arguments and expose them as attributes.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Make the repository root importable under the `PKG_NAME` alias.
#
# The alias contains hyphens, which Python's `import` statement cannot
# parse but `importlib.import_module` can. We register the repository root
# (`WORKTREE_DIR`) as a package with a proper ModuleSpec so submodule
# lookup (PathFinder traversal of `submodule_search_locations`) works.
# ---------------------------------------------------------------------------
WORKTREE_DIR = Path(__file__).resolve().parent.parent
PKG_NAME = "open-innovation-strategy"

# Pytest's `--import-mode=importlib` (see scripts/run_tests.sh) builds its own
# namespace-package chain after this conftest loads, which overwrites a plain
# `sys.modules[…] = …` during test collection. So we install a `sys.meta_path`
# finder that intercepts every lookup for the alias and resolves submodules from
# the repository root. A name it cannot find there goes to the next finder.
class _WorktreeFirstFinder(importlib.abc.MetaPathFinder):  # type: ignore[name-defined]
    """Meta-path finder: serves the `PKG_NAME` alias from the repository root first."""

    def __init__(self, pkg_name: str, worktree_dir: Path):
        self.pkg_name = pkg_name
        self.worktree_dir = worktree_dir

    def find_spec(self, fullname, path, target=None):
        if fullname != self.pkg_name and not fullname.startswith(f"{self.pkg_name}."):
            return None

        if _os.environ.get("CONFTEST_DEBUG"):
            print(f"[finder] find_spec({fullname!r})", flush=True)

        # Top-level package: synthesise a namespace spec rooted at the repository root.
        if fullname == self.pkg_name:
            spec = importlib.machinery.ModuleSpec(
                name=fullname,
                loader=None,
                is_package=True,
            )
            spec.submodule_search_locations = [str(self.worktree_dir)]
            return spec

        # Submodule: find by file inside the repository root.
        rel = fullname[len(self.pkg_name) + 1:].split(".")
        candidate_pkg_init = self.worktree_dir.joinpath(*rel) / "__init__.py"
        candidate_module = self.worktree_dir.joinpath(*rel[:-1]) / f"{rel[-1]}.py"

        if candidate_pkg_init.is_file():
            spec = importlib.util.spec_from_file_location(
                fullname,
                str(candidate_pkg_init),
                submodule_search_locations=[str(candidate_pkg_init.parent)],
            )
            return spec
        if candidate_module.is_file():
            spec = importlib.util.spec_from_file_location(fullname, str(candidate_module))
            return spec
        return None


def _install_worktree_finder() -> None:
    # Idempotent: don't install twice if conftest is re-evaluated.
    for existing in sys.meta_path:
        if isinstance(existing, _WorktreeFirstFinder) and existing.pkg_name == PKG_NAME:
            return
    sys.meta_path.insert(0, _WorktreeFirstFinder(PKG_NAME, WORKTREE_DIR))

    # Evict any cached package entries that resolve to files outside
    # the repository root, so the finder gets to handle the next import.
    # We leave entries already rooted there alone (this conftest, pytest's
    # namespace entries, etc.).
    worktree_str = str(WORKTREE_DIR)
    for name in list(sys.modules):
        if name != PKG_NAME and not name.startswith(f"{PKG_NAME}."):
            continue
        mod = sys.modules.get(name)
        # Use object.__getattribute__ to avoid namespace-package
        # __path__ KeyErrors during pytest's mid-load conftest tree.
        try:
            file_attr = getattr(mod, "__file__", None) or ""
        except (KeyError, ImportError):
            file_attr = ""
        try:
            path_attr = list(getattr(mod, "__path__", []) or [])
        except (KeyError, ImportError, TypeError):
            path_attr = []
        is_in_worktree = (worktree_str in file_attr) or any(
            worktree_str in str(p) for p in path_attr
        )
        if not is_in_worktree:
            del sys.modules[name]


import importlib.abc  # noqa: E402  (needed by the finder class above)
_install_worktree_finder()


import os as _os  # noqa: E402  (must be defined before the finder may print)


# Debug instrumentation (set CONFTEST_DEBUG=1 to inspect path setup).
if _os.environ.get("CONFTEST_DEBUG"):
    print(f"[conftest] meta_path[0]: {sys.meta_path[0]}", flush=True)


# ---------------------------------------------------------------------------
# 2. Stub `google.adk` and submodules if the real SDK isn't installed.
# ---------------------------------------------------------------------------

def _ensure_stub_module(name: str) -> types.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


def _adk_is_real() -> bool:
    """True if a real google.adk package is on sys.path."""
    try:
        spec = importlib.util.find_spec("google.adk")
    except (ImportError, ValueError):
        return False
    return spec is not None


if not _adk_is_real():
    google_pkg = _ensure_stub_module("google")
    google_pkg.__path__ = []  # type: ignore[attr-defined]

    adk_pkg = _ensure_stub_module("google.adk")
    adk_pkg.__path__ = []  # type: ignore[attr-defined]

    # --- google.adk.agents.LlmAgent -----------------------------------
    agents_mod = _ensure_stub_module("google.adk.agents")

    class _StubLlmAgent:
        """Lightweight stand-in for google.adk.agents.LlmAgent.

        Captures every kwarg as an attribute so tests can assert on
        `agent.name`, `agent.model`, `agent.output_schema`, etc.
        """

        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    agents_mod.LlmAgent = _StubLlmAgent

    # --- google.adk.runners.Runner ------------------------------------
    runners_mod = _ensure_stub_module("google.adk.runners")

    class _StubRunner:  # pragma: no cover  (orchestration not tested here)
        async def run(self, *args, **kwargs):
            raise NotImplementedError("Stub runner — not used by unit tests.")

    runners_mod.Runner = _StubRunner

    # --- google.adk.sessions.InMemorySessionService -------------------
    sessions_mod = _ensure_stub_module("google.adk.sessions")

    class _StubSession:
        def __init__(self, id: str):
            self.id = id

    class _StubSessionService:
        """Mimics google.adk.sessions.InMemorySessionService surface
        used by `agent.py::_get_role_session_id` and the per-call
        runners — `create_session(app_name, user_id, session_id)`
        returning a session object with an `.id` attribute.
        """

        def __init__(self):
            self._sessions: dict[tuple, _StubSession] = {}

        async def create_session(self, *, app_name, user_id, session_id=None, state=None):
            key = (app_name, user_id, session_id)
            if key not in self._sessions:
                self._sessions[key] = _StubSession(session_id or f"stub_{len(self._sessions)}")
            return self._sessions[key]

        def create_session_sync(self, *, app_name, user_id, session_id=None, state=None):
            import asyncio as _asyncio
            return _asyncio.get_event_loop().run_until_complete(
                self.create_session(
                    app_name=app_name, user_id=user_id,
                    session_id=session_id, state=state,
                )
            )

    sessions_mod.InMemorySessionService = _StubSessionService

    # --- google.adk.a2a (to_a2a, RemoteA2aAgent) ----------------------
    a2a_mod = _ensure_stub_module("google.adk.a2a")

    def _stub_to_a2a(agent):  # pragma: no cover
        return agent

    class _StubRemoteA2aAgent:  # pragma: no cover
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    a2a_mod.to_a2a = _stub_to_a2a
    a2a_mod.RemoteA2aAgent = _StubRemoteA2aAgent

    # --- google.adk.models.lite_llm.LiteLlm ---------------------------
    models_mod = _ensure_stub_module("google.adk.models")
    models_mod.__path__ = []  # type: ignore[attr-defined]
    lite_llm_mod = _ensure_stub_module("google.adk.models.lite_llm")

    class _StubLiteLlm:
        def __init__(self, model: str, **kwargs):
            self.model = model
            for k, v in kwargs.items():
                setattr(self, k, v)

        def __repr__(self) -> str:
            return f"LiteLlm(model={self.model!r})"

    lite_llm_mod.LiteLlm = _StubLiteLlm

    # --- google.genai.types (Content, Part) ---------------------------
    # The live integration tests in tests/integration/ import
    # `from google.genai import types` at module level. Stub it so
    # pytest's collection succeeds without the real SDK; the live
    # tests themselves are skip-marked and won't be executed unless
    # --run-live is passed.
    genai_mod = _ensure_stub_module("google.genai")
    genai_mod.__path__ = []  # type: ignore[attr-defined]
    types_mod = _ensure_stub_module("google.genai.types")

    class _StubPart:
        def __init__(self, text: str = "", **kwargs):
            self.text = text
            for k, v in kwargs.items():
                setattr(self, k, v)

    class _StubContent:
        def __init__(self, role: str = "user", parts=None, **kwargs):
            self.role = role
            self.parts = parts or []
            for k, v in kwargs.items():
                setattr(self, k, v)

    types_mod.Part = _StubPart
    types_mod.Content = _StubContent
    genai_mod.types = types_mod


# ---------------------------------------------------------------------------
# 3. Live integration tests — register the `live` marker and skip by default.
# ---------------------------------------------------------------------------
#
# Tests in `tests/integration/` that hit real LLM APIs are marked
# `@pytest.mark.live`. They cost real money and take real time, so
# they're SKIPPED by default. Run with `pytest --run-live` to include
# them. CI invocations should never pass that flag.

def pytest_addoption(parser):
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help=(
            "Run integration tests that hit live LLM APIs. Requires a "
            "GOOGLE_API_KEY (and possibly billing). Skipped by default."
        ),
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: integration test that hits live LLM APIs (~£0.05-0.30/run). "
        "Skipped unless --run-live is passed.",
    )
    config.addinivalue_line(
        "markers",
        "asyncio: coroutine test; run by pytest-asyncio if installed, "
        "otherwise by the asyncio.run fallback below.",
    )


def pytest_pyfunc_call(pyfuncitem):
    """Run `async def` tests with asyncio.run when pytest-asyncio is absent.

    Some tests (e.g. test_rate_limit_bucket.py) are coroutines marked
    `@pytest.mark.asyncio`. Without the plugin pytest would fail them, so this
    fallback executes them on a fresh event loop. If pytest-asyncio is
    installed, it handles them and this hook steps aside.
    """
    import asyncio as _asyncio
    import inspect as _inspect

    if not _inspect.iscoroutinefunction(pyfuncitem.obj):
        return None
    if pyfuncitem.config.pluginmanager.hasplugin("asyncio"):
        return None
    argnames = pyfuncitem._fixtureinfo.argnames
    kwargs = {name: pyfuncitem.funcargs[name] for name in argnames}
    _asyncio.run(pyfuncitem.obj(**kwargs))
    return True


def pytest_collection_modifyitems(config, items):
    import pytest as _pytest

    if config.getoption("--run-live"):
        return
    skip_live = _pytest.mark.skip(reason="needs --run-live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
