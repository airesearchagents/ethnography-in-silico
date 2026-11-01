"""Tests for `rag.vertex_corpus` — the thin Vertex AI RAG wrapper.

The wrapper lazy-imports `vertexai.rag` so we mock the SDK by injecting
a fake `vertexai` package into `sys.modules` before the wrapper's first
call. This keeps the tests hermetic (no GCP auth required) while
exercising the wrapper's call-shape and response-translation logic.

What the tests assert
---------------------
- `build_or_get_corpus` finds an existing corpus by display name and
  returns its resource name without calling `create_corpus`.
- `build_or_get_corpus` calls `create_corpus` with the correct embedding-
  model config when no matching corpus exists.
- `upload_documents` computes SHA256 locally, skips already-uploaded
  files (matched by display name), uploads new ones with the SHA in the
  description.
- `retrieve` translates Vertex's nested response shape (`response.
  contexts.contexts[*]`) into a flat list of `RetrievedSnippet`.
- Lazy-import raises a clear error if `vertexai.rag` is missing.
"""

from __future__ import annotations

import hashlib
import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fake Vertex RAG SDK
# ---------------------------------------------------------------------------

class _FakeCorpus:
    def __init__(self, display_name: str, name: str):
        self.display_name = display_name
        self.name = name


class _FakeFile:
    def __init__(self, display_name: str, description: str = "", name: str = ""):
        self.display_name = display_name
        self.description = description
        self.name = name or f"files/{display_name}"


class _FakeContext:
    def __init__(self, *, source_uri="", source_display_name="",
                 text="", score=0.0):
        self.source_uri = source_uri
        self.source_display_name = source_display_name
        self.text = text
        self.score = score


class _FakeContextsHolder:
    def __init__(self, ctxs):
        self.contexts = ctxs


class _FakeRetrieveResponse:
    def __init__(self, ctxs):
        self.contexts = _FakeContextsHolder(ctxs)


def _install_fake_vertex_rag(monkeypatch, *, existing_corpora=None,
                              existing_files=None,
                              retrieve_contexts=None):
    """Replace `vertexai.rag` in sys.modules with a configurable fake.

    Returns the fake module so tests can introspect calls (every method
    is a MagicMock that the test can `assert_called_with(...)` against).
    """
    fake_vertexai = types.ModuleType("vertexai")
    fake_rag = types.ModuleType("vertexai.rag")

    # Config classes — the wrapper constructs these and passes them to
    # create_corpus / retrieval_query. We expose them as MagicMocks so
    # the test can inspect what the wrapper built.
    fake_rag.RagVectorDbConfig = MagicMock(name="RagVectorDbConfig")
    fake_rag.RagEmbeddingModelConfig = MagicMock(name="RagEmbeddingModelConfig")
    fake_rag.VertexPredictionEndpoint = MagicMock(name="VertexPredictionEndpoint")
    fake_rag.TransformationConfig = MagicMock(name="TransformationConfig")
    fake_rag.ChunkingConfig = MagicMock(name="ChunkingConfig")
    fake_rag.RagResource = MagicMock(name="RagResource")
    fake_rag.RagRetrievalConfig = MagicMock(name="RagRetrievalConfig")

    # Corpora.
    fake_rag.list_corpora = MagicMock(return_value=existing_corpora or [])
    fake_rag.create_corpus = MagicMock(
        side_effect=lambda **kw: _FakeCorpus(
            display_name=kw["display_name"],
            name=f"projects/fake/locations/fake/ragCorpora/{kw['display_name']}_id",
        )
    )
    fake_rag.delete_corpus = MagicMock()

    # Files.
    fake_rag.list_files = MagicMock(return_value=existing_files or [])
    fake_rag.upload_file = MagicMock()

    # Retrieval.
    if retrieve_contexts is None:
        retrieve_contexts = []
    fake_rag.retrieval_query = MagicMock(
        return_value=_FakeRetrieveResponse(retrieve_contexts)
    )

    fake_vertexai.rag = fake_rag
    fake_vertexai.init = lambda **_: None
    monkeypatch.setenv("RAG_LOCATION", "us-west1")
    monkeypatch.setitem(sys.modules, "vertexai", fake_vertexai)
    monkeypatch.setitem(sys.modules, "vertexai.rag", fake_rag)
    return fake_rag


