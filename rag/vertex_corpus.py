"""Thin wrapper around Google Vertex AI's RAG Engine.

Vertex AI is Google's paid cloud service. Its RAG Engine (RAG:
retrieval-augmented generation) stores a firm's document collection and
searches it, so that the passages found can be added to an agent's prompt (the
text sent to it). A wrapper is code that hides another service's details: the
rest of the software calls these few commands rather than Google's own.

Three primitives (basic commands):

- `build_or_get_corpus(display_name)` — idempotent (safe to repeat, since a
  second go changes nothing). Returns the resource name (Google's full address)
  of the corpus (the document collection), creating it if no corpus with
  that display name
  exists. One corpus per firm; the framework (the shared software) picks display
  names like
  `openness_study__OpenAI`.

- `upload_documents(corpus_name, paths)` — idempotent. Computes the SHA256
  (a short fingerprint of the contents) of each local file, skips any
  document whose display name is already
  uploaded, otherwise uploads. Returns one record per path including
  the SHA so the run's manifest (the file listing what produced a run) can
  pin which content went into the
  corpus.

- `retrieve(corpus_name, query, top_k)` — runs a similarity query (a search by
  closeness of meaning) and returns a list of `RetrievedSnippet` (up to `top_k`
  passages found). The orchestrator (the code that runs each phase) calls this before
  each role's LLM (large language model) call in Phases 1, 2, and 4
  (deliberation, strategy documents and debrief).

Why a wrapper exists at all
---------------------------
1. `vertexai.rag` is imported lazily (only when needed) so the rest of the
   codebase loads without the SDK (Google's software kit) or GCP (Google Cloud
   Platform) auth (proof of identity) being present. Tests that don't need
   live retrieval don't need to install or authenticate Vertex.

2. The SDK's retrieval response shape (`RetrieveContextsResponse` →
   `.contexts.contexts[*]`) is awkward and version-sensitive. The
   wrapper translates it into the framework's `RetrievedSnippet` once,
   so every downstream consumer sees a stable Pydantic shape (a fixed record
   layout, checked by the Pydantic tool).

3. Adding a per-file SHA256 (computed locally before upload) lets the
   replication manifest pin which content went into the corpus —
   important because the corpus state lives in GCP and is not in git (the tool
   that keeps the repository's shared history).

Auth
----
Retrieval has its own region (the location of the rented computers),
`RAG_LOCATION`, which falls back to `GOOGLE_CLOUD_LOCATION`. Gemini 3.x models
(Gemini: Google's language models) need `global`, and RAG Engine has no `global`
endpoint (web address for requests), so a run on those models must set
`RAG_LOCATION`.
Check the region's RAG Engine tier (price level) before creating a corpus:
`Scaled` runs at least one node (unit of rented capacity) of Spanner (the
Google database behind the corpus) and bills until the tier is set to
`Unprovisioned`.

Costs
-----
Vertex RAG bills per (a) the region's RagManagedDb Spanner instance, which
bills by tier for as long as it exists, whatever the corpus size, (b)
embedding generation (turning text into lists of numbers,
called vectors, that stand for its meaning) at upload time (one-time per doc),
(c) retrieval queries (per-1k-token rate, a token being a small piece of text;
roughly $0.0001 per top-k query, one returning the k closest passages, at
top_k=5). For the 40-run study sweep (a planned set of runs) at ~250
retrievals per
run, total retrieval cost is well under $10.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, List, Optional

from .schemas import RetrievedSnippet

logger = logging.getLogger(__name__)


# Default Vertex embedding model (the model that makes those vectors).
# text-embedding-005 is the current
# (2025) general-purpose text embedding model on Vertex; the framework
# pins to it so the manifest's `rag_config.embedding_model` is
# unambiguous. Bump this only when re-uploading all corpora — embedding
# models are not interchangeable for retrieval (the corpus's vectors
# would be in the wrong space).
DEFAULT_EMBEDDING_MODEL = "publishers/google/models/text-embedding-005"

# Default chunking (cutting documents into passages, or chunks). Vertex RAG
# chunks at upload time; the framework
# picks ~1000-token chunks with ~200-token overlap as a sensible
# starting point for the two document classes in the openness corpus
# (annual reports / SEC filings / annual letters, and podcast /
# long-form interview transcripts). Chunk size is calibrated
# empirically — a future PR (pull request, a proposed set of changes) may
# move this onto `StudyConfig` for
# per-study override.
DEFAULT_CHUNK_SIZE = 1024
DEFAULT_CHUNK_OVERLAP = 200

# Default retrieval depth. Each LLM call sees this many snippets in the
# "REFERENCE MATERIAL" prompt block. Top-k = 5 keeps the prompt-token
# overhead bounded (~5 × ~250 tokens per chunk = ~1.25 k extra input
# tokens per call) while giving the role enough material to choose
# from. Configurable per-call in the orchestrator if needed.
DEFAULT_TOP_K = 5


def _import_rag() -> Any:
    """Lazy import. Raises a friendly error if `vertexai.rag` is missing.

    Centralised so the rest of the wrapper can call `_import_rag()` and
    immediately use the returned module — no try/except scatter.
    """
    try:
        from vertexai import rag  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised only without SDK
        raise RuntimeError(
            "Vertex RAG support requires `google-cloud-aiplatform`. "
            "Install it (it should already be in the framework's "
            "requirements for the Gemini-via-Vertex path) and ensure "
            "GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_LOCATION env vars are "
            "set + `gcloud auth application-default login` has been run."
        ) from exc
    _init_rag_region()
    return rag


def rag_location() -> str:
    """Region for RAG Engine calls. Raises if none is set or it is `global`."""
    location = (
        os.environ.get("RAG_LOCATION", "").strip()
        or os.environ.get("GOOGLE_CLOUD_LOCATION", "").strip()
    )
    if not location or location == "global":
        raise RuntimeError(
            "RAG Engine needs a regional endpoint, but the location is "
            f"{location or 'unset'!r}. Set RAG_LOCATION to a region where the "
            "project's RAG Engine tier suits the work."
        )
    return location


def rag_engine_tier() -> str:
    """The project's RAG Engine tier in this region, such as basic or scaled.

    The tier sets the database's bill, whatever the corpus's size: Scaled costs
    about ten times Basic, and both bill until the tier is set to Unprovisioned.
    """
    import google.auth
    import google.auth.transport.requests
    import requests

    credentials, default_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(google.auth.transport.requests.Request())
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or default_project
    region = rag_location()
    reply = requests.get(
        f"https://{region}-aiplatform.googleapis.com/v1beta1/projects/{project}"
        f"/locations/{region}/ragEngineConfig",
        headers={
            "Authorization": f"Bearer {credentials.token}",
            "x-goog-user-project": project,
        },
        timeout=30,
    )
    reply.raise_for_status()
    return next(iter(reply.json().get("ragManagedDbConfig") or {}), "unknown")


def _init_rag_region() -> None:
    """Point the `vertexai` SDK at the retrieval region only.

    Gemini routing reads `GOOGLE_CLOUD_LOCATION` separately, so this does not
    move model calls.
    """
    import vertexai  # type: ignore[import-untyped]

    vertexai.init(
        project=os.environ.get("GOOGLE_CLOUD_PROJECT") or None,
        location=rag_location(),
    )


def _sha256_of_file(path: Path) -> str:
    """Compute the SHA256 of a local file in 64 KB chunks (memory-friendly)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def find_corpus(display_name: str) -> Optional[str]:
    """Look up a corpus by display name. Read-only — does NOT create.

    Returns the resource name of the corpus whose `display_name`
    matches, or None if no corpus with that display name exists in
    the active Vertex project + location.

    Use this when the caller wants to know "is there a corpus for
    this firm?" without the side-effect of accidentally creating an
    empty one. The study-level RAG loader uses this so that a missing
    corpus surfaces as a "no RAG for this firm" log line instead of
    silently creating a vector store (a store that keeps embeddings, the numbers
    standing for texts, and finds the closest matches) with no documents in it.
    """
    rag = _import_rag()
    for corpus in rag.list_corpora():
        if corpus.display_name == display_name:
            return corpus.name
    return None


