"""RAG corpus loader for the openness_maneuvering study.

RAG (retrieval-augmented generation) means searching a document collection, the
corpus, and adding the passages found to an agent's prompt (the text sent to
it). This file finds a firm's corpus in Google's cloud service at the start of
a run. It never creates one.

What this module exports
------------------------
`load_corpus(company: str) -> Optional[dict]` — the callable (the runnable code)
referenced by `StudyConfig.rag_corpus_loader` (which holds the dotted-path
string, the code's address, not the callable itself, so the manifest, the file
listing what produced a run, stays JSON-clean, meaning savable as plain text).

The loader is **read-only**: it looks up a corpus in Vertex AI RAG Engine
(Google's paid service that stores and searches document collections) by
display name (`openness_maneuvering__<Company>`) and returns its
identity + the documents currently uploaded. It deliberately does NOT
auto-create a corpus when none exists — that path would silently give
the operator an empty vector store (the searchable store of a corpus's
embeddings, numbers standing for meaning) and a long run with no citations.
Instead a missing corpus surfaces as `None`, and a `--rag` run then stops
with an error before it spends anything (`run_research_session.py`).

How to populate a corpus
------------------------
Use the build CLI (command-line tool):

    python -m rag.corpus_build --company OpenAI \\
        --docs-dir rag_corpora/OpenAI/

That command will (a) create the corpus `openness_maneuvering__OpenAI`
if it doesn't exist, (b) idempotently (safely repeatable) upload every file
under
`rag_corpora/OpenAI/` (skipping any already-uploaded by display name),
(c) compute and record local SHA256s (short fingerprints of file contents) so
the manifest pins which
content went in.

Once the corpus is populated, a subsequent `--rag` run (one that uses
documents) resolves it
via this loader and threads retrieval (the search step) through Phases
1 / 2 / 4 (deliberation, strategy documents, debrief).

Loader return shape
-------------------
Matches the contract that `rag.runtime.build_rag_session_for_company`
expects:

    {
        "corpus_name": "projects/<proj>/locations/<loc>/ragCorpora/<id>",
        "embedding_model": "publishers/google/models/text-embedding-005",
        "documents": [
            {"display_name": "openai_2024_annual_letter.md",
             "description": "sha256=abc...",
             "sha256": "abc...",
             "source_uri": "gs://..."},
            ...
        ],
    }

The loader extracts the SHA256 from the Vertex file's `description`
field (the build CLI writes it there as `sha256=<hex>` by convention)
so reviewers can verify corpus content didn't drift between runs.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

# Dual-import pattern (relative for pkg-style, flat for script-style)
# matches the convention used across the rest of the codebase —
# `orchestrator/*.py`, `analysis/*.py`, etc.
try:
    from ...rag import vertex_corpus as _vertex_corpus
except (ImportError, ValueError):  # pragma: no cover  (script-style execution)
    from rag import vertex_corpus as _vertex_corpus  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


# Display-name pattern for the corpus this study expects. The build CLI
# writes corpora under this pattern; this loader looks them up. Mismatch
# means the loader returns None and a `--rag` run stops with an error.
CORPUS_DISPLAY_NAME_PATTERN = "openness_maneuvering__{company}"


# Pre-compiled extractor for the SHA256 the build CLI writes into a
# file's `description` field as `sha256=<hex>`. The capture group is
# 64 hex chars; we don't enforce length so future variants (e.g.
# different hash) still resolve.
_SHA_RE = re.compile(r"sha256=([0-9a-fA-F]+)")


def _extract_sha256(description: str) -> str:
    """Pull the SHA256 from a Vertex file's description field, if present."""
    if not description:
        return ""
    m = _SHA_RE.search(description)
    return m.group(1) if m else ""


def load_corpus(company: str) -> Optional[dict]:
    """Resolve the Vertex RAG corpus for `<study>__<Company>` if it exists.

    Returns the corpus payload `rag.runtime.build_rag_session_for_company`
    expects, or `None` if:
      - no corpus with the expected display name exists in the active
        Vertex project + location, OR
      - the Vertex SDK (Google's software kit) is missing / GCP (Google Cloud
        Platform) auth (proof of identity) isn't configured (lazy
        import in `rag.vertex_corpus`).

    A `--rag` run treats `None` as an error and stops, because a run that
    quietly went ungrounded (without documents) would cost a full run and
    give the wrong condition.
    """
    # `_vertex_corpus` is imported at module-load time via the dual-
    # import pattern at the top of this module; using a module-level
    # binding (rather than a per-call lazy import) keeps `monkeypatch.
    # setattr(_vertex_corpus, ...)` working in the test suite.
    vertex_corpus = _vertex_corpus

    display_name = CORPUS_DISPLAY_NAME_PATTERN.format(company=company)

    # Look up the corpus by display name (does NOT create).
    try:
        corpus_name = vertex_corpus.find_corpus(display_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "openness_maneuvering.rag_loader: find_corpus(%s) failed: %s",
            display_name, exc,
        )
        return None

    if not corpus_name:
        logger.info(
            "openness_maneuvering.rag_loader: no corpus found with display_name=%s "
            "(build it via `python -m rag.corpus_build --company %s`)",
            display_name, company,
        )
        return None

    # List the files currently in the corpus. Build CLI writes the
    # SHA256 into each file's description field; we surface that
    # alongside the display name so the manifest pins content.
    try:
        file_records = vertex_corpus.list_files_in_corpus(corpus_name)
    except Exception as exc:  # noqa: BLE001  pragma: no cover
        logger.warning(
            "openness_maneuvering.rag_loader: list_files_in_corpus(%s) failed: %s",
            corpus_name, exc,
        )
        file_records = []

    documents = []
    for r in file_records:
        documents.append({
            "display_name": r.get("display_name", ""),
            "description": r.get("description", ""),
            "sha256": _extract_sha256(r.get("description", "")),
            # Vertex's file listing exposes `name` (the file's resource
            # name) but not the original gs:// source_uri the upload
            # came from. Surface what we have; reviewers can resolve
            # name → uri via the Vertex console if needed.
            "vertex_file_name": r.get("name", ""),
        })

    logger.info(
        "openness_maneuvering.rag_loader: resolved %s for company=%s with %d docs",
        corpus_name, company, len(documents),
    )

    return {
        "corpus_name": corpus_name,
        "embedding_model": vertex_corpus.DEFAULT_EMBEDDING_MODEL,
        "documents": documents,
    }
