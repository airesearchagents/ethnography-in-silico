# 1. Architecture

## Top-level view

The framework (the shared software in this repository, not a conceptual framework) is one Python codebase (a single body of code in the Python programming language) that hosts multiple research studies. Each study supplies its own *framing* (research question, theoretical lens, construct-specific vocabulary, scenario brief) but reuses the framework's *behaviour* (role definitions, deliberation orchestrator, researcher prompts, persistence layer, replication manifest). Deliberation is the team's simulated meeting, the orchestrator is the code that runs it and the later phases (the numbered stages of a run), prompts are the text sent to a language model, the persistence layer is the code that saves records, and the replication manifest is a file listing what produced a run. A scenario brief is a short description of the kind of firm simulated. A run is one complete simulated meeting and debrief, also called a research session.

Key to the diagram below (full definitions are in the [glossary](GLOSSARY.md)). `<slug>` is a study's short folder name, and `StudyConfig` holds its settings. RQ is the research question. TMT is the top management team, here the six role agents (simulated executives). An agent is a language model given a name, a role and instructions, and a factory is code that builds one. An artefact is a role's strategy document. The observer, field noter and debriefer are the researcher agent set up three ways, called shells. CLI (command-line interface) means running a program by typing commands, and `--judge` and `--rag` are flags, options added to a command. ADK (Agent Development Kit) is Google's ready-made software for building agents, and LiteLLM lets one program reach models from many providers (the companies or services supplying them) in the same way. A Runner hands a prompt to an agent and collects the reply, a Session is a stored conversation re-sent to the model with each new prompt, and Content is a message in ADK's format. RAG (retrieval-augmented generation) means searching a document collection, called a corpus, and adding the passages found to a model's prompt before it writes. `.md` files are Markdown, plain text with simple marks for headings and lists, and `.json` files are JSON, plain text holding data as named fields. `00_meta.json` is a run's summary file.

```
                        ┌──────────────────────────────────────────┐
                        │            studies/<slug>/               │
                        │  StudyConfig: RQ, lens, scenario brief,  │
                        │  construct & flagged vocabulary, etc.    │
                        └────────────────────┬─────────────────────┘
                                             │ (study config)
              ┌──────────────────────────────┼──────────────────────────────┐
              │                              │                              │
              ▼                              ▼                              ▼
       ┌─────────────┐               ┌──────────────┐              ┌──────────────────┐
       │   roles/    │               │ orchestrator/│              │ run_research_    │
       │  6 TMT      │               │  deliberation│              │  session.py      │
       │  factories  │◄─────────────▶│  artefact    │◄────────────▶│ (entry point +   │
       │ + observer  │               │  collection  │              │  CLI)            │
       │ + field     │               │  panel       │              │                  │
       │   noter     │               │  debriefing  │              │                  │
       │ + debriefer │               │  researcher  │              │                  │
       │             │               │  stream      │              │                  │
       └──────┬──────┘               └──────┬───────┘              └────────┬─────────┘
              │                             │                                │
              └──────────────┬──────────────┘                                │
                             ▼                                               │
                      ┌──────────────┐                                       │
                      │  ADK 1.17    │                                       │
                      │  + LiteLLM   │                                       │
                      │  Runner,     │                                       │
                      │  Session,    │                                       │
                      │  Content     │                                       │
                      └──────────────┘                                       │
                                                                             ▼
                                                                    ┌────────────────┐
                                                                    │ analysis/      │
                                                                    │  persist       │
                                                                    │  replication   │
                                                                    │  compare       │
                                                                    │  manifest      │
                                                                    └────────────────┘
                                                                             │
                                                                             ▼
                                                                    results/runs/<id>/
                                                                      00_meta.json
                                                                      01_deliberation/
                                                                      02_strategy_documents/
                                                                      03_researcher/          (summary + field notes)
                                                                      04_interview/
                                                                      05_judging/             (opt-in via --judge)
                                                                      06_subdimension_scores/ (opt-in; openness study only)
                                                                      06_private_channel/     (notes, drafts, inboxes)
                                                                      07_rag/                 (--rag only)
                                                                      README.md
```

## Modules and what each owns

A module is a Python file or folder of code with one job.