def _vc():
    return importlib.import_module("open-innovation-strategy.rag.vertex_corpus")


# ---------------------------------------------------------------------------
# find_corpus  (read-only lookup; the building block under build_or_get_corpus)
# ---------------------------------------------------------------------------

class TestFindCorpus:
    def test_returns_resource_name_when_display_name_matches(self, monkeypatch):
        existing = [
            _FakeCorpus("openness_maneuvering__Anthropic",
                        "projects/p/locations/l/ragCorpora/anth-id"),
            _FakeCorpus("openness_maneuvering__OpenAI",
                        "projects/p/locations/l/ragCorpora/openai-id"),
        ]
        fake = _install_fake_vertex_rag(monkeypatch, existing_corpora=existing)
        vc = _vc()
        name = vc.find_corpus("openness_maneuvering__OpenAI")
        assert name == "projects/p/locations/l/ragCorpora/openai-id"
        # Read-only: must not create.
        fake.create_corpus.assert_not_called()

    def test_returns_none_when_display_name_absent(self, monkeypatch):
        fake = _install_fake_vertex_rag(monkeypatch, existing_corpora=[])
        vc = _vc()
        assert vc.find_corpus("openness_maneuvering__Unknown") is None
        fake.create_corpus.assert_not_called()


# ---------------------------------------------------------------------------
# build_or_get_corpus
# ---------------------------------------------------------------------------

class TestBuildOrGetCorpus:
    def test_returns_existing_corpus_name_without_creating(self, monkeypatch):
        existing = [
            _FakeCorpus("other_study__OpenAI", "projects/p/locations/l/ragCorpora/1"),
            _FakeCorpus("openness_maneuvering__OpenAI",
                        "projects/p/locations/l/ragCorpora/2"),
        ]
        fake = _install_fake_vertex_rag(monkeypatch, existing_corpora=existing)
        vc = _vc()
        name = vc.build_or_get_corpus("openness_maneuvering__OpenAI")
        assert name == "projects/p/locations/l/ragCorpora/2"
        fake.create_corpus.assert_not_called()

    def test_creates_new_corpus_when_display_name_absent(self, monkeypatch):
        fake = _install_fake_vertex_rag(monkeypatch, existing_corpora=[])
        vc = _vc()
        name = vc.build_or_get_corpus("openness_maneuvering__OpenAI")
        assert name.endswith("openness_maneuvering__OpenAI_id")
        fake.create_corpus.assert_called_once()
        kwargs = fake.create_corpus.call_args.kwargs
        assert kwargs["display_name"] == "openness_maneuvering__OpenAI"
        # backend_config carries the embedding model. The wrapper builds
        # RagVectorDbConfig + RagEmbeddingModelConfig + VertexPredictionEndpoint
        # so all three should have been instantiated at least once.
        assert fake.RagVectorDbConfig.called
        assert fake.RagEmbeddingModelConfig.called
        assert fake.VertexPredictionEndpoint.called

    def test_embedding_model_default_is_text_embedding_005(self, monkeypatch):
        fake = _install_fake_vertex_rag(monkeypatch, existing_corpora=[])
        vc = _vc()
        vc.build_or_get_corpus("foo")
        # The embedding model string is passed via VertexPredictionEndpoint.
        ep_calls = fake.VertexPredictionEndpoint.call_args_list
        assert ep_calls, "VertexPredictionEndpoint should have been called"
        last_kwargs = ep_calls[-1].kwargs
        assert "text-embedding-005" in last_kwargs.get("publisher_model", "")

    def test_embedding_model_can_be_overridden(self, monkeypatch):
        fake = _install_fake_vertex_rag(monkeypatch, existing_corpora=[])
        vc = _vc()
        vc.build_or_get_corpus(
            "foo",
            embedding_publisher_model="publishers/google/models/gemini-embedding-001",
        )
        ep_calls = fake.VertexPredictionEndpoint.call_args_list
        last_kwargs = ep_calls[-1].kwargs
        assert last_kwargs.get("publisher_model") == \
            "publishers/google/models/gemini-embedding-001"


