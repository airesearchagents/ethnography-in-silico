# 3. Simulation workflow

This file describes, step by step, what actually happens between `python3 run_research_session.py --study openness_maneuvering --company HuggingFace --industry-context Stable --product-type Enhancement` (the command typed to start one run, meaning one complete simulated meeting and debrief) and the final folder of artefacts (saved records, chiefly each role's strategy document).

Each step cites the code file + entry point (written `file.py::function`) so you can audit the description against the implementation. A phase is a numbered stage of a run, and an agent is a language model given a name, a role and instructions. Definitions of other terms are in the [glossary](GLOSSARY.md).

## Phase 0 — Build the system

**Driver** (the code that runs this phase): the Phase 0 block of `run_research_session.py::run_research_session`.

1. **Resolve the study.** `studies.load_study(slug)` (slug: the study's short folder name) imports `studies/<slug>/__init__.py` and returns its module-level `STUDY: StudyConfig` (the study's settings). The CLI (command-line interface: running a program by typing commands) default is `openness_maneuvering`; the caller can pass any other study slug. The framework will use this object as the source of truth for the research question, theoretical lens, construct-specific forbidden vocabulary (words the researcher agent must not use in its own writing unless quoting a team member), flagged vocabulary watch-list (words it logs word for word when team members use them unprompted), scenario brief (a short description of the kind of firm simulated), and strategic-question template.
2. **Instantiate (create) `TMTSystemWithA2A`** (`agent.py::TMTSystemWithA2A.__init__`; TMT: top management team; A2A: agent-to-agent, a removed method for agents to call each other, surviving in this name). The constructor (the code that sets the object up) builds six role agents (the simulated executives) by calling each role factory, the code that builds that agent (`roles/ceo_agent.py::create_ceo_agent`, etc.), instantiates an `InMemorySessionService` (a store for sessions, the stored conversations re-sent to a model with each new prompt), generates a `base_session_id` from microsecond timestamp + uuid (random unique code) suffix, and prepares an empty role-session cache, which only CEO-led mode uses. Each role factory reads its LLM (large language model) provider (the company or service supplying the model) via `providers.get_role_model(role)`, honouring `TMT_PROVIDER_<role>` env (environment variable: a named setting held outside the code) overrides if present.
3. **Build the per-call runner.** A runner hands a prompt (the text sent to a model) to an agent and collects the reply. `_build_default_runner(system)` returns an async callable (a function able to run alongside others) that takes `(agent, prompt)` and runs the agent in a new empty ADK (Agent Development Kit: Google's ready-made software for building agents) session. Nothing carries over between calls: each prompt holds what the agent needs (`orchestrator/role_memory.py`). Each call's token (a small piece of text, often about three-quarters of a word) counts go to `system.usage_log`.
4. **Build the live ethnographer.** `roles.create_field_noter_agent(study=study)` returns a free-form-prose researcher shell (the researcher agent has three set-ups, called shells: the field noter, which writes notes during Phases 1 and 2 without intervening; the observer, which summarises in Phase 3; and the debriefer, which questions the team in Phase 4) with no `output_schema` (a template forcing a reply into fixed fields). It is wrapped in a `ResearcherStream(synth_every=10)` (code that collects events and asks for a note about every ten) which the orchestrator (the code that runs the phases) will feed during Phases 1 and 2.
5. **Emit `phase0_complete`** to the logger (the running record the software writes). Total time at this point: a few seconds. No LLM calls yet.

## RAG grounding (active across Phases 1 / 2 / 4 when `--rag` is set)

RAG (retrieval-augmented generation) means searching a document collection and adding the passages found to a model's prompt before it writes. Grounding means giving agents a firm's real documents so their text can be traced to sources; it is unrelated to grounded theory and does not prove truth.

When the CLI's `--rag` flag (an option added to a command) is set, the framework resolves a per-firm Vertex AI (Google's paid cloud service) RAG corpus (the firm's public documents) at session start through the active study's `rag_corpus_loader` (the run exits with an error if no corpus session can be resolved) and threads a `RagSession` through Phases 1 / 2 / 4. Each role agent retrieves ~5 excerpts from the firm's corpus before each LLM call; each retrieved chunk (a piece cut from a document for searching) lands whole in a `REFERENCE MATERIAL` block in the role's prompt with a populate-citations instruction; the role's structured output (a reply forced into fixed, named fields) carries `Citation` records for excerpts it leaned on; the persistence layer (the code that saves records) renders citations as inline `[^cN]` Markdown (plain text with simple marks for headings and lists) footnotes in the per-run MD (Markdown) files. The researcher shells (Observer / FieldNoter / Debriefer) do **not** retrieve — invariants (rules that must always hold; see [`05_methodological_invariants.md`](05_methodological_invariants.md)) I1–I3 hold; new invariant I5 (retrieval queries built from role + task + transcript only, never RQ (research question) or lens) is enforced parametrically (by a test repeated across two studies). Audit trail lands in `07_rag/corpus_manifest.json` + `07_rag/retrieval_log.jsonl` per run (a manifest lists what produced something; JSON and JSONL are plain-text formats for data held as named fields); the log keeps each full retrieved chunk plus `shown_chars`, how much of it the role saw. Full detail: [`10_rag_repo_plan.md`](10_rag_repo_plan.md). For the methodological framing — why retrieval-grounded TMT deliberation matters for inductive qualitative research — see [`11_ethnography_in_silico.md`](11_ethnography_in_silico.md) §11.4 (the four channels of field data).

## Phase 1 — Concurrent deliberation

Deliberation is the team's simulated discussion of the decision task. An action is one move by a role, from one model call (one prompt sent to a model and one reply back). In the default concurrent mode, all six roles act at once rather than in a fixed order, and every public move is recorded.

**Driver:** `agent.py::run_strategic_discussion` → `orchestrator/deliberation.py::run_deliberation` → `orchestrator/concurrent_mode.py::run_concurrent_mode`.

1. **Resolve the strategic question.** If the caller didn't supply one, `run_research_session.py::run_research_session` builds one from the study's `strategic_question_template` (which may reference `{product_type}` and `{direction_hint}`). For `product_type=Novel` the direction hint is "a novel AI product direction — something the firm does not already offer"; for `Enhancement` it's "an enhancement of the firm's existing AI offering". This hint is framework text, the same for every study. The team must surface candidate product directions, evaluate, converge, and then propose how to develop / govern / release.
2. **Wrap each role agent for structured output.** `_build_concurrent_role_agent(role_agents[role], role)` returns a new `LlmAgent` (ADK's agent object) whose `output_schema=AgentAction`. ADK enforces JSON-conformance on every reply; the orchestrator coerces the parsed action into the right schema (a template saying which fields a reply must contain).
3. **Launch six `asyncio` tasks** (`asyncio` is Python's tool for running tasks side by side), one per role. Each task runs `_role_loop` which:
   - Snapshots the role's current state from `SharedState`, the record all the role loops read and update: action count, done flag, inbox of questions from colleagues, scratchpad of private notes, and draft.
   - Composes the per-turn prompt via `_compose_role_prompt`. The prompt embeds: the scenario context, the strategic question, the public transcript so far, the role's private inbox / scratchpad / draft, the role's discussion status (how many SPEAKs / ASKs / ANSWERs the role has made so far), nudges based on state ("answer your inbox before drafting"; "you haven't ASKed any peer yet"), and the `STRATEGIC DEPTH` block (no enumeration of dimensions — see `02_design_decisions.md` §9). The study's `scenario_brief` sits beside the firm's name in the scenario context.
   - Calls the LLM with `runner.run_async`. ADK returns one `AgentAction` JSON.
   - Applies the action via `_apply_action` — this mutates `SharedState`: a `SPEAK` adds a public transcript entry, an `ASK` pushes a `DirectedMessage` into the recipient's private inbox and a public echo into the transcript, an `ANSWER` pops the question from the answerer's inbox and pushes the reply into the asker's inbox (and optionally publicly), a `SCRATCHPAD` writes a private note, a `DRAFT` updates the role's strategy-document draft, and a `DONE` marks the role complete.
   - Feeds the action to the `ResearcherStream`. `_format_action_for_observer` renders the action as a single-line event ("[CEO SPEAK] we should…", "[CTO ASK → COO] what's the…"). The line goes into the stream's buffer (a temporary holding list). After every ~10 events, the stream invokes the FieldNoter LLM with the buffered batch and asks for a short field note. The note joins the stream's `field_notes` list, which later researcher prompts carry.
   - Increments the role's action count, ages stale inbox questions, yields briefly to let peer loops + the outer monitor run.
4. **The outer monitor** (`_outer_monitor`) checks wall-clock time (real elapsed time) and whether all six roles are done, and marks questions left unanswered too long so askers can move on. It tears the deliberation down when either all six roles have declared DONE (good case: `ended_reason='all_done'`) or `max_wall_clock_seconds` (default 30 min) elapses (cap case: `ended_reason='wall_clock_cap'` — any still-running role tasks are cancelled).
5. **Force-flush the ResearcherStream** at the phase-1 boundary so any tail-end events still produce a closing field note before Phase 2 begins.
6. **Materialise the deliberation log.** Every transcript entry from `SharedState.transcript` is converted to a `DeliberationEvent` and stored on `ResearchSessionOutputs.deliberation_log`. The CEO's draft (or the longest non-empty role draft) is appended as the closing "FinalSynthesis" event so downstream consumers (later code) see the headline text without parsing the action stream.
7. **Emit `phase1_complete events=N`** to the logger.

In the four prototype runs in `example_runs/` (test runs simulating one firm, used to learn about the method; they are not study results): 55–79 actions across the six roles. See "Total cost shape" below for run times.

## Phase 2 — Strategic artefact authoring

**Driver:** `orchestrator/artefact_collection.py::collect_role_artefacts`.

1. **For each role in panel order** (the team's fixed listing order; the panel is the six role agents when questioned in the debrief), build a fresh ADK shell named `{role}_Artefact` with `output_schema=StrategicArtefact`. The agent's `instruction` (standing text that tells a model who it is and how to behave) extends the role's deliberation-time persona with one additional block: "produce your role's strategic document for the deliberation that just concluded". The prompt carries the whole discussion and the role's own notes and draft.
2. **Compose the prompt.** `_build_artefact_prompt` adds the role-specific document framing (`_ROLE_DOC_FRAMING[role]` — what kind of memo this role should produce: a board memo for the CEO, a technical strategy document for the CTO, etc.) plus the `_DEPTH_REMINDER` (elaborate writing, epistemic honesty, no off-the-shelf methodology label). The prompt also includes the CEO's final synthesis, which is the CEO's working draft, as context.
3. **Invoke the LLM** via the runner. ADK validates the reply against `StrategicArtefact`; the orchestrator coerces dict / JSON-string returns (replies in other data forms) into a model instance (a filled-in record; "model" here is not a language model).
4. **Feed the artefact to the ResearcherStream.** `format_artefact(role, artefact)` renders the title + main decisions + key tensions + key challenges as a multi-line event. The stream's buffer fills; the FieldNoter is invoked again at the threshold.
5. **Append the artefact to the bundle.** Roles that fail to produce a valid artefact (validation error, meaning a reply that does not fit the template; or rate limit, a provider's cap on how much a customer may send per minute) are logged and skipped; the bundle is still returned so partial failure doesn't lose the whole session.
6. **Force-flush the ResearcherStream** at the phase-2 boundary.
7. **Emit `phase2_complete artefacts=N`** to the logger.

Six artefacts × one LLM call each = six calls. Typical Gemini Flash (a Google language model) latency (waiting time): 30–60 seconds per artefact.

## Phase 3 — Observer consolidation

The Observer is the researcher agent in Phase 3, when it consolidates everything it saw into one summary.

**Driver:** the Phase 3 block of `run_research_session.py::run_research_session` (`_build_observer_prompt`, `_run_observer`) + `roles/qualitative_researcher_agent.py::create_observer_agent`.

1. **Build the Observer shell.** `create_observer_agent(company=…, study=study, …)` returns an `LlmAgent` named `QualitativeResearcher_Observer` with `output_schema=ObservationSummary`, pinned to Gemini Pro via `providers.get_observer_model()` regardless of `TMT_PROVIDER` (the setting that chooses the team's model). The instruction names the company + industry context + product type, sets the observational-discipline rules (record using the panel's own vocabulary; do not paraphrase into analytical categories; do not summarise as theoretical categories), embeds the merged forbidden-vocabulary list, and embeds the study's `flagged_vocabulary` watch-list with no explanation of why those words matter. **By default the instruction contains NO reference to the study's research question or theoretical lens** — see `tests/test_methodological_invariants.py` for the test that enforces this. With `embedded_observation=True` it also states the research question, but never the lens. Either way the Observer has the word lists, and its task asks for unprompted use of the listed vocabulary.
2. **Compose the consolidation prompt** via `_build_observer_prompt(has_field_notes=True)`. The prompt includes: the scenario context, the full deliberation transcript, every per-role artefact (title + key challenges + main decisions + key tensions + body), the per-role private scratchpads (privileged channel; panellists never saw each other's scratchpads), and the CONSOLIDATION framing ("you have been observing live and have written running field notes — now consolidate everything into a single ObservationSummary").
3. **Invoke the LLM.** The prompt carries the researcher's running field notes from Phases 1 + 2, so it is not a cold first read — it's a "tighten the working notes into the structured schema" call.
4. **Coerce the reply** into an `ObservationSummary` (Pydantic validation: a Python tool checks the reply against the template). The schema enforces structured lists: decisions, components, disagreements, role contributions, alternatives considered, flagged-vocabulary uses.
5. **Emit `phase3_complete observation_summary=ok/missing`** to the logger.

One LLM call. Typical Gemini Pro latency: 60–90 seconds (the prompt is large — full transcript + six artefacts + scratchpads).

## Phase 4 — Panel debriefing

The researcher agent, set up as the Debriefer, interviews the whole team. An exchange is one researcher question and the replies to it, and a panellist with nothing to add replies PASS.

**Driver:** `orchestrator/panel_debriefing.py::run_panel_debriefing`.

1. **Build the Debriefer shell.** `create_debriefer_agent(study=study, observation_summary=…, …)` returns an `LlmAgent` named `QualitativeResearcher_Debriefer` with `output_schema=PanelUtterance`, pinned to the same model as the Observer and FieldNoter (`providers.OBSERVER_PROVIDER`). The instruction includes: the protocol's (the debrief's rules and topics) `stance` and `behavioural_rules`, the **RESEARCH CONTEXT** block (the study's research question as a guiding post its questions explore, the theoretical lens marked for later analysis, and background prose — the exact wording is in `_render_research_context`), the rendered observation summary, the merged forbidden-vocabulary list, the **merged thematic areas**, the debrief topics (framework areas A/B/C/I/J + any study-overlay areas, a study's own topics, from `StudyConfig.protocol_overlay` — for the openness study that's D/E/F/G/H from `studies/openness_maneuvering/debriefing_overlay.yaml`) with question stems, the panel-format rules, the variety rules, and the stop criterion. The overlay is deep-merged (combined item by item with the shared protocol) by `roles/qualitative_researcher_agent.py::_apply_study_overlay`; see `02_design_decisions.md` §21 for the contract.

   The Debriefer always sees the research question and lens; with the default blind setting it is the only researcher shell that does. It is told to record in `research_question_link` how each question could help explore the research question, or to mark it `adjacent`. The prompt explicitly forbids steering: *"The panel may or may not produce material directly relevant to this research question. Follow the panel where they actually went in the deliberation. Do NOT steer them toward the research question. If the deliberation reveals nothing about the construct under study, that absence is itself a finding."* It also forbids sharing the question with the panel.
2. **Wrap the debriefer with artefact + scratchpad extras.** `_build_debriefer` appends an `STRATEGIC ARTEFACTS PRODUCED BY THE PANEL` block (six per-role memos), a private-scratchpads block (concurrent mode only), and the debriefing-history / coverage-map / variety / stop-criterion rules.
3. **Run the turn loop** (`run_panel_debriefing`). On each turn:
   - Render the running transcript so far + the coverage map (how many exchanges in each thematic area; nag for any non-closing area still at zero).
   - Call `_next_researcher_utterance` which composes the prompt with "react to the most recent answer" framing (first-turn opening, or follow-up vs area-switch options when there was a substantive prior response, or no-PASS-repeat warning when all panellists abstained last turn).
   - Detect near-verbatim repeats against the last 3 exchanges via token-set Jaccard (≥ 0.65; a score from 0 to 1 of the words two texts share). On repeat, re-prompt the debriefer with the prior question quoted back.
   - Validate the proposed utterance against the forbidden-vocab guard (study-aware via `utterance_violates_protocol(study=study)`). On violation, re-prompt once with the violations quoted. Count violations on the transcript regardless.
   - Route the utterance to the panellists via `_collect_panel_responses`. The addressed role gets an "addressed YOU directly" prompt; peers get a strict PASS-biased opt-in framed around the addressee ("DEFAULT: PASS. Reply [PASS] unless you BUILD ON or CONTRADICT what {addressee} just said"). Group-addressed questions invite every role with a moderate-bias prompt. A panellist who joins after another sees the answers already given in that exchange.
   - Each panellist call starts an empty session, and its prompt carries the whole deliberation and the role's own notes, draft and document, so the CTO can recall its actions from Phase 1 when asked.
   - Record the exchange (`PanelExchange = utterance + responses`) on the transcript.
4. **Stop** when the Debriefer emits `ends_debriefing=true` OR `max_exchanges` (default 60, CLI default 20) is hit. Mark `ended_reason` accordingly.
5. **Emit `phase4_complete exchanges=N`** to the logger.

In the prototype runs: 12–20 exchanges, about 7 LLM calls per exchange (1 debriefer + 6 panellists, some of whom pass).

## Extra phases — construct judging (optional, default-study only)

A judge is a language model that scores a finished run against a rubric (a scoring guide).

**Driver:** `orchestrator/construct_judging.py::ConstructJudgingPhase` (a `PhaseHandler`, code a study plugs in to add a phase, registered in `studies/openness_maneuvering/__init__.py` via `extra_phases=[ConstructJudgingPhase()]`). Off by default; turn on via the CLI's `--judge` flag or `run_research_session(..., run_judges=True)`. It is specific to the openness study and not part of the method in the proposal.

This phase scores the deliberation against the study's `judgment_rubric` (a Pydantic `JudgmentRubric` carried on `StudyConfig`). For the default `openness_maneuvering` study the rubric has seven dimensions — `component_disclosure`, `process_openness`, `boundary_permeability_inbound`, `boundary_permeability_outbound`, `ecosystem_orchestration`, `value_capture_posture`, `temporal_openness_maneuvering` — each grounded in the literature (Henkel 2006 on selective revealing and on dynamic revealing; Chesbrough 2003 on open innovation; Dahlander & Gann 2010 on the inbound/outbound openness taxonomy; Jacobides et al. 2018 on ecosystem orchestration; Teece 2007 on value capture; Alexy, Henkel & Wallin 2013 on selective revealing as deliberate sequencing).

1. **Build four judges**, one per provider in `providers.JUDGE_PROVIDERS` (default: `gemini_pro` + `claude` + `openai` + `deepseek`). The ensemble (the set of judges together) is pinned to four different LLM vendors regardless of `TMT_PROVIDER` so single-model bias is controllable.
2. **Compose the judge input** via `_build_judge_inputs(...)` — artefacts in full, the public transcript only (private scratchpads + drafts excluded; the judges score the same evidence a human reviewer could see), the observation summary, the FieldNoter's running notes, the debriefing transcript.
3. **Two-stage scoring per judge** (see `roles/construct_judge.py::create_construct_judge_agent`). First the judge writes a qualitative summary of what the panel actually did along each rubric dimension; only then does it produce the Likert score. This reduces post-hoc rationalisation of scores chosen first. For the openness study the scores come from 26 sub-dimensions in percent, rolled up to the seven dimensions (`DECISIONS.md` §29).
4. **Run all four judges in parallel** via `asyncio.gather`. Each returns a `ConstructAssessment` with per-dimension `DimensionAssessment` items + a justification + the citations from the transcript that support each score.
5. **Aggregate.** Composite per judge = mean across dimensions (the rubric is equal-weighted). Composite across the ensemble = mean of the per-judge composites.
6. **Compute Krippendorff's α** (a measure of agreement among coders; ordinal variant, implemented in `_krippendorff_alpha_ordinal` so the framework does not depend on the `krippendorff` PyPI package, ready-made code from Python's public archive). α tells the reader how much the cross-vendor judges agreed.
7. **Emit `phase_complete name=construct_judging composite=<X> alpha=<Y>`** to the logger.

Four LLM calls (one per judge), each on a large input. For cost, see "Total cost shape" below. Skipped when the active study has no `judgment_rubric` or when `--judge` is absent. Verified by `tests/test_construct_judging.py`.

## Extra phases — sub-dimensional text scoring (optional, openness-study only)

**Driver:** `analysis/text_measures/dictionary.py::score_run`. Off by default; turn on via the CLI's `--subdimension-scores` flag. Pure text scoring; no LLM calls; runs in ~1 second.

The dictionary scorer (which scores text by counting words from a fixed list tied to a concept) reads the persisted artefacts + transcript + private scratchpads + draft + inbox + field notes (see channel definitions in [02_subdimension_measurement_plan.md](../studies/openness_maneuvering/docs/02_subdimension_measurement_plan.md)) and counts regex (a written pattern for finding text) hits per sub-dimension per channel against the published lexicon (the fixed word list) in `studies/openness_maneuvering/subdimension_lexicon.py`. Outputs land in `results/runs/<run_id>/06_subdimension_scores/`, mostly as CSV (comma-separated values: plain-text tables any spreadsheet can open) files:

```
06_subdimension_scores/
├── per_subdimension.csv     # raw hit counts + densities per (sub-dim × channel)
├── per_dimension.csv        # aggregated to the 7 rubric dimensions × channels
├── headline.csv             # overall openness score per channel
├── headline_by_role.csv     # per-role attribution (where source allows)
└── README.md                # markdown summary with the top-3 evidence sentences per sub-dimension
```

Independent of `--judge`. Verified by `tests/test_dictionary_method.py` + `tests/test_subdimension_lexicon.py` + `tests/test_private_channel_persist.py`.

## Output

**Driver:** `analysis.persist_artefacts.burst_run(...)`, called from the `__main__` block (the part that runs when the file is started) of `run_research_session.py`.

1. **Per-run folder** — the CLI writes one browseable folder at `<out-dir>/<run_id>/` (default `results/runs/<run_id>/`). **Markdown is mandatory; JSON is optional** (`--no-json`). Markdown is what a qualitative reviewer reads; JSON is for downstream code that wants to re-parse:
   ```
   00_meta.json
   01_deliberation/interaction_log.{json,md}
   01_deliberation/role_scratchpads/<Role>_scratchpad.md
   02_strategy_documents/{CEO,CTO,COO,CMO,Product_Strategist,Product_Designer}_strategy.{json,md}
   03_researcher/observation_summary.{json,md}
   03_researcher/field_notes.{json,md}
   04_interview/transcript.{json,md}
   05_judging/aggregate.{json,md}                  (opt-in via --judge)
   05_judging/<judge_id>_assessment.{json,md}      (opt-in via --judge — one per judge)
   05_judging/<judge_id>_quote_audit.md            (opt-in via --judge — one per judge)
   06_subdimension_scores/{per_subdimension,per_dimension,headline,headline_by_role}.csv
                                                    (opt-in via --subdimension-scores; openness study only)
   06_subdimension_scores/README.md                 (opt-in via --subdimension-scores; markdown summary)
   06_private_channel/<Role>_scratchpad.md
   06_private_channel/<Role>_draft.md
   06_private_channel/inbox_final.md
   06_private_channel/private_state.json
   07_rag/corpus_manifest.json                      (--rag only)
   07_rag/retrieval_log.jsonl                       (--rag only)
   07_rag/README.md                                 (--rag only)
   08_usage/token_usage.jsonl
   manifest.json
   README.md
   ```
   With `--no-json`, the per-phase JSON sub-files are skipped; `00_meta.json`, the judge JSON files, the CSV outputs and `07_rag/` are still written. `00_meta.json` records `study_slug`, `study_version`, scenario knobs (settings), timings, errors, each role's model, `researcher_provider`, `embedded_observation`, the code commit (one saved change in the code's history, naming the exact version), and which phases were captured.
2. **Replication manifest** — at the end of each completed run the CLI writes `manifest.json`: the team's models, providers, prompts, git (the tool that keeps the code's history) provenance (where it came from), redacted env (environment variables with secrets removed), and hashes (short fingerprints computed from a file's contents) of the files that set what agents are told. It leaves out the cloud project and local paths, because run folders get published. The folder is saved after each phase and each debrief exchange, so a late crash keeps earlier work, and `run_complete` in `00_meta.json` says whether the run finished. See [`07_reproducibility.md`](07_reproducibility.md).

## Diagram

```
                       ┌────────────────────────────────────────────────┐
                       │ Phase 0: BUILD                                 │
                       │   - load_study(slug)                           │
                       │   - TMTSystemWithA2A → 6 role agents           │
                       │   - one new session per call                   │
                       │   - FieldNoter + ResearcherStream              │
                       └─────────────────────┬──────────────────────────┘
                                             ▼
                       ┌────────────────────────────────────────────────┐
                       │ Phase 1: CONCURRENT DELIBERATION               │
                       │   6 role agents × asyncio loops                │
                       │   SCRATCHPAD / ASK / ANSWER / SPEAK / DRAFT    │
                       │   ResearcherStream observes live →             │
                       │   FieldNoter writes notes every ~10 events     │
                       │   stops on all_done OR wall_clock_cap          │
                       └─────────────────────┬──────────────────────────┘
                                             ▼
                       ┌────────────────────────────────────────────────┐
                       │ Phase 2: STRATEGIC ARTEFACTS                   │
                       │   6 role agents wrapped with                   │
                       │     output_schema=StrategicArtefact            │
                       │   each role's prompt carries what it needs     │
                       │   (memory of phase 1 is in the prompt)         │
                       │   ResearcherStream observes each artefact →    │
                       │   FieldNoter writes notes                      │
                       └─────────────────────┬──────────────────────────┘
                                             ▼
                       ┌────────────────────────────────────────────────┐
                       │ Phase 3: OBSERVER CONSOLIDATION                │
                       │   QualitativeResearcher_Observer               │
                       │   output_schema=ObservationSummary             │
                       │   reads full transcript + artefacts +          │
                       │     scratchpads + own running field notes      │
                       │   consolidates into structured summary         │
                       │   BLIND to research question + lens by default │
                       └─────────────────────┬──────────────────────────┘
                                             ▼
                       ┌────────────────────────────────────────────────┐
                       │ Phase 4: PANEL DEBRIEFING                      │
                       │   QualitativeResearcher_Debriefer (turn loop)  │
                       │   sees RESEARCH CONTEXT (RQ + lens + anti-     │
                       │     steering rule)                             │
                       │   thematic areas: framework A/B/C/I/J +        │
                       │     study-overlay (D/E/F/G/H for openness)     │
                       │   each turn: anchored PanelUtterance →         │
                       │     addressed role + PASS-biased peers         │
                       │   each panellist's prompt carries its memory   │
                       │     (recall their own deliberation positions)  │
                       │   stops on ends_debriefing OR max_exchanges    │
                       └─────────────────────┬──────────────────────────┘
                                             ▼
                       ┌────────────────────────────────────────────────┐
                       │ EXTRA PHASES (study.extra_phases, optional)    │
                       │   ConstructJudgingPhase  (gated by --judge)    │
                       │     4 judges (gemini_pro + claude + openai +   │
                       │       deepseek)                                │
                       │     two-stage rubric scoring per judge         │
                       │     ensemble composite + Krippendorff's α      │
                       │   Sub-dim text scoring (gated by               │
                       │     --subdimension-scores; openness study only)│
                       │     dictionary on 3 channels × 26 sub-dims     │
                       │     no LLM calls                               │
                       └─────────────────────┬──────────────────────────┘
                                             ▼
                       ┌────────────────────────────────────────────────┐
                       │ OUTPUT                                         │
                       │   markdown mandatory; --no-json skips JSON     │
                       │   burst into per-run folder (00–07 + README)   │
                       │   manifest.json written to the run folder      │
                       └────────────────────────────────────────────────┘
```

## Total cost shape

A run makes roughly 200 LLM calls:
- Phase 1: 55–79 LLM calls in the prototype runs (one per role action)
- Phase 2: 6 LLM calls (one per artefact)
- Phase 3: 1 LLM call (the consolidation)
- Phase 4: about 7 LLM calls per exchange (12–20 exchanges in the prototype runs; the CLI stops at 20 by default, a development limit the main runs will lift)
- Construct judging (opt-in): 4 LLM calls (one per judge in the ensemble), each on large inputs
- Sub-dimensional scoring (opt-in, openness study): 0 LLM calls (pure dictionary scoring)
- FieldNoter: about 6 LLM calls (one per ~10 events buffered)

Measured on `gemini-3.1-pro-preview` (a Google model in early release) at list prices (a provider's published rates): an ungrounded run (one with no documents) with optional scoring cost about $20 of Google charges (scoring on other vendors is extra), and a grounded run about $67, before we stopped re-sending earlier prompts. Runs took 38–90 minutes. We now estimate about $15 for a grounded run (`LEARNINGS.md` L15, a numbered learning). A grounded run also pays for its corpus store (the firm's documents loaded into Google's cloud service for searching) while the store exists (see [`10_rag_repo_plan.md`](10_rag_repo_plan.md) § Cost). These figures age quickly, so measure one run on your own setup before budgeting a sweep (a planned set of many runs).

**Low-cost development.** During development, set `TMT_PROVIDER=deepseek` or `TMT_PROVIDER=groq` (lower-priced model services; per `providers.py`) to lower the team's share of the cost without changing any code paths. The researcher agent stays on Gemini Pro. The cheaper providers slot in via the same LiteLLM (software that lets one program reach many providers' models in the same way) wrapper used for Claude and OpenAI — see `tests/integration/test_cells_live.py` (cell_5 for DeepSeek, cell_6 for Groq).