| Module | Owns | Does NOT own |
|---|---|---|
| `studies/` | Per-research-project framing: research question, theoretical lens, construct-specific vocab, scenario brief. One sub-package (subfolder of code) per study. Pure data + Pydantic schema (a template of required fields, checked by the Pydantic tool); no LLM (large language model) calls (a call is one prompt sent to a model and one reply back). (`panel_roles`, `role_factories_module` and `contexts_module` exist in the schema but are not yet wired in; planned, P2, a priority level in `ROADMAP.md`.) | Role definitions, orchestration, persistence. |
| `roles/` | Six TMT role agent factories (`create_ceo_agent`, …) + the qualitative researcher's three shells (Observer, FieldNoter, Debriefer). Each factory returns a Pydantic-configured `LlmAgent` (ADK's agent object). Also the code that loads the protocol (the debrief's rules and topics) from its YAML file (a plain-text settings format), and the forbidden-vocabulary (words the researcher may not use) runtime guard (a check made as the run goes). | The orchestration loop or session management. |
| `orchestrator/` | The deliberation modes (`CEO_LED`, `RANDOM_INITIATOR`, `PARALLEL_THEN_DISCUSS`, `ROUND_ROBIN`, `CONCURRENT` — the default, in which all six roles act at once) + artefact collection + panel debriefing turn loop + the live researcher stream + the construct-judge ensemble (a set of models scoring a finished run; `construct_judging.py`, registered by a study via `extra_phases`). State management (tracking what each role has done and holds) for the concurrent mode (`SharedState`). | Per-study content. |
| `agent.py` | The top-level `TMTSystemWithA2A` class (a bundle of code; A2A: agent-to-agent, a removed method for agents to call each other, surviving in this name): builds the six role agents, holds the `InMemorySessionService` (the store for sessions), implements `run_strategic_discussion`. | The phases beyond build — those live in the orchestrator. |
| `run_research_session.py` | End-to-end driver (the program that carries out a whole run). Loads the study, builds the TMT, runs the four required phases (Build / Deliberation / Artefacts / Observation / Debriefing) plus every `PhaseHandler` (code a study plugs in to add a phase) the study registers in `extra_phases`, persists outputs. CLI entry point with `--judge` (opt into construct-judging phases — see PhaseHandler below) and `--no-json` flags. | Any phase-specific orchestration; it delegates to the orchestrator modules. |
| `analysis/` | Persistence (`persist_artefacts.burst_run`), replication manifest (`replication_package.ReplicationManifest`, written to the folder of every completed command-line run), comparison reports (`compare_runs.render_report` for multi-LLM robustness; `compare_rag.py` for the with-RAG vs without-RAG harness, a small comparison program — see [`10_rag_repo_plan.md`](10_rag_repo_plan.md)), citation-rendering (`citation_rendering.py` — inline Markdown footnotes from `Citation` structured outputs, replies forced into fixed, named fields), sub-dimensional text-scoring (counting words from fixed lists; `text_measures/dictionary.py` — study-specific layer for the openness study, see [`studies/openness_maneuvering/docs/02_subdimension_measurement_plan.md`](../studies/openness_maneuvering/docs/02_subdimension_measurement_plan.md)). Markdown is the mandatory output format; JSON is optional (`--no-json`). | LLM calls during a run. The replay (re-running one later stage from a saved run) and test tools here (`replay_debrief`, `replay_judges`, `researcher_turn_test`, `panel_probe`) make their own. |
| `rag/` | RAG-grounded (given a firm's real documents; unrelated to grounded theory) TMT deliberation layer. `schemas.py` (`Citation`, `RetrievedSnippet`); `vertex_corpus.py` (wrapper, a thin layer of code, over `vertexai.rag` in Google's Vertex AI cloud service); `queries.py` (per-phase retrieval-query builders; a query is the text a document search uses — invariant I5, a rule that must always hold, baked in; see [`05_methodological_invariants.md`](05_methodological_invariants.md)); `prompt_inject.py` (REFERENCE MATERIAL block + populate-citations instruction); `runtime.py` (`RagSession` + loader resolver); `corpus_build.py` (`python -m rag.corpus_build` CLI). Active only when `--rag` is set + the active study has `rag_corpus_loader` set. Detail: [`10_rag_repo_plan.md`](10_rag_repo_plan.md). | LLM calls (those live in `roles/` + `orchestrator/`). |
| `providers.py` | Provider selection (`gemini_pro`, `gemini_flash`, `claude`, `openai`, `deepseek`, `groq`, `ollama`; Gemini is Google's language model, Claude is Anthropic's, OpenAI makes GPT models, and Ollama runs publicly released models on your own computer), per-role overrides, the rule pinning the researcher (Observer, FieldNoter, Debriefer) to `OBSERVER_PROVIDER` (Gemini Pro), judge ensemble (pinned to `gemini_pro` + `claude` + `openai` + `deepseek` for cross-provider construct comparability), structured-output adapter (`build_structured_agent` / `classify_structured_output_mode`). DeepSeek (a language model company) and Groq (a company hosting publicly released models) are low-cost LiteLLM-routed alternatives for development runs. Gemini calls can route through Vertex AI (`--vertex`) for runs spending GCP (Google Cloud Platform) credits — see `enable_vertex`, `validate_vertex_config`, `snapshot_vertex_config`. | Any prompt content. |
| `data_capture.py` | The structured `DeliberationLog` and `DeliberationEvent` schemas. | The orchestration that fills them. |
| `protocols/ethnographic_protocol.yaml` | **Framework-level** ethnographic-debriefing protocol: methodological forbidden vocabulary, the five generic thematic areas (A — decision anchoring, B — counterfactuals, C — disagreement and resolution, I — context sensitivity, J — reflection and unresolved), panel format, behavioural rules, stance. **Study-agnostic.** A study can extend the thematic areas with its own construct-anchored probes through `StudyConfig.protocol_overlay` (see `studies/openness_maneuvering/debriefing_overlay.yaml` for the openness study's D–H overlay, its own debrief topics merged on top of the shared protocol). | Study-specific construct vocabulary and construct-anchored thematic areas (those live in `studies/<slug>/`). |
| `tests/` | Unit tests (small automatic checks of one part of the code) + integration tests (checks that parts work together). Three categories: `tests/*.py` (fast unit), `tests/integration/test_*_live.py` (gated on `--run-live`, hits real LLMs), and `tests/test_methodological_invariants.py` (the load-bearing safety net that enforces the framework's blindness (by default the observer and field noter are not told the research question or lens) and anti-steering (no leading agents toward what a study hopes to find) rules across study fixtures, prepared inputs that tests run on). | — |

## The phases of a research session

Each `run_research_session.py` invocation drives four required phases (0/1/2/3/4 — Build / Deliberation / Artefacts / Observation / Debriefing) plus every extra phase the active study registers via `StudyConfig.extra_phases`. The default `openness_maneuvering` study registers `ConstructJudgingPhase`, which is gated by the CLI `--judge` flag. Detailed walkthrough in `03_simulation_workflow.md`. In the table below, the driver is the code that runs the phase, written as `file::function`.

| Phase | Driver | Outputs |
|---|---|---|
| **0. Build** | `TMTSystemWithA2A.__init__`, `_build_default_runner` | Six role agents, the session service, the FieldNoter + ResearcherStream (code feeding it live events) |
| **1. Deliberation** | `orchestrator/concurrent_mode.py::run_concurrent_mode` (dispatched via `orchestrator/deliberation.py`) | `DeliberationLog` of every public action |
| **2. Artefacts** | `orchestrator/artefact_collection.py::collect_role_artefacts` | Six `StrategicArtefact` documents (one per role) |
| **3. Observation** | `roles/qualitative_researcher_agent.py::create_observer_agent` + `_build_observer_prompt` | One `ObservationSummary` |
| **4. Debriefing** | `orchestrator/panel_debriefing.py::run_panel_debriefing` (uses the merged thematic-areas protocol: framework areas A/B/C/I/J + any study-overlay areas — D/E/F/G/H for the openness study) | `DebriefingTranscript` of researcher ↔ panel exchanges |
| **Extra phases** | Each `PhaseHandler` in `study.extra_phases`, in order. Default-study: `orchestrator/construct_judging.py::ConstructJudgingPhase` (opt-in via `--judge`) | E.g. `ConstructJudgmentBundle` — four-model ensemble scores against the study's rubric + Krippendorff's α (a measure of agreement among coders) |

The researcher (one persona, three LlmAgent shells — Observer/FieldNoter/Debriefer) is in the room from Phase 1 onward via `orchestrator/researcher_stream.py`. The FieldNoter accumulates live observations during Phases 1 + 2; the Observer consolidates at the start of Phase 3; the Debriefer drives Phase 4. Each call receives what the researcher has observed so far (`orchestrator/role_memory.py`).

### Extra phases via `PhaseHandler`

A `PhaseHandler` is a small `typing.Protocol` (Python's way of stating what such code must provide, unrelated to the debrief protocol; `studies/base.py::PhaseHandler`) with five members:

- `name: str` — used in logs, in `00_meta.json`'s `phases_captured` + the CLI gate (e.g. `--judge` opts into any handler whose name is `"construct_judging"`).
- `async run(...)` (async: able to run alongside other tasks) — invoked after Phase 4 with the run's transcripts + artefacts.
- `persist(out_dir, result, write_json)`: writes the handler's outputs into the run folder.
- `folder_prefix: str`: the numbered folder its outputs go in, for example `05_judging`.
- `should_run(study=..., outputs=...)`: whether the handler runs on this session.

A study registers handlers by setting `extra_phases=[MyHandler(), …]` on its `StudyConfig`. The framework iterates and runs each handler whose `should_run(...)` returns True. Handler identifiers are exposed via `StudyConfig.extra_phase_ids_for_manifest()` so a reviewer can resolve them back to the implementing class. This is the seam that lets a study add quantitative scoring, judge ensembles, or other post-deliberation phases without modifying any framework code.

### RAG grounding (optional, `--rag`)

When the CLI's `--rag` flag is set, the framework resolves a per-firm Vertex AI RAG corpus at session start through the active study's `rag_corpus_loader` (the run exits with an error if no corpus session can be resolved) and threads a `RagSession` through Phases 1 / 2 / 4. Every role agent retrieves ~5 excerpts from the firm's corpus before each LLM call and sees each one whole, with the query built from role + task + transcript only (invariant I5 — never from RQ or lens). Role agents populate `citations: List[Citation]` in their structured outputs; the persistence layer renders citations as inline Markdown footnotes in the per-run MD files. The researcher shells (Observer / FieldNoter / Debriefer) do **not** retrieve — invariants I1–I3 hold. A `07_rag/` audit folder per run records the corpus manifest + retrieval log + per-doc SHA256s (fingerprints computed from each file's contents) for reproducibility. The comparison harness `python -m analysis.compare_rag` pairs RAG vs no-RAG runs and writes the methodological-evidence report. Detail: [`10_rag_repo_plan.md`](10_rag_repo_plan.md). For the framing — why a TMT-simulation framework is documented as **ethnography in silico**, see [`11_ethnography_in_silico.md`](11_ethnography_in_silico.md).

## Why these boundaries

- **Studies separate from roles** — so a different study can have different research framing without rewriting any role factory.
- **Roles separate from orchestration** — so the same six role agents work under any deliberation mode (sequential CEO-led, parallel, concurrent).
- **Orchestration separate from persistence** — so a future change to how runs are saved (e.g. a database backend) doesn't touch any LLM-facing code.
- **Phases separate from each other** — so a future change to e.g. the debriefing loop (different stop rule, different routing) doesn't risk corrupting Phase 1. A stop rule is the condition that ends a discussion.

## What each call carries

Every model call has its own empty ADK session, and its prompt carries what the agent needs, once. A session shared across calls re-sends every earlier prompt each time, which was most of a run's cost (`DECISIONS.md` §52, a numbered entry).

| Call | What it receives |
|---|---|
| Deliberation turn | The public transcript so far, and the role's own notes, draft and inbox (questions colleagues sent it) |
| Strategy document | The whole discussion, the role's own notes and draft, and the CEO's synthesis |
| Field note | The new events and all the researcher's notes so far |
| Observation summary | The whole discussion, the documents, every role's private notes, and the field notes |
| Debrief answer | The whole discussion, the role's own notes, draft and document, the debrief so far, and the answers already given to this question |
| Debrief question | Everything the researcher observed, and the debrief so far |

A role never sees another role's notes, and sees another role's draft in one case: the CEO's working draft closes the log as the team's final synthesis, so every role reads it before writing its document and during the debrief. If the CEO wrote no draft, the longest other draft takes its place. What stays the same between calls goes first in the prompt, so that a provider's automatic caching (charging less for input text it recently processed) could discount it. In a grounded run the long repeated openings are in debrief calls: a deliberation turn's retrieved passages change early in its prompt, and document calls do not repeat. Live checks have recorded no discount so far (`LEARNINGS.md` L15). `orchestrator/role_memory.py` builds these blocks, and `tests/test_call_context.py` checks them by running a whole session on a stub model (a simple stand-in giving set replies, so tests run free).

## Tested invariants

The framework's methodological boundaries are guarded by tests, not just docstrings (descriptions written inside the code):

- `tests/test_methodological_invariants.py` — by default, Observer and FieldNoter prompts MUST NOT contain the study's research question or theoretical lens. Debriefer prompt MUST contain both AND the anti-steering framing. Parametric (repeated for each) over the studies in `STUDY_SLUGS`, a fixed tuple (a list that does not change), so a new study must be added to it. The construct-word check in this file (I4) runs on the openness study only.
- `tests/test_observation_stance.py` — with `embedded_observation=True`, the Observer and FieldNoter know the question but still not the lens.
- `tests/test_rag_persistence.py::TestInvariantI5NoQueryLeakAcrossStudies` — retrieval queries carry neither the research question nor the lens (I5), on two named studies.
- `tests/test_study_config.py` — `StudyConfig` schema + loader behave correctly.
- `tests/test_protocol_overlay.py` — `_apply_study_overlay` deep-merge (combining nested settings item by item) semantics: `thematic_areas_overlay` append, `behavioural_rules_additions` paragraph-append, `panel_format_additions` dict-merge, unknown overlay keys silently ignored.
- `tests/test_phase_handlers.py` — `PhaseHandler` protocol contract + framework's iteration over `study.extra_phases`.
- `tests/test_call_sessions.py` — every model call has its own session.
- `tests/test_call_context.py` — each kind of call receives what it needs, and no role sees another's private notes.
- `tests/test_researcher_stream.py` — live observation buffering + flush behaviour (holding events, then passing them on).
- `tests/test_open_product_deliberation.py` — Phase 1 prompts do not pre-bake a product, do not enumerate 5W+lifecycle as a checklist.
- `tests/test_discussion_dynamics.py` — peer-vs-CEO behavioural framing, cross-talk (a role joining in after a first reply) routing.
- `tests/test_construct_judging.py` — construct-judge ensemble: rubric scoring, aggregation, Krippendorff's α.
- `tests/test_dictionary_method.py` + `tests/test_subdimension_lexicon.py` + `tests/test_private_channel_persist.py` — the openness study's sub-dimensional measurement layer.
- `tests/test_structured_output_adapter.py` — per-provider structured-output mode classification (strict `json_schema` vs `json_object` hint).
- `tests/test_provenance_and_llm_selector.py` — provider resolution + low-cost provider support (DeepSeek, Groq) via LiteLLM.
- `tests/test_vertex_mode.py` — Vertex AI routing for Gemini providers.
- `tests/integration/test_cells_live.py` — end-to-end live tests across six provider cells (gemini_pro, claude, openai, ollama, deepseek, groq); each cell pairs a different LLM with a different company × industry × product combination so the suite can run in parallel via `pytest-xdist -n 6` (a tool for running tests side by side).

Run with `scripts/run_tests.sh` (or `scripts/run_tests.sh <path>`). There is no CI (continuous integration: automatic testing of every change), so the tests guard a change only when someone runs them. Live tests (which call real models and cost money) are gated on `--run-live` and `GOOGLE_API_KEY`, an API key: the secret code that identifies who is using a service and who pays (plus the relevant provider key per cell): `scripts/run_tests.sh tests/integration --run-live`.
