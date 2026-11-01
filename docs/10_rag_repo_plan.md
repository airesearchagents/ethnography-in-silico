# 10. RAG-grounded TMT deliberation

This file describes RAG (retrieval-augmented generation: searching a document collection and adding the passages found to a model's prompt, the text sent to it for one reply), the optional retrieval layer of the framework (the shared software in this repository). Other terms are explained in the [glossary](GLOSSARY.md). Grounding means giving agents a firm's real documents so their text can be traced to sources; it is unrelated to grounded theory. The layer is activated by `--rag` on the CLI (command line). When set, every TMT (top management team) role agent, one of the six simulated executives, retrieves ~5 excerpts from the active firm's RAG corpus (document collection) on Vertex AI (Google's paid cloud service) before each LLM (large language model) call in Phases 1, 2, and 4 (deliberation, strategy documents, debrief), and sees each one whole. The role emits structured `Citation` records (in fixed, named fields) for excerpts it leaned on; the persistence layer (the code that saves records) renders those citations as inline Markdown footnotes (Markdown is plain text with simple marks for headings and lists) in the run's output files. Citations are kept on public messages, strategy documents and debrief answers, not on private notes, drafts or private answers. The qualitative researcher agent (Observer / FieldNoter / Debriefer) does **not** retrieve — invariants (rules that must always hold) I1–I3 hold, and a fifth invariant I5 (retrieval queries, the search text, built from role + task + transcript only, never from the study's RQ, or research question, or lens, the theory it will analyse through) is enforced parametrically (tested once for each) across study fixtures (the studies prepared for testing).