def build_or_get_corpus(
    display_name: str,
    *,
    embedding_publisher_model: str = DEFAULT_EMBEDDING_MODEL,
) -> str:
    """Return the resource name of the corpus with this display name.

    If a corpus with this display name already exists in the active
    Vertex project + location, returns its resource name without
    recreation. Otherwise creates a fresh corpus configured with the
    given embedding model and returns the new resource name.

    The framework picks display names by convention:
        `<study_slug>__<company>`
    e.g. `openness_maneuvering__OpenAI`. This makes per-firm corpora
    discoverable and lets multiple studies share a Vertex project
    without colliding.

    Returns
    -------
    str
        The Vertex resource name, of the form
        `projects/<proj>/locations/<loc>/ragCorpora/<id>`. This is what
        every subsequent `upload_documents` / `retrieve` call needs to
        identify the corpus.
    """
    existing = find_corpus(display_name)
    if existing:
        logger.info("rag.build_or_get_corpus: found existing %s -> %s",
                    display_name, existing)
        return existing
    logger.info("rag.build_or_get_corpus: creating new corpus %s", display_name)
    rag = _import_rag()
    new_corpus = rag.create_corpus(
        display_name=display_name,
        backend_config=rag.RagVectorDbConfig(
            rag_embedding_model_config=rag.RagEmbeddingModelConfig(
                vertex_prediction_endpoint=rag.VertexPredictionEndpoint(
                    publisher_model=embedding_publisher_model,
                ),
            ),
        ),
    )
    return new_corpus.name


