"""Tests for the `python -m rag.corpus_build` CLI.

Covers:
  - File discovery (recursive, supported extensions only, sorted).
  - Display-name construction.
  - argparse + main() return codes:
      * --dry-run prints plan but doesn't call Vertex
      * --company invokes build_or_get_corpus + upload_documents
      * --list invokes find_corpus + list_files_in_corpus
      * --delete-corpus without --yes is a no-op; with --yes deletes
      * --all-firms iterates rag_corpora/*/
      * missing --company without --all-firms exits non-zero

All vertex_corpus calls are mocked through monkeypatch on the resolved
module (same dual-namespace caveat as test_openness_rag_loader.py).
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _cb_mod():
    """The corpus-build CLI module the resolver loads."""
    return importlib.import_module("open-innovation-strategy.rag.corpus_build")


def _install_mock_vertex(monkeypatch):
    """Patch the four wrapper functions the CLI calls.

    Returns the patched module so the test can assert call shape.
    """
    cb = _cb_mod()
    vc = cb.vertex_corpus  # the module the CLI imports
    monkeypatch.setattr(vc, "build_or_get_corpus",
                        MagicMock(return_value="projects/p/locations/l/ragCorpora/x"))
    monkeypatch.setattr(vc, "upload_documents",
                        MagicMock(return_value=[]))
    monkeypatch.setattr(vc, "find_corpus",
                        MagicMock(return_value="projects/p/locations/l/ragCorpora/x"))
    monkeypatch.setattr(vc, "list_files_in_corpus",
                        MagicMock(return_value=[]))
    monkeypatch.setattr(vc, "delete_corpus", MagicMock())
    monkeypatch.setattr(vc, "rag_engine_tier", MagicMock(return_value="basic"))
    return vc


def _write_docs(dir_path: Path, files: list[tuple[str, str]]) -> Path:
    """Helper to materialise (filename, body) pairs under `dir_path`."""
    dir_path.mkdir(parents=True, exist_ok=True)
    for name, body in files:
        (dir_path / name).write_text(body)
    return dir_path


# ---------------------------------------------------------------------------
# discover_source_files
# ---------------------------------------------------------------------------

class TestDiscoverSourceFiles:
    def test_returns_supported_files_only(self, tmp_path):
        _write_docs(tmp_path, [
            ("annual.md", "..."),
            ("interview.txt", "..."),
            ("report.pdf", "..."),
            ("notes.docx", "..."),
            ("ignored.zip", "..."),
            ("ignored.png", "..."),
        ])
        m = _cb_mod()
        out = m.discover_source_files(tmp_path)
        names = sorted(p.name for p in out)
        assert names == ["annual.md", "interview.txt", "notes.docx", "report.pdf"]

    def test_skips_hidden_files(self, tmp_path):
        _write_docs(tmp_path, [
            ("annual.md", "..."),
            (".DS_Store", "..."),
        ])
        m = _cb_mod()
        out = m.discover_source_files(tmp_path)
        assert [p.name for p in out] == ["annual.md"]

    def test_recurses_into_subdirectories(self, tmp_path):
        _write_docs(tmp_path / "letters", [("annual.md", "...")])
        _write_docs(tmp_path / "blogs", [("post1.md", "...")])
        _write_docs(tmp_path / "transcripts", [("interview.txt", "...")])
        m = _cb_mod()
        out = m.discover_source_files(tmp_path)
        names = sorted(p.name for p in out)
        assert names == ["annual.md", "interview.txt", "post1.md"]

    def test_empty_dir_returns_empty_list(self, tmp_path):
        m = _cb_mod()
        assert m.discover_source_files(tmp_path) == []

    def test_missing_dir_returns_empty_list(self, tmp_path):
        m = _cb_mod()
        assert m.discover_source_files(tmp_path / "nope") == []

    def test_returns_sorted_order(self, tmp_path):
        _write_docs(tmp_path, [
            ("z.md", "..."), ("a.md", "..."), ("m.md", "..."),
        ])
        m = _cb_mod()
        out = m.discover_source_files(tmp_path)
        assert [p.name for p in out] == ["a.md", "m.md", "z.md"]


# ---------------------------------------------------------------------------
# corpus_display_name
# ---------------------------------------------------------------------------

class TestCorpusDisplayName:
    def test_combines_slug_and_company(self):
        m = _cb_mod()
        assert m.corpus_display_name(
            study_slug="openness_maneuvering", company="OpenAI",
        ) == "openness_maneuvering__OpenAI"

    def test_matches_loader_pattern(self):
        """The CLI's display-name MUST match what the openness loader
        looks up — otherwise a freshly-built corpus is invisible to
        the loader."""
        cb = _cb_mod()
        loader = importlib.import_module(
            "open-innovation-strategy.studies.openness_maneuvering.rag_loader"
        )
        built = cb.corpus_display_name(
            study_slug="openness_maneuvering", company="OpenAI",
        )
        expected = loader.CORPUS_DISPLAY_NAME_PATTERN.format(company="OpenAI")
        assert built == expected


# ---------------------------------------------------------------------------
# run_build (the upload path)
# ---------------------------------------------------------------------------

class TestRunBuild:
    def test_uploads_each_discovered_file(self, monkeypatch, tmp_path, capsys):
        vc = _install_mock_vertex(monkeypatch)
        # upload returns a record per path (mimics what the wrapper does).
        vc.upload_documents.return_value = [
            {"path": str(tmp_path / "a.md"), "display_name": "a.md",
             "sha256": "abc", "uploaded": True},
            {"path": str(tmp_path / "b.txt"), "display_name": "b.txt",
             "sha256": "def", "uploaded": True},
        ]
        _write_docs(tmp_path, [("a.md", "..."), ("b.txt", "...")])

        m = _cb_mod()
        rc = m.run_build(
            company="OpenAI", study_slug="openness_maneuvering",
            docs_dir=tmp_path, dry_run=False,
        )
        assert rc == 0
        vc.build_or_get_corpus.assert_called_once_with(
            "openness_maneuvering__OpenAI",
        )
        vc.upload_documents.assert_called_once()
        out = capsys.readouterr().out
        assert "2 uploaded" in out
        assert "0 skipped" in out
        assert "a.md" in out
        assert "b.txt" in out

    def test_dry_run_does_not_call_vertex(self, monkeypatch, tmp_path, capsys):
        vc = _install_mock_vertex(monkeypatch)
        _write_docs(tmp_path, [("a.md", "...")])
        m = _cb_mod()
        rc = m.run_build(
            company="OpenAI", study_slug="openness_maneuvering",
            docs_dir=tmp_path, dry_run=True,
        )
        assert rc == 0
        vc.build_or_get_corpus.assert_not_called()
        vc.upload_documents.assert_not_called()
        out = capsys.readouterr().out
        assert "[dry run]" in out

    def test_empty_dir_returns_nonzero_non_dry_run(self, monkeypatch, tmp_path, capsys):
        _install_mock_vertex(monkeypatch)
        m = _cb_mod()
        rc = m.run_build(
            company="OpenAI", study_slug="openness_maneuvering",
            docs_dir=tmp_path, dry_run=False,
        )
        assert rc == 1
        assert "no source files found" in capsys.readouterr().out

    def test_empty_dir_returns_zero_under_dry_run(self, monkeypatch, tmp_path):
        _install_mock_vertex(monkeypatch)
        m = _cb_mod()
        rc = m.run_build(
            company="OpenAI", study_slug="openness_maneuvering",
            docs_dir=tmp_path, dry_run=True,
        )
        assert rc == 0

    def test_corpus_build_failure_returns_nonzero(self, monkeypatch, tmp_path):
        vc = _install_mock_vertex(monkeypatch)
        vc.build_or_get_corpus.side_effect = RuntimeError("vertex unreachable")
        _write_docs(tmp_path, [("a.md", "...")])
        m = _cb_mod()
        rc = m.run_build(
            company="OpenAI", study_slug="openness_maneuvering",
            docs_dir=tmp_path, dry_run=False,
        )
        assert rc == 2

    def test_upload_failure_returns_nonzero(self, monkeypatch, tmp_path):
        vc = _install_mock_vertex(monkeypatch)
        vc.upload_documents.side_effect = RuntimeError("upload blew up")
        _write_docs(tmp_path, [("a.md", "...")])
        m = _cb_mod()
        rc = m.run_build(
            company="OpenAI", study_slug="openness_maneuvering",
            docs_dir=tmp_path, dry_run=False,
        )
        assert rc == 3


# ---------------------------------------------------------------------------
# run_list
# ---------------------------------------------------------------------------

class TestRunList:
    def test_lists_files_when_corpus_exists(self, monkeypatch, capsys):
        vc = _install_mock_vertex(monkeypatch)
        vc.list_files_in_corpus.return_value = [
            {"display_name": "annual.md", "description": "sha256=abcdef"},
            {"display_name": "interview.txt", "description": "sha256=fedcba"},
        ]
        m = _cb_mod()
        rc = m.run_list(company="OpenAI", study_slug="openness_maneuvering")
        assert rc == 0
        out = capsys.readouterr().out
        assert "files: 2" in out
        assert "annual.md" in out
        assert "interview.txt" in out

    def test_returns_zero_when_corpus_absent(self, monkeypatch, capsys):
        vc = _install_mock_vertex(monkeypatch)
        vc.find_corpus.return_value = None
        m = _cb_mod()
        rc = m.run_list(company="Unknown", study_slug="openness_maneuvering")
        assert rc == 0
        assert "no corpus found" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# run_delete
# ---------------------------------------------------------------------------

class TestRunDelete:
    def test_without_yes_is_no_op(self, monkeypatch, capsys):
        vc = _install_mock_vertex(monkeypatch)
        m = _cb_mod()
        rc = m.run_delete(
            company="OpenAI", study_slug="openness_maneuvering", yes=False,
        )
        assert rc == 0
        vc.delete_corpus.assert_not_called()
        assert "re-run with --yes" in capsys.readouterr().out

    def test_with_yes_deletes(self, monkeypatch, capsys):
        vc = _install_mock_vertex(monkeypatch)
        m = _cb_mod()
        rc = m.run_delete(
            company="OpenAI", study_slug="openness_maneuvering", yes=True,
        )
        assert rc == 0
        vc.delete_corpus.assert_called_once()

    def test_absent_corpus_is_no_op(self, monkeypatch, capsys):
        vc = _install_mock_vertex(monkeypatch)
        vc.find_corpus.return_value = None
        m = _cb_mod()
        rc = m.run_delete(
            company="Unknown", study_slug="openness_maneuvering", yes=True,
        )
        assert rc == 0
        vc.delete_corpus.assert_not_called()


# ---------------------------------------------------------------------------
# run_all_firms
# ---------------------------------------------------------------------------

class TestRunAllFirms:
    def test_iterates_each_subdirectory(self, monkeypatch, tmp_path):
        vc = _install_mock_vertex(monkeypatch)
        # 3 firm folders, each with at least one supported doc.
        _write_docs(tmp_path / "OpenAI", [("a.md", "x")])
        _write_docs(tmp_path / "Meta", [("b.md", "y")])
        _write_docs(tmp_path / "Anthropic", [("c.md", "z")])
        # A leading-underscore folder is skipped (the README convention).
        _write_docs(tmp_path / "_test_alt", [("d.md", "w")])
        # The README.md at the root is at the parent level, not a firm.

        m = _cb_mod()
        rc = m.run_all_firms(
            study_slug="openness_maneuvering",
            corpora_root=tmp_path, dry_run=False,
        )
        assert rc == 0
        # 3 build_or_get_corpus calls — one per firm, _test_alt skipped.
        assert vc.build_or_get_corpus.call_count == 3
        # And 3 uploads.
        assert vc.upload_documents.call_count == 3

    def test_missing_root_returns_nonzero(self, monkeypatch, tmp_path, capsys):
        _install_mock_vertex(monkeypatch)
        m = _cb_mod()
        rc = m.run_all_firms(
            study_slug="openness_maneuvering",
            corpora_root=tmp_path / "nope", dry_run=False,
        )
        assert rc == 1
        assert "does not exist" in capsys.readouterr().out

    def test_empty_root_returns_nonzero(self, monkeypatch, tmp_path, capsys):
        _install_mock_vertex(monkeypatch)
        m = _cb_mod()
        rc = m.run_all_firms(
            study_slug="openness_maneuvering",
            corpora_root=tmp_path, dry_run=False,
        )
        assert rc == 1
        assert "no firm subdirectories found" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# main() — argparse + dispatch
# ---------------------------------------------------------------------------

class TestMainDispatch:
    def test_no_company_no_all_firms_errors(self, monkeypatch, capsys):
        _install_mock_vertex(monkeypatch)
        m = _cb_mod()
        rc = m.main([])
        assert rc == 1
        assert "--company is required" in capsys.readouterr().out

    def test_company_dry_run(self, monkeypatch, tmp_path):
        vc = _install_mock_vertex(monkeypatch)
        _write_docs(tmp_path, [("a.md", "x")])
        m = _cb_mod()
        rc = m.main([
            "--company", "OpenAI",
            "--docs-dir", str(tmp_path),
            "--dry-run",
        ])
        assert rc == 0
        vc.build_or_get_corpus.assert_not_called()

    def test_company_real_build(self, monkeypatch, tmp_path):
        vc = _install_mock_vertex(monkeypatch)
        _write_docs(tmp_path, [("a.md", "x")])
        vc.upload_documents.return_value = [
            {"path": str(tmp_path / "a.md"), "display_name": "a.md",
             "sha256": "abc", "uploaded": True},
        ]
        m = _cb_mod()
        rc = m.main([
            "--company", "OpenAI",
            "--docs-dir", str(tmp_path),
        ])
        assert rc == 0
        vc.build_or_get_corpus.assert_called_once()
        vc.upload_documents.assert_called_once()

    def test_list_mode(self, monkeypatch):
        vc = _install_mock_vertex(monkeypatch)
        m = _cb_mod()
        rc = m.main(["--company", "OpenAI", "--list"])
        assert rc == 0
        vc.find_corpus.assert_called_once()
        vc.list_files_in_corpus.assert_called_once()

    def test_delete_without_yes_is_dry(self, monkeypatch):
        vc = _install_mock_vertex(monkeypatch)
        m = _cb_mod()
        rc = m.main(["--company", "OpenAI", "--delete-corpus"])
        assert rc == 0
        vc.delete_corpus.assert_not_called()

    def test_delete_with_yes(self, monkeypatch):
        vc = _install_mock_vertex(monkeypatch)
        m = _cb_mod()
        rc = m.main(["--company", "OpenAI", "--delete-corpus", "--yes"])
        assert rc == 0
        vc.delete_corpus.assert_called_once()

    def test_all_firms_incompatible_with_list(self, monkeypatch, capsys):
        _install_mock_vertex(monkeypatch)
        m = _cb_mod()
        rc = m.main(["--all-firms", "--list"])
        assert rc == 1
        assert "incompatible" in capsys.readouterr().out

    def test_study_override(self, monkeypatch, tmp_path):
        vc = _install_mock_vertex(monkeypatch)
        _write_docs(tmp_path, [("a.md", "x")])
        vc.upload_documents.return_value = [
            {"path": str(tmp_path / "a.md"), "display_name": "a.md",
             "sha256": "abc", "uploaded": True},
        ]
        m = _cb_mod()
        rc = m.main([
            "--company", "Pfizer",
            "--study", "absorptive_capacity",
            "--docs-dir", str(tmp_path),
        ])
        assert rc == 0
        vc.build_or_get_corpus.assert_called_with(
            "absorptive_capacity__Pfizer",
        )


class TestRagEngineTier:
    def _build(self, tmp_path, **kwargs):
        _write_docs(tmp_path, [("a.md", "words")])
        return _cb_mod().run_build(
            company="ACME", study_slug="s", docs_dir=tmp_path, **kwargs,
        )

    def test_refuses_the_scaled_tier(self, monkeypatch, tmp_path, capsys):
        vc = _install_mock_vertex(monkeypatch)
        vc.rag_engine_tier = MagicMock(return_value="scaled")
        assert self._build(tmp_path) == 2
        vc.upload_documents.assert_not_called()
        assert "Scaled" in capsys.readouterr().out

    def test_scaled_is_allowed_when_asked_for(self, monkeypatch, tmp_path):
        vc = _install_mock_vertex(monkeypatch)
        vc.rag_engine_tier = MagicMock(return_value="scaled")
        assert self._build(tmp_path, allow_scaled=True) == 0
        vc.upload_documents.assert_called_once()

    def test_an_unreadable_tier_warns_and_continues(self, monkeypatch, tmp_path, capsys):
        vc = _install_mock_vertex(monkeypatch)
        vc.rag_engine_tier = MagicMock(side_effect=RuntimeError("no access"))
        assert self._build(tmp_path) == 0
        assert "could not read" in capsys.readouterr().out
