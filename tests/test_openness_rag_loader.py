"""Tests for `studies.openness_maneuvering.rag_loader.load_corpus`.

Mocks `rag.vertex_corpus.find_corpus` + `list_files_in_corpus` so the
loader tests don't require GCP auth or a live Vertex project. The
mocking lives on the test side (not in the loader) so the loader's
production code path stays untested-here-but-untouched.
"""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock

import pytest


def _loader_mod():
    return importlib.import_module(
        "open-innovation-strategy.studies.openness_maneuvering.rag_loader"
    )


def _vertex_corpus_mod():
    return importlib.import_module(
        "open-innovation-strategy.rag.vertex_corpus"
    )


def _install_mock_vertex_corpus(monkeypatch, *, find_returns, list_files_returns):
    """Patch the wrapper functions the loader calls.

    The loader's `_vertex_corpus` binding is set at module-load time
    via a try/except dual-import (relative-pkg or flat). Whichever
    form succeeded, the loader's `_vertex_corpus` attribute points
    at the resolved module — patch on that attribute directly so the
    test works regardless of which sys.modules entry the import
    landed in (relative-pkg imports vs flat imports can produce two
    separate module objects under the conftest's meta-path setup).
    """
    loader = _loader_mod()
    vc = loader._vertex_corpus  # the resolved module the loader uses
    monkeypatch.setattr(vc, "find_corpus", MagicMock(return_value=find_returns))
    monkeypatch.setattr(vc, "list_files_in_corpus",
                        MagicMock(return_value=list_files_returns))
    return vc


# ---------------------------------------------------------------------------
# CORPUS_DISPLAY_NAME_PATTERN
# ---------------------------------------------------------------------------

class TestDisplayNamePattern:
    def test_pattern_uses_study_slug_and_company(self):
        m = _loader_mod()
        # The convention the build CLI uses + the loader looks up.
        assert m.CORPUS_DISPLAY_NAME_PATTERN == "openness_maneuvering__{company}"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestLoadCorpusHappyPath:
    def test_returns_corpus_dict_when_found(self, monkeypatch):
        _install_mock_vertex_corpus(
            monkeypatch,
            find_returns="projects/p/locations/l/ragCorpora/openai-id",
            list_files_returns=[
                {"display_name": "openai_2024_annual_letter.md",
                 "description": "sha256=abcdef1234567890",
                 "name": "projects/p/locations/l/ragCorpora/openai-id/files/1"},
                {"display_name": "openai_founders_essay.md",
                 "description": "sha256=fedcba0987654321",
                 "name": "projects/p/locations/l/ragCorpora/openai-id/files/2"},
            ],
        )
        m = _loader_mod()
        result = m.load_corpus("OpenAI")
        assert result is not None
        assert result["corpus_name"] == "projects/p/locations/l/ragCorpora/openai-id"
        assert result["embedding_model"].endswith("text-embedding-005")
        assert len(result["documents"]) == 2
        doc0 = result["documents"][0]
        assert doc0["display_name"] == "openai_2024_annual_letter.md"
        assert doc0["sha256"] == "abcdef1234567890"
        assert doc0["vertex_file_name"].endswith("/files/1")

    def test_extracts_sha256_from_description_field(self, monkeypatch):
        _install_mock_vertex_corpus(
            monkeypatch,
            find_returns="projects/p/locations/l/ragCorpora/x",
            list_files_returns=[
                # Description starts with extra prefix; SHA still found.
                {"display_name": "a.md", "description": "uploaded by build_cli; sha256=deadbeef"},
                # Description without SHA — empty string.
                {"display_name": "b.md", "description": "manual upload"},
                # Empty description — empty string.
                {"display_name": "c.md", "description": ""},
            ],
        )
        m = _loader_mod()
        result = m.load_corpus("OpenAI")
        shas = [d["sha256"] for d in result["documents"]]
        assert shas == ["deadbeef", "", ""]

    def test_display_name_passed_to_find_corpus(self, monkeypatch):
        vc = _install_mock_vertex_corpus(
            monkeypatch, find_returns="some/corpus", list_files_returns=[],
        )
        m = _loader_mod()
        m.load_corpus("Anthropic")
        vc.find_corpus.assert_called_with("openness_maneuvering__Anthropic")


# ---------------------------------------------------------------------------
# Missing-corpus fallback
# ---------------------------------------------------------------------------

