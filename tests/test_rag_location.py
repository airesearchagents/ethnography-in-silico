"""Retrieval has its own region, because Gemini 3.x needs `global` and RAG Engine refuses it."""

from __future__ import annotations

import importlib

import pytest

PKG = "open-innovation-strategy"


def _location():
    return importlib.import_module(f"{PKG}.rag.vertex_corpus").rag_location


def test_rag_location_wins_over_the_model_location(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")
    monkeypatch.setenv("RAG_LOCATION", "us-west1")
    assert _location()() == "us-west1"


def test_falls_back_to_the_model_location(monkeypatch):
    monkeypatch.delenv("RAG_LOCATION", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "europe-west4")
    assert _location()() == "europe-west4"


@pytest.mark.parametrize("location", ["", "global"])
def test_refuses_global_or_no_region(monkeypatch, location):
    monkeypatch.delenv("RAG_LOCATION", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", location)
    with pytest.raises(RuntimeError, match="RAG_LOCATION"):
        _location()()
