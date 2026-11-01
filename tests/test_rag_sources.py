"""Tests for the `python -m rag.sources` source-list check.

Covers:
  - All listed documents present and matching -> no problems, exit 0.
  - A changed document and a missing document are both reported, exit 1.
  - The `--column` option checks an alternative layout (e.g. pilot_path).
  - The committed rag_corpora/SOURCES.csv is well formed.
"""

from __future__ import annotations

import csv
import hashlib
import importlib
from pathlib import Path


def _mod():
    return importlib.import_module("open-innovation-strategy.rag.sources")


def _write_list(path: Path, rows: list[dict]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["doc_id", "path", "pilot_path", "sha256"])
        w.writeheader()
        w.writerows(rows)
    return path


def _setup(tmp_path: Path):
    root = tmp_path / "corpora"
    (root / "Acme").mkdir(parents=True)
    a = root / "Acme" / "a.txt"
    b = root / "Acme" / "b.txt"
    a.write_text("first document")
    b.write_text("second document")
    rows = [
        {"doc_id": "acme-int-01", "path": "Acme/a.txt", "pilot_path": "old/a.txt",
         "sha256": hashlib.sha256(b"first document").hexdigest()},
        {"doc_id": "acme-int-02", "path": "Acme/b.txt", "pilot_path": "old/b.txt",
         "sha256": hashlib.sha256(b"second document").hexdigest()},
    ]
    return root, rows


def test_all_present_and_matching(tmp_path):
    root, rows = _setup(tmp_path)
    assert _mod().check_sources(rows, root) == []
    sources = _write_list(tmp_path / "SOURCES.csv", rows)
    assert _mod().main(["--root", str(root), "--sources", str(sources)]) == 0


def test_changed_and_missing_documents_are_reported(tmp_path):
    root, rows = _setup(tmp_path)
    (root / "Acme" / "a.txt").write_text("edited")
    (root / "Acme" / "b.txt").unlink()
    problems = _mod().check_sources(rows, root)
    assert len(problems) == 2
    assert "content differs" in problems[0] and "acme-int-01" in problems[0]
    assert "missing" in problems[1] and "acme-int-02" in problems[1]
    sources = _write_list(tmp_path / "SOURCES.csv", rows)
    assert _mod().main(["--root", str(root), "--sources", str(sources)]) == 1


def test_alternative_column(tmp_path):
    root, rows = _setup(tmp_path)
    (root / "old").mkdir()
    (root / "old" / "a.txt").write_text("first document")
    (root / "old" / "b.txt").write_text("second document")
    assert _mod().check_sources(rows, root, column="pilot_path") == []


def test_committed_source_list_is_well_formed():
    rows = _mod().load_sources(_mod().DEFAULT_SOURCES)
    assert rows, "rag_corpora/SOURCES.csv is empty"
    ids = [r["doc_id"] for r in rows]
    assert len(ids) == len(set(ids)), "doc_id values must be unique"
    for r in rows:
        assert len(r["sha256"]) == 64, r["doc_id"]
        assert r["path"].split("/", 1)[0] == r["firm"], r["doc_id"]
        assert r["source_type"] in {"interview", "earnings_call", "case_study"}, r["doc_id"]