class TestLoadCorpusReturnsNone:
    def test_when_find_corpus_returns_none(self, monkeypatch):
        _install_mock_vertex_corpus(
            monkeypatch, find_returns=None, list_files_returns=[],
        )
        m = _loader_mod()
        assert m.load_corpus("OpenAI") is None

    def test_when_find_corpus_raises(self, monkeypatch):
        vc = _loader_mod()._vertex_corpus

        def _boom(display_name):
            raise RuntimeError("vertex unreachable")
        monkeypatch.setattr(vc, "find_corpus", _boom)
        m = _loader_mod()
        # Loader catches and returns None rather than letting the
        # session-start crash.
        assert m.load_corpus("OpenAI") is None

    def test_no_documents_still_returns_corpus_dict(self, monkeypatch):
        """Edge case: a corpus exists but is empty (build CLI hasn't
        run yet). The loader still returns the corpus dict — the
        framework can retrieve from an empty corpus (and just get no
        snippets) without crashing."""
        _install_mock_vertex_corpus(
            monkeypatch,
            find_returns="projects/p/locations/l/ragCorpora/empty-corpus",
            list_files_returns=[],
        )
        m = _loader_mod()
        result = m.load_corpus("FreshFirm")
        assert result is not None
        assert result["corpus_name"].endswith("empty-corpus")
        assert result["documents"] == []


# ---------------------------------------------------------------------------
# StudyConfig integration
# ---------------------------------------------------------------------------

class TestStudyConfigRegistersLoader:
    def test_openness_study_sets_rag_corpus_loader(self):
        studies = importlib.import_module(
            "open-innovation-strategy.studies"
        )
        study = studies.load_study("openness_maneuvering")
        assert study.rag_corpus_loader == (
            "studies.openness_maneuvering.rag_loader:load_corpus"
        )

    def test_loader_path_is_importable(self):
        """The dotted-path string on StudyConfig must actually resolve.
        Without this test, a typo in the registration would only surface
        at --rag run time."""
        studies = importlib.import_module(
            "open-innovation-strategy.studies"
        )
        study = studies.load_study("openness_maneuvering")
        module_path, attr = study.rag_corpus_loader.rsplit(":", 1)
        mod = importlib.import_module(module_path)
        loader = getattr(mod, attr)
        assert callable(loader)


# ---------------------------------------------------------------------------
# End-to-end: build_rag_session_for_company uses the loader
# ---------------------------------------------------------------------------

class TestEndToEndViaBuildRagSession:
    """Verifies the loader plays nicely with the runtime resolver.

    `build_rag_session_for_company` uses `importlib.import_module(
    study.rag_corpus_loader.split(':')[0])` to resolve the loader. The
    StudyConfig stores the flat dotted-path form, so the resolver
    loads `studies.openness_maneuvering.rag_loader` (NOT the
    hyphenated alias). The loader's `_vertex_corpus` binding in that
    flat-name module is what we need to patch.
    """

    def _install_mock_on_resolver_module(self, *, find_returns, list_files_returns):
        """Patch the loader module the runtime resolver will reach.

        Returns the (loader_module, vc_module) pair so the test can
        introspect calls.
        """
        # Resolve via the same path the runtime does — guarantees we
        # patch the same sys.modules entry.
        loader_mod = importlib.import_module(
            "studies.openness_maneuvering.rag_loader"
        )
        vc = loader_mod._vertex_corpus
        vc.find_corpus = MagicMock(return_value=find_returns)
        vc.list_files_in_corpus = MagicMock(return_value=list_files_returns)
        return loader_mod, vc

    def test_build_rag_session_resolves_via_loader(self):
        self._install_mock_on_resolver_module(
            find_returns="projects/p/locations/l/ragCorpora/x",
            list_files_returns=[{"display_name": "a.md",
                                  "description": "sha256=abc",
                                  "name": "files/1"}],
        )
        runtime = importlib.import_module(
            "open-innovation-strategy.rag.runtime"
        )
        studies = importlib.import_module(
            "open-innovation-strategy.studies"
        )
        study = studies.load_study("openness_maneuvering")
        sess = runtime.build_rag_session_for_company(study=study, company="OpenAI")
        assert sess is not None
        assert sess.enabled
        assert sess.corpus_name.endswith("ragCorpora/x")
        assert len(sess.corpus_documents) == 1
        assert sess.corpus_documents[0]["display_name"] == "a.md"

    def test_build_rag_session_returns_none_when_corpus_absent(self):
        self._install_mock_on_resolver_module(
            find_returns=None, list_files_returns=[],
        )
        runtime = importlib.import_module(
            "open-innovation-strategy.rag.runtime"
        )
        studies = importlib.import_module(
            "open-innovation-strategy.studies"
        )
        study = studies.load_study("openness_maneuvering")
        assert runtime.build_rag_session_for_company(
            study=study, company="Unknown",
        ) is None
