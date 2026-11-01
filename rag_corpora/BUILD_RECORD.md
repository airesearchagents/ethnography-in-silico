# How the grounded test's corpus was built

This records the one store (a firm's corpus, or document collection, as loaded into Google's cloud service for searching) built so far, for repeatability. The test was grounded: agents (language models given roles and instructions) were given a firm's real documents so their text could be traced to sources. Terms are defined in [`docs/GLOSSARY.md`](../docs/GLOSSARY.md). Source documents stay out of git (the tool that keeps the repository's shared history), because they may be under copyright. The source documents can be made available privately on request, through the editors, for review purposes only and as copyright permits. [`build_record_OpenAI_2026-10-31.csv`](build_record_OpenAI_2026-10-31.csv) lists each file, its hash (a fingerprint computed from its contents, so any change alters it) and its upload time.

## The store

| Item | Value |
|---|---|
| Date | 31 October 2026, 10:21–10:33 UTC |
| Service | Vertex AI RAG Engine (Google's paid service that stores a corpus and runs the searches; RAG is retrieval-augmented generation), on Spanner mode (Spanner is the Google database behind the store; RAG Engine in `us-west1` is listed as Preview, an early release) |
| Region | `us-west1` (the location of the rented computers), because RAG Engine has no `global` endpoint (web address for requests) |
| Tier | Basic (a price level: Spanner at 100 processing units, Enterprise edition) |
| Store name | `openness_maneuvering__OpenAI` |
| Documents | 37 (35 interviews, 2 case studies), about 298,000 words |
| Embedding model (turns text into a list of numbers standing for its meaning) | `publishers/google/models/text-embedding-005`: 768 dimensions (numbers per text; measured), 2,048-token (a token is a small piece of text, about three-quarters of a word) input limit, specialized for English and code |
| Vector database (keeps those lists of numbers, or vectors, and finds the closest) | RagManagedDb, Google-managed and backed by Spanner, the default |
| Search algorithm | k-nearest neighbors (KNN): exact search that compares every stored vector, the default. Not approximate search (ANN) |
| Distance metric | Cosine (how alike two lists of numbers are), the only metric listed for RagManagedDb |
| Document parsing | RAG Engine's default parser (the step that extracts text from files). No layout parser or LLM (large language model) parser |
| Chunking (cutting documents into pieces for searching) | Fixed-size: 1,024 tokens with 200 overlap (one exception below). Passages as stored had a median of 751 words and 4,013 characters. Each agent was shown the first 1,200 characters of each |
| Tokenizer (splits text into tokens) | Google's. RAG Engine counts chunks in tokens, but we found no published name for the tokenizer |
| Retrieval (the search step) | Top 5 passages per query (the text a search uses). No score threshold, metadata filter, hybrid search or re-ranking (optional ways to narrow or reorder results) was set |
| Retrieval scores | 0.245 to 0.427, lowest first in all 185 retrievals, so they appear to be cosine distances (where lower means closer) |
| Encryption | Google-managed key, the default |
| Software | `google-cloud-aiplatform` 1.122.0, `google-adk` 1.17.0, `google-genai` 1.46.0, Python (the programming language) 3.10.8 |
| Code | The branch (a separate line of work in the code history) that became `DECISIONS.md` §49 (entry 49). Run D predates the recorded code commit, so its `00_meta.json` (the run's summary file) names none |

## Steps

1. **Get the documents.** They came from the data folder of the pilot (the earlier study, built on different software). `SOURCES.csv` (the table listing every document) maps each document's `pilot_path` to its `path` under `rag_corpora/`.
2. **Check them.** All 37 matched the SHA-256 (the standard fingerprint method) hashes in `SOURCES.csv`. Run `python -m rag.sources --root rag_corpora`; it reports other firms' documents as missing unless you copied them too.
3. **Check the region's tier.** Read `ragEngineConfig` (the region's settings) for the region. Do not build on the Scaled tier for a small study.
4. **Build.**

   ```bash
   export GOOGLE_GENAI_USE_VERTEXAI=true
   export GOOGLE_CLOUD_PROJECT=<your-project>
   export GOOGLE_CLOUD_LOCATION=global
   export RAG_LOCATION=us-west1
   python -m rag.corpus_build --company OpenAI
   ```

5. **Run.** Add the flags (command options) `--vertex --rag` to `run_research_session.py` (the program that starts a run), with the same environment variables (named settings, the `export` lines above) set.
6. **Remove it afterwards.** Delete the store and set the region's tier to Unprovisioned (the setting that stops the database), or the database keeps billing.

## How agents retrieved

Only the six role agents (the simulated executives) retrieve. The query is built from the role, the task and recent transcript, never from the research question (`rag/queries.py`). In the run there were 185 retrievals: 59 in deliberation (the team's discussion), 6 for strategy documents and 120 in the debrief (the researcher agent's interview of the team). In the run reported, debrief queries kept the start of the transcript, not the end, and deliberation queries lost the role's latest note, since changed (`DECISIONS.md` §50). Every passage retrieved is logged in that run's `07_rag/retrieval_log.jsonl` (a plain-text file with one record per line), in full, while agents saw its first 1,200 characters. `chunk_id` is the passage's rank within one retrieval, not a stable ID for a chunk.

## What did not go to plan

Report these if you compare against this store.

- **One document was ingested differently.** "Is Developing AI Worth the Money? - Sam Altman (OpenAI).txt" went up first, in a single-file test, using the service's default chunking (documented as 1,024 tokens with 256 overlap) and without its hash in the store. Its local file matched the source list. The other 36 used the settings above, and the run did not separate them. Agents cited this document 9 times in the debrief, but most of those quotes are not in it, as `docs/LEARNINGS.md` L13 (learning 13) explains.
- **The first build failed.** It stopped after about five minutes with an indexing (preparing documents for search) error (code 13) and left no files. After the test upload worked, a rerun completed without changes to the documents.
- **No retrieval test is repeatable to the passage.** The store is a live service, so a rebuild may split or rank passages differently. The logged passages, cut to their first 1,200 characters, are the record of what agents saw.

## Sources for these settings

The store's export, the run's retrieval log and a test embedding gave the values marked measured or specific to this run. Google's documentation, read on 31 October 2026, gave the defaults and descriptions: [vector database choices](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/rag-engine/vector-db-choices), [RagManagedDb](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/rag-engine/use-ragmanageddb-with-rag), [chunking](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/rag-engine/fine-tune-rag-transformations), [deployment modes](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/rag-engine/deployment-modes) and [embeddings](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/embeddings/get-text-embeddings). These are managed services, so Google can change them; that is another limit on exact repeatability.

## Cost

Embedding the corpus cost under $1 at list prices (published rates). The run itself cost about $67 in model calls (prompts sent and replies received) at list prices, before later changes that bring a run like it to an estimated $15 (`docs/LEARNINGS.md` L15). The Basic-tier database comes to about $3 a day at Spanner's list price for 100 processing units, and bills while the store exists. Check the price in your region.
