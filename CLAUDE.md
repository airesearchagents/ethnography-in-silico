# CLAUDE.md — ethnography-in-silico

Guidance for Claude Code and for developers working in this repository. Personal, machine-specific notes belong in `CLAUDE.local.md` (gitignored), not here.

## What this repository is

`ethnography-in-silico` is a reusable framework for simulating and observing deliberation among role-based LLM agents, built on Google's Agent Development Kit (ADK) and LiteLLM. A team of agents deliberates under conditions a study defines, a researcher agent observes and debriefs them, and every run is persisted as an auditable record for qualitative analysis. The first study built on it is `studies/openness_maneuvering/`: ethnography in silico applied to how firms maneuver openness.

Start with `README.md` (quickstart), then `docs/README.md` for the reading order. To add a study, see `studies/README.md`. The CrewAI pilot has its own repository, `ethnography-in-silico-pilot`.

## Framework vs study: keep the boundary

- **Study-specific content lives under `studies/<slug>/`.** This includes the research question, theoretical lens, vocabulary, scenario brief, debriefing overlay, rubrics and lexicons, RAG corpus loader, and the study's own documents in `studies/<slug>/docs/`.
- **Framework code and docs stay study-agnostic.** That covers `agent.py`, `run_research_session.py`, `orchestrator/`, `roles/`, `rag/`, `analysis/`, `protocols/`, `providers.py` and `docs/`. Do not add new study-specific logic there. Some legacy coupling remains (for example, the industry and product scenarios in `roles/context_definitions.py`) and is being moved into the study; see P2 in `ROADMAP.md`.
- **To add a study**, follow `docs/06_extending_to_new_studies.md`. The worked example is `studies/openness_maneuvering/docs/01_study_anatomy.md`.

## Methodological invariants: do not break

These are enforced by tests; see `docs/05_methodological_invariants.md`.

- By default the Observer and FieldNoter prompts never contain the study's research question or theoretical lens; they do receive the word lists. A study can set `embedded_observation=True`, which gives them the question but still not the lens. The Debriefer always receives both, with anti-steering framing. The panel never sees the question.
- The researcher agents (Observer, FieldNoter, Debriefer) do not retrieve from RAG corpora.
- Retrieval queries are built from role, task and transcript only, never from the research question or lens (invariant I5).
- Debriefing questions pass through the forbidden-vocabulary guard.

If a change touches any prompt, run `scripts/run_tests.sh tests/test_methodological_invariants.py` before committing.

## Commands

- Fast tests: `scripts/run_tests.sh` (or a single file: `scripts/run_tests.sh tests/<file>.py`)
- Live tests (real LLM calls; they cost money and need provider keys): `scripts/run_tests.sh tests/integration --run-live`
- One run: `python3 run_research_session.py --study openness_maneuvering --company OpenAI --industry-context Dynamic --product-type Novel`. Optional flags: `--rag` (grounding), `--judge` (construct judging), `--vertex` (route Gemini through Vertex AI). See `docs/03_simulation_workflow.md`.
- Build a RAG corpus: `python -m rag.corpus_build --company <Firm>`. Set `RAG_LOCATION` first. The store bills while it exists; see `README.md`.
- Compare grounded and ungrounded runs: `python -m analysis.compare_rag`
- Test the debrief researcher's next question on a saved run (about a minute, researcher calls only): `python -m analysis.researcher_turn_test --run-dir <run> --after-exchange <N> --repeats 10 --vertex`. Use the cheapest test that answers the question; see `docs/REPRODUCE.md`.
- Rerun only the debrief on a saved deliberation: `python -m analysis.replay_debrief --run-dir <run> --vertex`. Add `--max-exchanges` and `--roles` to spend less.
- Provider and model selection: `providers.py`, set through `TMT_PROVIDER` and per-role `TMT_PROVIDER_<ROLE>` environment variables.

## Conventions

- **`DECISIONS.md` is a numbered decision log, split into a framework part and one part per study.** Never rewrite an entry or change its number. Add a new entry that supersedes it and a one-line pointer in the old one. The top of the file says where a new entry goes, and every entry needs an index row.
- **`ROADMAP.md` lists what is built and what is planned.** Update its statuses when work lands.
- **In docs, the code is the source of truth.** Cite the file and function (`path.py::function`) and the test that enforces a behaviour. If code and docs disagree, fix the doc.
- **Keep pull requests small and reviewable,** each with tests. Run the fast suite before committing.
- **Per-run outputs are Markdown** (JSON optional, `--no-json` to skip).

## Secrets and data

- API keys live only in `.env` or `.env.local`, both gitignored. Never commit keys, paste them into chat or docs, or put them in URLs.
- Never commit data. `results/`, RAG source documents (the contents of `rag_corpora/<Firm>/`) and other datasets stay out of git.
- Keep raw data outside the repository and outside cloud-synced folders, and point tools at it with a path or environment variable. Grounding documents are the exception: they go in `rag_corpora/<Firm>/`, which is gitignored, unless you pass `--docs-dir` to `rag.corpus_build`.
- RAG source documents may be under publisher copyright. Do not redistribute them.
