# 2. Design decisions

This file documents the major architectural choices and the reasoning behind each. Where a decision is grounded in the methodological literature we cite the reference; where reasonable alternatives exist we say what we ruled out and why. This is a **reference document** — read on demand, not end-to-end. Technical terms are defined at first use and in the [glossary](GLOSSARY.md). **Where it lives** entries name code files: `file.py::name` means the part called `name` in that file, and `tests/` holds the automatic checks.

## How to navigate this document

The 24 decisions are numbered (§1 means decision 1) in the order they were added to the framework (the shared software in this repository), not by topic. Use the thematic groupings below to jump to what you need:

**Foundational methodology** — read these before anything else if you're new to the framework
: §1 (six roles in the top management team, or TMT, not one), §3 (concurrent deliberation mode: the team's discussion, with all six roles acting at once), §5 (live researcher agent, a language model given a role, which watches and questions the team, not retrospective), §6 (researcher blind to the research question, or RQ, during observation, by default), §7 (forbidden vocabulary, words the researcher agent must not use, split: methodological + construct-specific), §24 (framework framing — ethnography in silico, carried out by computer rather than in the field)

**Researcher discipline + protocol overlays**
: §6 (blindness), §9 (no enumerated dimensions in role prompts, the text sent to a language model to get one reply), §16 (construct judging: models score a run, one complete simulated meeting and debrief, against an anchored rubric, or scoring guide), §21 (per-study debriefing-protocol overlay: a study's own topics for the researcher agent's interview of the team, added to the shared ones)

**Roles + agent architecture**
: §1, §2 (in-process delegation, inside one running program, through ADK, Google's Agent Development Kit for building agents; not network A2A, agent-to-agent calls over a network), §4 (each model call, one prompt to a language model and one reply, carries what it needs), §11 (per-role overrides of the LLM, the large language model that writes each role's text)

**Study extensibility**
: §10 (study as a Python module, a file of code in the project's programming language), §20 (extra phases, or numbered stages of a run, via `PhaseHandler`, a template for adding one), §21 (protocol overlay), §22 (sub-dimensional text scoring: counting listed words for narrow items within a rubric's dimensions)

**Persistence + reproducibility**
: Persistence means saving a run's records. §12 (redaction, or removal from records, of API keys, the secret codes that identify who uses and pays for a service), §14 (browseable folder for each run), §15 (logging, the software's running record, set up for the CLI, or command line, at `__main__`, the program's starting point), §17 (Markdown, plain text with simple marks for headings and lists, mandatory; JSON, a plain-text format for named fields, optional)

**Providers + structured output**
: §13 (retrying after error 429, meaning too many requests to the company supplying the model, and after temporary errors), §18 (support for low-cost providers, the companies supplying models — DeepSeek, Groq), §18.1 (per-provider adapter for structured output, replies forced into fixed, named fields), §19 (routing Gemini, Google's language model, through Vertex AI, Google's paid cloud service)

**RAG grounding**
: §23 (RAG-grounded TMT deliberation via Google Vertex AI RAG Engine — includes the Vertex-vs-local justification). RAG (retrieval-augmented generation) means searching a document collection and adding the passages found to a model's prompt. Grounding means giving agents a firm's real documents so their text can be traced to sources; it is unrelated to grounded theory. RAG Engine is Google's paid service that stores the documents and runs the searches

**Framing**
: §24 (ethnography in silico, not "simulation with an observer") — the methodological commitment behind every other choice

---

## 1. Six TMT roles, not one chief executive

**Decision.** The synthetic TMT comprises six functional roles: CEO, CTO, COO, CMO, Product Strategist, Product Designer.

**Why.** Single-LLM "the firm decides X" simulations collapse the TMT's *differentiated functional expertise* (Lawrence & Lorsch 1967) and the *behavioural integration* (Simons, Pelled & Smith 1999) that strategy research treats as the substantive unit of analysis. The six-role decomposition forces the LLM to surface inter-role tension — disagreement, asymmetric attention, role-specific framings — that the single-LLM version flattens. The role portraits are heuristic syntheses aligned with three literature streams (upper echelons; functional differentiation; behavioural integration in TMTs); see the docstring (the explanatory text at the top) of `roles/__init__.py` for the full reference list.

**Alternatives ruled out.** (a) Two roles (CEO + CFO) — too thin. (b) One generic "TMT" agent — collapses what we want to study. (c) Fully customisable role list per study — added complexity without a current need; the `StudyConfig.panel_roles` field (in the template for a study's settings) exists for future override.

**Where it lives.** `roles/ceo_agent.py`, `roles/cto_agent.py`, ..., one factory (the code that builds an agent) per role.

## 2. ADK in-process delegation, not network A2A

**Decision.** All agents run inside one Python process through Google ADK. In the default concurrent mode, role agents (the six simulated executives) do not call each other: they exchange messages through `SharedState`, the record all role loops read and update. Only CEO-led mode uses ADK's in-process `transfer_to_agent` mechanism, where one agent hands the conversation to another. The framework does not use network A2A (Agent-to-Agent over HTTP, the web's standard for requests).

**Why.** ADK (held at version 1.17.0 in `requirements.txt`, the list of ready-made code to install) supports in-process delegation natively, so the framework does not use ADK's network A2A tools (`to_a2a`, `RemoteA2aAgent`). In-process delegation gives simpler debugging (finding and fixing errors), no extra process management, and adequate isolation between agents, because outside CEO-led mode each model call has its own ADK session (stored conversation). Inter-process isolation between agents is not required for the framework's use case.

**Trade-offs.** Multiple agents share one Python process (running program). CPU contention (programs competing for the computer's processor) is not a concern (LLM calls are network-bound, mostly waiting on the provider's reply), but a poorly-bounded loop (code that keeps repeating) in one role *can* stall the entire deliberation. The `max_wall_clock_seconds` (default 30 min) and `max_actions_per_role` (default 30) caps in `ConcurrentConfig` are the safety net.

**Where it lives.** `agent.py::TMTSystemWithA2A.__init__` (session-service construction) and `_new_call_session_id` (one session per call); `_run_one_agent` inside `run_strategic_discussion` (per-call ADK Runner, the part that hands a prompt to an agent).

## 3. CONCURRENT default discussion mode

**Decision.** By default all six roles run as parallel `asyncio` tasks (Python's way of running work side by side), each emitting one structured `AgentAction` (one move, in fixed fields) per turn against a shared `SharedState` (the record all roles share). They cooperate via directed `ASK`/`ANSWER` messages (a question to one colleague, and its reply) on private inboxes and `SPEAK` on a public transcript. The deliberation ends when all six declare DONE or wall-clock (elapsed-time)/action caps trip.

**Why.** Sequential CEO-led delegation produces a hierarchical waterfall — the CEO speaks first, the CTO speaks when asked, etc. — that does not match how real TMTs actually deliberate (Hambrick 1994: TMTs are characterised by horizontal interaction, not a tree). The CONCURRENT mode is more faithful to TMT interaction dynamics by letting all six roles act in parallel, ask each other questions, push back, and converge through cross-talk (roles joining in after a first reply) rather than through a chain of command.

**Alternative modes available for ablation (changing or removing one part to see the effect).** Four other discussion modes are accessible via the setting `DeliberationConfig.discussion_mode`: `CEO_LED` (ADK tree-based transfer chain with CEO as root, the agent that starts it), `RANDOM_INITIATOR` (one-shot, random root), `PARALLEL_THEN_DISCUSS` (Phase A parallel positions + Phase B discussion rounds + Phase C CEO synthesis), `ROUND_ROBIN` (shuffled per-round, abstention allowed). Useful for studies that want to ask whether the deliberation mode itself influences findings. Modes are chosen through `DeliberationConfig` in Python (the `deliberation_config` argument of `run_research_session`); the command line always uses the default. During deliberation, grounding, live field notes and the private channel apply only to concurrent mode.

**Where it lives.** `orchestrator/concurrent_mode.py` (the SharedState + per-role action loops); `orchestrator/deliberation.py` (dispatcher, which starts the chosen mode).

## 4. Each model call carries what it needs

**Decision.** Every model call has its own empty ADK session, and its prompt carries what the agent needs: for a role, the whole public discussion and its own notes, draft and document; for the researcher, everything it observed. This replaced persistent per-role sessions on 31 Oct 2026.

**Why.** Persistent sessions re-sent every earlier prompt on every call, and each prompt already held the debrief so far, so by the end of a long debrief one call carried about 300,000 tokens (small pieces of text, often about three-quarters of a word) against about 20,000 of transcript. They also did not do their job: the deliberation ran in a separate session, so a role writing its document or answering the debrief had only the last 8,000 characters of the deliberation (`DECISIONS.md`, the project's numbered record, §52).

**Where it lives.** `orchestrator/role_memory.py`, `run_research_session.py::_build_default_runner`, `agent.py::_new_call_session_id`. Verified by `tests/test_call_sessions.py` and `tests/test_call_context.py`. The legacy CEO-led mode still shares one session within its single call, because its agents hand the conversation to each other.

## 5. Live researcher, not retrospective reader

**Decision.** A `QualitativeResearcher_FieldNoter` agent (the researcher agent in its note-taking set-up; no `output_schema`, the template that fixes a reply's fields; free-form prose) is invoked periodically during Phases 1 + 2 (deliberation and strategy documents) with the latest batch of public events. Its notes accumulate in a list on `ResearcherStream` and, carried in each later researcher prompt, inform the Observer's structured `ObservationSummary` (the researcher agent's single account of the deliberation) at Phase 3 + the Debriefer's probes (the researcher agent's questions to the team) at Phase 4.

**Why.** A retrospective Observer reading a 100-event transcript in one shot produces summary-flavoured notes. A live ethnographer in the room takes notes as moments happen, captures nuance that compression loses, and arrives at the structured summary with a rich working journal. The FieldNoter design follows the live-ethnography traditions of Hine (2015) and Charmaz (2014) — observation is interleaved with note-taking, not separated from it.

**Cost.** A handful of extra small LLM calls per run (6 in run D, one of four prototype test runs: one FieldNoter invocation per ~10 deliberation events plus per ~10 artefact, or strategy-document, events). Cheap relative to the deliberation itself.

**Where it lives.** `orchestrator/researcher_stream.py` + `roles/qualitative_researcher_agent.py::create_field_noter_agent`. Verified by `tests/test_researcher_stream.py` (23 tests).

## 6. Researcher BLIND to the research question during observation, by default

**Decision.** By default (`StudyConfig.embedded_observation=False`) the Observer and FieldNoter prompts contain NO reference to the study's research question or theoretical lens. A study can choose embedded observation (`embedded_observation=True`): the Observer and FieldNoter then know the question, but never the lens. The Debriefer always sees both, and the panel (the six role agents when questioned in the debrief) never sees the question. The Debriefer's questions are there to explore the research question through what the panel actually did: its prompt calls the question a guiding post, tells it to record in `research_question_link` how each question could help (or mark it `adjacent`), and tells it not to steer the panel, and that if relevant material is absent, that absence is itself a finding. The lens is marked as being for later analysis, not for questioning.

**Why.** This is the load-bearing methodological invariant (a rule that must always hold) of the framework. Telling the researcher *what to look for* before they observe is the strongest known source of confirmation bias in qualitative research (Charmaz 2014 on grounded theory; Strauss & Corbin 1998 on inductive coding; Patton 2015 on observer bias). The default therefore keeps the research question and theoretical lens out of the observation prompts. The Debriefer does use the question to choose what to explore, so the question shapes what the debrief collects; that is bounded by the anti-steering rule ("Do NOT steer them toward the research question"; "that absence is itself a finding") and by never sharing the question with the panel. Embedded observation trades this protection for the chance to watch for what bears on the question, at the risk of seeing what it expects; each run records the choice in `00_meta.json` (the run's summary file).

**Blind to the question, not to the word list.** The Observer and FieldNoter are blind to the question by default, but they do receive a word list: a merged forbidden-vocab list (words to avoid in their own prose) and a "flagged vocabulary" watch-list (spontaneous panellist words to quote; the Observer logs them in `flagged_vocabulary_used`). The Observer's task also asks for "unprompted use of the listed vocabulary". The lists come with no explanation of why the words matter, and they are meant as a capture mechanism, but the words themselves can hint at the topic, so blindness here is partial.

**Where it lives.** `roles/qualitative_researcher_agent.py::create_observer_agent` (Observer); `::create_field_noter_agent` (FieldNoter); `::create_debriefer_agent` + `::_render_research_context` (Debriefer with the RESEARCH CONTEXT block + anti-steering rule); `::_render_observation_stance` (the embedded option). Verified by `tests/test_methodological_invariants.py` — parametric (repeated for each) over the studies in `STUDY_SLUGS`, a fixed tuple (a list set in advance), so a new study must be added to it — and `tests/test_observation_stance.py`.

## 7. Forbidden vocabulary split into methodological + construct-specific

**Decision.** The forbidden-vocabulary list is split between two sources:

- `methodological_forbidden_vocabulary` in the protocol YAML (the debrief's rules and topics, in a plain-text settings format; universal across studies): `strategy`, `strategic`, `shift`, `capability` — terms loaded across the strategy literature that any TMT-ethnography researcher should avoid introducing.
- `construct_forbidden_vocabulary` per-study, in `studies/<slug>/__init__.py` (a slug is a study's short name with no spaces): words specific to the construct under study. For `openness_maneuvering`: `open`, `closed`, `open-source`, `value capture`, `architectural leverage`, etc.

At runtime the two lists are merged via `_merged_forbidden_vocab` and presented to the researcher as one list. The researcher does not know which words come from which subset.

**Why.** A single hard-coded list (one written into the code) would tie the framework to one construct. The split lets any study supply its own construct vocabulary while the universal methodological terms stay framework-level.

**Where it lives.** `protocols/ethnographic_protocol.yaml::methodological_forbidden_vocabulary`; `studies/openness_maneuvering/__init__.py::construct_forbidden_vocabulary`; merge logic in `roles/qualitative_researcher_agent.py::_merged_forbidden_vocab`.

## 8. Product NOT pre-baked into the deliberation

**Decision.** `product_description` defaults to `None` (empty). When `None`, no `PRODUCT` block is added to the role prompts. The default `strategic_question` asks the team to *first decide what to build* and *then* propose how to develop / govern / release it. `product_type` (Novel / Enhancement) bounds the scope; the panel chooses the specific direction.

**Why.** Pre-filling `product_description` with a concrete spec turns the deliberation into a release-strategy meeting — the WHAT is already decided, only HOW is deliberated. Leaving the field unset forces the team to surface candidate product directions, evaluate them, converge on one, and then deliberate on development/governance/release. The `scenario_brief` from the study config bounds the firm's domain (e.g. "An AI firm operating in a competitive industry") without dictating a specific product; the default concurrent mode and CEO-led mode put it beside the firm's name in the prompt. `product_type` (Novel / Enhancement) further bounds the scope of what the team can choose.

**Where it lives.** `run_research_session.py::run_research_session` (no auto-fill, study-driven strategic question template). Verified by `tests/test_open_product_deliberation.py`.

## 9. No enumerated dimensions in the role prompts

**Decision.** The role prompts ask each role to write elaborately and comprehensively, with epistemic honesty ("we don't know X yet — we plan to discover it by Y" rather than fabricated confidence). The prompts do NOT enumerate dimensions like `WHAT / HOW / WHY / WHO / WHEN / WHERE + LIFECYCLE VISION` as a checklist.

**Why.** LLMs follow enumerated lists literally regardless of disclaimers like "use as prompts, not a checklist". An enumerated dimension list inside the prompt produces role documents with one section per dimension and homogeneous structure across roles. The framework instead asks each role to choose which aspects matter for *its* function and to write at the depth that role's perspective demands.

**Where it lives.** `orchestrator/concurrent_mode.py::_compose_role_prompt` (the `STRATEGIC DEPTH` block, no dimension list); `orchestrator/artefact_collection.py::_DEPTH_REMINDER`. Verified by `tests/test_role_prompts_and_debriefer.py` (the leak guard, a test, asserts the enumeration is NOT present in any role prompt).

## 10. Study as a Python module, not a YAML config

**Decision.** Per-study configuration lives in `studies/<slug>/__init__.py` exporting a `STUDY: StudyConfig` instance (a filled-in copy of that template) — not in `studies/<slug>.yaml`.

**Why.** Python lets the study author embed rich text + literature references + inline comments in the same file as the schema (the template of required fields). The theoretical lens for the openness study, for example, references Henkel (2006) + Teece et al. (1997) + Jacobides et al. (2018) — citations that a YAML file would force into a separate location. A Python module also makes extension points (places where a study adds its own behaviour) such as `protocol_overlay` and `rag_corpus_loader` natural. (`role_factories_module` is a string path (text naming a code location) for the same reason, but it is not yet wired in; planned, P2, a priority level in `ROADMAP.md`.)

**Where it lives.** `studies/base.py` (the `StudyConfig` schema + `load_study` loader); `studies/openness_maneuvering/__init__.py` (the default study).

## 11. Per-role LLM overrides

**Decision.** `TMT_PROVIDER` (a setting held outside the code) selects the team-wide LLM; per-role overrides (`TMT_PROVIDER_CEO`, `TMT_PROVIDER_CTO`, …) let a researcher run heterogeneous teams (e.g. claude, Anthropic's model, for CEO + gemini for everyone else) for ablation studies. The researcher (Observer, FieldNoter and Debriefer) is pinned to one model, `providers.OBSERVER_PROVIDER` (Gemini Pro), regardless, so cross-provider observation summaries and debriefs are comparable. `00_meta.json` records it as `researcher_provider`.

**Why.** A robustness study should be able to vary one role's LLM at a time and watch what changes in the deliberation. The researcher-pinning rule comes from the same logic — the field notes and debrief questions are part of the dataset, so they must not vary by which provider the TMT used.

**Where it lives.** `providers.py` (`get_role_provider`, `get_role_model`, `snapshot_role_providers`, `snapshot_role_model_ids`). Verified by `tests/test_provenance_and_llm_selector.py`.

## 12. API-key redaction in the replication manifest

**Decision.** Any env var (environment variable, a named setting held outside the code) whose NAME contains `KEY` / `TOKEN` / `SECRET` / `PASSWORD` / `CREDENTIAL` / `AUTH` (case-insensitive) has its value masked to `<redacted>` when written to the replication manifest (a file listing what produced a run). The *presence* of the variable is preserved so a reviewer can see that an API key was set, without seeing its value.

**Why.** A replication manifest ships with the persisted run folder. Without redaction, an accidentally committed manifest (one saved to the project's shared history) would leak the operator's API keys.

**Where it lives.** `analysis/replication_package.py:_SENSITIVE_SUBSTRINGS` + `redact_env`. Verified by `tests/test_provenance_and_llm_selector.py::TestRedactEnv`.

## 13. Generic 429 / transient-error retry

**Decision.** The per-agent LLM runner retries on transient errors, meaning temporary failures (HTTP 429 from Gemini / 529 from Anthropic / OpenAI retry-after / network errors) with exponential backoff (waiting longer before each new attempt). Retries do NOT consume per-role action slots (the cap on a role's moves).

**Why.** A live run hitting Gemini's free-tier quota (its cap on free use) would otherwise terminate the deliberation prematurely. The retry budget is per-call, not per-run; the wall-clock cap is the global ceiling.

**Where it lives.** `agent.py::_parse_retry_delay` + the retry loop in `_run_one_agent`. Verified by `tests/test_rate_limit_retry.py`.

## 14. Browseable per-run folder, gitignored

**Decision.** Outputs land in `results/runs/<run_id>/` as a folder with `00_meta.json`, subfolders `01_deliberation/`, `02_strategy_documents/`, `03_researcher/`, `04_interview/`, `06_private_channel/` and, when switched on, `05_judging/`, `06_subdimension_scores/` and `07_rag/`, plus a `README.md` index. The whole `results/runs/` tree is gitignored (deliberately left out of the shared repository).

**Why.** Run folders are for qualitative review and stay out of git (the tool that keeps the project's change history) by default (they may contain firm-specific scenario content, copyrighted reference material, or partially-redacted LLM outputs). The exception is `example_runs/`, which publishes records of four prototype runs so that others can repeat and compare them, with source text removed from the grounded run (the one given source documents) by `analysis/redact_run.py` (`DECISIONS.md` §49). The folder layout is designed to be browseable in any file manager or Markdown previewer.

**Where it lives.** `analysis/persist_artefacts.py::burst_run` + `burst_run_from_files`. `.gitignore` excludes `results/runs/` and `results/smoke/`.

## 15. CLI logging configured at `__main__`, not at module load

**Decision.** `run_research_session.py`'s `__main__` block calls `logging.basicConfig(level=INFO)`. Library-mode imports (when other code uses the file rather than running it) do NOT configure a root logger (the program-wide logging setting). Per-phase progress is emitted via `log.info(...)` at every phase boundary.

**Why.** A live run can take 38–90 minutes. Without a configured logger the CLI looked frozen. With the basicConfig in `__main__` only, library callers (e.g. a notebook, an interactive coding document, driving multiple runs) retain full control of logging.

**Where it lives.** The `__main__` block of `run_research_session.py` (CLI). Verified by `tests/test_call_sessions.py::TestPhaseLoggingEmitted`.

## 16. Construct judging — a four-model ensemble against an anchored rubric

**Decision.** An extra phase scores the deliberation against the study's `judgment_rubric` using four LLM judges (models that score a finished run) from four different vendors (`gemini_pro` + `claude` + `openai` + `deepseek`; `providers.JUDGE_PROVIDERS`). Each judge produces a per-dimension Likert score after a two-stage rubric walkthrough (qualitative summary first, then score); for the openness study these roll up from 26 sub-dimensions scored in percent (`DECISIONS.md` §29). Aggregation = simple mean across dimensions per judge, then mean across judges. Inter-rater agreement is reported as Krippendorff's α (ordinal variant). The phase is wired via the `PhaseHandler` protocol (see §20 below): the openness study registers `ConstructJudgingPhase()` in its `extra_phases`, and the CLI's `--judge` flag (an option added to a command) opts in.

**Why.** The deliberation transcript + artefacts + debriefing carry rich qualitative material about how the team treated the construct (here: openness). Asking a single LLM to score the construct is brittle — any one LLM's prior biases the judgment. A four-vendor ensemble (several models scoring the same run) + an α statistic lets the reviewer see *how much* the judges agreed; low α is informative (it signals the construct under study is poorly resolved by the deliberation), not a failure. Anchoring each dimension with a literature-grounded low/mid/high description (Henkel 2006; Chesbrough 2003; Jacobides et al. 2018; Teece 2007 for the default openness rubric) reduces post-hoc score drift.

**Why two-stage scoring.** Asking for a Likert score first invites the LLM to rationalise. Asking for a qualitative summary first and *then* a score is closer to how human raters do anchored scoring — the score is derived from the summary, not the other way around.

**Why off by default.** It adds cost: judges hit premium APIs (paid model services) regardless of `TMT_PROVIDER`. On `gemini-3.1-pro-preview` (an early release of Gemini) at list prices (providers' published rates), an ungrounded run (one with no source documents) with optional scoring measured about $20 of Google charges, and scoring on other vendors is extra. These figures age quickly. Researchers can leave the judges off during development and turn them on for the final run via `--judge`.

**Alternatives ruled out.** (a) Single-judge — fails the cross-vendor robustness story. (b) Deterministic keyword count — incompatible with the framework's inductive stance (we don't want construct vocabulary to drive scoring; that would entrench confirmation bias). (c) Human-only scoring — defeats the framework's automation thesis and prevents the framework from running at study scale.

**Where it lives.** `orchestrator/construct_judging.py` (orchestrator, the code that runs the phase, + `ConstructJudgingPhase` handler + Krippendorff's α implementation); `roles/construct_judge.py` (the judge agent factory); `roles/judge_schemas.py` (schemas — `ConstructAssessment`, `ConstructJudgmentBundle`); `studies/openness_maneuvering/__init__.py::_OPENNESS_RUBRIC` (the default-study rubric instance — registered via `extra_phases=[ConstructJudgingPhase()]`). The machinery is study-agnostic; the rubric instance is the only construct-specific piece. Verified by `tests/test_construct_judging.py`.

## 17. Markdown mandatory, JSON optional in per-run output

**Decision.** Every artefact in `results/runs/<id>/` is written as Markdown unconditionally. JSON is emitted alongside by default but can be suppressed via `--no-json` (CLI) or `write_json=False` (programmatic, from other code).

**Why.** The persisted folder exists for *qualitative review*, not for downstream code. A reviewer reads `02_strategy_documents/CEO_strategy.md` in a Markdown previewer; nobody reads the JSON unless they're writing analysis code. Making Markdown mandatory matches what reviewers actually consume; making JSON optional lets development runs that don't need the structured echo cut storage in half.

**Where it lives.** `analysis/persist_artefacts.py::burst_run(write_json=...)`. CLI flag in `run_research_session.py::__main__` (`--no-json`). Verified by `tests/test_persist_artefacts.py::TestWriteJsonFlag`.

## 18. Low-cost provider support (DeepSeek + Groq) for development

**Decision.** `providers.py` accepts two additional provider keys (names used in settings) — `deepseek` (default model `deepseek/deepseek-v4-flash`) and `groq` (default `groq/llama-4-maverick`) — routed through the same LiteLLM wrapper (software that reaches many providers' models in the same way) as Claude and OpenAI. The judge ensemble stays pinned to `gemini_pro` + `claude` + `openai` + `deepseek` for cross-provider construct comparability; its DeepSeek judge uses `deepseek/deepseek-reasoner`, not the low-cost team default.

**Why.** DeepSeek costs far less per token than the premium providers, and Groq serves open-weight Llama models (from Meta, with their trained numbers published so anyone can run them) at low latency (quick replies). During development we want to exercise the framework end-to-end cheaply, and these two providers let us do that without changing any code paths.

**Why the judges are NOT cheap.** Phase 5 (the judge scoring) is optional, specific to the openness study and not part of the method in the proposal, in which human researchers read and code the records. In a run that does use it, the judges supply a construct-validity check. Picking the cheapest LLMs available would be defensible for cost but indefensible methodologically — the α statistic is meaningful precisely because the four judges are vendor-diverse and individually well-known. Keeping the ensemble premium is a deliberate trade-off against the deliberation-side savings DeepSeek and Groq make possible.

**Where it lives.** `providers.py::_DEFAULTS` + `get_model()`. Live smoke tests (quick first checks that call real models and cost money) in `tests/integration/test_cells_live.py::test_cell_5_mistral_deepseek_dynamic_novel` and `::test_cell_6_xai_groq_stable_enhancement`. Unit tests (small automatic checks that cost nothing) in `tests/test_provenance_and_llm_selector.py::TestLowCostProviders`.

### 18.1. Per-provider structured-output adapter

**Decision.** Structured-output (Pydantic `output_schema`; Pydantic is a Python tool that checks replies against a template) on `LlmAgent` (the agent type in ADK) is routed through `providers.build_structured_agent(...)`, which classifies each provider into one of two modes:

| Mode | Providers | How `output_schema` is enforced |
| --- | --- | --- |
| `schema` | `gemini_pro`, `gemini_flash`, `claude`, `openai`, `groq` | Passed to `LlmAgent(output_schema=...)`; ADK + LiteLLM send `response_format={"type":"json_schema","json_schema":{...}}` and the provider enforces strict schema server-side (on its own computers). |
| `json_object` | `deepseek`, `ollama` | `output_schema` is **omitted** from the `LlmAgent`. The Pydantic JSON Schema is rendered as a prompt-suffix block. The LiteLlm wrapper is cloned with `response_format={"type":"json_object"}`. Client-side parsers (code on our side that reads replies: `_coerce_action`, `_coerce_artefact`, `_coerce_assessment`, `_coerce_utterance`) become the enforcement boundary. |

**Why.** DeepSeek-Chat explicitly rejects `response_format={"type":"json_schema",...}` with `BadRequestError: "This response_format type is unavailable now"`. Before this adapter existed, Phase 1 of `run_research_session.py` failed on every turn for `TMT_PROVIDER=deepseek` because the role wrapper pinned `output_schema=AgentAction` directly. The adapter is the seam that lets us treat each provider's structured-output capability as a first-class attribute instead of assuming strict json_schema works everywhere.

**Why the `json_object` mode is safe enough.** All four consumer parsers (`_coerce_action` in `concurrent_mode`, `_coerce_artefact` in `artefact_collection`, `_coerce_assessment` in `construct_judging`, `_coerce_utterance` in `panel_debriefing`) already validate via `Pydantic.model_validate(...)` and tolerate stray formatting (markdown fences and `{"action": ...}` wrapper-nesting) — they have to, because even strict-mode providers occasionally produce those quirks. The `json_object` `response_format` hint + the schema-in-prompt suffix is enough to keep the failure rate at parse-time below what those parsers already absorb. We trade strict server-side enforcement for client-side validation, which is what every non-Gemini provider's "structured" mode actually is in practice.

**Why the default bias is `schema`.** The capability table is a frozen allow-list (`_LITELLM_JSON_OBJECT_PREFIXES`), not a deny-list. A LiteLLM prefix that doesn't appear in the set is treated as strict-capable. This means a new provider added to `_DEFAULTS` keeps strict enforcement until we explicitly observe it failing and weaken it. The alternative — defaulting to `json_object` — would silently lose construct validity for any provider that *does* support strict mode.

**How to add a new provider.** Add the LiteLLM model-ID prefix to `_LITELLM_JSON_OBJECT_PREFIXES` if the provider only supports the weaker hint; otherwise the default `schema` mode applies. No call-site changes (edits where the code uses it) needed — every site that needs structured output already goes through `build_structured_agent`.

**Where it lives.** `providers.py::classify_structured_output_mode`, `providers.py::build_structured_agent`. Five call sites: `orchestrator/concurrent_mode.py::_build_concurrent_role_agent`, `orchestrator/artefact_collection.py::_build_artefact_agent`, `roles/qualitative_researcher_agent.py::create_observer_agent`, `roles/qualitative_researcher_agent.py::create_debriefer_agent`, `roles/construct_judge.py::create_construct_judge_agent`. Contract tests (checks of agreed behaviour) in `tests/test_structured_output_adapter.py` (20 tests). End-to-end coverage via `tests/integration/test_cells_live.py::test_cell_5_mistral_deepseek_dynamic_novel`.

## 19. Gemini-on-Vertex AI for GCP-credit runs

**Decision.** The Gemini providers (`gemini_pro`, `gemini_flash`, the pinned researcher, and the gemini judge) can route through Vertex AI instead of AI Studio (Google's direct route, using a personal key) via the standard Google SDK (software development kit, a company's toolkit for its service) env vars (`GOOGLE_GENAI_USE_VERTEXAI=true` + `GOOGLE_CLOUD_PROJECT` + `GOOGLE_CLOUD_LOCATION`). A CLI flag `--vertex` and an `enable_vertex(project, location)` helper set the three env vars in one call and validate them up-front. Non-Gemini providers (Claude, OpenAI, DeepSeek, Groq, and Ollama, which runs models on your own computer) are unaffected.

**Why.** Operators with Google Cloud credits — most often EDU grants for academic researchers — want to bill Gemini calls to GCP (Google Cloud Platform, Google's rented computing services) rather than to a personal AI Studio key. The Gemini SDK already supports both modes; the framework's job is to expose the switch ergonomically, fail-fast when configuration is incomplete (a misconfig that would otherwise blow up 30s into a Phase 1 LLM call), and record the active mode in the replication manifest so a reviewer knows which routing produced the run.

**Why not extend `TMT_PROVIDER`.** A separate `gemini_pro_vertex` provider key would force every test and override path to be aware of the routing distinction, even though the *model behaviour* is identical between AI Studio and Vertex for the same model ID. Treating routing as an orthogonal env-level concern keeps `TMT_PROVIDER` about model selection, not auth (how the caller is identified).

**Why not also wire Vertex Garden for Claude/OpenAI.** Vertex Model Garden's non-Google catalog (its list of other companies' models) is partial and lagging. The judge ensemble (gemini_pro + claude + openai + deepseek) is meant to test *cross-vendor* agreement; routing Claude/OpenAI through Vertex would re-introduce single-cloud dependency for that comparison. Out of scope for now.

**Where it lives.** `providers.py::is_using_vertex`, `validate_vertex_config`, `enable_vertex`, `snapshot_vertex_config`. CLI flag in `run_research_session.py::__main__` (`--vertex`, `--vertex-project`, `--vertex-location`). Manifest field `ReplicationManifest.vertex_config`. Verified by `tests/test_vertex_mode.py`.

## 20. Extra phases via `PhaseHandler` protocol

**Decision.** A study can register additional post-deliberation phases through `StudyConfig.extra_phases: List[PhaseHandler]`. Each handler is a small `typing.Protocol`, Python's way of stating what parts a piece of code must have (`studies/base.py::PhaseHandler`), with five members: `name: str`, `folder_prefix: str`, a `should_run(...)` gate, `async run(...)`, and `persist(out_dir, result, write_json)`. The framework iterates the list after Phase 4 and runs each handler whose gate returns True; the CLI `--judge` flag opts into any handler whose name is `"construct_judging"`.

**Why.** Hardcoding a fixed Phase 5 in `run_research_session.py` would tie the framework to one construct and one scoring approach — incompatible with the multi-study thesis. The `PhaseHandler` seam lets a study (a) register the construct-judge ensemble (the openness study does), (b) register a different scoring method, or (c) register nothing at all. Handler identifiers are exposed via `StudyConfig.extra_phase_ids_for_manifest()` so a reviewer can resolve which extra phases ran for a given run.

**Alternatives ruled out.** (a) A boolean `run_judging` on `StudyConfig` — works for one phase, but reproduces the hardcoding problem the moment a study wants a second extra phase. (b) Handler instances stored directly in the manifest — Pydantic-serialisation-unfriendly (hard to save as plain text); the `extra_phase_ids_for_manifest()` dotted-path approach (names like `a.b.C` that point to code) keeps the manifest JSON-dumpable (savable as JSON).

**Where it lives.** `studies/base.py::PhaseHandler` + `StudyConfig.extra_phases` + `extra_phase_ids_for_manifest()`. Default-study handler: `orchestrator/construct_judging.py::ConstructJudgingPhase`. CLI gate: `run_research_session.py::__main__` (`--judge`). Verified by `tests/test_phase_handlers.py`.

## 21. Per-study debriefing-protocol overlay

**Decision.** The framework-level `protocols/ethnographic_protocol.yaml` carries five **generic** thematic areas — A (decision anchoring), B (counterfactuals), C (disagreement and resolution), I (context sensitivity), J (reflection and unresolved). A study can extend this set with **study-specific** areas via `StudyConfig.protocol_overlay` — either an inline dict (named settings written in the file) or a path to a YAML file. The default `openness_maneuvering` study loads `studies/openness_maneuvering/debriefing_overlay.yaml`, which adds areas D–H (differences in handling / who does the work / changes over time / what the firm gets and gives / position relative to others). At load time the overlay is deep-merged (combined level by level) via `roles/qualitative_researcher_agent.py::_apply_study_overlay` — `thematic_areas_overlay` appends after the framework's areas, `behavioural_rules_additions` appends as a separate paragraph, `panel_format_additions` dict-merges. Unknown overlay keys are silently ignored.

**Why.** Hardcoding all thematic areas in the framework YAML would tie the framework to one construct's probing structure. Hardcoding all areas per-study would force every study to re-state the generic A/B/C/I/J probes. Splitting between framework-generic and study-specific overlay lets a new study supply only its construct-anchored additions while the methodologically-generic probes stay framework-level.

**Alternatives ruled out.** (a) One YAML per study (no inheritance) — loses the framework-level methodological backbone; every study has to re-implement generic probes. (b) String-substitution templating (filling blanks in text) — too low-level for the structured thematic-areas schema. (c) Allow overlays to delete framework areas — methodologically risky; the overlay contract is **add-only**.

**Where it lives.** `roles/qualitative_researcher_agent.py::_apply_study_overlay` + `closing_area_id` (resolves the `always_ask` flag in the merged protocol). `studies/openness_maneuvering/debriefing_overlay.yaml` for the openness study's D–H areas. Verified by `tests/test_protocol_overlay.py`.

## 22. Sub-dimensional text-grounded scoring (openness study only)

**Decision.** The openness study ships a `Method A` text-scoring layer underneath the LLM-judge ensemble: `analysis/text_measures/dictionary.py` reads the run's persisted transcripts and scores them against a published lexicon, a fixed word list tied to the concept (`studies/openness_maneuvering/subdimension_lexicon.py`) — 26 sub-dimensions across three channels (public artefacts + public transcript + debriefing; private scratchpads (notes) + drafts + inbox; researcher field notes) — and writes `06_subdimension_scores/{headline,headline_by_role,per_subdimension,per_dimension}.csv` (plain-text tables) + a markdown summary. The dictionary scorer runs alongside the LLM-judge ensemble, not instead of it.

**Why.** The seven-dimensional LLM-judge rubric — `component_disclosure`, `process_openness`, `boundary_permeability_inbound`, `boundary_permeability_outbound`, `ecosystem_orchestration`, `value_capture_posture`, `temporal_openness_maneuvering` — collapses 3–5 latent sub-constructs per dimension into one Likert score. The first live judge run on the five-dimensional v0.1 rubric produced Krippendorff's α ≈ 0 — the three judges were integrating sub-constructs with different implicit weights, which a published per-sub-dimension lexicon makes auditable. Every text-score traces to a sub-dimension + an evidence sentence + a published regex (a written pattern for finding text); the LLM-judge ensemble traces to the qualitative summary it wrote before scoring. Reporting both produces convergent-validity numbers across two axes (cross-vendor judge agreement + text-grounded reproducibility) that any single axis cannot. The rubric was upgraded to seven dimensions at v0.2 (May 2026): `boundary_permeability` split into inbound and outbound (Dahlander & Gann 2010), and `temporal_openness_maneuvering` added (Henkel 2006 dynamic; Alexy, Henkel & Wallin 2013) to score the firm's *reasoning about timing*, which the RQ explicitly asks about but the v0.1 rubric could not capture.

**Why three channels separately.** The simulation produces three distinct text channels — public artefacts (firm-committed), private scratchpads + drafts (firm-internal), researcher field notes (researcher's read). Conflating them contaminates the construct: a field-noter sentence is the researcher's interpretation, not the firm's commitment; a private scratchpad note was never visible to peers at deliberation time. The public-vs-private *gap* is itself a separable research question, deferred to a later paper — this layer just reports the per-channel numbers.

**What's deferred.** Method B (sentence-transformer embedding similarity: comparing lists of numbers that stand for a text's meaning), Method G (BERTopic cross-run topic discovery: software that groups texts into topics automatically), and pre-submission τ calibration (setting a cut-off score, τ) for Method B.

**Where it lives.** Methodological design — [`studies/openness_maneuvering/docs/02_subdimension_measurement_plan.md`](../studies/openness_maneuvering/docs/02_subdimension_measurement_plan.md). Lexicon — `studies/openness_maneuvering/subdimension_lexicon.py`. Scorer — `analysis/text_measures/dictionary.py`. CLI flag — `run_research_session.py::__main__` (`--subdimension-scores`). Verified by `tests/test_dictionary_method.py` + `tests/test_subdimension_lexicon.py` + `tests/test_private_channel_persist.py`.

## 23. RAG-grounded TMT deliberation via Google Vertex AI RAG Engine

**Decision.** When `--rag` is set, each TMT role agent retrieves ~5 excerpts from a per-firm corpus (document collection) before each LLM call in Phases 1 / 2 / 4, and emits structured `Citation` records (`{doc_id, chunk_id, quote, supports}`, where a chunk is a passage cut from a document) for excerpts it leaned on. Agents see each retrieved passage whole (`TMT_PASSAGE_CHARS` sets a limit for testing). The persistence layer renders citations as inline Markdown footnotes in the per-run MD files. The retrieval backend (the software doing the search) is **Google Vertex AI RAG Engine** — `vertexai.rag` — with one corpus per firm named `<study_slug>__<Company>` and embeddings (lists of numbers standing for a text's meaning) via `text-embedding-005`. The researcher shells, the three set-ups of the researcher agent (Observer / FieldNoter / Debriefer) do **not** retrieve — invariants I1–I3 (numbered in `05_methodological_invariants.md`) stay, and a new I5 (a query is the search text; "retrieval queries built from role + task + transcript only, never RQ or lens") tested parametrically.

**Why Vertex AI RAG Engine over a local RAG (sentence-transformers + FAISS / Chroma, software that runs on your own computer).** A local stack would also work for the openness study's 127-document set and was the prior pattern of the PI, the principal investigator (CrewAI work, using other software for teams of agents). Three converging reasons made Vertex the lower-friction default for *this* framework:

1. **Auth + project + billing already wired.** The framework's `--vertex` flag (decision §19) routes Gemini calls through Vertex AI. Adding `vertexai.rag` reuses the same env-var auth path (`GOOGLE_GENAI_USE_VERTEXAI=true` + project + location + ADC, Application Default Credentials, Google's stored login). A sentence-transformers backend would have added ~500 MB of embedding-model files on disk, a chunking pipeline (code that cuts documents into pieces), an index file to maintain, and a second sentence-transformers usage co-existing with Method B's prototype-sentence embedding plan (`studies/openness_maneuvering/docs/02_subdimension_measurement_plan.md`, deferred Phase E) — different purpose, same dep (package of code), harder to reason about.
2. **Reproducibility shifts to SHA-pinning, not index-shipping.** Per-doc SHA256s (fingerprints computed from each file's contents) land in `07_rag/corpus_manifest.json` at run time. A reviewer reproducing the run uses the SHAs to verify their reconstructed corpus matches the run's content, then rebuilds via `python -m rag.corpus_build`. The `--vertex` route already uses Google Cloud credentials, and the RAG layer lives on the same auth path.
3. **The framework is not air-gap-oriented (built to run cut off from the internet).** Every Phase 1 / 2 / 3 / 4 / 5 LLM call already hits a hosted provider. The deployment story is "needs internet + at least one API key"; adding a managed RAG backend doesn't change that.

**What we give up.** Vendor lock-in to Google Cloud for the RAG path; ~100–300 ms per-retrieval network latency vs ~1 ms for local; and a database bill. Embedding and retrieval calls cost little, but the RAG Engine database bills for as long as a corpus exists, whatever its size: about $3 a day on the Basic tier (price level) and about $30 a day on Scaled, at list rates for Spanner (the Google database behind it) (see [`10_rag_repo_plan.md`](10_rag_repo_plan.md) § Cost). A future port to a local backend is feasible: `rag.vertex_corpus` is the only Vertex-specific module; the rest of the layer (schemas, runtime, query builders, persistence, comparison harness) is backend-agnostic. If air-gapped operators ever need this framework, that port is the lowest-friction path. The trade-off is recorded explicitly in `DECISIONS.md` §8 so future re-consideration has the rationale to reverse.

**Why citations are a structured schema field, not inline markers.** `AgentAction.citations`, `StrategicArtefact.citations`, and `PanelResponse.citations` are Pydantic fields populated via the schema-enforced structured output the framework already trusts for every role's outputs. The LLM never emits raw `[ref:doc_id]` markdown markers; the persistence layer adds inline `[^cN]` footnotes during rendering from the structured citations. Inline-marker handling would have required a brittle regex parser; the structured-field route reuses the same `output_schema` enforcement (`AgentAction.kind`, `StrategicArtefact.main_decisions`) the framework already validates per call.

**Why the researcher does not retrieve.** Invariants I1–I3 require Observer + FieldNoter, by default, to be blind to the study's RQ + lens; if the researcher could retrieve, the query itself would be a back-door for analytical framing to leak into data collection. The LLM-researcher asking "what's the firm's stance on open weights?" would surface documents that prime its own observation. Keeping retrieval inside the panellists (who don't know the construct under study) preserves the asymmetry: the panel acts; the researcher observes. The new invariant I5 formalises this for the query construction itself — builders in `rag/queries.py` take role + task + transcript only.

**Where it lives.** `rag/` package (bundle of code): `schemas.py` (Citation + RetrievedSnippet); `vertex_corpus.py` (Vertex SDK wrapper); `prompt_inject.py` (REFERENCE MATERIAL block + populate-citations instruction); `queries.py` (the three retrieval-query builders); `runtime.py` (RagSession + loader resolver). Per-study loader: `studies/openness_maneuvering/rag_loader.py`. Build CLI: `python -m rag.corpus_build`. Comparison harness (a small program that runs the comparison): `analysis/compare_rag.py` ([`docs/10_rag_repo_plan.md`](10_rag_repo_plan.md)). CLI flag: `run_research_session.py::__main__` (`--rag`). Manifest field: `ReplicationManifest.rag_config`. Per-run audit folder: `07_rag/`. Verified by `tests/test_rag_*.py` (across schemas, runtime, queries, prompt-injection, orchestrator wiring, persistence, loader resolution, build CLI, and the comparison harness).

## 24. Framework framing — ethnography in silico, not "simulation with an observer"

**Decision.** The framework is documented and prompt-instructed as **a tool for conducting qualitative ethnography on synthetic subjects in real time**, not as a simulator that happens to log outputs. The Observer / FieldNoter / Debriefer agents are ethnographers; the deliberation is the field; the persisted folder is field data the principal investigator codes inductively.

**Why.** The "simulator with an observer" framing collapses what the framework actually offers. Two things the framing change makes load-bearing:

1. **The researcher agents inherit ethnographic discipline by design.** Their system prompts (standing text telling a model who it is and how to behave; `roles/qualitative_researcher_agent.py`) enforce "record using the panel's own vocabulary, do not paraphrase into your analytical categories, do not seek evidence of any particular construct, describe what you see." The blindness invariants (I1–I3 + I5) operationalise reflexive bracketing of researcher bias at the prompt level — independently testable, not researcher virtue.
2. **The persisted output is the field data a human PI codes inductively, not a "result" the framework computes.** Live field notes during Phases 1 + 2, structured ObservationSummary at Phase 3, debriefing transcript at Phase 4, source-citation footnotes throughout when `--rag` was on — these are the inputs to the PI's analytical judgement, which remains the final stage.

This affects how a methods section describes the framework's role in the research process: as a methodological apparatus, not as a black-box simulator. The full framing is articulated in [`11_ethnography_in_silico.md`](11_ethnography_in_silico.md) — including the four channels of field data the framework gives the PI (public / private / researcher / source) and the auditing protocol a qualitative reviewer can apply to any run.

**Where it lives.** Three ethnographic commitments operationalised in code:
- **Participant observation** — `orchestrator/researcher_stream.py` + `create_field_noter_agent` (live note-taking during deliberation).
- **Inductive description** — observational-discipline rules in `create_observer_agent` + `create_field_noter_agent` system prompts.
- **Reflexive bracketing of bias** — `_render_research_context` (asymmetric access across the three shells) + the five invariants in `tests/test_methodological_invariants.py` + `tests/test_rag_persistence.py::TestInvariantI5NoQueryLeakAcrossStudies`.
