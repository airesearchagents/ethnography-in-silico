# Reproducing our work

This guide explains how to rerun the two pieces of work behind the accompanying Organization Science proposal:
1. the openness study on this framework (the shared software held here);
2. the CrewAI pilot (an earlier study, built on other software called CrewAI) that preceded it, which has its own repository (a project's folder of files with its full history of changes).

This copy is anonymised for double-blind review.

## What "reproduce" means here

Language models (programs trained on vast amounts of text to write likely continuations of the text they receive) are stochastic (involving chance, so the same prompt, the text sent to a model, can produce a different reply each time), so rerunning a scenario (one firm, one industry context and one product type) gives a **new sample from the same process**, not the same transcript. Patterns are therefore judged across repeated runs (a run is one complete simulated meeting and its debrief, the interview that follows) of each scenario, not from a single run. What defines the process is pinned (fixed and recorded):
- the study and its version;
- the prompts;
- the model for each agent (an agent is a language model given a name, a role and instructions);
- the code commit (one saved change in the code's history, which names an exact version);
- the package (bundle of ready-made code) versions.

[`07_reproducibility.md`](07_reproducibility.md) covers the replication manifest (a file recording what produced a run) in detail.

## 1. The openness study on the framework

### Setup

Type the commands below at the command line (where programs are run by typing rather than clicking).

1. Check out (switch your copy of the code to) tag `v2.0` (the version the proposal describes; a tag is a fixed name for one commit) or the latest `main` (the principal line of work).
2. Install: `pip install -r requirements.txt` (pip installs packages for Python, the programming language used here; you need Python 3.10 to 3.13).
3. Copy `.env.example` to `.env.local`, add your keys (API keys: secret codes that identify who is using a service and who pays), and load them with `set -a; source .env.local; set +a`.
   - Every run needs `GOOGLE_API_KEY`, or a project on Vertex AI (Google's paid cloud service offering models), for the observer (the researcher agent that watches the team).
   - Add the key for the provider (the company or service that supplies a model) that will run the team.
4. Check the install with `scripts/run_tests.sh` (a short program that runs automatic checks). This needs no keys.

### One run

```bash
python3 run_research_session.py --study openness_maneuvering --company OpenAI --industry-context Dynamic --product-type Novel
```

**The design.** Five firms (OpenAI, Anthropic, HuggingFace, Meta, Alphabet) × industry context (`Dynamic`, `Stable`) × product type (`Novel`, `Enhancement`) give 20 scenario cells (combinations). Repeat each cell to see which patterns recur.

**Choosing models.** Set `TMT_PROVIDER` (a named setting held outside the code; TMT stands for top management team) for the team, for example `claude`, `openai`, `gemini_pro`, `deepseek`, `groq` or `ollama` (the last two reach open-weight models, whose trained numbers are published so anyone can run them). To vary models within a team, set `TMT_PROVIDER_<ROLE>`.

**Limits you can set.**

| Setting | What it does | Default |
|---|---|---|
| `TMT_RATELIMIT_<PROVIDER>_TPM`, `TMT_RATELIMIT_<PROVIDER>_RPM` | Caps tokens (pieces of text providers charge by) and requests per minute for that provider. `off` removes the cap | A cautious figure for each hosted provider; none for local Ollama |
| `TMT_LLM_CALL_TIMEOUT_S` | Seconds before a model call counts as failed and is retried | 180 |
| `TMT_RETRIEVAL_TIMEOUT_S` | Seconds allowed for one document search | 60 |
| `TMT_PASSAGE_CHARS` | Characters of each retrieved passage agents see | The whole passage |

### Grounded runs

A grounded run gives agents a firm's real documents so their text can be traced to sources. It is unrelated to grounded theory and does not prove truth.

1. Obtain the documents listed in [`../rag_corpora/SOURCES.csv`](../rag_corpora/SOURCES.csv) and place each in `rag_corpora/<Firm>/`, as given in the `path` column.
2. Confirm they match the list: `python -m rag.sources --root rag_corpora`. This checks each file's SHA-256 hash (a short fingerprint computed from its contents, so any change alters it).
3. Choose a region (the location of Google's rented computers) and check its RAG Engine tier (RAG Engine is Google's paid service that stores documents and runs searches; RAG means retrieval-augmented generation; a tier is a price level), because the database behind it bills about $3 a day on Basic and about $30 a day on Scaled while any corpus (document collection) exists, whatever its size. Set `RAG_LOCATION` to that region; retrieval (the search step) needs a regional endpoint (the web address of a service) while Gemini 3.x (Google's language model) needs `GOOGLE_CLOUD_LOCATION=global`.
4. Build each firm's corpus with `python -m rag.corpus_build --company <Firm>`. This needs a project on Google Cloud (Google's rented computing services) with Vertex AI RAG Engine. It prints the tier and refuses Scaled unless you pass `--allow-scaled`.
5. Add `--rag` (a flag, meaning an option added to a command) to the run command. The run stops if it cannot open the corpus. Every retrieved passage, and the corpus manifest with per-document hashes, is saved in the run's `07_rag/` folder, with `shown_chars` giving how much of each passage agents saw.
6. **When you finish, delete the store and stop the database.** Run `python -m rag.corpus_build --company <Firm> --delete-corpus --yes` with the same `RAG_LOCATION`. Then set the region's tier to Unprovisioned with a `PATCH` (a web request that changes a setting) to `https://<region>-aiplatform.googleapis.com/v1beta1/projects/<project>/locations/<region>/ragEngineConfig`, body `{"name": "projects/<project>/locations/<region>/ragEngineConfig", "ragManagedDbConfig": {"unprovisioned": {}}}`. A `GET` (a web request that reads a setting) on the same address shows the current tier.

### Recording what produced a run

Every completed command-line run writes `manifest.json` to its folder, recording the team's models, hashes of the files that set what agents are told, the code version and package versions. Runs A to D predate it; [`../example_runs/short_check/manifest.json`](../example_runs/short_check/manifest.json) is a sample. That sample names our private development commit, which is not in the public history, so compare its hashes instead (see [`07_reproducibility.md`](07_reproducibility.md)).

### Comparing runs

`analysis.compare_runs.render_report([run_dir_1, run_dir_2, ...])` compares the shape of runs. `python -m analysis.compare_rag` pairs grounded and ungrounded runs of the same study version, scenario and provider, reading each run's `manifest.json`, or its `00_meta.json` where it has none.

## 2. The CrewAI pilot

The pilot came first: we built it to test our ideas, and the framework grew from its lessons. It has its own repository, [`ethnography-in-silico-pilot`](https://github.com/airesearchagents/ethnography-in-silico-pilot), tag [`pilot-as-run`](https://github.com/airesearchagents/ethnography-in-silico-pilot/tree/pilot-as-run). Its [README](https://github.com/airesearchagents/ethnography-in-silico-pilot/blob/main/README.md) describes the setup as run, and its [`REPRODUCE.md`](https://github.com/airesearchagents/ethnography-in-silico-pilot/blob/main/REPRODUCE.md) gives the steps to rerun it. To check a local copy of its documents against the source list, run `python -m rag.sources --root <pilot>/data --column pilot_path` from this repository.

## Repeat the OpenAI tests

The prototype runs (four test runs, not study results) in [`../example_runs/`](../example_runs/) all simulate one firm in a dynamic industry with a novel product. Outputs differ on every run, so you compare measures, not text.

**What you need.** A Google Cloud project with Vertex AI, on `gemini-3.1-pro-preview`, which is a preview model (an early release the provider may still change or withdraw) and may be retired. The panel probe (a test that puts one saved run's group questions to each role twice, under three conditions) also needs OpenAI and DeepSeek keys. Each ungrounded run cost us about $15 to $20 and took about 40 minutes; the grounded run cost about $67 and took 90 minutes, at list prices (a provider's published rates). The current code should cost about $15 and take about an hour for a grounded run (`docs/LEARNINGS.md` L15).

```bash
export GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_CLOUD_PROJECT=<your-project> GOOGLE_CLOUD_LOCATION=global
```

**1. Repeat a run.** The current code is closest to run D (the fourth, grounded prototype run) without `--rag`. For earlier versions, read the prompts each run used in [`../example_runs/prompts_as_run/`](../example_runs/prompts_as_run/).

```bash
python3 run_research_session.py --study openness_maneuvering --company OpenAI --industry-context Dynamic --product-type Novel --vertex
```

**2. Repeat the grounded run.** The documents cannot be redistributed. `rag_corpora/SOURCES.csv` lists them, with links where recorded, and [`../rag_corpora/BUILD_RECORD.md`](../rag_corpora/BUILD_RECORD.md) gives every setting. A copy you assemble yourself may not match our hashes, so it would be a similar corpus, not the same one. The source documents can be made available privately on request, through the editors, for review purposes only and as copyright permits.

**3. Compare with ours.** These work on your run and on the runs in `example_runs/`.

| Question | Command | Our results |
|---|---|---|
| Where did the words come from? | `python -m analysis.provenance --run-dir <run>` | `example_runs/provenance/` |
| How alike are roles, by meaning and topic? | `python -m analysis.semantic_similarity --run-dir <run> --out-dir <dir>` | `example_runs/panel_probe/semantic_full_runs/` |
| Do roles differ from their own repeat answers? | `python -m analysis.panel_probe --run-dir example_runs/run_C --vertex --allow-version-mismatch --questions 4 --mix CTO=openai,COO=openai,CMO=deepseek,Product_Designer=deepseek`, then `python -m analysis.semantic_similarity --probe <probe.json> --out-dir <dir>` | `example_runs/panel_probe/` |
| Is the gap significant, and do teams converge? | `python -m analysis.role_statistics --probe <probe.json> --runs <run> --out <report.md>` | `example_runs/panel_probe/statistics.md` |

**What will not match.** The text of any answer; the retrieved passages of run D and `short_check`, which we publish as hashes; and the provenance share for retrieved passages, which needs their text. We ran each version once, so a difference from one of our runs may be chance. Compare several runs of yours with ours.

The published copies differ from the records we analyzed. On the copies of run D and `short_check`, `analysis.provenance` cannot check quotes, which are replaced by hashes, or trace retrieved text, so it reports every quote as unmatched and shows shifted shares. The citation figures in the proposal's appendix come from the full records. `example_runs/provenance/` holds our reports on them for runs A to D. For run A, pass `--prompts-root example_runs/prompts_as_run/run_A` to trace against the prompts it used.

**The current code differs from all four runs.** `DECISIONS.md` §50 and §52 (numbered entries) list what has changed since these runs. Roles now see answers already given in an exchange (one researcher question and the replies to it) and keep the whole deliberation and their own notes, agents see whole passages, retrieval queries (the text each search uses) keep the latest context, and model calls (one prompt sent and one reply back) no longer re-send earlier prompts. A new run should not be expected to match them on those points.

## Testing a change without a full run

We estimate about $15 and about an hour for a full grounded run on Gemini 3.1 Pro at list prices, so use the cheapest test that can answer the question:

| Test | Use it for | Command |
|---|---|---|
| Unit tests (small automatic checks) | Wiring (how the parts connect), and wording the prompts must or must not contain. Free | `scripts/run_tests.sh` |
| Dry run (a rehearsal) | The whole pipeline (all stages of a run) on a stand-in model: what every prompt says, how large each call is, and a rough cost. Free. Add `--save-prompts <folder>` to read every prompt | `python -m analysis.dry_run --rag` |
| Researcher turn test | Whether the debrief researcher probes or moves on at a saved moment | `python -m analysis.researcher_turn_test --run-dir <run> --after-exchange <N> --repeats 10 --vertex` |
| Debrief replay (one later stage rerun from a saved run, with new text) | How a debrief unfolds, or comparing two debrief protocols on the same deliberation. Add `--rag` for a grounded run, and `--max-exchanges 3` to spend about $1 | `python -m analysis.replay_debrief --run-dir <run> --vertex` |
| Provenance report | Where a run's words came from, claims to check, shared phrases, citation accuracy. No model calls | `python -m analysis.provenance --run-dir <run>` |
| Panel probe | Whether roles are different voices: repeat samples, isolated answers, mixed models. Ungrounded runs only | `python -m analysis.panel_probe --run-dir <run> --vertex --mix CTO=openai,CMO=deepseek` |
| Semantic comparison | Whether roles differ in meaning and topics, from a probe or a saved run. Uses embeddings (lists of numbers standing for a text's meaning), at a very small cost, and needs the `gcloud` command (Google Cloud's tool) signed in with `gcloud auth application-default login` | `python -m analysis.semantic_similarity --probe <probe.json> --out-dir <dir>` |
| Role statistics | Significance of the role gap, and convergence during deliberation | `python -m analysis.role_statistics --probe <probe.json> --runs <run> --out <report.md>` |
| Short run | The whole pipeline on a live model and the real corpus, to check a change to the deliberation or grounding. It cost us $2.67 and took 17 minutes. Not for data | `python run_research_session.py --study <study> --company <firm> --vertex --rag --max-actions-per-role 3 --max-exchanges 3` |
| Full run | Final checks and data | see above |

The turn test starts from a finished run that kept its JSON (plain-text data as named fields) files, and it never calls the panel (the six role agents when questioned). Runs saved before field notes were kept give the researcher none. Treat results as a quick check on behaviour, not as evidence for a paper.

The debrief replay skips the deliberation, documents and observer, and writes a transcript and `comparison.md` to `results/debrief_replays/` without changing the source run. Agents get the same memory as in a full run, built from the saved files. `--max-exchanges` and `--roles` reduce cost, but with fewer roles the researcher may still address someone who is not seated. A grounded run needs `--rag`, which retrieves from the live store. Its log holds source text, so keep the output out of git (the tool that keeps a project's shared history).

## What to look at when auditing a run

- `00_meta.json`: which study, version, firm and scenario, each role's model, and any errors. The command exits with code 1 (it signals failure) if this list is not empty, and the folder keeps whatever was captured. A failed judge (a model that scores a finished run) does not count here; it leaves `05_judging/<provider>_error.txt`.
- `01_deliberation/` and `06_private_channel/`: what each agent said publicly and noted privately.
- `03_researcher/` and `04_interview/`: what the researcher agent observed, noted and asked. The transcript marks any panel answer lost to a failed call, which is not the same as a `[PASS]` (a reply meaning the agent has nothing to add).
- `07_rag/`: every passage each role retrieved and the hash of each source document. Citations are saved on the public messages, strategy documents and debrief answers that carry them, not on private notes, drafts or private answers.
