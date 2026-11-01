"""Tests for `rag.runtime` — `RagSession` + `build_rag_session_for_company`.

Mocks `vertex_corpus.retrieve` so the tests don't need GCP auth.
"""

from __future__ import annotations

import asyncio
import time
import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _rt():
    return importlib.import_module("open-innovation-strategy.rag.runtime")


def _schemas():
    return importlib.import_module("open-innovation-strategy.rag.schemas")


def _install_fake_retrieve(monkeypatch, retrieve_returns):
    """Patch `rag.vertex_corpus.retrieve` to return a fixed list."""
    m = _rt()
    fake = MagicMock(return_value=retrieve_returns)
    monkeypatch.setattr(m._vertex_corpus, "retrieve", fake)
    return fake


def _two_snippets():
    s = _schemas()
    return [
        s.RetrievedSnippet(
            doc_id="a.md", chunk_id="a.md#1", text="text-A", score=0.9,
        ),
        s.RetrievedSnippet(
            doc_id="b.md", chunk_id="b.md#1", text="text-B", score=0.7,
        ),
    ]


# ---------------------------------------------------------------------------
# RagSession.enabled
# ---------------------------------------------------------------------------

class TestEnabledFlag:
    def test_enabled_true_when_corpus_name_present(self):
        m = _rt()
        sess = m.RagSession(corpus_name="projects/p/locations/l/ragCorpora/x")
        assert sess.enabled is True

    def test_enabled_false_when_corpus_name_none(self):
        m = _rt()
        sess = m.RagSession(corpus_name=None)
        assert sess.enabled is False

    def test_enabled_false_when_corpus_name_empty_string(self):
        m = _rt()
        sess = m.RagSession(corpus_name="")
        assert sess.enabled is False


# ---------------------------------------------------------------------------
# retrieve_for_role
# ---------------------------------------------------------------------------

class TestRetrieveForRole:
    def test_log_says_how_much_of_each_passage_agents_saw(self, monkeypatch):
        m = _rt()
        long = _two_snippets()[0].model_copy(update={"text": "word " * 1000})
        short = _two_snippets()[1].model_copy(update={"text": "a short passage"})
        _install_fake_retrieve(monkeypatch, [long, short])
        monkeypatch.delenv("TMT_PASSAGE_CHARS", raising=False)
        sess = m.RagSession(corpus_name="projects/p/locations/l/ragCorpora/x")
        asyncio.run(sess.retrieve_for_role(role="CEO", query="q", phase="p"))
        passages = sess.retrieval_log[0]["retrieved"]
        assert passages[0]["shown_chars"] == 5000
        assert passages[1]["shown_chars"] == len("a short passage")

    def test_a_passage_limit_can_be_set_for_a_test(self, monkeypatch):
        m = _rt()
        long = _two_snippets()[0].model_copy(update={"text": "word " * 1000})
        _install_fake_retrieve(monkeypatch, [long])
        monkeypatch.setenv("TMT_PASSAGE_CHARS", "1200")
        sess = m.RagSession(corpus_name="projects/p/locations/l/ragCorpora/x")
        asyncio.run(sess.retrieve_for_role(role="CEO", query="q", phase="p"))
        passage = sess.retrieval_log[0]["retrieved"][0]
        assert passage["shown_chars"] == 1200
        assert len(passage["text"]) == 5000

    def test_a_hung_retrieval_times_out_and_does_not_stall_other_roles(self, monkeypatch):
        m = _rt()
        monkeypatch.setattr(
            m._vertex_corpus, "retrieve",
            lambda *_, **__: time.sleep(0.5) or [],
        )
        monkeypatch.setenv("TMT_RETRIEVAL_TIMEOUT_S", "0.05")
        sess = m.RagSession(corpus_name="projects/p/locations/l/ragCorpora/x")
        ticks = []

        async def other_role():
            for _ in range(3):
                await asyncio.sleep(0.01)
                ticks.append(1)

        async def go():
            result, _ = await asyncio.gather(
                sess.retrieve_for_role(role="CEO", query="q", phase="p"), other_role(),
            )
            return result

        assert asyncio.run(go()) == []
        assert len(ticks) == 3
        assert sess.retrieval_log[0]["error"] == "TimeoutError"

    def test_returns_snippets_and_appends_log(self, monkeypatch):
        m = _rt()
        snippets_returned = _two_snippets()
        fake_retrieve = _install_fake_retrieve(monkeypatch, snippets_returned)

        sess = m.RagSession(
            corpus_name="projects/p/locations/l/ragCorpora/x",
            top_k=5,
        )
        snippets = asyncio.run(sess.retrieve_for_role(
            role="CEO", query="some query", phase="phase_1",
        ))
        assert len(snippets) == 2
        # The Vertex call was made with the right args.
        fake_retrieve.assert_called_once_with(
            "projects/p/locations/l/ragCorpora/x",
            "some query",
            top_k=5,
        )
        # The retrieval log gained one record.
        assert len(sess.retrieval_log) == 1
        rec = sess.retrieval_log[0]
        assert rec["phase"] == "phase_1"
        assert rec["role"] == "CEO"
        assert rec["query"] == "some query"
        assert rec["retrieved_count"] == 2
        assert rec["retrieved"][0]["doc_id"] == "a.md"
        assert "timestamp" in rec

    def test_returns_empty_list_and_logs_skip_when_disabled(self, monkeypatch):
        m = _rt()
        # corpus_name None → disabled.
        sess = m.RagSession(corpus_name=None)
        snippets = asyncio.run(sess.retrieve_for_role(
            role="CEO", query="some query", phase="phase_1",
        ))
        assert snippets == []
        assert len(sess.retrieval_log) == 1
        assert sess.retrieval_log[0]["skipped_reason"] == "disabled"

    def test_returns_empty_list_and_logs_skip_when_query_empty(self, monkeypatch):
        m = _rt()
        sess = m.RagSession(corpus_name="some/corpus")
        snippets = asyncio.run(sess.retrieve_for_role(
            role="CEO", query="   ", phase="phase_1",
        ))
        assert snippets == []
        assert len(sess.retrieval_log) == 1
        assert sess.retrieval_log[0]["skipped_reason"] == "empty_query"

    def test_logs_error_when_retrieve_raises(self, monkeypatch):
        m = _rt()

        def _boom(corpus_name, query, top_k):
            raise RuntimeError("vertex blew up")

        monkeypatch.setattr(m._vertex_corpus, "retrieve", _boom)
        sess = m.RagSession(corpus_name="some/corpus")
        snippets = asyncio.run(sess.retrieve_for_role(
            role="CEO", query="q", phase="phase_1",
        ))
        assert snippets == []
        assert len(sess.retrieval_log) == 1
        assert "vertex blew up" in sess.retrieval_log[0]["error"]