def upload_documents(
    corpus_name: str,
    paths: List[Path],
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> List[dict]:
    """Upload (or skip if already-uploaded) each local file to the corpus.

    Idempotence
    -----------
    Skips a file whose `display_name` (== filename) is already a member
    of the corpus's file list. This means re-running the build script
    after adding one new document only uploads the new one. If a
    document needs to be re-uploaded (e.g. its content changed), the
    caller should `rag.delete_file(...)` it first — this wrapper does
    not detect content changes, only display-name collisions.

    The SHA256 is computed locally before upload regardless of whether
    the file is actually uploaded; it lands in the returned record so
    the run's manifest pins which content was in the corpus at the
    time of this run. A reviewer comparing two runs can detect corpus
    drift by SHA mismatch.

    Returns
    -------
    list[dict]
        One record per input path:
            {"path": str, "display_name": str, "sha256": str,
             "uploaded": bool}
        `uploaded=False` means "already in the corpus, skipped".
    """
    rag = _import_rag()
    existing_names = {f.display_name for f in rag.list_files(corpus_name=corpus_name)}
    transform_cfg = rag.TransformationConfig(
        chunking_config=rag.ChunkingConfig(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    )
    records: List[dict] = []
    for path in paths:
        path = Path(path)
        display_name = path.name
        sha = _sha256_of_file(path)
        if display_name in existing_names:
            logger.info("rag.upload_documents: skip (already present) %s", display_name)
            records.append({
                "path": str(path),
                "display_name": display_name,
                "sha256": sha,
                "uploaded": False,
            })
            continue
        logger.info("rag.upload_documents: uploading %s (sha256=%s)",
                    display_name, sha[:12])
        rag.upload_file(
            corpus_name=corpus_name,
            path=str(path),
            display_name=display_name,
            description=f"sha256={sha}",
            transformation_config=transform_cfg,
        )
        records.append({
            "path": str(path),
            "display_name": display_name,
            "sha256": sha,
            "uploaded": True,
        })
    return records


def retrieve(
    corpus_name: str,
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
) -> List[RetrievedSnippet]:
    """Run a similarity query against the corpus, return top-k snippets.

    The orchestrator calls this once per role per LLM call in Phases 1,
    2, and 4. The query is built from `(role, current task, last few
    transcript entries)` by the orchestrator's prompt-composition layer;
    this function does not see role / study context — it just translates
    a query string into snippets.

    Empty queries are sent through unmodified; Vertex returns an empty
    `contexts.contexts` list, which becomes an empty `[]` here. The
    orchestrator should treat that as "no retrieval material this turn"
    and skip the REFERENCE MATERIAL prompt block.
    """
    rag = _import_rag()
    response = rag.retrieval_query(
        rag_resources=[rag.RagResource(rag_corpus=corpus_name)],
        text=query,
        rag_retrieval_config=rag.RagRetrievalConfig(top_k=top_k),
    )
    snippets: List[RetrievedSnippet] = []
    # The SDK response is RetrieveContextsResponse → .contexts.contexts
    # where each item has source_uri, source_display_name, text, score.
    inner_contexts = getattr(getattr(response, "contexts", None), "contexts", []) or []
    for idx, ctx in enumerate(inner_contexts, start=1):
        display_name = getattr(ctx, "source_display_name", "") or ""
        source_uri = getattr(ctx, "source_uri", None)
        # Pick the most stable identifier available.
        doc_id = display_name or (source_uri or f"unknown_doc_{idx}")
        # chunk_id reflects this retrieval's ordering; stable within one
        # call but not across calls because Vertex re-ranks per query.
        chunk_id = f"{doc_id}#{idx}"
        snippets.append(RetrievedSnippet(
            doc_id=doc_id,
            doc_display_name=display_name,
            chunk_id=chunk_id,
            text=getattr(ctx, "text", "") or "",
            score=float(getattr(ctx, "score", 0.0) or 0.0),
            source_uri=source_uri,
        ))
    return snippets


def delete_corpus(corpus_name: str) -> None:
    """Delete a corpus. Test cleanup + manual reset; not used in normal runs."""
    rag = _import_rag()
    logger.warning("rag.delete_corpus: deleting %s", corpus_name)
    rag.delete_corpus(corpus_name)


def list_files_in_corpus(corpus_name: str) -> List[dict]:
    """List the files currently in a corpus. Used by the manifest writer.

    Returns one record per file with the display_name + (when retrievable)
    the description field, which by our convention carries `sha256=...`.
    The manifest writer reconciles this against the local
    `upload_documents` records to detect drift (e.g. a corpus that has
    files we didn't upload, or that's missing files we did).
    """
    rag = _import_rag()
    records: List[dict] = []
    for f in rag.list_files(corpus_name=corpus_name):
        records.append({
            "display_name": getattr(f, "display_name", ""),
            "description": getattr(f, "description", ""),
            "name": getattr(f, "name", ""),
        })
    return records
