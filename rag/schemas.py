"""Pydantic schemas for the RAG layer.

A schema is a template saying which fields a record must contain, and Pydantic
is the Python tool that checks records against it. RAG (retrieval-augmented
generation) means searching documents and adding the passages found to a
model's prompt (the text sent to it) before it writes.

Two types:

- `RetrievedSnippet` — a single chunk (a passage cut from a document)
  returned from the corpus (document collection) retrieval (search) call. The
  orchestrator (the code that runs a run's phases) builds a list of these and
  threads them into the role's prompt as a "REFERENCE MATERIAL" block.

- `Citation` — what a role agent (one of the six simulated executives)
  emits in its structured output (a reply in fixed, named fields) when it
  draws on a snippet. Populated by the LLM (large language model) itself
  (schema-enforced field on `AgentAction`, `StrategicArtefact`,
  `PanelResponse`). The persistence layer (the code that saves a run's records)
  expands citations into Markdown (plain text with simple marks for headings
  and lists) footnotes.

These schemas are deliberately separated from `vertex_corpus.py` so any
caller (tests, the prompt-injection helper, the citation auditor) can
import them without pulling in the `vertexai.rag` SDK (the software kit for
Vertex AI, Google's paid cloud service) or requiring GCP (Google Cloud
Platform) auth (proof of identity) at import time.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class RetrievedSnippet(BaseModel):
    """One chunk of source text retrieved from a company's RAG corpus.

    Wraps Vertex AI RAG's `RagContexts.contexts[*]` items into a
    transport-stable shape the framework (the shared software) can carry through
    the orchestrator
    and the persistence layer. The `chunk_id` is constructed locally
    (Vertex doesn't return a stable per-chunk identifier in the retrieval
    response) so two snippets from the same document still distinguish
    themselves in the citation audit.
    """

    doc_id: str = Field(
        ...,
        description=(
            "Stable identifier for the source document. Derived from "
            "`source_display_name` (e.g. 'openai_2024_annual_letter.md') "
            "when available, otherwise from `source_uri`. Used by the "
            "citation audit to verify a role's emitted `Citation.doc_id` "
            "actually corresponds to a chunk the role was shown."
        ),
    )
    doc_display_name: str = Field(
        "",
        description=(
            "Human-readable document name (typically the original "
            "filename uploaded to the corpus). Surfaces in the rendered "
            "Markdown footnote so a reviewer sees 'OpenAI 2024 annual "
            "letter' rather than a raw URI."
        ),
    )
    chunk_id: str = Field(
        ...,
        description=(
            "Constructed-locally identifier for this particular chunk "
            "within its document. Format: '<doc_display_name>#<index>' "
            "where index is the chunk's position in the retrieval "
            "response (1-based). Stable for a single retrieval call but "
            "not across calls — Vertex re-ranks chunks per query."
        ),
    )
    text: str = Field(
        ...,
        description=(
            "The chunk text returned by Vertex RAG. This is what the "
            "role agent sees in its prompt; this is also what the "
            "citation audit compares against."
        ),
    )
    score: float = Field(
        0.0,
        description=(
            "Vertex RAG's relevance score for the (query, chunk) pair. "
            "Higher = more relevant. Captured in the retrieval log so "
            "a reviewer can see how confident the retriever was."
        ),
    )
    # URI: a resource's address. GCS: Google Cloud Storage, Google's file store.
    source_uri: Optional[str] = Field(
        None,
        description=(
            "GCS URI (or other source URI) of the original uploaded "
            "document. Captured in the run's `07_rag/corpus_manifest.json` "
            "so a reviewer can trace any citation back to the source file."
        ),
    )


class Citation(BaseModel):
    """A citation a TMT (top management team) role attaches to a statement when
    drawing on a snippet.

    Populated by the role agent itself in its structured output. The role's
    prompt instructs: "If your output draws on any retrieved snippet,
    populate `citations[]` with `{doc_id, quote, supports}` for every
    snippet you leaned on. If you didn't use any, leave `citations=[]`."

    `quote` is verbatim from the snippet's `text`. The citation auditor
    verifies this at persistence time (substring check) and flags any
    drift in `07_rag/citation_audit.md`. Drift is informative — it can
    surface LLM fabrication of citations that look real but quote text
    that was never in the corpus.

    `supports` is a short tag the role provides to indicate what claim
    of theirs this citation backs. Free-form prose; used in the rendered
    Markdown footnote.
    """

    doc_id: str = Field(
        ...,
        description=(
            "Document identifier the role is citing. Must match a "
            "`RetrievedSnippet.doc_id` from the snippets shown to the "
            "role on this LLM call. The citation auditor verifies this; "
            "a doc_id that wasn't in the retrieval set is flagged as "
            "potential hallucination."
        ),
    )
    chunk_id: Optional[str] = Field(
        None,
        description=(
            "Optional chunk identifier within the document. When the "
            "role copies it from the retrieved snippet header it makes "
            "the citation audit's substring check trivial; when "
            "omitted, the auditor falls back to scanning every chunk "
            "of `doc_id` for the quote."
        ),
    )
    quote: str = Field(
        ...,
        description=(
            "Verbatim sentence (or short passage) from the cited "
            "snippet. The citation auditor verifies this is a substring "
            "of the retrieved chunk text. If not a substring, the "
            "citation is flagged as quote-drift (possible LLM "
            "fabrication or paraphrase). Either way it surfaces in "
            "07_rag/citation_audit.md for review."
        ),
    )
    supports: str = Field(
        "",
        description=(
            "Short free-form tag describing what claim of the role's "
            "this citation supports. Surfaces in the rendered Markdown "
            "footnote. "
            "Empty string is allowed but discouraged — it makes the "
            "citation less useful to the qualitative review."
        ),
    )