# ---------------------------------------------------------------------------
# manifest_dict
# ---------------------------------------------------------------------------

class TestManifestDict:
    def test_carries_corpus_name_embedding_model_topk_documents(self):
        m = _rt()
        sess = m.RagSession(
            corpus_name="some/corpus",
            embedding_model="publishers/google/models/text-embedding-005",
            corpus_documents=[
                {"display_name": "a.md", "sha256": "abc", "source_uri": "gs://"},
            ],
            top_k=7,
        )
        mfst = sess.manifest_dict()
        assert mfst["enabled"] is True
        assert mfst["corpus_resource_name"] == "some/corpus"
        assert mfst["embedding_model"] == "publishers/google/models/text-embedding-005"
        assert mfst["top_k"] == 7
        assert len(mfst["documents"]) == 1
        assert mfst["documents"][0]["display_name"] == "a.md"

    def test_manifest_marks_disabled_session(self):
        m = _rt()
        sess = m.RagSession(corpus_name=None)
        assert sess.manifest_dict()["enabled"] is False


# ---------------------------------------------------------------------------
# build_rag_session_for_company
# ---------------------------------------------------------------------------

# A fake loader module we'll inject into sys.modules.
_FAKE_LOADER_RETURNS: dict = {}


def _fake_loader(company: str):
    """Test loader. Returns the dict captured in _FAKE_LOADER_RETURNS, or
    None when the dict has no entry for this company."""
    return _FAKE_LOADER_RETURNS.get(company)


class TestBuildRagSessionForCompany:
    def _install_loader(self, monkeypatch):
        """Install this test module as a loader-providing module."""
        fake_mod = types.ModuleType("fake_loader_mod")
        fake_mod.load_corpus = _fake_loader  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "fake_loader_mod", fake_mod)

    def test_returns_none_when_study_has_no_loader(self):
        m = _rt()
        study = SimpleNamespace(rag_corpus_loader=None)
        assert m.build_rag_session_for_company(study=study, company="OpenAI") is None

    def test_returns_none_when_loader_returns_none(self, monkeypatch):
        global _FAKE_LOADER_RETURNS
        _FAKE_LOADER_RETURNS = {}  # loader returns None for any company
        self._install_loader(monkeypatch)
        m = _rt()
        study = SimpleNamespace(rag_corpus_loader="fake_loader_mod:load_corpus")
        assert m.build_rag_session_for_company(study=study, company="OpenAI") is None

    def test_resolves_loader_with_colon_separator(self, monkeypatch):
        global _FAKE_LOADER_RETURNS
        _FAKE_LOADER_RETURNS = {"OpenAI": {
            "corpus_name": "some/corpus",
            "documents": [{"display_name": "a.md", "sha256": "abc"}],
        }}
        self._install_loader(monkeypatch)
        m = _rt()
        study = SimpleNamespace(rag_corpus_loader="fake_loader_mod:load_corpus")
        sess = m.build_rag_session_for_company(study=study, company="OpenAI")
        assert sess is not None
        assert sess.corpus_name == "some/corpus"
        assert sess.corpus_documents == [{"display_name": "a.md", "sha256": "abc"}]

    def test_resolves_loader_with_dot_separator(self, monkeypatch):
        global _FAKE_LOADER_RETURNS
        _FAKE_LOADER_RETURNS = {"OpenAI": {"corpus_name": "some/corpus"}}
        self._install_loader(monkeypatch)
        m = _rt()
        study = SimpleNamespace(rag_corpus_loader="fake_loader_mod.load_corpus")
        sess = m.build_rag_session_for_company(study=study, company="OpenAI")
        assert sess is not None

    def test_returns_none_when_module_unimportable(self, monkeypatch):
        m = _rt()
        study = SimpleNamespace(rag_corpus_loader="nonexistent_module:loader")
        assert m.build_rag_session_for_company(study=study, company="x") is None

    def test_returns_none_when_loader_attribute_missing(self, monkeypatch):
        self._install_loader(monkeypatch)
        m = _rt()
        study = SimpleNamespace(rag_corpus_loader="fake_loader_mod:does_not_exist")
        assert m.build_rag_session_for_company(study=study, company="x") is None

    def test_returns_none_when_loader_raises(self, monkeypatch):
        # Build a loader that raises.
        fake_mod = types.ModuleType("fake_raising_mod")

        def _raises(company):
            raise RuntimeError("boom")
        fake_mod.load_corpus = _raises  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "fake_raising_mod", fake_mod)
        m = _rt()
        study = SimpleNamespace(rag_corpus_loader="fake_raising_mod:load_corpus")
        assert m.build_rag_session_for_company(study=study, company="x") is None
