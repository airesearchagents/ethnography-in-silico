"""Tests for `rag.schemas` — `Citation` and `RetrievedSnippet`.

These schemas carry no behaviour; the tests check that
  - required fields are required,
  - optional fields default correctly,
  - JSON round-trip is lossless (so the manifest + persistence layer
    can serialise / deserialise without surprises),
  - default `citations=[]` shape on a host model serialises cleanly
    (mirrors how `AgentAction` / `StrategicArtefact` / `PanelResponse`
    carry the citations field).
"""

from __future__ import annotations

import importlib
import json

import pytest


def _rag_schemas():
    return importlib.import_module("open-innovation-strategy.rag.schemas")


class TestRetrievedSnippet:
    def test_minimal_construction(self):
        m = _rag_schemas()
        s = m.RetrievedSnippet(
            doc_id="openai_2024_annual_letter.md",
            chunk_id="openai_2024_annual_letter.md#1",
            text="We continue to believe broad accessibility accelerates safety research.",
        )
        assert s.doc_id == "openai_2024_annual_letter.md"
        assert s.chunk_id == "openai_2024_annual_letter.md#1"
        assert s.doc_display_name == ""  # default
        assert s.score == 0.0  # default
        assert s.source_uri is None  # default

    def test_required_fields(self):
        m = _rag_schemas()
        with pytest.raises(Exception):
            m.RetrievedSnippet(doc_id="x", chunk_id="y")  # missing text
        with pytest.raises(Exception):
            m.RetrievedSnippet(doc_id="x", text="t")  # missing chunk_id

    def test_json_roundtrip(self):
        m = _rag_schemas()
        s = m.RetrievedSnippet(
            doc_id="d",
            doc_display_name="DisplayName",
            chunk_id="d#3",
            text="Some chunk text.",
            score=0.82,
            source_uri="gs://bucket/path",
        )
        round_tripped = m.RetrievedSnippet.model_validate_json(s.model_dump_json())
        assert round_tripped == s


class TestCitation:
    def test_minimal_construction(self):
        m = _rag_schemas()
        c = m.Citation(
            doc_id="openai_2024_annual_letter.md",
            quote="Broad accessibility accelerates safety research.",
        )
        assert c.doc_id == "openai_2024_annual_letter.md"
        assert c.quote.startswith("Broad accessibility")
        assert c.chunk_id is None  # default
        assert c.supports == ""    # default

    def test_required_fields(self):
        m = _rag_schemas()
        with pytest.raises(Exception):
            m.Citation(doc_id="d")  # missing quote
        with pytest.raises(Exception):
            m.Citation(quote="some quote")  # missing doc_id

    def test_full_form(self):
        m = _rag_schemas()
        c = m.Citation(
            doc_id="d",
            chunk_id="d#2",
            quote="...verbatim quote...",
            supports="open-weight commitment",
        )
        assert c.chunk_id == "d#2"
        assert c.supports == "open-weight commitment"

    def test_json_roundtrip(self):
        m = _rag_schemas()
        c = m.Citation(
            doc_id="d",
            chunk_id="d#7",
            quote="some quote",
            supports="some claim",
        )
        round_tripped = m.Citation.model_validate_json(c.model_dump_json())
        assert round_tripped == c

    def test_citation_list_as_field_default(self):
        """`citations: List[Citation] = []` on AgentAction /
        StrategicArtefact / PanelResponse must serialise the default
        empty list as `[]`, not `null`. Verifies the shape downstream
        consumers (persistence, the citation auditor) rely on."""
        from pydantic import BaseModel
        m = _rag_schemas()

        class _Host(BaseModel):
            citations: list[m.Citation] = []

        host = _Host()
        assert host.citations == []
        # JSON shape: empty list, not null. Downstream renderers should
        # see "[]" so an absent citations field never indicates "this
        # was citing something but lost the list".
        data = json.loads(host.model_dump_json())
        assert data == {"citations": []}
