# `rag_corpora/` — per-firm source documents for RAG-grounded TMT runs

This directory is where the **principal investigator** (the lead researcher) drops the
documents that get uploaded to each firm's Vertex AI RAG corpus: the collection of documents (corpus) that Google's paid cloud service (Vertex AI) searches for retrieval-augmented generation (RAG), in which the passages found are added to a model's prompt before it writes. In a RAG-grounded run (one complete simulated meeting and debrief) of the TMT (top management team: the six simulated executives), agents (language models given roles and instructions) receive and cite those passages, so their text can be traced to sources. Terms are defined in [`docs/GLOSSARY.md`](../docs/GLOSSARY.md).

The framework (the shared software in this repository) reads them, the `python -m rag.corpus_build` CLI (command-line interface: a program used by typing commands)
uploads them, and a subsequent `python3 run_research_session.py --rag
--company <Company> ...` retrieves from the uploaded corpus.

## Folder convention

```
rag_corpora/
├── OpenAI/
│   ├── example_interview.txt
│   ├── example_case_study.pdf
│   └── ...
├── Meta/
│   ├── ...
├── Alphabet/
│   ├── ...
├── Anthropic/
│   ├── ...
└── HuggingFace/
    └── ...
```

One subdirectory per firm. The folder name is what gets passed to
`--company` (a flag, or option added to the command), and it becomes part of the Vertex corpus display name, after the study's slug (its short name with no spaces):

```
<study_slug>__<Company>   e.g. openness_maneuvering__OpenAI
```

## Supported file types

Vertex AI RAG Engine (Google's paid service that stores a corpus and runs the searches) extracts text natively from:

- `.md` — Markdown (plain text with simple marks for headings and lists)
- `.txt` — plain text
- `.pdf` — PDF (Vertex handles the parsing server-side, on Google's computers)
- `.docx` — Word
- `.html` — HTML
- `.rtf` — Rich Text Format

Files with other extensions are silently ignored by the build CLI.

[`BUILD_RECORD.md`](BUILD_RECORD.md) records how the one store (a firm's corpus as loaded into Google's service) built so far was made. For reviewers of the accompanying submission: the source documents can be made available privately on request, through the editors, for review purposes only and as copyright permits.

## Build a corpus

Retrieval (the search step) has its own region (the location of the rented computers). Gemini 3.x (Google's language model) needs `GOOGLE_CLOUD_LOCATION=global`, and RAG Engine has no global endpoint (web address that receives requests), so set `RAG_LOCATION` to a region. **Check that region's RAG Engine tier (the price level of its database) first.** The database bills for as long as a corpus exists, whatever its size: about $3 a day on the Basic tier and about $30 a day on Scaled, at the list rates (published prices) of Spanner, the Google database behind the store. The build prints the tier and refuses Scaled unless you pass `--allow-scaled`. To stop billing, delete the corpus and set the tier to Unprovisioned.

One firm at a time:

```bash
python -m rag.corpus_build --company OpenAI
```

All firms at once (walks every subdirectory of `rag_corpora/`):

```bash
python -m rag.corpus_build --all-firms
```

Inspect the plan without uploading:

```bash
python -m rag.corpus_build --company OpenAI --dry-run
```

List the files currently in a firm's corpus (read-only, no uploads):

```bash
python -m rag.corpus_build --company OpenAI --list
```

Tear down (irreversibly deletes the Vertex corpus + every file in it):

```bash
python -m rag.corpus_build --company OpenAI --delete-corpus --yes
```

## Run with RAG

Once a firm's corpus is populated:

```bash
python3 run_research_session.py --rag \
    --company OpenAI --industry-context Dynamic --product-type Novel
```

The framework resolves the corpus via `studies.openness_maneuvering.
rag_loader.load_corpus("OpenAI")`, and the run exits with an error if
none can be resolved. It threads retrieval through Phases
1 / 2 / 4 (deliberation, strategy documents and debrief), and renders citations (each role's record of the document, passage and words it drew on) as Markdown footnotes in every
per-run output file. The corpus manifest (a file listing the corpus's documents and settings) + per-retrieval audit log
lands in `results/runs/<run_id>/07_rag/`.

## What gets committed to git

This README and the per-firm `.gitkeep` files (empty files that hold the folders in place) are **committed** (saved in the history kept by git, the project's version-tracking tool). Every
actual source document under `rag_corpora/<Firm>/` is **gitignored**
(deliberately left out of the shared repository; see `.gitignore` at the top of the repo, short for repository: the project's files and their history). The per-firm Vertex corpus state
also lives outside the repo (in GCP, Google Cloud Platform: Google's rented computing services). Both are intentional: source
documents are firm-specific reference material, often under publisher
copyright; we don't put them in the repository.

Reproducibility comes from the per-doc SHA256 (a fingerprint computed from a file's contents, so any change alters it) in each run's corpus
manifest (`07_rag/corpus_manifest.json`). A reviewer can verify a corpus they have access to
matches the run's manifest by re-uploading the same source files via
the build CLI and checking the SHA256s line up.

## Source list: `SOURCES.csv`

Because the documents stay out of git, `SOURCES.csv` (a plain-text table that any spreadsheet can open) lists them instead, so anyone can obtain the same documents and check that they have the right versions. It is committed and starts from the 127 documents that grounded the CrewAI pilot (the earlier study, built on different software, CrewAI).

| Column | Meaning |
|---|---|
| `doc_id` | Stable identifier, e.g. `openai-int-01` |
| `firm`, `source_type` | Folder name under `rag_corpora/`; `interview`, `earnings_call` or `case_study` |
| `title` | Title as saved |
| `path` | Where the file goes in this folder (`<Firm>/<file>`) |
| `pilot_path` | Where the file sat in the pilot's `data/` folder |
| `period` | Quarter, for earnings calls |
| `url`, `published_date`, `retrieved_date` | Where and when the document was published and obtained (being completed) |
| `access` | `public` or `licensed` (case studies) |
| `sha256`, `word_count` | Content hash (the fingerprint) and length of the file |
| `used_in`, `notes` | Which work used it; anything to know |

Check your local copies against the list:

```bash
python -m rag.sources --root rag_corpora
```

Add new documents to the list when you add them to a corpus, with their hash (`shasum -a 256 <file>`).

## Document quality matters

The RAG layer's value is bounded by the corpus's relevance and depth.
The 127-document set in `SOURCES.csv` has **three document classes**:

- **Interview and public-talk transcripts (73)** — first-person
  accounts where the CEO, CTO, or senior leader describes their
  thinking in their own words. Most useful when the panellist agent (one of the simulated executives being questioned in the debrief)
  is asked "what was your reasoning?" — the text gives the LLM (large language model)
  something specific to anchor on.
- **Earnings-call transcripts (49)** — Alphabet (13) and Meta (36).
- **Published case studies (5)** — three Harvard Business School
  cases, one INSEAD case and one journal article.

Annual reports, SEC filings, blog posts and press releases are not
in the set. Coverage is uneven: Alphabet 20, Anthropic 9, Hugging Face
16, Meta 45, OpenAI 37. Report how a corpus was built and what it
leaves out; see [`docs/LEARNINGS.md`](../docs/LEARNINGS.md), L14 (learning 14).
