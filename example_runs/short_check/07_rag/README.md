# RAG audit folder

**Enabled:** yes
**Corpus resource name:** `projects/<project>/locations/us-west1/ragCorpora/2305843009213693952`
**Documents in corpus:** 37
**Retrievals run:** 42
**Retrievals skipped:** 0
**Retrieval errors:** 0

## Files
- [corpus_manifest.json](corpus_manifest.json) — corpus + per-doc SHAs + embedding model
- [retrieval_log.jsonl](retrieval_log.jsonl) — one record per LLM-call retrieval

## Reproducibility
The `corpus_manifest.json` pins which document content was in the corpus at run time
(via per-doc SHA256). The corpus state itself lives in Google Vertex AI RAG Engine,
not in this folder — a reviewer reconstructing the run uses the SHAs here to verify
that the document content matches what was indexed.