# ---------------------------------------------------------------------------
# upload_documents
# ---------------------------------------------------------------------------

class TestUploadDocuments:
    def _write_doc(self, tmp_path: Path, name: str, content: str) -> Path:
        p = tmp_path / name
        p.write_text(content)
        return p

    def test_uploads_new_files_and_computes_sha256(self, monkeypatch, tmp_path):
        fake = _install_fake_vertex_rag(monkeypatch, existing_files=[])
        vc = _vc()
        p1 = self._write_doc(tmp_path, "openai_2024_annual_letter.md", "alpha bravo")
        p2 = self._write_doc(tmp_path, "openai_founders_essay.md", "charlie")

        records = vc.upload_documents("corpus/x", [p1, p2])

        assert len(records) == 2
        # SHA256 computed correctly for both.
        assert records[0]["sha256"] == hashlib.sha256(b"alpha bravo").hexdigest()
        assert records[1]["sha256"] == hashlib.sha256(b"charlie").hexdigest()
        assert records[0]["uploaded"] is True
        assert records[1]["uploaded"] is True
        # Two uploads, with SHA in description.
        assert fake.upload_file.call_count == 2
        kwargs_first = fake.upload_file.call_args_list[0].kwargs
        assert kwargs_first["corpus_name"] == "corpus/x"
        assert kwargs_first["display_name"] == "openai_2024_annual_letter.md"
        assert kwargs_first["description"] == \
            f"sha256={records[0]['sha256']}"

    def test_skips_files_already_in_corpus(self, monkeypatch, tmp_path):
        # Two files in corpus; one matches what we're about to upload.
        existing = [
            _FakeFile(display_name="openai_2024_annual_letter.md"),
        ]
        fake = _install_fake_vertex_rag(monkeypatch, existing_files=existing)
        vc = _vc()
        p1 = self._write_doc(tmp_path, "openai_2024_annual_letter.md", "alpha")
        p2 = self._write_doc(tmp_path, "openai_founders_essay.md", "bravo")

        records = vc.upload_documents("corpus/x", [p1, p2])

        # The annual letter is skipped; the founders essay is uploaded.
        assert records[0]["uploaded"] is False
        assert records[1]["uploaded"] is True
        # Only one upload call.
        fake.upload_file.assert_called_once()
        assert fake.upload_file.call_args.kwargs["display_name"] == \
            "openai_founders_essay.md"
        # SHA256 is still computed for the skipped file so the manifest
        # can record what we'd have uploaded if it weren't already
        # there (drift detection).
        assert records[0]["sha256"] == hashlib.sha256(b"alpha").hexdigest()

    def test_chunking_config_carried_through(self, monkeypatch, tmp_path):
        fake = _install_fake_vertex_rag(monkeypatch, existing_files=[])
        vc = _vc()
        p = self._write_doc(tmp_path, "a.md", "x")
        vc.upload_documents("corpus/x", [p], chunk_size=512, chunk_overlap=64)
        chunk_calls = fake.ChunkingConfig.call_args_list
        assert chunk_calls
        assert chunk_calls[-1].kwargs == {"chunk_size": 512, "chunk_overlap": 64}


# ---------------------------------------------------------------------------
# retrieve
# ---------------------------------------------------------------------------