> **Status (24 Oct 2026):** retrieval is back in scope for the openness study and the Organization Science proposal (`DECISIONS.md`, the project's numbered record, §33, superseding §22). It stays switchable with `--rag` for other studies. Study runs for the openness study will use it, after the citation-accuracy evaluation described in §33.

For the methodological framing — what this gives a qualitative reviewer that the no-RAG path cannot — see [`11_ethnography_in_silico.md`](11_ethnography_in_silico.md) §11.4 (the four channels of field data) and §11.6 (the qualitative reviewer's auditing protocol). For the Vertex-AI-RAG-Engine (Google's paid service that stores documents and searches them) vs local-RAG (run on your own computer) trade-off, see [`02_design_decisions.md`](02_design_decisions.md) §23.

---

## What the RAG layer is for

The deliberation phase produces a synthetic TMT transcript shaped by whatever the LLM's pre-training prior (what it absorbed from the text it learned from) happens to encode about the firm under study. Without retrieval, *every* utterance is the role agent's best guess from that diffuse prior — there is no traceable link to the firm's actual public history. With retrieval enabled, each role agent additionally sees excerpts from public documents about the firm and is instructed to cite when it leans on them. The corpus starts from the 127-document set of the pilot (the earlier study that preceded this framework): 73 interview and public-talk transcripts, 49 earnings-call transcripts and 5 published case studies (three Harvard Business School cases, one INSEAD case and one journal article). The structured `Citation` field on every role's output makes those references **traceable**: every citation names a document and a quote, and the comparison harness (a small program that runs a comparison) checks each quote as a substring (an exact word-for-word match) of the retrieved passages.

What the layer answers, methodologically: *did the TMT actually use the retrieved documents, and if so, how did retrieval change the deliberation?* The companion comparison harness (`analysis/compare_rag.py`) pairs RAG with no-RAG runs (a run is one complete simulated meeting and debrief) cell-by-cell (a cell is one combination of firm, industry context and product type) and produces the headline report that surfaces grounded claims first, then quantitative diffs.

---

## Architecture

This map lists the code folders and files involved. `.py` files are Python, the project's programming language, and Pydantic is a Python tool that checks replies against a template. The panel, and any one panellist, are the six role agents when questioned in the debrief, and an artefact is a role's strategy document.

```
rag/                            standalone retrieval library
├── schemas.py                  Citation, RetrievedSnippet (pure Pydantic)
├── vertex_corpus.py            Wrapper over `vertexai.rag`: find/build/upload/retrieve
├── queries.py                  Per-phase query builders (I5: no RQ/lens leak)
├── prompt_inject.py            REFERENCE MATERIAL block + populate-citations instruction
├── runtime.py                  RagSession (corpus + log + retrieval coroutine) +
│                               build_rag_session_for_company loader resolver
└── corpus_build.py             `python -m rag.corpus_build` CLI

studies/openness_maneuvering/
├── rag_loader.py               load_corpus(company) callable referenced by
│                               StudyConfig.rag_corpus_loader (read-only — does
│                               NOT auto-create)

rag_corpora/                    per-firm folders for the source documents
├── README.md
├── OpenAI/ Meta/ Alphabet/ Anthropic/ HuggingFace/    .gitkeep + (gitignored docs)

orchestrator/
├── concurrent_mode.py          Phase 1: retrieves per role-turn before LLM call
├── artefact_collection.py      Phase 2: retrieves per role's artefact-authoring
├── panel_debriefing.py         Phase 4: retrieves per panellist response

analysis/
├── compare_rag.py              Comparison harness — auto-pairs runs + writes
│                               grounded-claims-first per-pair MD + cross-pair
│                               summary + CSV
├── citation_rendering.py       Markdown footnote rendering of Citation lists
├── persist_artefacts.py        Calls into citation_rendering; writes 07_rag/

run_research_session.py         `--rag` flag opts in; resolves rag_corpus_loader
                                at session start; threads RagSession through
                                every retrieval site

tests/
├── test_rag_schemas.py
├── test_rag_vertex_corpus.py
├── test_rag_runtime.py
├── test_rag_queries.py
├── test_rag_prompt_inject.py
├── test_rag_orchestrator_wiring.py
├── test_rag_persistence.py     ← invariant I5 enforcement
├── test_rag_corpus_build.py
├── test_openness_rag_loader.py
└── test_compare_rag.py
```

### Data flow (Phase 1 turn, with `--rag`)

The diagram follows one role's turn from search to saved record. `top_k=5` means the five closest passages, a snippet is a retrieved passage, and `AgentAction` is one move by a role.

```
                            (per role per turn)

  role + task + transcript        ───►   rag.queries.build_role_turn_query
                                                │
                                                ▼
                                          query string
                                          (NO RQ, NO lens — I5)
                                                │
                                                ▼
  vertex_corpus.retrieve(corpus_name, query, top_k=5)
                                                │
                                                ▼
                                    list[RetrievedSnippet]
                                                │
                              ┌─────────────────┴─────────────────┐
                              ▼                                     ▼
                rag_session.retrieval_log         rag.prompt_inject.format_retrieved_context
                  (appended)                         (REFERENCE MATERIAL block +
                                                      populate-citations instruction)
                                                                  │
                                                                  ▼
                                                 _compose_role_prompt() embeds it
                                                                  │
                                                                  ▼
                                                       LLM call returns AgentAction
                                                       (with citations[…] if used)
                                                                  │
                                                                  ▼
                                            citations flow through TranscriptEntry →
                                            DeliberationEvent → persisted MD with
                                            inline [^cN] footnotes
```

Phases 2 and 4 follow the same shape, with `build_artefact_query` / `build_panellist_query` substituted for `build_role_turn_query`. The orchestrator's signature (the inputs that the code running the phases takes) for each phase accepts `rag_session: Optional[RagSession] = None` so the no-RAG path stays byte-identical (exactly the same) to today — empty list of snippets → empty REFERENCE MATERIAL block → prompt unchanged.

---

## Methodological invariants

| # | Invariant | How RAG affects it |
|---|---|---|
| I1 | Observer is BLIND to RQ + lens (by default) | **Unchanged.** Observer doesn't retrieve; sees citations only as panel behaviour, like any utterance content. |
| I2 | FieldNoter is BLIND to RQ + lens (by default) | **Unchanged.** Same. |
| I3 | Debriefer sees RQ + lens, anti-steering | **Unchanged.** Debriefer doesn't retrieve. May probe the panel about *what they cited* — a fair behavioural probe. |
| I4 | Construct words only in forbidden-vocab (words the researcher agent must not use) block | **Slightly nuanced.** Retrieved snippets may contain construct vocabulary (a Henkel quote will include "selective revealing"). The prompt-injection layer (the code that adds passages to the prompt) does NOT strip forbidden vocab from retrieved text — panellists may quote it back verbatim. Flagged-vocabulary capture (logging listed words when panellists use them) continues to log any such verbatim panel use, so the analytical signal survives. |
| **I5** | **Retrieval query is built from role + task + transcript only — never from RQ or lens.** | Builders in `rag/queries.py` accept role, task, transcript, and role state — never the study config's RQ / lens. Enforced parametrically over study fixtures by `tests/test_rag_persistence.py::TestInvariantI5NoQueryLeakAcrossStudies`. |

Detail of I1–I4 and the methodological reasoning: `05_methodological_invariants.md`.

---

## Output shape

Per-run folder additions when `--rag` was set. A SHA256 is a fingerprint computed from a file's contents, an embedding model turns text into lists of numbers standing for its meaning, a chunk is a passage cut from a document, and `.jsonl` is a plain-text format with one record per line.

```
results/runs/<run_id>/
├── 01_deliberation/interaction_log.md     ← inline footnotes when a role cited
├── 02_strategy_documents/<Role>_strategy.md  ← inline footnotes + References section
├── 04_interview/transcript.md             ← inline footnotes per panellist response
├── 07_rag/
│   ├── corpus_manifest.json               which docs, SHA256s, embedding model
│   ├── retrieval_log.jsonl                one line per LLM call: query, full retrieved chunks, shown_chars
│   └── README.md                          human-readable summary
```

Example footnote, with invented content (rendered inline at persistence time by `analysis/citation_rendering.py`):

```markdown
We should release the model with permissive licensing.[^c1]

[^c1]: **example_interview.txt** (chunk example_interview.txt#3)
    — quote: _"We continue to believe that broad accessibility of frontier
    models accelerates safety research."_ — supports: open-weight commitment
```

---

## Per-run reproducibility

The corpus state lives in Google Vertex AI RAG Engine, not in git (the tool that keeps the project's change history). The framework therefore pins **what content was indexed (loaded for searching) at run time** via two mechanisms:

1. **Per-doc SHA256s in `07_rag/corpus_manifest.json`.** Computed locally at upload time by `vertex_corpus.upload_documents`, recorded in `documents[*].sha256`. A reviewer reproducing the run uses these to verify their reconstructed corpus matches the run's content (rebuild via `python -m rag.corpus_build`, then compare).

2. **Per-call retrieval log.** Every retrieval landed in `07_rag/retrieval_log.jsonl` with `(role, phase, query, retrieved[])`. Each `retrieved` entry carries `doc_id`, `chunk_id`, `score`, the full chunk text and `shown_chars`. `shown_chars` is how much of it the role agent saw: all of it by default, and `TMT_PASSAGE_CHARS` sets a limit for testing. It is the audit trail the comparison harness's quote verification works against.

Detail: `07_reproducibility.md` § RAG corpus reproducibility.

---

## Cost

- **The database is the bill to watch.** RAG Engine's database bills for as long as a corpus exists in the region, whatever its size: about $3 a day on the Basic tier (price level) and about $30 a day on Scaled, at list rates for Spanner (the Google database behind it). `python -m rag.corpus_build` prints the tier and refuses Scaled unless you pass `--allow-scaled`. When you finish, delete the corpus and set the tier to Unprovisioned, which stops it (steps in [`REPRODUCE.md`](REPRODUCE.md)).
- **Embedding (turning text into lists of numbers that stand for its meaning) and retrieval calls** cost little: embedding the 37 OpenAI documents cost under $1 at list prices (providers' published rates).
- **Model calls** are the rest. Retrieved passages add input tokens (small pieces of text that providers charge by) to every call. Measured on `gemini-3.1-pro-preview` (an early release of Google's Gemini model) at list prices, before we stopped re-sending earlier prompts, a grounded run (one given a firm's documents) cost about $67 (now an estimated $15; `docs/LEARNINGS.md` L15, a numbered learning), against about $20 of Google charges for an ungrounded run with optional scoring by judge models (scoring on other vendors is extra). Runs took 38–90 minutes. These figures age quickly.

---

## Operating the layer

1. **Drop source documents** under `rag_corpora/<Company>/` per the layout in that folder's README. The framework supports `.md`, `.txt`, `.pdf`, `.docx`, `.html`, `.rtf` natively (Vertex extracts text server-side, on Google's computers, at upload time). Per-firm folders are committed, or saved in the shared history (`.gitkeep`, an empty placeholder file); the documents themselves are gitignored, or left out of the shared repository — the PI (principal investigator) keeps them locally.

2. **Build the corpora** with the CLI. Set `RAG_LOCATION` to a region (the geographic location of the rented computers) first, because Gemini 3.x needs `GOOGLE_CLOUD_LOCATION=global` and RAG Engine has no `global` endpoint (web address for requests). The CLI prints the region's RAG Engine tier and refuses Scaled unless you pass `--allow-scaled`:

   ```bash
   python -m rag.corpus_build --all-firms       # everyone at once
   python -m rag.corpus_build --company OpenAI  # one firm
   python -m rag.corpus_build --company OpenAI --dry-run
   python -m rag.corpus_build --company OpenAI --list
   python -m rag.corpus_build --company OpenAI --delete-corpus --yes
   ```

Idempotent (safe to repeat): re-running with the same docs-dir uploads only new files (display-name dedup, skipping names it already holds). Per-doc SHA256s are computed locally and land in each file's Vertex `description` field.

3. **Run with `--rag`:**

   ```bash
   python3 run_research_session.py --rag \
       --company OpenAI --industry-context Dynamic --product-type Novel
   ```

Composable (usable together) with `--judge`, `--subdimension-scores`, `--vertex`. Exits with an error when no corpus session can be resolved for the given company under the active study, rather than continuing ungrounded.

4. **Compare runs** when you have at least one RAG and one no-RAG run of matching `(study, company, industry, product, provider)`:

   ```bash
   python -m analysis.compare_rag           # auto-pair under results/runs/
   python -m analysis.compare_rag --dry-run
   ```

Outputs land in `results/comparisons/<timestamp>/` — one per-pair MD, or Markdown file (grounded claims first; then decision diff, citation density, corpus coverage, quote verification, optional judging delta) plus a cross-pair `README.md` + `summary.csv` (a plain-text table).

---

## What the layer deliberately does not do

- **The researcher does not retrieve.** Observer / FieldNoter / Debriefer never call `retrieve`. Putting retrieval inside the researcher would let analytical framing (the RQ that's only meant to live in the Debriefer's prompt) leak into the retrieval query and pre-filter which documents the LLM-researcher gets to see. The asymmetry is load-bearing: the panel acts; the researcher observes.
- **No semantic-paraphrase guard (a check for rewordings with the same meaning) on retrieved text.** A Henkel quote that includes "selective revealing" passes through verbatim into a panellist's prompt; if the panellist quotes it back, the flagged-vocabulary capture in the Observer logs the use. The framework's discipline is "quote the panel" — including when the panel is quoting source documents.
- **No per-role corpus filtering.** All six roles share the same firm-corpus; the retriever's relevance score handles role differentiation at query time. A future variant could split per-role (CTO documents vs CEO documents) if methodological value emerges.
- **No public-vs-private RAG-channel split.** All retrievals are private to the role being prompted. The retrieval log captures what was retrieved per role for downstream comparison; conflation isn't possible because every record is role-tagged.
- **Citation accuracy is LLM-discretionary (left to the model).** The comparison harness's quote verification catches fabrications (cited quote not in the retrieved chunks for that doc). It does NOT catch the converse: a claim that was influenced by retrieval but for which the role neglected to populate `citations[]`. See `08_known_limitations.md` § Limit 16.

---

## Cross-references

- Design rationale (Vertex AI RAG Engine vs local): `02_design_decisions.md` § 23.
- Methodological framing (ethnography in silico): `11_ethnography_in_silico.md`.
- Methodological invariants in detail: `05_methodological_invariants.md`.
- Architecture overview: `01_architecture.md` § RAG grounding.
- Per-phase workflow: `03_simulation_workflow.md` § RAG grounding.
- Per-study configuration: `studies/openness_maneuvering/docs/01_study_anatomy.md` § `rag_corpus_loader`.
- Reviewer auditing protocol: `11_ethnography_in_silico.md` § 11.6.
- Reproducibility — corpus SHAs and retrieval audit: `07_reproducibility.md` § RAG corpus reproducibility.
