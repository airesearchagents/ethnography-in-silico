# 7. Reproducibility

This file documents how a reviewer can reproduce a run (one complete simulated meeting and debrief) from the output of the framework (the shared software in this repository), and what the framework persists (saves) to make that possible. Terms are also explained in the [glossary](GLOSSARY.md).

## What "reproducibility" means here

Reproducibility in this framework means a reviewer with the run's record
(`00_meta.json`, the run's summary file) + the code + the env (computer set-up and settings) can re-run the framework and get **another sample from the
same generative process**. It does NOT mean they get the same transcript
verbatim — LLMs (large language models, programs that write likely continuations of text) are stochastic (the same text sent to a model can get a different reply each time).

What reproducibility CAN show:

- Whether the same RQ (research question) + lens (the theory a study will analyse through) + scenario (one firm, industry context and product type) produces consistently similar
  *shapes* of outputs (number of decisions, distribution across roles,
  area coverage in debriefing, the researcher agent's interview of the team).
- Whether the methodological invariants (rules that must always hold) still hold under a fresh run
  (the test suite, the project's automatic checks, is the gate).
- Whether a different provider (the company or service supplying a model) materially changes the findings
  (multi-LLM robustness — see below).

What reproducibility CANNOT show:

- Whether the framework's findings would survive replication with human
  ethnographers + human TMTs (top management teams). That's external validity, not internal
  reproducibility.
- Whether a different prompt (the text sent to a model to get one reply) would change the findings. Prompt-
  sensitivity analysis is not part of the standard reproduction
  protocol.

See `08_known_limitations.md` for the full list of what we explicitly do
not claim.

## Reproduction protocol — the short version

To reproduce a recorded run:

1. **Read the run's record.** `00_meta.json` in the per-run folder holds
   the scenario, the study slug (its short name) and version, each role's model, the
   researcher provider and the code commit (the saved version of the code). Every completed
   command-line run also writes `manifest.json`, a fuller record of what produced it
   (see "The replication manifest" below). Runs A to D (four prototype test runs) predate the
   recorded commit, the researcher provider and the manifest, and only run D records each
   role's model; `example_runs/short_check/` has all of these.
2. **Check out the source (restore that version of the code with git, the tool that keeps a project's history).** `git checkout <code_commit>`, from
   `00_meta.json`. A value ending in `-modified` means the tree (the project's files) had
   uncommitted changes (edits not yet saved in git). That diff (those edits) is not recorded; it's the operator's
   responsibility to preserve it. In the public repository, history is one anonymised commit, so
   `short_check`'s commit does not resolve. Use tag `v2.0` and compare the manifest's hashes.
3. **Recreate the environment (the packages of ready-made code the project uses, installed with pip).** `pip install -r requirements.txt` at
   that commit.
4. **Load the same study at the same version.**
   ```python
   from studies import load_study
   study = load_study(meta["study_slug"])
   assert study.version == meta["study_version"]
   ```
5. **Re-run with the same scenario knobs (settings).**
   ```bash
   python3 run_research_session.py \
     --study <study_slug> \
     --company <company> \
     --industry-context <industry_context> \
     --product-type <product_type> \
     --out-dir <new_output_dir> \
     [--judge]                       # if the original recorded 05_judging/
     [--subdimension-scores]         # if the original recorded 06_subdimension_scores/
     [--rag]                         # if the original recorded 07_rag/
     [--vertex]                      # if the original ran Gemini through Vertex AI
   ```
   Square brackets mark optional flags (options added to a command). Gemini is Google's language model, and Vertex AI is Google's paid cloud service. Set `TMT_PROVIDER` and any `TMT_PROVIDER_<ROLE>` (settings held outside the code) to match `role_models`,
   and supply your own API keys (secret codes that identify who uses and pays for a service). The new run lands in
   `<new_output_dir>/<run_id>/`.
6. **Compare outputs.** Use `analysis.compare_runs.render_report([
   <original_run_dir>, <new_run_dir>])`. The presence of `05_judging/`,
   `06_subdimension_scores/`, and `07_rag/` in the original run is
   your signal for the corresponding `--<flag>` arguments.

The reference manifest fields, the persistence layout (how records are saved), and the
optional reproduction story for the `--rag` corpus (RAG, retrieval-augmented generation, adds passages from a searched document collection, or corpus, to a model's prompt) follow as appendices below.

## What the framework persists

Every research session (one run) produces the files below. JSON and JSONL are plain-text formats for named fields, CSV is a plain-text table, and `.md` marks Markdown. Agents are language models given a name, a role and instructions, and a hash is a fingerprint computed from a file's contents.

```
results/
└── runs/                                 # default --out-dir: browseable per-run folders (gitignored)
    └── <run_id>/
        ├── 00_meta.json                  # scenario, study identity, timings, errors, models, code commit
        ├── 01_deliberation/
        │   ├── interaction_log.json      # every deliberation event
        │   ├── interaction_log.md        # markdown render
        │   └── role_scratchpads/<Role>_scratchpad.md
        ├── 02_strategy_documents/
        │   ├── CEO_strategy.{json,md}
        │   ├── CTO_strategy.{json,md}
        │   ├── COO_strategy.{json,md}
        │   ├── CMO_strategy.{json,md}
        │   ├── Product_Strategist_strategy.{json,md}
        │   └── Product_Designer_strategy.{json,md}
        ├── 03_researcher/
        │   ├── observation_summary.json
        │   ├── observation_summary.md
        │   ├── field_notes.json
        │   └── field_notes.md
        ├── 04_interview/
        │   ├── transcript.json
        │   └── transcript.md
        ├── 05_judging/                   # opt-in via --judge (any study registering ConstructJudgingPhase in extra_phases)
        │   ├── aggregate.{json,md}
        │   ├── <judge_id>_assessment.{json,md}
        │   └── <judge_id>_quote_audit.md
        ├── 06_subdimension_scores/       # opt-in via --subdimension-scores (openness study only)
        │   ├── per_subdimension.csv
        │   ├── per_dimension.csv
        │   ├── headline.csv
        │   ├── headline_by_role.csv
        │   └── README.md                 # markdown summary
        ├── 06_private_channel/           # each role's private notes, drafts and inbox
        │   ├── <Role>_scratchpad.md
        │   ├── <Role>_draft.md
        │   ├── inbox_final.md
        │   └── private_state.json
        ├── 07_rag/                       # --rag only
        │   ├── corpus_manifest.json
        │   ├── retrieval_log.jsonl
        │   └── README.md
        ├── 08_usage/token_usage.jsonl    # tokens each model call used
        ├── manifest.json                 # models, prompts, hashes of what agents are told
        └── README.md                     # index for the folder
```

`--out-dir X` writes the run to `X/<run_id>/`, through `analysis.persist_artefacts.burst_run(...)`. The CLI (command line) also writes `manifest.json` and, in `08_usage/`, the tokens (small pieces of text that models read and write and providers charge by) each model call (one prompt and one reply) used. The whole `results/runs/` tree is gitignored (deliberately left out of the shared repository).

**Markdown (plain text with simple marks for headings and lists) is mandatory; JSON is optional.** By default every artefact (saved record) is written as both `.json` and `.md`. Pass `--no-json` (CLI) or `write_json=False` (programmatic, from other code) to skip the JSON sub-files — the Markdown still gets written. Markdown is what qualitative reviewers read; JSON is for downstream code.

## The replication manifest

**Note (October 2026):** runs A to D (four prototype test runs) predate the manifest and token log, so their folders have neither; `short_check` has both. Their token counts come from Google's monitoring (`docs/LEARNINGS.md` L15, a numbered learning).

`analysis/replication_package.py::ReplicationManifest` (`::` points to a part inside a file) is the fuller record for reproducing a run. Every completed command-line run writes one to its folder. Its schema (the template of its fields):

```python
class ReplicationManifest(BaseModel):
    schema_version: str = "1"
    run_id: str
    company: str
    industry_context: str
    product_type: str
    launch_year: int
    started_at: str
    finished_at: Optional[str]

    # Pin the exact study configuration that produced this run.
    study_slug: str = ""
    study_version: str = ""

    # Question framing
    research_question: str
    strategic_question: str
    product_description: str
    deliberation_config: Dict[str, Any]    # mode, convergence, seeds

    # Per-agent provenance
    models_used: Dict[str, str]            # agent name → resolved model ID
    providers_used: Dict[str, str]         # agent name → provider key
    prompts_used: Dict[str, str]           # agent name → exact instruction

    # Source code provenance
    git_provenance: Dict[str, Any]         # commit_sha, branch, dirty flag, dirty files

    # Hashes of the files that set what agents are told
    protocol_hashes: Dict[str, str]        # file path → SHA-256

    # Environment snapshot
    env_snapshot: Dict[str, Any]           # TMT_* env vars + python + key package versions

    # Routing, retrieval and default models
    vertex_config: Dict[str, Any]
    rag_config: Dict[str, Any]
    default_models: Dict[str, str]
```

The command-line run builds it with `capture_from_system(system, run_id=..., started_at=..., study_slug=..., study_version=..., ...)` and writes it with `write_manifest(manifest, out_dir)`. That run passes neither `deliberation_config` nor `extra_agents`, so in its manifest `deliberation_config` is empty and `models_used` and `prompts_used` cover the six team roles. The researcher agent's provider is in `00_meta.json`, and `protocol_hashes` covers `roles/qualitative_researcher_agent.py`.

`example_runs/short_check/manifest.json` is a sample. It records our private development commit, with uncommitted changes, which is not in the public history. Ten of its eleven file hashes match this copy; `studies/openness_maneuvering/__init__.py` differs by one word in a code comment, changed for anonymisation.

## API-key redaction

Any env var (environment variable, a named setting held outside the code) whose NAME contains `KEY` / `TOKEN` / `SECRET` / `PASSWORD` / `CREDENTIAL` / `AUTH` (case-insensitive) has its value masked to `<redacted>` in `env_snapshot`. The *presence* of the variable is preserved so a reviewer can see that an API key was set without seeing its value.

Implementation: `analysis/replication_package.py::redact_env` + `_SENSITIVE_SUBSTRINGS`. Verified by `tests/test_provenance_and_llm_selector.py::TestRedactEnv`.

## Git provenance

Provenance is the record of where something came from. `git_provenance` captures:
- `commit_sha` — the HEAD commit (the latest saved version) of the run's working tree
- `branch` — the branch name (a branch is a separate line of work in the history)
- `dirty` — `True` if the working tree had uncommitted changes
- `dirty_files_count` — how many files were modified

A reviewer can:
1. Check out the commit_sha
2. Confirm `dirty = False` (otherwise the manifest's claim about "what code produced this run" is approximate)
3. Reproduce the run on the same code

If `dirty = True`, the manifest tells you how many files diverged from the commit — but cannot tell you what those changes were. For research-quality runs, the framework recommends committing changes before any run that will be referenced in a paper.

## Environment snapshot

`env_snapshot` captures:
- `env_vars` — all `TMT_*` env vars (provider selection, model overrides) + any sensitive vars (with values redacted)
- `python_version` — exact Python interpreter version
- `packages` — versions of `google-adk`, `google-genai`, `pydantic`, `litellm`, `anthropic`, `openai`

A reviewer can recreate the package versions via `pip install google-adk==<version> google-genai==<version> …`. `requirements.txt` pins (fixes) the versions the test suite passes with.

## Gemini routing: AI Studio vs Vertex AI

The framework's native Gemini providers (`gemini_pro`, `gemini_flash`, the pinned researcher, the gemini judge, a model that scores a finished run) can route through either **AI Studio** (the default; Google's direct route, using a personal key) or **Vertex AI** — useful when the operator is spending Google Cloud credits (e.g. an EDU grant) rather than an AI Studio key. The Gemini SDK (software development kit, Google's toolkit) auto-detects which one to use from the standard env vars:

| Env var | AI Studio | Vertex AI |
|---|---|---|
| `GOOGLE_GENAI_USE_VERTEXAI` | unset or `"0"` / `"false"` | `"true"` / `"1"` / `"yes"` / `"on"` |
| `GOOGLE_API_KEY` | the AI Studio key | n/a |
| `GOOGLE_CLOUD_PROJECT` | n/a | your GCP (Google Cloud Platform) project ID |
| `GOOGLE_CLOUD_LOCATION` | n/a | `global` for Gemini 3.x preview models (early releases), which are the defaults; a region (location of the rented computers) works only for GA (generally available, finished) models |
| Auth method (how you log in) | API-key string | Application Default Credentials (Google's stored login) |

For Vertex, authenticate once per machine (`gcloud` is Google Cloud's command-line tool):

```bash
gcloud auth application-default login
gcloud config set project <your-gcp-project-id>
```

Then either set the env vars yourself or pass `--vertex`:

```bash
# Option A: env vars, then a normal run
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_PROJECT=my-project
export GOOGLE_CLOUD_LOCATION=global
python3 run_research_session.py --study openness_maneuvering ...

# Option B: CLI flag (flips the env vars in-process; project + location
# must already be exported, or pass them via --vertex-project /
# --vertex-location)
python3 run_research_session.py --vertex \
  --vertex-project my-project --vertex-location global \
  --study openness_maneuvering ...
```

The framework's `providers.validate_vertex_config()` is called at startup so a missing `GOOGLE_CLOUD_PROJECT` or `GOOGLE_CLOUD_LOCATION` fails fast with an actionable message — not 30 seconds into a Phase 1 (the team's deliberation) LLM call. The manifest's `vertex_config` block records whether Vertex AI was on and its location, with the project shown as `(not recorded)`, so a reviewer can tell which mode produced the run.

**Retrieval (searching a firm's documents) has its own region.** Gemini 3.x preview models need `GOOGLE_CLOUD_LOCATION=global`, but RAG Engine (Google's paid service that stores documents and searches them) has no `global` endpoint (web address for requests), so a grounded run (one given source documents) also needs `RAG_LOCATION` set to a region. Check that region's RAG Engine tier first, and do not assume `us-central1`: it may be on the Scaled tier (price level), which bills about $30 a day against about $3 for Basic, at list rates for Spanner (the Google database behind it), while a corpus exists. See [`10_rag_repo_plan.md`](10_rag_repo_plan.md) § Cost.

Non-Gemini providers (Claude from Anthropic, OpenAI, DeepSeek, Groq, which hosts other companies' models, and Ollama, which runs models on your own computer) are **unaffected** by `--vertex` — they continue to call their own APIs (the routes for reaching their models) with their own keys. If you want Claude or OpenAI on Vertex AI's Model Garden (its catalogue of models from Google and other companies), that's a separate (currently unimplemented) wiring.

Verified by `tests/test_vertex_mode.py` (covers the env-var parser, validator, idempotent (safe to repeat) enable helper, manifest capture, and env-snapshot preservation).

## RAG corpus reproducibility

When `--rag` was set for a run, `07_rag/corpus_manifest.json` records the corpus (the run's `manifest.json` carries the same content as its `rag_config` block):

```jsonc
"rag_config": {
  "enabled": true,
  "corpus_resource_name": "projects/<proj>/locations/<loc>/ragCorpora/<id>",
  "embedding_model": "publishers/google/models/text-embedding-005",
  "top_k": 5,
  "documents": [
    {"display_name": "example_interview.txt",
     "sha256": "9e8a...", "vertex_file_name": "..."},
    ...
  ]
}
```

The corpus state lives in Google Vertex AI RAG Engine — not in git — but the **per-doc SHA256 hashes (fingerprints computed from each file's contents) pin which content was indexed (loaded for searching) at run time**. A reviewer reproducing the run uses the SHA256s to verify their reconstructed corpus matches the run's content:

1. Obtain the source documents listed in `rag_corpora/SOURCES.csv` (see [`../rag_corpora/README.md`](../rag_corpora/README.md)).
2. Set `RAG_LOCATION`, then run `python -m rag.corpus_build --company <Firm>` against your own Vertex project. Delete the store (the corpus as loaded into Google's service) when you finish, because it bills while it exists.
3. Run `python -m rag.corpus_build --company <Firm> --list` and compare the SHA256s in each file's description against `documents[*].sha256` in `07_rag/corpus_manifest.json`.
4. If they match, the documents are bit-identical to the run's, though a rebuild may still split or rank passages differently. If they don't, the document set has drifted and the reviewer can either re-source or accept the partial match.

Each run also writes a per-call retrieval log at `results/runs/<run_id>/07_rag/retrieval_log.jsonl` recording, for every LLM call in Phases 1 / 2 / 4 (deliberation, strategy documents, debrief), each full passage retrieved for the role plus `shown_chars`. Agents see each passage whole unless `TMT_PASSAGE_CHARS` sets a limit: `text[:shown_chars]` is what they were shown. See [`11_ethnography_in_silico.md`](11_ethnography_in_silico.md) §11.6 for the qualitative-reviewer auditing protocol.

The full RAG layer design is in [`10_rag_repo_plan.md`](10_rag_repo_plan.md); the Vertex AI RAG Engine vs local-RAG trade-off is documented in [`02_design_decisions.md`](02_design_decisions.md) §23. Verified by `tests/test_rag_runtime.py`, `tests/test_rag_persistence.py`, and `tests/test_compare_rag.py`.

## Multi-LLM robustness

The framework supports running the same scenario against different LLMs to assess robustness. Six providers are supported (open-weight means a model's trained numbers are published so anyone can run it):

```bash
TMT_PROVIDER=gemini_pro python3 run_research_session.py --study openness_maneuvering --out-dir results/runs/openai_gemini_dynamic_novel
TMT_PROVIDER=claude     python3 run_research_session.py --study openness_maneuvering --out-dir results/runs/openai_claude_dynamic_novel
TMT_PROVIDER=openai     python3 run_research_session.py --study openness_maneuvering --out-dir results/runs/openai_openai_dynamic_novel
TMT_PROVIDER=deepseek   python3 run_research_session.py --study openness_maneuvering --out-dir results/runs/openai_deepseek_dynamic_novel   # ~1/10 the cost of premium
TMT_PROVIDER=groq       python3 run_research_session.py --study openness_maneuvering --out-dir results/runs/openai_groq_dynamic_novel       # open-weight Llama 4 Maverick on Groq's fast service for running models
TMT_PROVIDER=ollama     python3 run_research_session.py --study openness_maneuvering --out-dir results/runs/openai_ollama_dynamic_novel     # local, free
```

The end-to-end live test suite (tests that call real models and cost money) covers all six providers via `tests/integration/test_cells_live.py` (cell_1 through cell_6; a cell is one combination of firm, industry context and product type). Each cell skips cleanly when its provider credentials are absent, so the suite is safe to run with whatever keys are available.

Then:

```bash
python3 -m analysis.compare_runs \
  results/runs/openai_gemini_dynamic_novel/*/ \
  results/runs/openai_claude_dynamic_novel/*/ \
  results/runs/openai_openai_dynamic_novel/*/ \
  > comparison.md
```

`--out-dir X` writes each run to `X/<run_id>/`, so pass the run folders, as the `*/` does here for an `X` that holds one run. Pointing `compare_runs` at `X` itself finds nothing to compare.

`compare_runs.render_report` produces a side-by-side markdown report comparing:

- Top-level scalars, or single values (company, year, timings), **models per role across runs** and git provenance, if the run folders hold a `manifest.json`, which runs A to D do not (of those, only run D has `role_models` in its `00_meta.json`; all four ran on Gemini 3.1 Pro)
- Observation-summary (the researcher agent's account of the deliberation) cardinalities, or counts (decisions / components / disagreements / alternatives / flagged-vocab uses, meaning listed words the team used unprompted)
- Debriefing shape (exchanges, each one question and its replies; ended_reason; forbidden-vocab violations, uses of words the researcher agent must avoid; areas covered)
- Strategy-document main_decisions + key_tensions per role per provider

The researcher (Observer, FieldNoter and Debriefer, the three set-ups of the one agent that watches and questions the team) is pinned to one model across all runs (`providers.OBSERVER_PROVIDER`, Gemini Pro, whatever `TMT_PROVIDER` says) so the observation summaries and debrief questions are produced by the same model regardless of which provider ran the TMT. This is what makes cross-provider comparison of the *deliberation*, not the *observation*, possible.

## Per-role LLM overrides for ablation

Ablation means changing or removing one part to see the effect. `TMT_PROVIDER_<ROLE>` overrides the team-wide LLM for one role only:

```bash
TMT_PROVIDER=gemini_pro \
TMT_PROVIDER_CEO=claude \
python3 run_research_session.py --study openness_maneuvering --out-dir results/runs/openai_ceoclaude_else_gemini
```

`role_models` in `00_meta.json` records each role's model, so it tells you which LLM produced each role's contributions. The run's manifest adds `providers_used` and `models_used`.

Verified by `tests/test_provenance_and_llm_selector.py::TestPerRoleProviderResolution`.

## Recommended reproducibility workflow

For research-quality runs that will be cited in a paper:

1. **Commit everything before the run.** `git status` should be clean (showing no unsaved edits). A `code_commit` in `00_meta.json` without the `-modified` suffix is your evidence.
2. **Tag the commit (give it a fixed name).** `git tag run-2030-cell-openai-dynamic-novel-v1` so the commit_sha is stable + human-findable.
3. **Pin the study version.** Bump `study.version` to a fresh semver (semantic version, numbered major.minor.patch) if you changed the study config; commit the bump before the run.
4. **Keep the manifest.** Every completed command-line run writes one to its folder. Either include it in the per-run folder (gitignored) and ship the folder out-of-band (outside the repository), or commit a redacted version to the repo (the repository, the project's files and their history) for traceability.
5. **Record the LLM provider versions.** Gemini, Claude, OpenAI all rotate their model IDs occasionally. `00_meta.json` records the resolved model ID at the time of the run, but the LLM behaviour at that ID may shift. For papers, record the rough date of the run alongside the commit_sha + study_version. The code sets no temperature, top-p or seed for the models, so each provider's default sampling settings apply, and neither the manifest nor `00_meta.json` records them.
6. **For a multi-run study (e.g. the 2×2 × 5-firm design), publish a single manifest summarising all 20 runs**, with per-run commit_shas + study_versions + provider IDs. Reviewers want one document, not 20.

See `08_known_limitations.md` for the full list of what we explicitly do not claim about the framework's outputs.
