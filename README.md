# Ethnography in silico

*In silico* means carried out by computer rather than in the field. This is a framework (shared software that any study can use, not a conceptual framework) for simulating and observing deliberation among role-based language-model agents. A language model is a program trained on vast amounts of text to write likely continuations of the text it receives, and an agent is a language model given a name, a role and instructions. [`docs/GLOSSARY.md`](docs/GLOSSARY.md) explains the terms used here.

1. A team of agents (by default a six-person top management team) deliberates on a strategic decision under conditions you define.
2. A researcher agent observes without intervening, keeps field notes, and then debriefs (interviews) the team.
3. Every run (one complete simulated meeting and debrief) is saved as linked text records that you can analyze qualitatively and audit back to their sources.

In these documents, "model" means a language model, not a statistical or theoretical model.

The first study built on the framework is `studies/openness_maneuvering/`, which asks how firms maneuver openness to create and capture value.

**Status.** This is a research prototype. Tag `v2.0` (a tag is a fixed name for one saved version of the code) is the version described in the accompanying Organization Science proposal. This copy is anonymised for double-blind review. No licence has been granted yet; we will add an open-source licence at final release. [`ROADMAP.md`](ROADMAP.md) lists what is built and what is planned.

**Reviewing this?** Start with:

1. the [summary table of what we learned](docs/LEARNINGS.md#summary);
2. the [table of safeguards](docs/05_methodological_invariants.md#the-five-invariants);
3. the [tests we will run before collecting data](ROADMAP.md#before-collecting-the-studys-data);
4. one run: the [walkthrough of run D](example_runs/README.md#read-one-run-run-d), with its [provenance report](example_runs/provenance/run_D.md) (where its words first appeared).

[`docs/README.md`](docs/README.md) gives a longer route.

## Start here if you are new to AI agents

An agent is a language model (the kind of system behind ChatGPT) playing a named role.

**To read only,** you need no software, account or payment. Follow the [walkthrough of one run](example_runs/README.md#read-one-run-run-d).

**To run it,** you need Python, a plain-text editor and the Terminal. The tests and dry run below are free and need no keys.

**Real runs cost money.** At Google's list prices we estimate about $15 for a full run grounded in a firm's documents. Set a budget with your provider. Grounded runs also bill about $3 to $30 a day until the document store is shut down, so involve a technical colleague.

## What these records can and cannot show

Everything agents write is generated text, not the view of a person or firm. A debrief answer is newly written, not a memory, so it can describe agreements that never happened.

The records show how language-model agents deliberate under given prompts. They do not by themselves show how real executives behave. Patterns can suggest propositions about real firms, which need testing on archival or public data.

One run is one sample, and prompts can come back as apparent findings. So judge patterns across repeated runs, and trace who supplied each passage. The safeguards limit what prompts tell the agents; they cannot remove what models absorbed in training.

See [`docs/LEARNINGS.md`](docs/LEARNINGS.md) and [`docs/08_known_limitations.md`](docs/08_known_limitations.md).

## Quickstart

You need Python 3.10 to 3.13 (Python is the programming language this project is written in; a pinned package does not install on 3.14 or later, so if your default `python3` is newer, use, for example, `python3.13 -m venv .venv` below). Type the commands below at the command line (the terminal window, where programs are run by typing rather than clicking), from the top folder of this repository.

**1. Install.** These commands create a virtual environment (`.venv`: a private folder of packages, kept apart from the rest of the computer) and use pip (Python's installer) to add the packages (bundles of ready-made code) the project needs.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**2. Run the tests.** These are unit tests (small automatic checks that one part of the code behaves as intended). They need no keys and cost nothing:

```bash
scripts/run_tests.sh
```

The repository root (its top folder) is itself a Python package, so the script (a short program run from the command line) runs pytest (a tool that runs Python tests) in importlib mode (one way of loading the code) with the folder above it as pytest's root directory. Plain `python3 -m pytest tests/` fails with import errors.

**3. See a whole run for free.** This runs every step on a stand-in for the model. It needs no keys, takes seconds, and prints how many calls each phase makes, how large they are and a rough list cost. The stand-in's text is filler, so this checks wiring and size, not behavior, and its cost runs low because real answers are longer. Add `--save-prompts <folder>` to read every prompt.

```bash
python -m analysis.dry_run --rag
```

**4. Add API keys.** The steps so far need none; a real run needs at least a Google key or a Vertex AI project (see Choosing models). An API (application programming interface) is the agreed way one program asks another for a service, and here it is how the framework reaches models. An API key is a secret code that identifies who is using a service and who pays. Copy the template and fill in the keys you have:

```bash
cp .env.example .env.local
```

The code does not read `.env.local` by itself, so load it into your shell (the program in which commands are typed) before each session:

```bash
set -a; source .env.local; set +a
```

`.env.local` is gitignored: git, the tool that keeps a project's history of changes, deliberately leaves it out of the shared repository (the project's folder of files and that history). Never commit keys (never save them into that history).

**5. Run one scenario.** This runs one firm in one scenario (a setting of firm, industry context and product type) of the openness study:

```bash
python3 run_research_session.py --study openness_maneuvering --company OpenAI --industry-context Dynamic --product-type Novel
```

A run makes roughly 200 model calls (one model call is one prompt, the text sent to a model, and one reply back). On Gemini (Google's language model) at list prices (the company's published rates) we estimate about $15 and about an hour for a full grounded run (one where agents get a firm's real documents; unrelated to grounded theory); the prototype runs (four test runs, not study results) took 38 to 90 minutes and cost about $15 to $67, before we stopped re-sending earlier prompts (`docs/LEARNINGS.md` L15). The command above is ungrounded, which the dry run puts about a quarter lower, but we have not measured a full run on the current code. To spend less first, add `--max-actions-per-role 3 --max-exchanges 3`: this checks every step and is not data, and our grounded short run cost $2.67 and took 17 minutes. `00_meta.json` (the run's summary file) records what your run used. Time and cost depend on the provider (the company or service that supplies a model). The construct judges (models that score a finished run against a scoring guide) are optional and not part of the method: add `--judge` (a flag, meaning an option added to a command) to run them.

**6. Read the records.** Each run writes a folder under `results/runs/<run_id>/`. Start with its `README.md`. The folder holds:
- the deliberation (`01_deliberation/`);
- one strategy document per role (`02_strategy_documents/`);
- the researcher agent's observation summary and field notes (`03_researcher/`);
- the debrief transcript (`04_interview/`);
- each role's private notes and drafts (`06_private_channel/`);
- for grounded runs, every retrieved passage (`07_rag/`);
- the tokens (small pieces of text, often about three-quarters of a word, that models read and write and providers charge by) each model call used (`08_usage/`), with the total and list cost in `00_meta.json`;
- `manifest.json` (a file listing what produced the run), with each role's model and hashes (short fingerprints computed from a file's contents, so any change alters them) of what agents are told.

## Choosing models

- **`TMT_PROVIDER`** (an environment variable, meaning a named setting held outside the code; TMT stands for top management team) sets the model for the whole team. Options: `gemini_pro`, `gemini_flash` (Google), `claude` (Anthropic), `openai`, `deepseek`, `groq` (open-weight Llama, Meta's model, hosted by the company Groq; open-weight models have their trained numbers published so anyone can run them) and `ollama` (local open-weight models, run on your own computer).
- **`TMT_PROVIDER_<ROLE>`** overrides one role, for example `TMT_PROVIDER_CTO=claude`.
- **The researcher agent (observer, field noter and debriefer) is currently fixed to Gemini Pro,** so every run needs `GOOGLE_API_KEY` or a project on Vertex AI (Google's paid cloud service offering models). Making it configurable is planned.

See `providers.py` and [`docs/07_reproducibility.md`](docs/07_reproducibility.md).

## Grounding runs in documents

Grounding means giving agents a firm's real documents so their text can be traced to sources. It is unrelated to grounded theory and does not prove truth. With `--rag` (RAG, retrieval-augmented generation, means searching a document collection and adding the passages found to a model's prompt before it writes), each role retrieves passages from its own firm's corpus (collection of documents) before every model call and cites what it uses. If no corpus can be opened, the run stops with an error instead of continuing ungrounded.

1. Put the firm's documents in `rag_corpora/<Firm>/`. The documents themselves stay out of git; see [`rag_corpora/README.md`](rag_corpora/README.md).
2. Check them against the source list [`rag_corpora/SOURCES.csv`](rag_corpora/SOURCES.csv) (a plain-text table of every document and its fingerprint): `python -m rag.sources --root rag_corpora`.
3. Build the corpus: `python -m rag.corpus_build --company <Firm>`.

**Cost warning.** Grounded runs need `RAG_LOCATION` set to a region (the geographic location of the rented computers), because RAG Engine (Google's paid service that stores a corpus and runs the searches) has no `global` endpoint (the web address at which a service receives requests). A corpus store (a firm's corpus as loaded into Google's cloud service for searching) bills for as long as it exists, whatever its size: about $3 a day on the Basic tier (price level) and about $30 a day on Scaled, at Spanner (the Google database behind the store) list rates. `rag.corpus_build` prints the tier and refuses Scaled unless you pass `--allow-scaled`. When you finish, delete the store and set the tier to Unprovisioned (which stops the database); [`docs/REPRODUCE.md`](docs/REPRODUCE.md) has the steps.

Retrieval currently runs on Google Vertex AI RAG Engine. A local vector-store option (a store on your own computer that finds the texts closest in meaning to a search) is planned.

## Create your own study

A study is a folder under `studies/` that supplies the question, the decision task, the debrief topics and, optionally, a corpus. You don't edit framework code to add one, but the six-person team and the scenario conditions (the fixed wording for industry and product settings) are fixed for now: setting them per study is planned (P2, priority level 2 in [`ROADMAP.md`](ROADMAP.md)). Start with [`studies/README.md`](studies/README.md).

## Reproduce our work

[`docs/LEARNINGS.md`](docs/LEARNINGS.md) records what the pilot (the earlier study that preceded this framework, held in its own repository) and prototype runs taught us, and [`example_runs/`](example_runs/) holds records of four prototype runs. [`docs/REPRODUCE.md`](docs/REPRODUCE.md) explains how to rerun the openness study on this framework, and the CrewAI pilot (CrewAI is other software for building teams of agents) that preceded it.

## Repository map

The framework is built on Google's Agent Development Kit (ADK: ready-made software for building agents) and LiteLLM (software that reaches many companies' models in the same way), which let it run on commercial or open-weight models.

| Path | What it holds |
|---|---|
| `run_research_session.py` | Command-line entry point for one run |
| `agent.py`, `orchestrator/` | Builds the team and runs deliberation, strategy documents, observation and debrief |
| `roles/` | Role agents and the researcher agent (field noter, observer, debriefer) |
| `protocols/` | The ethnographic debrief protocol (its rules and topics) |
| `rag/` | Grounding: corpus building, retrieval, citations, source-list check |
| `analysis/` | Saving run folders, replication manifest, quote verification (checking a quote appears word for word), run comparison |
| `providers.py` | Model selection per role |
| `studies/` | One folder per study; `openness_maneuvering` is the worked example |
| `tests/` | Unit tests, including the method's safeguards; live tests (which call real models and cost money) run only with `--run-live` |
| `docs/` | Framework documentation; start with [`docs/README.md`](docs/README.md) |
| `example_runs/` | Records of four prototype runs and a short check of the current code |
| `rag_corpora/` | The source list and how to build a corpus; the documents themselves stay out of git |
| `scripts/` | `run_tests.sh`, and two batch scripts from development that start several paid runs. Use `run_research_session.py` instead; a batch runner is planned |

## The method's safeguards

The researcher agent must not steer what it studies.

1. **Observing.** By default it observes blind to the research question and theoretical lens (the theory the study will analyze through), though it receives a list of words to avoid and to log. A study can instead choose embedded observation (`embedded_observation=True`), where it knows the question while observing but still not the lens. The openness study's main runs will use embedded observation; the four prototype runs used the default.
2. **Debriefing.** The debriefer always knows the question and lens, and the panel (the six role agents when questioned in the debrief) never does.
3. **Questions.** Debrief questions are checked against the study's construct vocabulary (its list of theory terms).
4. **Retrieval.** Retrieval queries (the text each search uses) never include the research question. In the debrief, a role's query does include the question the researcher agent just asked, so its framing can affect which passages return; every query and passage is logged.
5. **Tests.** Tests check these rules on fixed lists of studies, not on every study, so add a new study to `STUDY_SLUGS` (the test list of studies' short folder names) in `tests/test_methodological_invariants.py`, and run them with `scripts/run_tests.sh`; see [`docs/05_methodological_invariants.md`](docs/05_methodological_invariants.md).

## Data, keys and copyright

- Run outputs (`results/`) and grounding documents stay out of git.
- Grounding documents may be under publisher copyright, so we share a source list with hashes instead of the documents.
- Keys belong only in `.env` or `.env.local`.

## More

- The CrewAI pilot that preceded the framework has its own repository: [`ethnography-in-silico-pilot`](https://github.com/airesearchagents/ethnography-in-silico-pilot)
- Design decisions: [`DECISIONS.md`](DECISIONS.md) and [`docs/02_design_decisions.md`](docs/02_design_decisions.md)
- Known limitations: [`docs/08_known_limitations.md`](docs/08_known_limitations.md)
