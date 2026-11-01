"""Per-session RAG runtime state.

RAG (retrieval-augmented generation) means searching a firm's documents and
adding the passages found to a role's prompt. This file keeps track, during
one run (also called a research session), of the document collection in use
and of every search made.

`RagSession` bundles everything a running research session needs to
know about its RAG corpus (its document collection):

  - `corpus_name`        the resource name in Vertex (Google's paid cloud
                         service), or None for no-RAG
  - `embedding_model`    the model that turns text into numbers standing for
                         meaning; captured for the manifest (the file
                         listing what produced a run)
  - `corpus_documents`   one record per doc that's in the corpus (display
                         name + SHA256, a fingerprint of the contents, +
                         source URI, its address); used to write the
                         corpus_manifest.json under 07_rag/
  - `top_k`              retrieval depth (how many passages each search
                         returns) used for every call
  - `retrieval_log`      one record per `retrieve_for_role` call —
                         written to 07_rag/retrieval_log.jsonl (JSONL: a
                         plain-text file with one record per line) at the
                         end of the session

A `RagSession` is constructed once at session start by
`build_rag_session_for_company(study, company)` and threaded through the
orchestrators (the code that runs each phase). When the study has no
`rag_corpus_loader` set, or the
loader returns None for this firm, `build_rag_session_for_company`
returns None — the orchestrator then knows to skip retrieval entirely
(every `retrieve_for_role` call is a no-op, doing nothing, anyway, but
skipping the
call early avoids constructing the query string at all).

Why not stateless functions
---------------------------
Stateless functions keep no record between uses. Two reasons:

1. The retrieval log accumulates across phases (the numbered stages of a
   run). A single mutable (changeable)
   object collects every retrieval and is then dumped to a JSONL file
   at persistence time. Passing the log as a separate argument across
   six functions would be noisy.

2. The orchestrator should be able to disable RAG mid-run (e.g. if
   Vertex returns repeated errors) by flipping a flag on the session,
   without unwinding the call stack (the chain of code parts now running) to
   remove the argument. The
   `.enabled` property is the seam for that — flip it to False and
   every subsequent `retrieve_for_role` returns `[]`. (No flip-able
   guard yet in v1 — added if needed.)
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from . import vertex_corpus as _vertex_corpus
    from .prompt_inject import excerpt_char_limit
    from .schemas import RetrievedSnippet
except ImportError:  # pragma: no cover  (script-style execution)
    from rag import vertex_corpus as _vertex_corpus  # type: ignore[no-redef]
    from rag.prompt_inject import excerpt_char_limit  # type: ignore[no-redef]
    from rag.schemas import RetrievedSnippet  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


# Default top-k retrieval depth. Aligns with `vertex_corpus.DEFAULT_TOP_K`.
DEFAULT_TOP_K = 5

# Default embedding model. Aligns with `vertex_corpus.DEFAULT_EMBEDDING_MODEL`.
DEFAULT_EMBEDDING_MODEL = _vertex_corpus.DEFAULT_EMBEDDING_MODEL


@dataclass
class RagSession:
    """Runtime state for one research session's RAG plumbing.

    A `None` `corpus_name` would be unusual here — by convention the
    framework's (the shared software's) loader resolver returns `None` instead of a
    no-name
    session — but the property `.enabled` covers that case cleanly so
    a defensively-built RagSession still degrades to no-op.
    """

    corpus_name: Optional[str]
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    corpus_documents: List[Dict[str, Any]] = field(default_factory=list)
    top_k: int = DEFAULT_TOP_K
    retrieval_log: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def enabled(self) -> bool:
        """Whether retrieval is active. Callers can short-circuit on this."""
        return bool(self.corpus_name)

    async def retrieve_for_role(
        self,
        *,
        role: str,
        query: str,
        phase: str,
    ) -> List[RetrievedSnippet]:
        """Run a retrieval for one role's turn, log it, return the snippets.

        Returns an empty list when the session is disabled (no corpus),
        the query is empty, or Vertex returns no snippets. Logs every
        call to `retrieval_log` — even disabled ones get a single
        skipped-retrieval record so the audit trail is complete.
        """
        if not self.enabled or not (query or "").strip():
            self.retrieval_log.append({
                "phase": phase,
                "role": role,
                "query": query or "",
                "retrieved_count": 0,
                "skipped_reason": "disabled" if not self.enabled else "empty_query",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return []

        # On its own thread (a separate line of work in the program) with a
        # timeout (giving up after waiting too long), so a slow or hung retrieval holds
        # up only this role and not every role sharing the event loop (the part of
        # the program that takes turns among waiting tasks).
        try:
            snippets = await asyncio.wait_for(
                asyncio.to_thread(
                    _vertex_corpus.retrieve,
                    self.corpus_name,  # type: ignore[arg-type]
                    query,
                    top_k=self.top_k,
                ),
                timeout=float(os.environ.get("TMT_RETRIEVAL_TIMEOUT_S", "60")),
            )
        except Exception as exc:  # noqa: BLE001  pragma: no cover
            logger.warning(
                "rag.retrieve_for_role: Vertex retrieval failed (role=%s, phase=%s): %s",
                role, phase, exc,
            )
            self.retrieval_log.append({
                "phase": phase,
                "role": role,
                "query": query,
                "retrieved_count": 0,
                "error": str(exc) or type(exc).__name__,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return []

        limit = excerpt_char_limit()
        self.retrieval_log.append({
            "phase": phase,
            "role": role,
            "query": query,
            "retrieved_count": len(snippets),
            "retrieved": [
                {
                    "doc_id": s.doc_id,
                    "chunk_id": s.chunk_id,
                    "score": s.score,
                    # Full chunk (passage) text. `shown_chars` says how much of it the
                    # role was shown (see prompt_inject), so a check of what
                    # a role saw stops there.
                    "text": s.text or "",
                    "shown_chars": (
                        len(s.text or "") if limit is None
                        else min(len(s.text or ""), limit)
                    ),
                }
                for s in snippets
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return snippets

    def manifest_dict(self) -> Dict[str, Any]:
        """Render the `corpus_manifest.json` / `manifest.rag_config` payload.

        Everything a reviewer needs to pin which corpus + which
        documents were available at run time:
          - corpus resource name (so they can re-list its files)
          - embedding model (so they know which vector space, meaning the
            numbering scheme its stored numbers use)
          - top_k (so they know retrieval depth)
          - per-document SHA256 + display name + source URI (so they
            can verify content drift)
        """
        return {
            "enabled": self.enabled,
            "corpus_resource_name": self.corpus_name,
            "embedding_model": self.embedding_model,
            "top_k": self.top_k,
            "documents": list(self.corpus_documents),
        }


def build_rag_session_for_company(
    *,
    study: Any,
    company: str,
    top_k: int = DEFAULT_TOP_K,
) -> Optional[RagSession]:
    """Resolve `study.rag_corpus_loader` for this company.

    The loader is an importable dotted path (the address of a piece of code) on
    `StudyConfig.rag_corpus_loader` (string, meaning plain text, not
    callable, meaning runnable code — see `studies/base.py` for the same
    rationale as `role_factories_module`). Format:
        "module.path:attribute"
    or  "module.path.attribute"   (last dotted segment is the attribute).

    The loaded callable is invoked with the company name. It returns
    either a dict (see below) or None. None means "this study has no
    corpus for this firm", and a `--rag` run then stops with an error.

    Loader return shape
    -------------------
    {
        "corpus_name": "projects/<proj>/locations/<loc>/ragCorpora/<id>",
        "embedding_model": "publishers/google/models/text-embedding-005",  # optional
        "documents": [
            {"display_name": "...", "sha256": "...", "source_uri": "..."},
            ...
        ],
    }

    Returns
    -------
    RagSession | None
        None means RAG is off for this run. The orchestrator handles
        that case transparently — every retrieve call is short-
        circuited.
    """
    loader_path: Optional[str] = getattr(study, "rag_corpus_loader", None)
    if not loader_path:
        return None

    # Accept both ":" and "." as the module/attribute separator. The
    # `:` form is slightly more explicit ("module:attr") and matches
    # what the entrypoints spec uses; the `.` form is what most
    # callers write naturally.
    if ":" in loader_path:
        module_path, attr_name = loader_path.rsplit(":", 1)
    else:
        module_path, attr_name = loader_path.rsplit(".", 1)

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        logger.warning(
            "rag.build_rag_session_for_company: cannot import loader module %r: %s",
            module_path, exc,
        )
        return None

    loader = getattr(module, attr_name, None)
    if not callable(loader):
        logger.warning(
            "rag.build_rag_session_for_company: loader %s is not callable", loader_path,
        )
        return None

    try:
        result = loader(company)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "rag.build_rag_session_for_company: loader(%s) raised: %s", company, exc,
        )
        return None

    if not result:
        logger.info(
            "rag.build_rag_session_for_company: loader returned None for company=%s — "
            "running without RAG",
            company,
        )
        return None

    return RagSession(
        corpus_name=result.get("corpus_name"),
        embedding_model=result.get("embedding_model", DEFAULT_EMBEDDING_MODEL),
        corpus_documents=list(result.get("documents", [])),
        top_k=top_k,
    )