class TestRetrieve:
    def test_translates_response_to_retrieved_snippet_list(self, monkeypatch):
        contexts = [
            _FakeContext(
                source_uri="gs://b/annual.md",
                source_display_name="openai_2024_annual_letter.md",
                text="We continue to believe broad accessibility helps.",
                score=0.91,
            ),
            _FakeContext(
                source_uri="gs://b/essay.md",
                source_display_name="openai_founders_essay.md",
                text="Open weights are part of our roadmap.",
                score=0.77,
            ),
        ]
        fake = _install_fake_vertex_rag(monkeypatch, retrieve_contexts=contexts)
        vc = _vc()
        snippets = vc.retrieve("corpus/x", "What is the firm's stance on open weights?",
                                top_k=2)
        assert len(snippets) == 2
        s0 = snippets[0]
        assert s0.doc_id == "openai_2024_annual_letter.md"
        assert s0.doc_display_name == "openai_2024_annual_letter.md"
        assert s0.chunk_id == "openai_2024_annual_letter.md#1"
        assert s0.text.startswith("We continue to believe")
        assert s0.score == pytest.approx(0.91)
        assert s0.source_uri == "gs://b/annual.md"
        # The second snippet's chunk_id increments.
        assert snippets[1].chunk_id == "openai_founders_essay.md#2"

    def test_empty_response_yields_empty_list(self, monkeypatch):
        _install_fake_vertex_rag(monkeypatch, retrieve_contexts=[])
        vc = _vc()
        snippets = vc.retrieve("corpus/x", "any query")
        assert snippets == []

    def test_top_k_passed_through(self, monkeypatch):
        fake = _install_fake_vertex_rag(monkeypatch, retrieve_contexts=[])
        vc = _vc()
        vc.retrieve("corpus/x", "q", top_k=3)
        # RagRetrievalConfig was constructed with top_k=3.
        cfg_calls = fake.RagRetrievalConfig.call_args_list
        assert cfg_calls
        assert cfg_calls[-1].kwargs == {"top_k": 3}

    def test_falls_back_to_source_uri_when_display_name_missing(self, monkeypatch):
        # Some Vertex configurations return chunks without source_display_name.
        contexts = [
            _FakeContext(source_uri="gs://b/x.md", source_display_name="",
                         text="t", score=0.5),
        ]
        _install_fake_vertex_rag(monkeypatch, retrieve_contexts=contexts)
        vc = _vc()
        snippets = vc.retrieve("corpus/x", "q")
        # doc_id falls back to source_uri.
        assert snippets[0].doc_id == "gs://b/x.md"

    def test_falls_back_to_unknown_doc_when_both_missing(self, monkeypatch):
        contexts = [
            _FakeContext(source_uri=None, source_display_name=None, text="t"),
        ]
        _install_fake_vertex_rag(monkeypatch, retrieve_contexts=contexts)
        vc = _vc()
        snippets = vc.retrieve("corpus/x", "q")
        # Last-resort fallback for the doc_id keeps the schema valid.
        assert snippets[0].doc_id == "unknown_doc_1"


# ---------------------------------------------------------------------------
# Lazy import
# ---------------------------------------------------------------------------

class TestLazyImport:
    def test_raises_friendly_error_when_vertexai_missing(self, monkeypatch):
        # Force vertexai.rag to be un-importable.
        monkeypatch.setitem(sys.modules, "vertexai", None)
        monkeypatch.setitem(sys.modules, "vertexai.rag", None)
        vc = _vc()
        with pytest.raises(RuntimeError, match="google-cloud-aiplatform"):
            vc.build_or_get_corpus("x")


# ---------------------------------------------------------------------------
# list_files_in_corpus
# ---------------------------------------------------------------------------

class TestListFilesInCorpus:
    def test_returns_records_for_each_file(self, monkeypatch):
        existing = [
            _FakeFile(display_name="a.md", description="sha256=abc"),
            _FakeFile(display_name="b.md", description="sha256=def"),
        ]
        _install_fake_vertex_rag(monkeypatch, existing_files=existing)
        vc = _vc()
        records = vc.list_files_in_corpus("corpus/x")
        assert len(records) == 2
        assert records[0]["display_name"] == "a.md"
        assert records[0]["description"] == "sha256=abc"
