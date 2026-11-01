"""Retrieval-augmented grounding for the TMT simulation.

RAG (retrieval-augmented generation) means searching a document collection
and adding the passages found to a model's prompt (the text sent to it) before
it writes. Grounding means giving agents a firm's real documents so their text
can be traced to sources. TMT (top management team) here means the six
simulated executives, each a language model given a role.

This package (a folder of code) gives the six TMT role agents access to
per-firm document corpora (collections of documents) at deliberation time
(while the team discusses its task). The role agents read retrieved snippets
(passages cut from a document) in their prompt and emit `Citation` records
when they draw on the material; the persistence layer (the code that saves a
run's records) then expands those citations into Markdown (plain text with
simple marks for headings and lists) footnotes in every per-run output file.

The retrieval (search) backend, the service that does the work, is the RAG
Engine of Google Vertex AI, Google's paid cloud service. RAG Engine is a managed
service that stores a corpus, makes embeddings (lists of numbers standing for a
text's meaning) and runs the searches. This is consistent with the existing
Vertex routing that the framework (the shared software) uses for Gemini
(Google's language model) providers — same auth (proof of identity), same
project, same EDU-credit (education credit) billing. Auth assumes the standard
`GOOGLE_GENAI_USE_VERTEXAI=true` + `GOOGLE_CLOUD_PROJECT` +
`GOOGLE_CLOUD_LOCATION` env vars (named settings held outside the code) are
set (see `providers.enable_vertex`
and `docs/07_reproducibility.md` § Gemini routing).

Public surface
--------------
- `Citation` / `RetrievedSnippet` — pure Pydantic schemas (templates of
  required fields, checked by the Pydantic tool), no Vertex import. Safe to
  import from any code path including tests that don't have GCP (Google Cloud
  Platform) auth configured.
- `vertex_corpus` — the thin wrapper (code that hides another service's
  details) around `vertexai.rag` that builds,
  uploads to, and retrieves from per-firm corpora. Lazy-imports the SDK
  (Google's software kit), loading it only when needed, so the rest of the
  package stays usable without it.
- `prompt_inject` — `format_retrieved_context(role, snippets)` renders
  the REFERENCE MATERIAL block + populate-citations instruction the
  framework appends to a role's prompt at retrieval time.
- `queries` — three retrieval-query builders, one per phase (numbered stage
  of a run), built
  from role + task + transcript only (invariant I5, a rule that must always
  hold: never the RQ, or research question, nor the lens, the theory used in
  analysis).
- `runtime` — `RagSession` runtime state + `build_rag_session_for_
  company` loader resolver; tracks the per-call retrieval log used
  by persistence and the comparison harness (a small program that runs a
  comparison under set conditions).

See `docs/10_rag_repo_plan.md` for the architecture; see
`docs/02_design_decisions.md` §23 for the Vertex-vs-local rationale.
"""

from .schemas import Citation, RetrievedSnippet

__all__ = ["Citation", "RetrievedSnippet"]
