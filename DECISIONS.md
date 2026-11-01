# DECISIONS

The consequential methodological and architectural choices behind this repository (the project's files and their history of changes): what was decided, when, and why. The broader, code-cross-referenced design rationale of the framework (the shared software in this repository) lives in `docs/02_design_decisions.md`. Terms are defined in [`docs/GLOSSARY.md`](docs/GLOSSARY.md).

## How to use this file

- **To find a decision,** use the index below, or go to the section for its topic.
- **To add a decision:**
  1. Use the next unused number. The highest number is the last row of the index.
  2. Choose the part. Ask whether the decision would still hold if the study were deleted. If yes, it goes in Part A (framework). If no, it goes in that study's part.
  3. If it touches both, place it where the decision is mainly about, and name the other side in the index's Notes column.
  4. Add it at the end of its section, and add a row to the index. `tests/test_decisions_log.py` checks both.
- **Numbers are permanent.** Code, tests and documents cite entries as `§N`, so entries are grouped by topic and are not in number order.
- **Never rewrite an entry.** To change a decision, add a new entry that supersedes it, add a one-line pointer in the old one, and update both Notes cells.
- **A new study gets its own part,** Part C, Part D and so on, with its slug (short name with no spaces) in the heading.
- **"Session N" references:** some older code comments and plan notes cite "Session N". They come from an earlier grouping by working session. This file has no session headings, so use the entry number where one is given.

## Index

| § | Decision | Section | Notes |
|---|---|---|---|
| 1 | Per-provider (model supplier) adapter (translating code) for the structured output (replies in fixed fields) of DeepSeek (a language model) | [A3](#a3-providers-and-structured-output) |  |
| 2 | Openness rubric (scoring guide) broken into sub-dimensions | [B2](#b2-construct-and-measurement) |  |
| 3 | Public, private and researcher channels (kinds of record) kept separate | [A4](#a4-data-capture) | Also study: scoring per channel |
| 4 | Text-based scorer runs alongside the judges (models that score a finished run) | [B2](#b2-construct-and-measurement) |  |
| 5 | Default to strict construct validity | [A3](#a3-providers-and-structured-output) |  |
| 6 | Measurement plan published with the lexicon (word lists) | [B2](#b2-construct-and-measurement) | Path moved by §34 |
| 7 | Refuse API keys (secret codes for using a service) pasted into chat | [A7](#a7-repository-and-working-practice) |  |
| 8 | Vertex AI RAG Engine (Google's paid service for RAG, retrieval-augmented generation: searching documents to add passages to a prompt) as the retrieval (search) backend | [A5](#a5-retrieval-and-grounding) |  |
| 9 | Citations (a role's record of what it drew on) as a schema (template of fields) field | [A5](#a5-retrieval-and-grounding) |  |
| 10 | Corpus (document collection) loader is read-only | [A5](#a5-retrieval-and-grounding) | Also study: loader lives in the study |
| 11 | Researcher agents (language models set up to observe and question the team) do not retrieve | [A5](#a5-retrieval-and-grounding) |  |
| 12 | Comparison pairs runs (complete simulated meetings and debriefs) within one provider | [A5](#a5-retrieval-and-grounding) |  |
| 13 | Full retrieved text kept in the audit log | [A5](#a5-retrieval-and-grounding) | Corrected by §52 |
| 14 | Grounded (traced to firm documents) claims lead the per-pair report | [A5](#a5-retrieval-and-grounding) |  |
| 15 | Five-firm corpus, documents supplied outside git (the tool that keeps the project's history) | [B1](#b1-research-design-and-corpus) | Document classes widened by §33 |
| 16 | RAG work stacked as small PRs (pull requests: proposed code changes) | [A7](#a7-repository-and-working-practice) |  |
| 17 | Framed as in-silico ethnography | [A1](#a1-method-framing) | Refined by §18, §54 |
| 18 | Three-layer framing of the method | [B3](#b3-paper-framing-and-contribution) | Refines §17; see §54 |
| 19 | Sweep (planned set of runs) reduced from 240 cells (firm, context and product combinations) to 20 | [B1](#b1-research-design-and-corpus) | Path moved by §34; scoring made optional by §54 |
| 20 | Rubric v0.2: seven dimensions | [B2](#b2-construct-and-measurement) |  |
| 21 | Longitudinal web-archive corpus deferred | [B1](#b1-research-design-and-corpus) |  |
| 22 | RAG scoped out of the executed paper | [B1](#b1-research-design-and-corpus) | **Superseded by §33** |
| 23 | Contribution is methods and microfoundations | [B3](#b3-paper-framing-and-contribution) | Scoring made optional by §54 |
| 24 | Reference set for that framing | [B3](#b3-paper-framing-and-contribution) |  |
| 25 | Judge failures captured with a traceback (the error's technical record) | [A6](#a6-judging-infrastructure) |  |
| 26 | Replay (rerunning a later stage from a saved run) tool for judges | [A6](#a6-judging-infrastructure) |  |
| 27 | DeepSeek-R1 added as a fourth judge | [A6](#a6-judging-infrastructure) | Also study: rationale draws on §23 |
| 28 | Reasoning discipline in the role prompt (text sent to a model) | [A2](#a2-agent-prompts-and-the-debrief) | Worked example replaced by §35 |
| 29 | Scoring moved to 26 sub-dimensions, 0–100 | [B2](#b2-construct-and-measurement) | Also framework: judge schemas and aggregator |
| 30 | Judge timeouts (giving up on a slow call), error classifier and retry | [A6](#a6-judging-infrastructure) | Retry loop moved by §31 |
| 31 | Live and replay judges share one retry helper | [A6](#a6-judging-infrastructure) |  |
| 32 | OpenAI judge moved to GPT-5.4 | [A6](#a6-judging-infrastructure) |  |
| 33 | RAG back in scope: traceable grounding | [B1](#b1-research-design-and-corpus) | Supersedes §22. Also framework: `rag/` |
| 34 | Study docs live in the study; committed (saved to the project's history) `CLAUDE.md` (guidance for anyone working on the code) | [A7](#a7-repository-and-working-practice) |  |
| 35 | No prompt may steer toward open vs closed | [A2](#a2-agent-prompts-and-the-debrief) | Also study: overlay (a study's own topics for the debrief, its interview of the team), lens (theory for analysis) and word lists |
| 36 | Research question is a guiding post | [A2](#a2-agent-prompts-and-the-debrief) |  |
| 37 | Area J closes the debrief | [A2](#a2-agent-prompts-and-the-debrief) |  |
| 38 | Debrief researcher explores; areas are a guide | [A2](#a2-agent-prompts-and-the-debrief) |  |
| 39 | Test debrief behaviour from saved runs | [A8](#a8-testing-from-saved-runs) |  |
| 40 | Replay the debrief on a saved deliberation (the team's recorded discussion) | [A8](#a8-testing-from-saved-runs) |  |
| 41 | This file split into framework and study parts | [A7](#a7-repository-and-working-practice) |  |
| 42 | Run record tells a failure from silence | [A4](#a4-data-capture) |  |
| 43 | Research question matches the proposal | [B1](#b1-research-design-and-corpus) | Study v0.5.0 |
| 44 | Debrief questions explore the research question | [A2](#a2-agent-prompts-and-the-debrief) | Refines §36, §38 |
| 45 | Retrieval region (location of the rented computers); panel citations parsed | [A5](#a5-retrieval-and-grounding) |  |
| 46 | Provenance (where text came from) report and panel probe (a test putting one run's questions to each role) | [A8](#a8-testing-from-saved-runs) | Also study: `example_runs/` |
| 47 | Environmental conditions are a future study | [B1](#b1-research-design-and-corpus) | Replaces the P1 (priority level in `ROADMAP.md`) scenario-events item |
| 48 | Test the risks before collecting data | [B1](#b1-research-design-and-corpus) | Also framework: `analysis/role_statistics.py` |
| 49 | Publish what lets reviewers repeat and compare runs | [B1](#b1-research-design-and-corpus) | Also framework: `analysis/redact_run.py` |
| 50 | Review of runs A to D (four prototype test runs): corrections and changes | [A4](#a4-data-capture) | Corrects §13, §42, §45 |
| 51 | Blind or embedded observation (whether the observer knows the research question) is the study's choice | [A2](#a2-agent-prompts-and-the-debrief) | Refines the blind researcher in §44 |
| 52 | Each model call (one prompt and its reply) carries what it needs, once | [A4](#a4-data-capture) | Replaces §4 of `docs/02_design_decisions.md`; refines §50 |
| 53 | Pose the study's problem in the decision task | [B1](#b1-research-design-and-corpus) | Refines §47, §48 |
| 54 | Ethnography's practice, not its warrant; scoring is optional and not part of the method | [A1](#a1-method-framing) | Refines §17, §18, §23; also study: scoring |

---

## Part A: Framework

Decisions that would still hold if the openness study were deleted.

### A1. Method framing

#### 17. Frame the framework as **in-silico ethnography**, not as a "TMT (top management team) simulator with an observer".

**What.** The methodological framing across `docs/11_ethnography_in_silico.md` and the role-prompts in `roles/qualitative_researcher_agent.py` treats the framework as a tool for **conducting qualitative ethnography on synthetic subjects in real time**, not as a simulator that happens to log outputs. The Observer / FieldNoter / Debriefer (the three set-ups of the researcher agent) are ethnographers; the deliberation is the field. The framework's contribution is methodological — it lets a PI (principal investigator) run inductive qualitative research at study scale with full provenance — not just computational.

**Why.** The "simulator with an observer" framing collapses what the framework actually offers. Two things the framing change makes load-bearing: (1) the researcher agents inherit ethnographic discipline by design (their prompts already enforce "panel's own vocabulary", "do not paraphrase into analytical categories", "do not seek evidence of any particular construct"; the rename makes that intentional rather than incidental); (2) the persisted (saved) output (live field notes during Phase 1 + 2, the team's discussion and documents; structured ObservationSummary at Phase 3, debriefing transcript at Phase 4) is the **field data a human PI codes inductively**, not a "result" the framework computes. This affects how a methods section describes the framework's role in the research process; the new doc 11 articulates the framing in full.

**Scope clarified 2026-05-24** (see §18, §54). The ethnography framing is for the data-collection method (the Observer / FieldNoter / Debriefer agents), inside a simulation, and §54 says what it claims. §18 records the three layers.

#### 54. **The approach claims ethnography's practice, not its warrant. Human analysts hold interpretive authority. Scoring is optional and not part of the method.**

**What.** The approach is called ethnography in silico, inside a simulation framework. It claims ethnography's practice (observing in process, field notes, following surprises), not its warrant. Human analysts who read the full records code them and hold interpretive authority. We observe agents, not executives' minds. The scoring tools (`--judge`, `--subdimension-scores`) are optional, off by default and not part of the method, and neither is `scripts/run_frontier_sweep.sh`, an older sweep that scores every run. Earlier entries that rest validity on the judges (§19, §22, §29) describe an earlier design.

**Why.** Agents have no lived experience, stakes or shared history, and the fieldworker is a model, so the records cannot speak for themselves. A scorer also has to give a score, so it can rate a team on something the team never discussed (L12 in `docs/LEARNINGS.md`).

**Where it lives.** `docs/11_ethnography_in_silico.md`, `docs/05_methodological_invariants.md`. To keep this log to decisions, the bodies of §5, §7, §15, §16, §17, §18, §19, §21, §22, §23, §24, §29 and §33 were shortened and references to a plan outside this repository were removed. Their numbers and headings are unchanged.

### A2. Agent prompts and the debrief

#### 28. **Operationalise reasoning-disclosure discipline in the role prompt + tighten ASK/ANSWER (putting a question to one colleague, and replying) length targets.** *(PR #74)*

**What.** Three coordinated edits to `orchestrator/concurrent_mode.py`:

1. New `REASONING DISCIPLINE` block in the role prompt (between `STRATEGIC DEPTH` and `YOUR DISCUSSION STATUS`). Every substantive utterance must make three things visible: **position** (the call), **reasoning** (assumptions trusted + trade-offs weighed + evidence pushing one way and not the other), **open questions** (what you don't know + where you'd want peers to push back). Plus a "What NOT to do" sub-list calling out four concrete anti-patterns (bare conclusions / named methodologies without articulation / agree-with-everything / fabricated confidence), and an anchor example showing the contrast between thin and substantive endorsement.

2. Word-count + structure targets baked into the `AgentAction.text` (~120–180w for SPEAK, a public statement; ~80–120w for ANSWER) and `AgentAction.ask_question` (~80–120w with explicit three-part structure: context that prompted the ask + specific value needed + constraints to weigh) field descriptions.

3. The "bare one-line question is almost always too thin" callout — directly targets the cryptic-delegation failure mode where ASK / ANSWER turns were ~50–90 words while SPEAK turns were ~100–200 words, leaving the deliberation transcript alternating between rich and cryptic depending on action kind.

**Why.** Phase-1 (deliberation) transcripts before this PR showed a clear bimodal pattern: SPEAK turns were substantive (~100–200w with reasoning visible), but ASK / ANSWER turns were terse (~50–90w, position-only, no reasoning surfaced) because the schema-field descriptions said only "the question text" / "the reply text" and the LLM (large language model) defaulted to brevity. Reading the deliberation top-to-bottom alternated between rich and cryptic. The user-reported "deliberation messages are short and cryptic" complaint was exactly this. Operationalising the three-part discipline in *both* the prompt prose and the schema-field descriptions pushes the LLM off its terseness default uniformly.

**Cost impact.** Expected ~$2–3 per cell on the deliberation phase from the longer transcript carrying forward into every subsequent turn. Within the user's "cost is fine" envelope; the methodological value of substantive ASK / ANSWER turns is the qualitative-coding payoff downstream.

**Where it lives.** `orchestrator/concurrent_mode.py` (the new block + tightened field descriptions), `tests/test_reasoning_disclosure_prompt.py` (11 prompt-content tests including block ordering, three-element naming, word-count targets, anti-pattern callouts, contrast example, AgentAction field shape).

#### 35. **No prompt the panel reads may steer it toward open vs closed, and worked examples must carry no strategy content.**

**What.** A test run on 30 Oct 2026 showed that the study's construct and a product idea were reaching the team through the prompts, although the forbidden-vocabulary (words the researcher agent must not use) check reported no violations. This entry removes them:

* The panellist prompt carried the research question on every debrief turn. It is gone, and the panel no longer receives it at all.
* The CTO's document prompt asked which assets are "internal vs. shared / proprietary vs. open / build vs. buy". The Designer's asked "which pieces are treated which way". Both are gone.
* A worked example in the turn prompt quoted an "edge-cloud architecture", "hybrid", "SLM … <2B params" and an "M2M protocol". The first product idea in that run repeated these terms. The example now describes the form of a good answer with no content. The artefact (strategy document) title example and the citation example ("open-weight commitment"; open-weight means a model's trained numbers are published) are also gone.
* The debrief areas D, E, G and H used synonyms the check could not catch ("stay close … go out", "keep tightest", "putting it out", "an outsider contributes"). They are rewritten in neutral terms.
* The Debriefer's lens and background told it to look for what firms "disclose vs keep internal" and "keep in vs let out". The field-note prompts asked for asymmetries in how pieces are treated. All are removed; the literature moves to `studies/openness_maneuvering/docs/01_study_anatomy.md`, for use in analysis.
* The decision task no longer asks how to "govern and release" the product. Role briefs and context bullets lose "ecosystem", "moat", "community" and "standards" lines, which also differed across scenario conditions.
* The forbidden and watch lists now include "openness", "proprietary", "open-weight" and similar words. "Openness" was not caught before, because the check matches whole words.

**Why.**

1. **The study asks how openness arises.** A pattern that the prompts ask for cannot be evidence of that, which is the objection the pilot (the earlier study, built on different software) already drew.
2. **The vocabulary check cannot catch paraphrase.** It matches words, so prompts must be neutral by construction.
3. **Framework code should carry no construct.** The CTO prompt, the worked example and the field-note prompts are in the framework and would have steered any study.

**What stays.** The Debriefer still receives the research question, under the rule not to steer. It is the only place the construct is stated in prose while a run is under way. The researcher's forbidden and watch lists name the construct's words so it can avoid and log them; the panel never sees them. The judges' rubric and lexicon name the construct because they score the run afterwards, and the panel never sees them. The pilot's code stays as it was run.

**Consequence.** Openness may now rarely come up, and that would be a finding about the design. If a scenario has to make it a live decision, that change must be stated openly as a condition of the study.

**Where it lives.** `tests/test_no_construct_steering.py` renders the panel-facing prompts and fails on this wording.

#### 36. **The research question is a guiding post for the Debriefer, not a rule for what to capture.**

**What.** The Debriefer knows the research question and uses it to choose where to begin exploring. It must never share the question with the panel. It follows interesting observations even when they lead away from the question, as long as each probe is anchored in something observed. New questions go in `PanelUtterance.emerging_question`, which the panel never sees, and are listed at the end of `04_interview/transcript.md`.

**Why.** Inductive research is cyclic. Researchers revise their questions as they see interesting phenomena in the field and read further literature. A Debriefer held to the original question would miss exactly the observations that could change it.

**What does not change.** The Debriefer still may not steer the panel toward the question, name the construct, or manufacture relevance. Agents do not change the research question. The researchers decide whether to revise it between runs, and a revised question means a new study version.

**Where it lives.** `roles/qualitative_researcher_agent.py::_render_research_context`, `roles/researcher_schemas.py`, `analysis/persist_artefacts.py`.

#### 37. **Area J closes the debrief: follow-ups come first, and the prompt names the real closing area.**

**What.** The merged protocol listed areas as A, B, C, I, J, D, E, F, G, H, and the first pass walks them in that order, so the 30 Oct 2026 test run asked the closing questions fifth. The Debriefer's prompt also still said that Area F closes, and that `area_id` could only be A to F. Areas are now merged in id order with the closing area last. The prompt takes the closing area and the valid ids from the protocol. In `structured_then_followup` mode the first pass holds the closing area back, so follow-ups come before it. Strict `structured` mode still covers it in the pass.

**Why.** Reflection questions work best after the rest of the debrief, and `DECISIONS.md` §36 needs room for follow-ups on what the panel raises. A prompt that names the wrong closing area contradicts the rest of the instructions.

#### 38. **The debrief researcher explores: the thematic areas are a guide, and what it finds decides where it goes.**

**What.** A test run on 31 Oct 2026 asked one real follow-up in 12 questions, because the first pass told the researcher that its next question MUST use the next unvisited area. It also ended below the 15–25 target. The first pass no longer binds in `structured_then_followup` mode: the researcher probes an answer first if it gives something to pursue, and moves on otherwise. It is told to look for surprises and for agreement worth questioning, and to keep pursuing the questions it records, which the coverage map now lists for it. It may anchor a question on an answer given in the debrief. It is told not to close before the target length unless nothing is left to explore; this is guidance, not a hard limit. Field notes also ask for anything surprising or puzzling.

**Why.** Ethnography finds out what matters from the field, including phenomena current theories do not explain. A researcher who must finish a list of areas cannot do that, and the previous rule also contradicted the protocol's own description of the mode. See §36.

**What does not change.** The researcher still may not steer the panel, name the construct, or share the research question, and every question must be anchored in something observed. Agents flag new questions. Researchers judge them, because something that looks new may be recalled from training data or caused by the prompts.

**Where it lives.** `orchestrator/panel_debriefing.py`, `roles/qualitative_researcher_agent.py`, `protocols/ethnographic_protocol.yaml`, `tests/test_flexible_debrief.py`.

#### 44. **The debrief researcher's questions explore the research question, through what the team did.**

**What.** Each question should help explore the research question and stay anchored in something the team said or produced. It records the link in `research_question_link`, or marks it `adjacent`. The panel never sees the question or the link, and the researcher may use a listed word only after a panelist has. No prompted question about the construct was added.

**Why.** The authors want the debrief tied to the research question as well as to the deliberation. §36 and §38 stay in force: the researcher may still follow surprises and record new questions. In one grounded run this gave 18 of 20 linked questions and 10 follow-ups, and reached the exchange cap without a closing question.

**Where it lives.** `roles/qualitative_researcher_agent.py`, `roles/researcher_schemas.py`, `tests/test_no_construct_steering.py`.

#### 51. **Whether the researcher agent knows the research question while observing is the study's choice.**

**What.** `StudyConfig.embedded_observation` sets it. False, the default, keeps the observer and field noter blind to the question, as before. True makes them embedded: they know the question while observing, though not the theoretical lens. The debriefer always knows the question, and the panel never does. Each run's meta records the choice.

**Why.** Ethnographers work both ways. A separate observer who does not know what the study hopes to find guards against seeing what one expects. An embedded ethnographer knows what to watch for and can notice more that bears on it. Neither is right for every study, so it is a design choice for researchers, and something we can test. Blindness is also only partial: a blind observer still receives the study's word list, which hints at the topic.

**Where it lives.** `studies/base.py`, `roles/qualitative_researcher_agent.py`, `run_research_session.py`, `tests/test_observation_stance.py`, `docs/05_methodological_invariants.md`.

**Update, 31 Oct 2026.** A check of the methods literature found that ethnographers normally enter the field with a question. Fieldworkers kept unaware exist but are rare, and those reported hid an outcome or a contrast, not the study's topic. So the openness study's main runs will use embedded observation, and the blind setting stays as a second view. No code changed; the technical appendix gives the sources.

### A3. Providers and structured output

#### 1. Treat DeepSeek as a first-class provider, not warn-and-defer.

**What.** When the structured-output assumption broke against DeepSeek's API (it rejects strict `response_format={"type":"json_schema",…}`), I chose to build a real per-provider adapter rather than warn at startup or silently downgrade every provider.

**Why.** DeepSeek had just been shipped as a "low-cost provider option" in the preceding commit (saved change). Warning that it can't run structured phases would have effectively un-shipped a feature still wet on the page. Silent downgrade to `{"type":"json_object"}` for every provider would have lost server-side construct validity for the providers that *do* support strict mode (replies must match the template exactly: Gemini, Claude, OpenAI, Groq) — a worse outcome than the original problem. The adapter route lets every provider keep the strongest enforcement it supports.

#### 5. Default toward strict construct validity, even at cost.

**What.** Several smaller decisions in the session bent the same direction: new LLM providers default to strict `json_schema` enforcement (allow-listed exceptions only); sub-dimension aggregation defaults to a uniform mean rather than a weighted one (no implicit claim about which sub-construct matters more); the LLM judge ensemble is kept as premium (no cost-downgrade to the cheap providers).

**Why.** The bias is "lose enforcement only when we observe the provider requires it" rather than "downgrade by default to save cost." Choices made to be cheap or convenient are hard to defend, so the framework defaults to defensible-and-strict and only weakens with a stated reason. This stance also keeps every methodological claim independently auditable.

### A4. Data capture

#### 3. Measure public, private, and researcher channels separately.

**What.** The simulation produces three distinct text channels: the firm's *publicly-enacted* posture (artefacts + public transcript — what the LLM judges already see), the firm's *internal* deliberation (scratchpads, working drafts, inbox messages — never shown to peers during Phase 1), and the *researcher's* running field notes (the FieldNoter's interpretation, not the firm's commitment). I decided to persist all three and score them separately.

**Why.** Conflating them contaminates the construct. A sentence in the field notes saying "the team showed little hesitation about open-sourcing" is the researcher's read, not the panel's. Working drafts were never visible to peers at deliberation time, so they cannot count as "publicly committed." The public-vs-private *gap* — which is what Henkel's selective-revealing lens is really about — is a separable research question deferred to a later paper; this paper just reports the numbers per channel.

#### 42. **A run's record must tell a failure from silence, and must hold what the paper says it holds.**

**What.** A panel answer lost to a failed model call is now recorded per exchange (`lost_roles`), shown in the transcript, and listed in the run's errors as `panel_answers_lost`, so the command exits 1 (reports failure). A `[PASS]` (a reply meaning nothing to add) is still silence. `google.auth`'s `TransportError` is now retried, and the classifier reads the exception's class name as well as its message. Field notes are saved to `03_researcher/`, and `00_meta.json` (the run's summary file) records each role's model. Judges run only with `--judge`.

**Why.** In run C a failed model call cost the Product Strategist's optional reply at exchange 2. It was not retried, the transcript showed nothing, and `errors` stayed empty, so a lost answer looked like a decision to stay silent. The panel prompt calls silence data, so this could corrupt analysis. Field notes and models are records the proposal promises. Judges ran on every run although `--judge` documents them as optional, and they score a rubric the Organization Science paper leaves out.

**Where it lives.** `orchestrator/llm_retry.py`, `orchestrator/panel_debriefing.py`, `roles/researcher_schemas.py`, `analysis/persist_artefacts.py`, `run_research_session.py`, `tests/test_lost_panel_answers.py`.


#### 50. **Review of runs A to D: corrections and changes.**

**What.** An independent read of the repository and run records on 31 Oct 2026 led to corrections in our documents and changes in the code. These are the changes that matter when reading runs A to D, which came before them and have not been rerun:

- Roles invited to build on an answer now see the answers already given in that exchange.
- The log records what each agent was shown (`shown_chars`).
- Retrieval queries keep the latest context.
- "Modular" no longer reaches the team's prompts. "Open questions" left the role prompt but stays in the inbox notice and the action template. The test reads the study's own list.
- Error handling is stricter: citations are checked one by one, finished exchanges are kept, a role stops after five failed calls in a row, `--rag` stops if it cannot run grounded, and a mistyped condition is refused.

**Why.** The method's selling point is that claims can be audited, so ours must survive an audit. Several of these also teach something: `docs/LEARNINGS.md` L17.

**Where it lives.** `docs/LEARNINGS.md`, `tests/test_panel_answers.py`, `tests/test_session_guards.py`, and the code named above. Saving after each phase came later (§52).

#### 52. **Each model call carries what it needs, once.**

**What.** Reading Google's token (a small piece of text, about three-quarters of a word) counts against the saved runs on 31 Oct 2026 showed two linked problems in how model calls were built. Runs A to D came before this change.

- Every call re-sent all the role's earlier prompts, though each prompt already held the debrief so far. By the end of run D a call carried about 300,000 input tokens, against about 20,000 of debrief transcript. Rebuilding each debrief call from the saved runs matches Google's counts within about 16%.
- The concurrent deliberation ran through `agent.py::_run_one_agent`, which named sessions (stored conversations re-sent to the model with each prompt) by agent, so `CEO_Concurrent` did not share `role_CEO`, against the design then in `docs/02_design_decisions.md` §4. Documents and debrief answers drew on the last 8,000 of about 26,000 characters of deliberation, the CEO's synthesis and, in the debrief, the role's own document. They did not draw on the earlier discussion or the role's own notes and drafts. Calls of 10,000 to 13,000 tokens as each debrief began confirm it. The session test missed it because it called the session resolver directly.

**Cost.** Run D's cost at list prices is about $67. Cloud Monitoring's call-size counts show 40 calls above 200,000 input tokens, which Google charges at its long-context rate ($4 and $18 per million, against $2 and $12). Runs A and C had none. Run A used 6.2M input and 0.22M output tokens, about $15.

**Decision.** Each model call has its own empty session, and its prompt carries what the agent needs: a role has the whole discussion and its own notes, draft and document, and the researcher has everything it observed (`orchestrator/role_memory.py`). What stays the same goes first, so caching (a lower price for text a provider recently processed) can discount it if the provider offers it. Also changed with this:

- Agents see whole passages, since showing them costs little once re-sending stops. `TMT_PASSAGE_CHARS` sets a limit for the planned test. This lifts the earlier limit of 1,200 characters.
- Debrief answers have no `citations` field, so the prompt now says to add citations after the answer. Before, roles copied the JSON (a plain-text format of named fields) from earlier replies in their session.
- The first speaker moves round the table each exchange, since later speakers now read earlier answers and no role should always frame them.
- Tokens per call go in `08_usage/` and `00_meta.json`, with list cost.
- Runs save after each phase and each debrief exchange, and `run_complete` says whether a run finished. `manifest.json` (a file recording what produced the run) is written to every run, with hashes (fingerprints of file contents) of what agents are told and without the cloud project or local paths.
- Retrieval runs on its own thread (a separate line of execution) with a timeout, so a hung call holds up one role only.
- The study's scenario brief reaches the team in the default mode.
- `analysis.replay_debrief --rag` replays a grounded run, with the same memory (earlier records copied into each prompt) as a full run. `analysis.dry_run` runs the whole pipeline on a stand-in model for free. `--max-actions-per-role` makes a short run.

**Checked.** 1,334 unit tests (small automatic checks of one part of the code); a dry run (a rehearsal with a stand-in for the model and no cost) through the real framework, with no call carrying earlier messages; a live debrief replay on run D's deliberation with retrieval; and a short live run through every phase, with no errors and 67 of its 68 citations a verbatim match to a passage that role retrieved (`example_runs/short_check/`, `docs/LEARNINGS.md` L15). We have not rerun the full scenarios. Roles now read each other's answers and keep more of the deliberation, so new runs should not be expected to match runs A to D, and the role-similarity results need repeating.

**Why it matters beyond cost.** In runs A to D, roles were asked what they thought and pushed back on during a deliberation most of which they could no longer see, and all six wrote their documents from the same text. This may add to L3 (narrated events) and L7 (similar roles) in `docs/LEARNINGS.md`. We have not tested how much.

**Where it lives.** `orchestrator/role_memory.py`, `orchestrator/usage_log.py`, `run_research_session.py::_build_default_runner`, `agent.py::_new_call_session_id`, `analysis/dry_run.py`, `tests/test_call_context.py`, `tests/test_call_sessions.py`.

### A5. Retrieval and grounding

#### 8. Use Google Vertex AI RAG Engine for the retrieval backend rather than a local RAG (sentence-transformers + FAISS / Chroma: tools for doing the search on your own computer).

**What.** The framework's RAG layer is built on Google's managed RAG service — `vertexai.rag` — rather than a local embedding-and-index stack (embeddings are lists of numbers standing for a text's meaning) of the kind the PI had previously used with CrewAI (other agent software, used in the pilot). One corpus per firm, named `<study_slug>__<company>`. Embeddings via `publishers/google/models/text-embedding-005`. Retrieval per LLM call goes over the network.

**Why.** Three converging reasons made this the lower-friction default for *this* framework, even though a local RAG would work fine for a 5-firm × ~5-doc corpus:

1. **Auth + project + billing already wired.** The framework's `--vertex` flag (`docs/02_design_decisions.md` §19) routes Gemini calls through Vertex AI. Adding `vertexai.rag` reuses the same `GOOGLE_GENAI_USE_VERTEXAI=true` + `GOOGLE_CLOUD_PROJECT` + `GOOGLE_CLOUD_LOCATION` + ADC (Google's standard sign-in method for programs) auth path. A sentence-transformers backend would have added a 500 MB+ embedding model on disk, a new chunking (cutting documents into passages) pipeline, an index file to manage, and a second backend to maintain alongside Method B's sentence-transformers usage (which embeds *prototype sentences*, not corpus chunks — different purpose, same library would have been confusing to co-maintain).
2. **Reproducibility shifts to SHA-pinning (fixing each file's SHA256 fingerprint in the run's record), not index-shipping.** A reviewer reproducing a run does NOT need our FAISS index file; they need (a) the per-doc SHA256s recorded in `manifest.rag_config.documents` and (b) the script that rebuilds the corpus (`python -m rag.corpus_build`). The framework already requires GCP (Google Cloud Platform) credentials for the Gemini judges in Phase 5; the RAG layer just lives on the same auth path. A local index file would mean either bloating git with binary blobs or trusting reviewers to rebuild from PI-supplied source documents anyway.
3. **The framework is not air-gap-oriented (built to run with no internet).** Every Phase 1 / 2 / 3 / 4 / 5 LLM call already goes to a hosted provider (Gemini / Claude / OpenAI / DeepSeek / Groq). The framework's deployment story is already "needs internet + at least one API key." Adding Vertex RAG Engine doesn't change that surface.

**What we give up.** Vendor lock-in to Google Cloud for the RAG path; ~100–300 ms per-retrieval network latency vs ~1 ms for local; ~$0.0001 per retrieval (small, but nonzero). A future port to a local backend (sentence-transformers + Chroma) is feasible — `rag.vertex_corpus` is the only Vertex-specific module; the rest of the layer (schemas, runtime, query builders, persistence) is backend-agnostic. If air-gapped operators ever need this framework, that port is the lowest-friction path.

**Alternative ruled out at the time, recorded for re-consideration.** Local sentence-transformers + Chroma / FAISS. Would have been the right call if the framework didn't already use Vertex for Gemini. The CrewAI precedent (which the PI raised) is valid; the deciding factor was infrastructure already in place, not a methodological preference for managed services.

#### 9. Structured `Citation` schema field, not inline `[ref:doc_id]` markers in prose.

**What.** Citations are an explicit Pydantic (a Python tool that checks fields against a schema) field on `AgentAction`, `StrategicArtefact`, and `PanelResponse`. Role agents populate `citations: List[Citation]` via schema-enforced structured output; the persistence layer reads the field and renders inline `[^cN]` Markdown (plain text with simple formatting marks) footnotes during output rendering. The LLM never emits raw markdown-footnote markers.

**Why.** Inline markers are unreliable — an LLM asked to "wrap citation markers around your claims" produces inconsistent results across providers, and the parser has to grep free-form text. The schema-field route uses the same `output_schema` enforcement the framework already trusts for `AgentAction.kind` and `StrategicArtefact.main_decisions`. A citation either makes it into the structured output or it doesn't; there's no parser ambiguity. Reuses the structured-output adapter (see `docs/02_design_decisions.md` §18.1) for the json_schema vs json_object split.

#### 10. Read-only `rag_corpus_loader` — never auto-create corpora at session start.

**What.** `studies.openness_maneuvering.rag_loader.load_corpus(company)` does NOT call `build_or_get_corpus`. It looks up the corpus by display name (`find_corpus`); returns `None` if the corpus doesn't exist. The framework treats `None` as "no RAG for this firm" and runs without retrieval with a clear log line.

**Why.** Auto-creating a corpus at session start would silently give the operator an *empty* vector store (the search store of embeddings) and a long simulation run that produces zero citations. The clean failure mode is the explicit log line directing them to `python -m rag.corpus_build --company <Company>`. Corpus creation is a one-time setup step that belongs in the build CLI (command-line interface: a program used by typing commands), not in every session-start path.

#### 11. Researcher (Observer / FieldNoter / Debriefer) does NOT retrieve.

**What.** Only the six TMT role agents call `vertex_corpus.retrieve` during a `--rag` run. The Observer / FieldNoter / Debriefer never receive a `rag_session`, never see retrieved snippets, and never get a "REFERENCE MATERIAL" prompt block.

**Why.** Invariants (rules that must always hold) I1–I3 in `docs/05_methodological_invariants.md` require the researcher shells (the agent's set-ups) to be blind to the study's research question and theoretical lens. If the researcher could retrieve from the firm's corpus, the retrieval query itself would be a back-door for analytical framing to leak into data collection: the LLM-researcher asking "what's the firm's stance on open weights?" would surface documents that prime its own observation. Keeping retrieval inside the panellists (who don't know the construct under study) preserves the asymmetry: the panel acts; the researcher observes. We added a new invariant I5 in §10.5 of the RAG plan formalising this: *retrieval queries are built from role + task + transcript only — never from RQ (research question) or lens*. Tested parametrically over study fixtures (prepared inputs that tests run on) in `tests/test_rag_persistence.py::TestInvariantI5NoQueryLeakAcrossStudies`.

#### 12. Pairing key for comparison includes the LLM provider.

**What.** The R6 (a numbered task in the retrieval work) comparison harness (a small program that runs the comparison) pairs runs by a 6-tuple key (a six-part label) — `(study_slug, study_version, company, industry_context, product_type, tmt_provider)`. Two runs pair iff every field matches except `rag_config.enabled`. A Gemini-Pro RAG run does NOT pair with a Claude no-RAG run; they go into separate buckets.

**Why.** The experimental design holds provider constant and varies only the RAG axis. Cross-provider differences are a separate, already-supported axis (`analysis/compare_runs.py` for the multi-LLM robustness story). Allowing cross-provider pairs would confound the RAG effect with the provider effect and quietly weaken the methodological claim.

#### 13. Persist full retrieved chunk text in the audit log, not a 200-char preview.

**What.** The retrieval log at `07_rag/retrieval_log.jsonl` persists each chunk's verbatim text (not a truncated preview).

**Why.** Quote verification — checking that a cited quote is a substring of the retrieved chunk for that doc — only works if the persisted log captures what the LLM actually saw. A 200-char preview meant quotes from the back half of a 1k-token chunk would always be flagged as unverified, indistinguishable from real fabrications. Storage cost is bounded (Vertex's default chunking is ~1k tokens ≈ ~4k chars per chunk; ~250 retrievals per run; ~1 MB per log = trivial). The methodological gain — honest fabrication detection — is worth the file-size hit.

**Correction.** The log holds the full passage; agents saw its first 1,200 characters. §52 later gave them the whole passage.

#### 14. Grounded claims lead the per-pair report; metrics follow.

**What.** Each `results/comparisons/<ts>/per_pair/<cell>.md` opens with the **grounded-claims extract** (per-role, every cited statement with phase tag + statement text + doc + verbatim quote + supports tag). Decision diff, citation density, corpus coverage, quote verification, and judging delta come after as supporting detail.

**Why.** The grounded-claims section is the direct evidence answering the PI's original methodological question — *"did the TMT actually use the retrieved documents?"* — in concrete form. The metrics tables tell a reviewer the shape of the answer; the grounded-claims section tells them the substance. Putting metrics first would make the report read like a routine A/B comparison; leading with claims makes it read like qualitative evidence with quantitative backing, which is what an ethnographic-tradition methods section actually needs.

#### 45. **Retrieval has its own region, and panel citations are parsed out of answers.**

**What.** `RAG_LOCATION` sets the retrieval region and falls back to `GOOGLE_CLOUD_LOCATION`, refusing `global`. `split_panel_reply` separates an answer from citations wrapped around it in JSON.

**Why.** Gemini 3.x needs `global`, and RAG Engine has no global endpoint (web address for requests), so grounded runs were blocked. In the first grounded run 45 of 54 debrief answers carried raw JSON, so 40 citations never reached the citation field. The database behind RAG Engine bills by tier for as long as a corpus exists, which the earlier cost note understated.

**Where it lives.** `rag/vertex_corpus.py`, `roles/researcher_schemas.py`, `orchestrator/panel_debriefing.py`, `tests/test_rag_location.py`.

### A6. Judging infrastructure

#### 25. **Surface judge failures with a captured traceback instead of swallowing the exception.** *(PR #71)*

**What.** When one of the construct judges fails during Phase 5, the failure now persists to `05_judging/<provider>_error.txt` with `repr(exc) + traceback.format_exc()`, lands in the bundle's new `ConstructJudgmentBundle.judge_errors: Dict[str, str]` field, and is surfaced in `aggregate.md` under a `**Failed judges (excluded from α + composite):**` line. Previously a bare `except Exception as exc: log.warning("... exc=%s", exc)` swallowed the exception entirely.

**Why.** The Meta-2032 run's OpenAI judge produced a silent failure: the log line `construct_judging.judge_failed provider=openai exc=` had an empty exception field (because `str(exc) == ""` for some LiteLLM (software that reaches many providers' models) exceptions). The bundle proceeded with `judges=2` and Krippendorff's α (a measure of agreement among coders) was computed on 2 raters — the weakest possible inter-rater statistic — without anyone noticing until the run finished 42 minutes later. Capturing `repr(exc)` (which always carries the exception class name) plus the full traceback makes post-mortem possible without re-running the LLM call.

**Methodological note.** `_coerce_assessment` failures (parse / validation / unexpected type — paths that already log at ERROR level) are also recorded as marker entries in `judge_errors` so the bundle is honest about *which* providers didn't produce a usable assessment, not just *whether* the call raised.

**Where it lives.** `orchestrator/construct_judging.py` (the failure capture + persistence policy), `roles/judge_schemas.py` (the new field), `analysis/persist_artefacts.py` (the aggregate.md render), `tests/test_construct_judging.py::TestFailedJudgeCapture` (8 regression tests including the empty-message-exception headline test).

#### 26. **Replay tool for re-running selected or all judges on a previously-completed run.** *(PR #72)*

**What.** New CLI: `python -m analysis.replay_judges --run-dir <path> [--providers <list>] [--rerun-all] [--allow-version-mismatch]`. Reads the run's persisted markdown artefacts, reconstructs the judge prompt, re-invokes only the specified providers, and re-runs the local aggregator. Locks the run's `study_version` (refuses to replay across a schema change without `--allow-version-mismatch`) so different cells' α statistics stay schema-comparable.

**Why.** Two failure modes the tool addresses: (a) a single judge fails silently in a 45-minute live run (the §25 scenario), and (b) the ensemble grows after the run — e.g. PR #73 added DeepSeek as a 4th judge, and historical runs need to be re-scored against the augmented ensemble without re-running the deliberation. Both used to require either accepting a degraded bundle or paying for a fresh 45-minute Phase-1–4 re-run.

**Companion policy change.** `ConstructJudgingPhase.persist()` now always writes `<provider>_assessment.json` and `aggregate.json` independent of the `--no-json` flag. The flag still governs burst-style JSON sub-files in other phase folders; judge JSONs are the *replay-enabling artefact* and must always land. Without this, a `--no-json` run (the openness-maneuvering 20-cell default) would be unrecoverable later because the aggregator needs typed `ConstructAssessment` objects to compute α and md is a render-not-source artefact.

**Recovery from pre-PR runs.** Runs persisted before this policy change have md-only assessments; targeted replay refuses (would silently drop the existing judges). `--rerun-all` re-scores every judge from scratch and produces a clean recovered bundle (cost ~$5 per run). The Meta-2032 v0.3 cell was recovered via this path.

**Methodological invariant added.** The judge prompt-input string assembled from md is *content-equivalent* to the typed-object render the original orchestrator produced, but not *byte-identical*. The α statistic remains comparable; what changes is which exact phrasing the judge sees in the section bookends. Acceptable for cross-cell α; not acceptable for byte-exact replication where the original prompt input was captured.

**Where it lives.** `analysis/replay_judges.py` (the CLI + library function), `orchestrator/construct_judging.py` (the always-persist-JSON policy), `tests/test_replay_judges.py` (23 regression tests covering prompt assembly, state discovery, version locking, replay-all + targeted paths, CLI argparse).

#### 27. **Add DeepSeek-R1 as a lineage-distinct 4th judge.** *(PR #73)*

**What.** The default judge ensemble in `providers.JUDGE_PROVIDERS` is now `("gemini_pro", "claude", "openai", "deepseek")` — DeepSeek lands LAST so historical per-cell Excel exports keep their column order (gemini / claude / openai) and append the new column at the right. The DeepSeek judge uses `deepseek/deepseek-reasoner` (R1 family alias — LiteLLM auto-routes to DeepSeek's current frontier, or newest and most capable, reasoner at call time), pinnable via env var (environment variable: a named setting outside the code) `TMT_JUDGE_DEEPSEEK_MODEL` for reproducibility snapshots. TMT-side DeepSeek default stays on `deepseek-chat-v4` (reasoner-mode CoT only earns its keep on long-form judge synthesis, not on Phase-1 / 2 / 4 structured-output JSON).

**Why.** The original three judges (Gemini Pro + Claude Opus + GPT-5.5-pro) share Western-aligned, English-corpus-dominant, RLHF-trained (reinforcement learning from human feedback: tuned using people's ratings of replies) lineage. Their disagreements are partly correlated by shared training-corpus quirks rather than genuine construct contestation — when all three agree, we can't tell whether they're agreeing because the construct is well-defined or because they share a Western-frame prior. DeepSeek-AI's R1 reasoner is the most lineage-distinct frontier model available with a working LiteLLM adapter — different corpus mix (Chinese tech literature heavy) and different RLHF philosophy. Adding it as the 4th judge: (a) narrows Krippendorff's α confidence interval by ~13% (N=4 vs N=3 per §20), and (b) surfaces genuine construct contestation (§23 claim 3) — when the Chinese-trained reasoner disagrees with the three Western judges, that disagreement carries more information than agreement-everyone-shared-priors does.

**Adapter readiness.** Zero new adapter code required. The per-provider adapter from §1 already covers DeepSeek's `json_object`-mode response_format quirk via `_LITELLM_JSON_OBJECT_PREFIXES` — the judge agent factory routes through `build_structured_agent` and the schema is injected as an instruction suffix. The §1 work paid forward to this PR.

**Where it lives.** `providers.py:122` (the 4-tuple), `providers.py:148` (`JUDGE_MODEL_OVERRIDES`), `tests/test_construct_judging.py::TestFourJudgeEnsemble` (6 regression tests: default ensemble + model override + env var + structured-output mode + factory build + aggregator handles N=4).

#### 30. **Judge-call resilience: per-judge timeout extension + transient-error (temporary-error) classifier covers connection-level disconnects + retry loop on the judge path.** *(PR #76)*

**What.** Three coordinated fixes addressing the OpenAI judge's reproducible `ServerDisconnectedError` failure at exactly 3:01 minutes on the Meta-2032 162K-char prompt:

1. New `providers.JUDGE_TIMEOUT_OVERRIDES` dict — defaults OpenAI + DeepSeek to 600s (10-min reasoning-model headroom) — with env-var override `TMT_JUDGE_<PROVIDER>_TIMEOUT_S`. The kwarg threads through `get_judge_model()` into the LiteLlm wrapper and from there to `litellm.acompletion`. Native Gemini bypasses LiteLLM so the kwarg doesn't apply there (Gemini call-site timeouts remain governed by `TMT_LLM_CALL_TIMEOUT_S` at the agent layer).

2. `orchestrator.llm_retry._TRANSIENT_RE` extended to match the actual Meta-2032 error patterns: `Server disconnected` / `ServerDisconnected` (aiohttp, web-request software: class name + human message), `ReadError` (httpx wrapper), `InternalServerError` (LiteLLM's wrapping class), `ConnectionError` and `connection (reset|refused|aborted)` (general connection failures). Existing categories (429 / 5xx error codes / rate-limit / overloaded / TimeoutError) preserved; word-boundary regex (written pattern for finding text) tightened to avoid spurious matches.

3. `_one_judge` in `orchestrator/construct_judging.py` wrapped in a local retry-with-backoff (waiting longer before each new attempt) loop reusing `is_transient_error` + `parse_retry_delay` from `llm_retry.py`. NOT wrapped in `safe_run` itself — that helper swallows the exception on exhaustion and would lose §25's audit trail. Up to MAX_RETRIES (5) attempts; non-transient errors short-circuit; final captured error text carries `transient={True|False} attempts=N/M` so the audit file makes the retry behaviour explicit.

**Why.** Diagnostic chain: GPT-5.5-pro is a reasoning model (it produces working-out text before replying); its thinking phase on a 162K-char prompt exceeds the default LiteLLM / HTTPX / aiohttp first-byte timeout (~180s); aiohttp interprets the silent connection-idle as `ServerDisconnectedError`; LiteLLM re-wraps it as `InternalServerError`. The error reproduced at exactly 3:01 across two replays, confirming a deterministic client-side timeout — NOT a server-side problem. Compounding problem: even if the framework *had* tried to retry, the classifier didn't include any of the error strings the actual exception emitted, so the retry would have refused to fire — these errors had to be added to `_TRANSIENT_RE` for `is_transient_error` to recognise them.

**What this PR does NOT fix.** The OpenAI Responses API has what appears to be a hard 3-minute synchronous timeout on the server side that the client-side `timeout=600` kwarg does not override (verified by the failed Meta-2032 v0.4 replay where OpenAI still died at 3:01 even with the new timeout setting). DeepSeek-R1, also a reasoning model, finishes the same prompt in ~40s — so this is an OpenAI-specific structural property, not a general reasoning-model issue. Switching the OpenAI judge to a non-reasoner model (`gpt-5.4` via Chat Completions) is the workaround captured in the §31 cross-reference; this PR's contribution is making the failure mode visible + retried + classifiable rather than eliminated.

**Where it lives.** `providers.py` (the timeout override + resolution function), `orchestrator/llm_retry.py` (the regex extension), `orchestrator/construct_judging.py` (the retry loop that later moved to §31), `tests/test_judge_resilience.py` (21 regression tests covering classifier extension, timeout resolution, retry-on-transient, retry exhaustion with captured audit text).

#### 31. **Consolidate live + replay judge paths onto a shared `safe_run_with_capture` helper.** *(PR #77)*

**What.** New `orchestrator.llm_retry.safe_run_with_capture(run_agent, agent, prompt, *, provider, max_retries)` returns `(raw_or_None, error_text_or_None)`. Sibling to the existing `safe_run`; differs only in that failures return the captured `repr(exc) + traceback.format_exc()` rather than swallowing them. Both `_one_judge` in `run_construct_judging` AND `replay_judges` now delegate to this helper. Identical retry-with-backoff semantics; identical on-disk audit-file shape (`<provider>_error.txt`) regardless of whether the failure happened in a live run or a replay.

**Why.** The Meta-2032 v0.4 `--rerun-all` replay surfaced a divergent-retry problem: PR-76 had added the retry loop only inside `_one_judge` (the *live*-judging path), but the *replay* tool's `replay_judges` function had its own call site that invoked the runner (the part that hands a prompt to an agent) bare — no retry, no transient classification, single-shot failure semantics. When the OpenAI judge hit its 3:01 failure during the replay, no retry fired, the bundle landed at 3 judges, and the very issue PR-76 was meant to fix went un-addressed on the replay path. Two call sites with divergent reliability is architectural debt that hides problems; consolidating onto one helper makes future judge-side resilience improvements land in both places by default.

**Methodological invariant added.** Replay and live runs now produce byte-identical `<provider>_error.txt` shapes — the only stable contract for downstream tooling that parses them. The error text follows the format: `<provider>: <repr(exc)>\ntransient=<bool>, attempts=<N>/<M>\n\n<traceback>`. Grep-friendly, parse-friendly, and stable across the two code paths.

**What this PR does NOT do.** Does not fix the OpenAI 3-min hard timeout itself (see §30). The retry now fires on the replay path, but every attempt hits the same 3-min cap, so the OpenAI judge will continue to fail on long prompts until the Chat-API switch (§30 follow-up). What changes is that the failure is now classified, retried, and diagnostic-captured uniformly.

**Where it lives.** `orchestrator/llm_retry.py` (the new helper), `orchestrator/construct_judging.py` (`_one_judge` delegates), `analysis/replay_judges.py` (replay loop delegates), `tests/test_safe_run_with_capture.py` (12 regression tests covering success paths, retry-on-transient with success / exhaustion / `max_retries` override, non-transient short-circuit, exception-not-raised invariant including the `CancelledError` exception, and error-text format contract).

#### 32. **Switch the OpenAI judge from GPT-5.5-pro (Responses API) to GPT-5.4 (Chat Completions API).**

**What.** `JUDGE_MODEL_OVERRIDES["openai"]` flips from `"openai/gpt-5.5-pro"` to `"openai/gpt-5.4"`. The `JUDGE_TIMEOUT_OVERRIDES["openai"]` entry (formerly 600s) is removed — gpt-5.4 on Chat Completions is fast enough on first-byte that the default LiteLLM / HTTPX timeout is appropriate. DeepSeek-R1 keeps its 600s timeout entry (reasoner-class; succeeded on the Meta-2032 162K-char prompt in ~40s with that headroom). Env-var override `TMT_JUDGE_OPENAI_MODEL=openai/gpt-5.5-pro` still works for the case where an operator needs the old reasoner-tier judge for an appendix robustness check.

**Why.** §30 and §31 hardened the framework against the GPT-5.5-pro `ServerDisconnectedError` failure mode (longer client-side timeout + transient classifier extension + retry-with-backoff on both live and replay paths), but the Meta-2032 v0.4 `--rerun-all` validation showed the underlying issue is structural: GPT-5.5-pro on the Responses API reproducibly fails at *exactly* 3:01 on a 162K-char prompt, regardless of the client-side timeout setting. DeepSeek-R1 — also a reasoner-class judge — finishes the same prompt in ~40s, confirming this is OpenAI-specific to the Responses API on long synchronous calls, not a general reasoning-model-on-long-prompt issue. The client-side fixes catch transient blips; this is a deterministic server-side cap.

The Chat Completions API does not have this cap. GPT-5.4 on Chat Completions is the workhorse model the framework already uses TMT-side, well-tested on this study's prompt patterns. Switching the OpenAI judge to it avoids the 3-min ceiling structurally — no more silent failures on long prompts, no more reliance on client-side timeout extension that doesn't actually take effect on the server side.

**Methodological cost.** GPT-5.4 is not reasoner-class. The STAGE 1 qualitative summary may be slightly less reflective than GPT-5.5-pro's would be — less time spent thinking before scoring, less explicit chain-of-thought before the structured output. Three of four judges in the ensemble remain reasoner-class:

| Judge | Reasoner | Lineage |
|---|---|---|
| Claude Opus 4.7 | ✅ extended thinking | Western (Anthropic) |
| Gemini 3.1 Pro Preview | ✅ extended thinking | Western (Google) |
| DeepSeek-R1 | ✅ explicit CoT | Chinese (DeepSeek-AI) |
| GPT-5.4 | ❌ chat-only | Western (OpenAI) |

The lineage-distinct claim (§27) is carried by DeepSeek; the long-form synthesis depth is carried by Claude + Gemini. Construct judging at v0.4 (§29) is rubric application against verbatim evidence quotes from the run's md — not novel reasoning — and GPT-5.4 is well-suited to that. The EVIDENCE QUOTING CONTRACT already constrains the judge to ground every score in textual evidence; the upside reasoning depth could provide is bounded by that contract.

**Alternatives considered + ruled out.**

* **Pin GPT-5.5-pro and accept it dies on long prompts.** Ruled out — the 162K-char prompt is the v0.4 minimum (six artefacts + deliberation + observation + debriefing rendered at full size), so the OpenAI judge would be permanently broken on every realistic study cell. A 3-of-4-judge ensemble for every Meta / OpenAI / Alphabet / Anthropic / HuggingFace cell would undermine the cross-vendor construct-validity claim.
* **Move to OpenAI's background mode for the Responses API.** Possible but expensive — requires polling a response ID for completion, different API surface than LiteLLM's current Responses-API integration, methodologically gains nothing over Chat Completions on the rubric-application task. Parked as a future option if reviewers specifically request gpt-5.5-pro evidence.
* **Truncate the judge prompt.** Methodologically incoherent — the judge must see the full deliberation, artefacts, observation, and debriefing to score the rubric. Truncation would bias the score in ways indistinguishable from the underlying construct.

**Cost impact.** GPT-5.4 is roughly 1/3 the per-token price of gpt-5.5-pro. Per-cell judging cost drops from ~$8–10 (v0.4 with all 4 reasoner-class judges) to ~$6–8. Incidental savings; the methodological argument carries the decision.

**Reproducibility note.** Future v0.4 runs against the OpenAI judge will record `default_models["judge_openai"] = "openai/gpt-5.4"` in the per-run manifest. The Meta-2032 v0.4 recovered bundle pre-dates this change — its OpenAI failure stays as documented in `openai_error.txt`. A fresh smoke run (a quick first run to confirm nothing breaks) under this configuration will be the first validation that the OpenAI judge actually lands on the v0.4 prompt size.

**Where it lives.** `providers.py:175` (the `JUDGE_MODEL_OVERRIDES["openai"]` flip + the `JUDGE_TIMEOUT_OVERRIDES["openai"]` removal); `tests/test_judge_resilience.py::TestJudgeTimeoutResolution` (timeout-default test reversed: openai now asserts None, env-var override still tested); `tests/test_provenance_and_llm_selector.py` (three docstring, or in-code explanation, + assertion updates to reflect the gpt-5.4 default + the manifest snapshot).

### A7. Repository and working practice

#### 7. Refuse to use API keys pasted into chat.

**What.** API keys never go in chat. A key that appears in a transcript is not used and is replaced at the provider, and work reads keys from a local secrets file kept out of the repository.

#### 16. Stack RAG-feature work as small, independently-reviewable PRs.

**What.** RAG capability landed as a stack of small PRs, each reviewable alone and each leaving runs without retrieval unchanged.

#### 34. **Study-specific documentation lives inside the study; framework docs stay in `docs/`. Commit a developer-agnostic `CLAUDE.md`.**

**What.** Three documents specific to the openness study move from `docs/` into the study's own folder, with their history kept by `git mv`:

| Old path (as cited in earlier entries) | New path |
|---|---|
| `docs/04_study_anatomy.md` | `studies/openness_maneuvering/docs/01_study_anatomy.md` |
| `docs/09_openness_subdimension_measurement_plan.md` | `studies/openness_maneuvering/docs/02_subdimension_measurement_plan.md` |
| `docs/12_frontier_sweep_plan.md` | `studies/openness_maneuvering/docs/03_frontier_sweep_plan.md` |

Earlier entries (§6, §19) keep their original paths, because entries are not rewritten in place; this table resolves them. The researcher agent's design document, previously an untracked Word file, is added as framework documentation at `docs/14_virtual_ethnography_field_protocol.md`.

A committed `CLAUDE.md` now carries developer-agnostic guidance: the framework/study boundary, methodological invariants, commands, conventions, and rules for secrets and data. Machine-specific notes, including links to other projects and absolute paths, move to `CLAUDE.local.md`, which is gitignored (deliberately left out of the shared repository).

**Why.**

1. **The framework claims that a study lives outside it, and the documentation should reflect that.** A new study keeps its own documents under `studies/<slug>/docs/`, just as it keeps its own configuration under `studies/<slug>/`.
2. **Anyone developing in this repository should get the same project guidance** without inheriting one person's local setup.

**Where it lives.**

* `studies/openness_maneuvering/docs/` (with a README index).
* `docs/README.md` (updated reading order).
* `docs/14_virtual_ethnography_field_protocol.md`.
* `CLAUDE.md`.
* `.gitignore` (adds `CLAUDE.local.md` and `.idea/`).

#### 41. **Organise this log into framework and study parts. Entry numbers and text stay as they were.**

**What.** Entries are grouped into Part A (framework) and Part B (one part per study), with topic sections and an index at the top. Each entry was moved unchanged except for its heading level, and `tests/test_decisions_log.py` keeps the numbering, the sections and the index in step. The numbers are permanent because code, tests and documents cite them, so entries no longer appear in number order.

**Why.** Framework and study decisions were interleaved by date, which made a decision hard to find. The split follows the boundary in §34: a study should be separable from the framework.

**Where it lives.** `DECISIONS.md`, `tests/test_decisions_log.py`, `CLAUDE.md`.

### A8. Testing from saved runs

#### 39. **Test debrief behaviour from saved runs before paying for a full run.**

**What.** `analysis/researcher_turn_test.py` gives the debrief researcher a saved moment from a finished run and asks for its next question, as many times as requested. It calls only the researcher, and each attempt has its own empty session. `analysis/saved_run.py` loads the run folder and refuses a run from another study version unless told otherwise.

**Why.** Full runs take about 40 minutes and most recent changes affected only the researcher. Repeating one turn gives a rate at a moment that stays fixed, whereas two full runs differ in everything, so a change in behaviour cannot be attributed to the prompt.

**What it cannot show.** How a whole debrief unfolds, or anything about the deliberation. Saved runs do not keep the researcher's live field notes, so its memory differs from a full run. Results are checks on behaviour, not evidence for a paper.

**Where it lives.** `analysis/saved_run.py`, `analysis/researcher_turn_test.py`, `tests/test_researcher_turn_test.py`, `docs/REPRODUCE.md`.

#### 40. **Replay the debrief on a saved deliberation to compare debriefs on identical input.**

**What.** `analysis/replay_debrief.py` reruns Phase 4 from a finished run and writes a comparison with the saved debrief. Agents receive the same memory as in a full run, built from the saved files (§52). The source run is never changed. A grounded run must be replayed with `--rag`, which retrieves from the firm's corpus.

**Why.** The debrief takes most of a run's time, and between full runs the deliberation changes as well, so a difference between two debriefs cannot be attributed to the debrief. With the deliberation fixed, it can. This also suits the planned comparison of debrief protocols on identical scenarios.

**What it cannot show.** Anything about the deliberation or documents. Runs saved before field notes were kept give the researcher none. A replay must be labelled as one if it is ever reported.

**Where it lives.** `analysis/replay_debrief.py`, `tests/test_replay_debrief.py`, `docs/REPRODUCE.md`.

#### 46. **Trace where a run's words came from, and test whether roles differ, before coding.**

**What.** `analysis/provenance.py` makes no model calls. It credits debrief phrases to their earliest source, lists new terms and unsupported claims about the past, flags questions that repeat a prompt, and checks citations. `analysis/panel_probe.py` compares different roles with a role's own second sample, with isolated answers and with mixed models. `analysis/semantic_similarity.py` repeats that comparison by meaning and topic. `docs/LEARNINGS.md` records what these and the runs taught us.

**Why.** Language models complete what they are given, so a passage can read like a finding when a prompt, a question or another agent supplied it. Shared models and conversation mean role labels do not make agreement independent. Word matching only flags passages to read.

**Where it lives.** `analysis/provenance.py`, `analysis/panel_probe.py`, `docs/LEARNINGS.md`, `example_runs/`, `tests/test_provenance.py`.

---

## Part B: Study `openness_maneuvering`

Decisions about this study's research design, construct, measurement and paper.

### B1. Research design and corpus

#### 15. Five-firm corpus set; PI supplies source documents.

**What.** The framework's `rag_corpora/` layout commits a fixed per-firm folder structure for OpenAI, Meta, Alphabet (Google), Anthropic, and HuggingFace — picked to span closed-research (OpenAI, Anthropic, Alphabet) and open-weight (Meta, HuggingFace) postures so the openness construct has within-sample variance. The actual source documents are gitignored — chosen by the PI, never in the repo. The corpus is restricted to **two document classes** by PI decision (2026-05-24): (a) annual reports / SEC filings / annual letters, and (b) podcast or long-form interview transcripts. Founder essays, blog posts, and press releases are excluded by design — they are PR-style narration and would amplify rather than counter the recall-bias concern.

**Why.** Documents are firm-specific reference material, often under publisher copyright, and they're not part of the framework's code. Reproducibility comes from the per-doc SHA256s in `manifest.rag_config.documents` — a reviewer with the same source files can verify the corpus state matches the manifest by re-uploading via `python -m rag.corpus_build`. Committing source docs would (a) blow up the repo size, (b) create a copyright / licensing surface, and (c) prevent the PI from refining the corpus mid-study without a git churn.

#### 19. **Reduce the planned cross-vendor sweep from 240 cells to 20 cells, all on Vertex Gemini.**

**What.** The frontier-sweep plan in `docs/12_frontier_sweep_plan.md` originally envisaged 5 firms × 4 cells × 2 conditions × 6 providers = 240 runs to establish cross-vendor construct validity at the TMT-deliberation level. PI decision 2026-05-24: scope the actual study run to the 20-cell core (5 firms × 4 cells × 1 condition), all driven by Gemini 3.1 Pro Preview via Vertex. The 3-vendor judge ensemble (Opus 4.7 + GPT-5.5-pro + Gemini 3.1 Pro Preview) is retained for Phase 5 — cross-vendor construct validity is still claimed at the JUDGE layer.

**Why.** Three converging pragmatic reasons:
1. **Vertex preview-tier (early-release) quota is the binding constraint.** Running cells in parallel against the same Gemini account exceeds the ~100k input-TPM (tokens per minute) ceiling — measured directly during the Meta-2032 cell post-mortem. Parallel cells produce equal wall-clock to sequential cells; no speedup.
2. **EDU credits (education credits on Google's cloud) cover Gemini, not the other vendors.** Six-vendor TMT means real cash for Claude + GPT + DeepSeek + Groq across 40 cells each. 20 cells on Gemini = $0 cash spend after EDU offset; 240 cells across 6 vendors = ~$285 cash.
3. **The cross-vendor robustness claim doesn't need cross-vendor TMT.** The 3-vendor judge ensemble already produces a Krippendorff's α across vendors. Adding cross-vendor TMT would add a second independent axis of variance (TMT vendor × judge vendor) but the design doesn't need both, because validity then rested on the judge ensemble.

**What we give up.** The "TMT method is portable across LLM vendors" claim is downgraded from "we ran the full design on 6 vendors" to "the framework supports 6 vendors and was smoke-tested on each." The full cross-vendor sweep is preserved as a follow-up paper if the per-firm Gemini results warrant scaling.

**Where it lives.** `docs/12_frontier_sweep_plan.md` (deferred design; path moved by §34). Scoring was later made optional and not part of the method (§54).

#### 21. **Defer the Wayback-Machine longitudinal corpus to a future paper.**

**What.** A proposed fourth field-data channel — scraping `web.archive.org` snapshots of each firm's AI blog + research + responsible-AI strategy pages from 2015 → present, scoring against the same 7-dim rubric — was sketched outside this repository with a 3-task implementation plan, per-firm URL allowlists and 7 documented openness-shift test cases. **Explicitly scoped out of the current paper.**

**Why.** A longitudinal channel from real corporate communications could help a later study, but it would expand the current scope. Capture, don't build now.

**What's preserved.** The implementation sketch (3 PRs, ~450 LOC (lines of code) + ~$60 of LLM cost), per-firm URL allowlists, 7 publicly-documented openness-shift moments the method must recover as construct-validity test cases (GPT-2 staged release; GPT-4 closing; LLaMA 1/2 trajectory; Transformer publication; Gemma launch; Anthropic stable pattern), and the four methodological pitfalls (bias from PR shaping, coverage gaps, page restructuring, robots.txt restrictions). All kept outside this repository for any later study.

#### 22. **Scope the RAG layer out of the executed paper. Keep the infrastructure as a tested, documented capability.**

**What.** The retrieval-augmented configuration built across §§8–16 — per-firm Vertex AI RAG corpus, `--rag` CLI flag, structured `Citation` field on the role-agent outputs, `compare_rag` harness — is **deliberately not used** in the executed 20-cell run for the current paper. The framework still supports `--rag` and the per-firm corpus infrastructure stays in place; the production runs use no retrieval.

**Why.** Three substantive reasons, in priority order:

1. **The construct-validation aim doesn't require grounding.** The paper validates that synthetic TMT deliberations yield well-formed construct scores under a cross-vendor judge ensemble. Whether the simulation matches any specific firm's public posture is a *separate* research question that grounding is designed for, but that the current paper does not aim to answer. The judge-ensemble Krippendorff's α across vendors is the construct-validity claim; nothing about that claim depends on retrieval.

2. **The five chosen firms are saturated in LLM training data.** OpenAI, Meta, Alphabet, Anthropic, and HuggingFace are among the most heavily-represented firms in any frontier model's pre-training corpus — SEC EDGAR filings (a major LLM training source), long-form podcast transcripts (Lex Fridman, Acquired, Stratechery, Hard Fork, Dwarkesh), founder essays, blog posts, conference talks. Retrieval from those same sources is unlikely to surface information the model does not already encode; it would at best re-anchor attention to documents the model already has internalised.

3. **Annual reports are shaped by PR.** Grounding the simulation in firm-authored disclosures risks importing the firms' preferred framing rather than counter-balancing the LLM's prior. The PR problem was already noted as a methodological pitfall when scoping the Wayback corpus idea (§21); it applies equally to annual-report grounding. The honest reading is that RAG against PR-shaped sources amplifies firm narration rather than correcting LLM bias.

**What the design rested on instead.** The 3-vendor judge ensemble (Opus 4.7 + GPT-5.5-pro + Gemini 3.1 Pro Preview) scoring against the 7-dimensional rubric (now v0.3 of the study config, with the inductively-restricted RQ) is the construct-validity backbone. Krippendorff's α across vendors is the cross-vendor robustness claim. Neither requires RAG.

**What we give up.** The "this synthetic deliberation aligns with firm X's actual public posture" claim is not made. The paper makes a narrower, more honest claim — "the method produces well-formed construct scores across vendors, on synthetic TMTs conditioned on the LLM's pre-training prior" — without the per-firm-grounding extension.

**What's preserved.** The full RAG infrastructure (§§8–16) stays in the codebase as a tested, documented capability. Three natural future deployments:

* **The Wayback longitudinal-corpus future paper (§21).** RAG over historical communications is the right tool there, and the per-firm corpus loader machinery is half of what that paper needs.
* **A robustness check.** Cost is small (~$15 of LLM spend per cell × 1–2 cells) and the infrastructure makes it cheap to run.
* **Studies on less-LLM-saturated firms** — pre-IPO startups, non-Western firms, or industries with thin public coverage. There the LLM's prior is genuinely weaker and RAG would add real information rather than re-anchoring.

**What this means for the PI right now.** Do not collect annual reports / podcast transcripts for the current paper. The manual effort is real (substantial PI hours per firm × 5 firms), and the marginal methodological gain is negative once the PR problem is acknowledged. If a robustness check becomes necessary, collection can be done in 1–2 days for 1–2 firms.

**Superseded 2026-10-24 by §33.** RAG is back in scope: per-firm grounding with traceable citations is now part of the method, and a citation-accuracy evaluation runs before any production simulation. The concerns recorded above (training-data saturation, PR shaping) still apply and are addressed in §33 rather than dismissed.

#### 33. **Bring the RAG layer back into scope: per-firm grounding with traceable citations is part of the method. Supersedes §22.**

**What.** Per-firm retrieval returns as a core part of the framework for the next runs and for the Organization Science special-issue proposal (v7, 24 Oct 2026, where Grounding is now a core module, not an optional one). The six TMT role agents retrieve from their firm's corpus in Phase 1 (deliberation), Phase 2 (artefacts) and Phase 4 (debrief answers). They cite and quote each passage they use, so any generated statement in the deliberation, the strategy documents or the debrief can be traced back to a named source document and a verbatim passage. The researcher agents (Observer, FieldNoter, Debriefer) still do not retrieve; invariants I1–I3 and I5 are unchanged. The machinery already exists (§§8–16, PRs R1–R6): the `Citation` schema, inline footnotes, the `07_rag/` audit folder, substring quote verification, and the `compare_rag` harness.

**Why.**

1. **Traceability is central to the method.** The ethnography-in-silico claim is that researchers can inspect how agents reasoned and on what evidence. A citation that resolves to a document and a verbatim quote makes that evidence auditable; an uncited claim rests on the model's training data, which cannot be inspected.
2. **Test the saturation assumption instead of relying on it.** §22 (and an interim decision on 20 Oct 2026 to run without a corpus) assumed the five firms' public material is already in the models' training data. Grounded runs, compared with ungrounded runs through `compare_rag`, let us measure how much retrieval changes what agents say, instead of assuming it changes nothing.
3. **§22's concerns are handled, not ignored.** For PR shaping: the corpus mixes source types (long-form interviews, earnings calls, published case studies), every document carries its source type, and citations can be analysed by type. For saturation: the grounded vs ungrounded comparison above.

**Evaluate before simulating.** No production runs until a citation-accuracy evaluation on a small set of grounded runs (at least one cell per firm) has been completed and reviewed:

* **Citation fidelity**: every quoted passage appears verbatim in the cited document (automated; quote drift is flagged in `07_rag/` and by `compare_rag`).
* **Attribution accuracy**: on a hand-coded sample, does the cited passage actually support the claim it is attached to?
* **Retrieval relevance**: on a sample of retrieved passages, are they relevant to the role's question at that turn?
* **Coverage**: what share of firm-specific factual claims carry a citation; uncited firm-specific claims are listed for review.
* **Out-of-corpus claims**: firm-specific claims that no corpus document supports.

Acceptance thresholds are to be agreed by the authors before production runs, and the results are reported in the replication package alongside the runs.

**Corpus.** Start from the pilot corpus: 127 documents (73 long-form interview transcripts, 49 earnings-call transcripts, 5 published case studies; Alphabet 20, Anthropic 9, Hugging Face 16, Meta 45, OpenAI 37). This widens the document classes fixed in §15 and `docs/10_rag_repo_plan.md` (annual reports/filings and interviews) to include earnings-call transcripts and published case studies. Anthropic's corpus is thin (9 documents) and should be extended before production runs. *Audit note (29 Oct 2026):* the pilot's files show that its vector store held 155 documents in one store shared by all five firms. The extra documents are 17 OpenAI "About" pages, 8 Meta company-news items and three further interviews. Serper web search and page scraping were also available, and agents used them in some runs. The 127-document set above is the starting point for R7; whether to add the other 28 is open. Following the data rules in `CLAUDE.md`, source documents live under `~/research-data/`, not in OneDrive or git; `rag.corpus_build` is pointed at that location, or `rag_corpora/<Firm>/` is a local link to it.

**What changes downstream.**

* New tasks R7 (build the corpora) and R8 (citation-accuracy evaluation) come before the production run.
* `docs/10_rag_repo_plan.md`: carries a status note that retrieval is in scope for the openness study.
* Production runs for the openness study use `--rag`.

**Where it lives.** `rag/` (unchanged), `analysis/compare_rag.py`, `rag/schemas.py` (citation audit), `docs/10_rag_repo_plan.md` (status note).

#### 43. **The study's research question matches the proposal: "How do firms maneuver openness to create and capture value?"**

**What.** `research_question` changes from "How do firms in volatile innovation ecosystems dynamically maneuver their degree of openness over time?", and the study moves to version 0.5.0.

**Why.** The authors decided on 20 Oct 2026 to keep the outcome clause in the proposal, and that the code should match if runs are to match. Runs were asking a different question from the paper. This reverses the v0.3 reason for dropping the clause, that it pre-names a purpose. The risk stays small because only the researcher sees the question and the panel never does. Other purposes, such as safety or legitimacy, remain findings the debrief can record.

**Where it lives.** `studies/openness_maneuvering/__init__.py`, `tests/test_study_config.py`, `tests/test_subdimension_schemas.py`.

#### 47. **Environmental conditions are a future study, and are not taken from the pilot.**

**What.** No trigger or event feature is built now. The planned "scenario events" item leaves P1 and becomes a future study adding a third dimension to context and task. Conditions could come from observed phenomena, existing theories or a mix, including ones existing theories do not explain. The pilot's 127 documents stay as run; a larger corpus would be a new version.

**Why.** Prototype runs showed agents may not explore the problem a study cares about, so researchers must specify it and build it into the firm's environment. Taking conditions from our own pilot would be circular.

**Where it lives.** `ROADMAP.md`, `docs/LEARNINGS.md`.

#### 48. **Test the method's risks thoroughly before collecting the study's data.**

**What.** Main data collection waits until the tests in `ROADMAP.md` have run and been reported, with passes agreed in advance. They cover repeated runs, models mixed from the first message, consensus wording removed, independent first drafts, coded positions and pushback, problem space, grounding, recall and framing.

**Why.** Prototype runs raised these risks from few runs. Teams were similar in meaning, dissent words were nearly absent, and our prompts ask for consensus. The mixed-model test covered only the debrief, because every role remembered a deliberation written on Gemini. Collecting data first could build a study on artifacts of the prompts.

**Where it lives.** `ROADMAP.md`, `docs/LEARNINGS.md` (L16), `analysis/role_statistics.py`.

#### 53. **Pose the study's problem in the decision task, in neutral words.**

**What.** Open release did not arise in the three neutral runs, whose task asks only what to develop and bring to market next. The authors' plan is to pose the problem in the decision task, without naming the constructs, and to test whether teams engage it before collecting data (§48). The conditions in §47 remain a later study. To be settled by Stage 2.

**Why.** A study of openness has to reach openness without telling agents the answer it hopes to find.

#### 49. **Publish what lets reviewers repeat and compare runs, without the source documents.**

**What.** `example_runs/` gains run D with source text removed (`analysis/redact_run.py`) and the prompts each run used. `docs/REPRODUCE.md` gains a guide to repeating the runs and comparing measures. New runs record their code commit. Source documents can be shared privately on request, through the editors, for review only and as copyright permits.

**Why.** The public repository is a single commit, so earlier prompt versions were otherwise out of reach. Reviewers need to verify, and source documents may be under copyright, so they stay out of git and out of the published records.

**Where it lives.** `analysis/redact_run.py`, `example_runs/`, `docs/REPRODUCE.md`, `run_research_session.py`.

### B2. Construct and measurement

#### 2. Decompose the openness rubric into measurable sub-dimensions.

**What.** The five-dimensional rubric (component disclosure, process openness, boundary permeability, ecosystem orchestration, value capture posture) is too coarse — each dimension is composite. I decided to add a sub-dimensional measurement layer underneath the LLM-judge ensemble, with each parent dimension broken into 4–5 sub-constructs.

**Why.** Krippendorff's α = −0.04 on the first live judge run signalled that the three LLM judges were collapsing distinct latent sub-constructs into one Likert score (a numbered rating) with different implicit weights — that's where the inter-judge disagreement was coming from, not from genuine construct ambiguity. Decomposing into sub-constructs grounded in the rubric's cited authors (Henkel 2006, Chesbrough 2003, Teece 2007, Jacobides/Cennamo/Gawer 2018) makes the construct auditable at the level where it actually varies.

#### 4. Triangulation, not replacement.

**What.** The new text-grounded scorer (Method A — anchored dictionary) runs *alongside* the LLM-judge ensemble, not instead of it.

**Why.** Cost-driven replacement of the judges was explicitly ruled out. The judge ensemble is the cross-vendor construct-validity statement — Krippendorff's α across Gemini + Claude + OpenAI tells you something the text scorer cannot. The text scorer is the *transparent, reproducible* statement — every score traces to an evidence sentence and a published lexicon. Running both produces convergent-validity numbers across both axes; that triple (LLM-vendor diversity + text-grounded reproducibility + convergence) is methodologically stronger than any one of them alone.

#### 6. Publish the methodology plan alongside the lexicon.

**What.** The full sub-dimensional measurement plan is committed to the repo at `docs/09_openness_subdimension_measurement_plan.md`, alongside the lexicon (`studies/openness_maneuvering/subdimension_lexicon.py`) and the scorer (`analysis/text_measures/dictionary.py`).

**Why.** A construct-validity layer is only as auditable as the documentation around it. The lexicon's regexes are the proximate citable artefact, but reviewers need the plan to understand which sub-dimensions are *intentionally* measurable by Method A vs deferred to Method B (embedding) or Method G (BERTopic), and which methodological commitments the dictionary scorer does or does not make. Withholding the plan would force every reader to reverse-engineer those commitments from the code. The plan stays a living document — it is versioned with the rest of the repo, and material changes follow the same review path as code.

#### 20. **Openness rubric v0.2 — split `boundary_permeability` into inbound/outbound + add `temporal_openness_maneuvering`** (7 dimensions, was 5).

**What.** The construct-judge rubric in `studies/openness_maneuvering/__init__.py` now declares seven dimensions: `component_disclosure`, `process_openness`, `boundary_permeability_inbound`, `boundary_permeability_outbound`, `ecosystem_orchestration`, `value_capture_posture`, `temporal_openness_maneuvering`. Study version bumped 0.1.0 → 0.2.0 (recorded in per-run manifests for reproducibility).

**Why.** Two methodological gaps in v0.1:
1. **The RQ literally names `maneuvering` as the construct, but v0.1 scored only static posture.** No dimension captured the firm's reasoning about WHEN to open or close — phased rollouts, conditional triggers, reversibility, sequencing across components. The new `temporal_openness_maneuvering` dimension is anchored on Henkel 2006 (dynamic selective revealing), Alexy/Henkel/Wallin 2013, and Lakhani/Tushman 2012. It scores the *move*, not the posture.
2. **v0.1 `boundary_permeability` was a single axis that conflated two flows firms almost always treat asymmetrically.** A firm may publish heavily outbound while restricting inbound talent flow, or vice versa. The Dahlander & Gann 2010 taxonomy is the standard split. The four v0.1 sub-dimensions (publication intensity, talent flow, public presence, NDA/IP enforcement) were all outbound-flavoured anyway — the split surfaces the inbound side, which the rubric was previously blind to.

Sub-dimensional lexicon (Method A) bumped to 26 sub-dimensions (was 21); two new inbound (`external_hiring`, `external_idea_absorption`) and three new temporal (`phased_rollout_language`, `conditional_triggers`, `reversibility`).

**Why now, not "add more judges".** The PI asked whether to add more judges OR more dimensions. Three judges from three distinct corporate-research lineages already make the cross-vendor claim defensible; the marginal value of a 4th judge is small (~13% tighter CI, or confidence interval, on α). Adding the **right** dimensions strengthens construct validity directly — it closes a known gap between the RQ ("maneuvering") and the measurement (static posture). Marginal cost ~$0.20/cell.

**Where it lives.** `studies/openness_maneuvering/__init__.py` (rubric), `studies/openness_maneuvering/subdimension_lexicon.py` (lexicon), `analysis/text_measures/dictionary.py` (`DIMENSIONS_ORDER`), `tests/test_construct_judging.py` + `tests/test_subdimension_lexicon.py`.

#### 29. **Migrate construct scoring from 7-dimension Likert to 26-sub-dimension 0–100 percent with Likert back-bin and mandatory evidence quoting.** *(PR #75, study v0.3.0 → v0.4.0)*

**What.** Phase-5 judging at v0.4 produces, per judge:

* 26 `SubDimensionAssessment` entries (one per sub-dim in `OPENNESS_SUBDIMENSION_LEXICON`), each carrying `score_pct ∈ [0, 100]`, `likert_back_binned ∈ [1, 7]` derived via fixed anchor thresholds at 14.5 / 28.5 / 42.5 / 56.5 / 70.5 / 85.5, a `qualitative_anchor` from {near-absent, minimal, partial, moderate, substantial, comprehensive, exemplary}, 3–5 sentences of reasoning, and ≥2 `EvidenceQuote` entries when `score_pct > 14` (≤300 chars each, sourced exclusively from the run's persisted markdown via the `source_file` attribution).
* 7 parent-dimension `DimensionAssessment` entries as a rollup (mean of children's `likert_back_binned`, rounded), preserved for v0.3 back-compat and reviewer-compatible reporting.

Krippendorff's α is computed at both granularities — 26 per-sub-dim values plus 7 per-parent rollup values plus the overall α. The aggregator's `per_sub_dimension_means_pct` / `per_sub_dimension_means_likert` / `per_sub_dimension_alpha` fields surface the finer-grained view; the `aggregate.md` renders both tables. v0.3 fixtures continue to validate cleanly — `sub_dimension_assessments` defaults to `[]` and the v0.3 path through aggregator + persistence is preserved unchanged.

**Why percent over Likert.** User's argument: openness is a continuous construct between fully closed (0%) and fully open (100%); the continuum is hard to visualise on a 7-point ordinal scale, and Likert hides legitimate gradations between adjacent buckets. Keeping the Likert back-bin lets the analysis pipeline report either scale — percent for the continuous-construct story, Likert for direct comparison against the field's standard convention.

**Why sub-dimensional.** The 7-parent Likert was too coarse to expose where the construct contests. The lexicon's 26 sub-dimensions are literature-grounded (Henkel 2006 / Chesbrough 2003 / Teece 2007 / Jacobides et al. 2018 / Dahlander & Gann 2010 / Alexy-Henkel-Wallin 2013), and per-sub-dim α surfaces exactly where the judges disagree on what counts as the construct — directly supporting §23 claim 3 (construct contestation as data).

**Why mandatory ≥2 evidence quotes from run md.** The auditability claim depends on every positive score being resolvable to specific text in the persisted artefacts. Two quotes is the minimum that demonstrates the score isn't anchored on a single passage; sourcing from the run's md (with substring verification, see below) prevents the judge from drawing on training-time priors about the firm rather than the deliberation actually observed. Near-absent scores (≤14%) may carry 1 demonstrating-the-absence quote or 0 with explicit "no evidence found" reasoning — the absence is itself a finding.

**Why post-hoc substring verification.** Every `EvidenceQuote.quote` is checked against its `source_file` content (whitespace-normalised on both sides; path-traversal guarded). Failures land in `05_judging/<provider>_quote_audit.md` and the bundle's `quote_verification_summary` records per-judge fail rates. Failed quotes are SURFACED, not auto-discarded — a quote that fails the substring check may still be useful evidence (the judge may have normalised em-dashes or dropped a trailing word), and surfacing them lets the PI's qualitative analysis adjudicate. The audit is the trust-but-verify layer on the "judge sources from md only" claim.

**Version lock.** `studies/openness_maneuvering/STUDY.version` bumped 0.3.0 → 0.4.0. The replay tool (§26) refuses to replay a v0.3-captured run under v0.4 code (or vice versa) without `--allow-version-mismatch` — this version bump is what activates that guard for new runs and protects cross-cell α statistics from silent schema pollution.

**Cost impact.** Judge output volume ~10× the v0.3 shape (26 sub-dim × structured scoring + 2 quotes + reasoning vs. 7 parent-dim Likert). Per-cell judging cost: ~$4 (v0.3 baseline, 2 judges scoring) → ~$8–10 (v0.4, 4 judges × ~10× output). Within the cost envelope per user direction.

**Where it lives.** Six commits in PR #75 (schemas + conversions in `roles/judge_schemas.py`; lexicon helpers in `studies/openness_maneuvering/subdimension_lexicon.py`; judge prompt rewrite in `roles/construct_judge.py`; aggregator + dual-granularity α in `orchestrator/construct_judging.py` + `analysis/persist_artefacts.py`; post-hoc quote verification in `analysis/quote_verification.py`; study version bump). Tests: 70 new across `tests/test_subdimension_schemas.py` (24) / `tests/test_subdimension_helpers.py` (11) / `tests/test_construct_judging.py::TestJudgePromptV04SubDimensional` (11) / `tests/test_subdimension_aggregator.py` (9) / `tests/test_quote_verification.py` (14) / `TestStudyVersionLockedAtV04` (1).

### B3. Paper framing and contribution

#### 18. **Hybrid three-layer framing** — in-silico simulation incorporating virtual ethnography for qualitative theory-building.

**What.** The method is described in three layers:

1. **Simulation.** Agent teams deliberate in a multi-agent simulation.
2. **Virtual ethnography inside the simulation.** The Observer, FieldNoter and Debriefer agents observe the team in process. `docs/11_ethnography_in_silico.md` describes this layer.
3. **Inductive coding.** Human researchers code the records to build theory.

This refines §17. §54 says what the approach claims.

#### 23. **Reframe the contribution as methods + microfoundations, NOT new theoretical constructs.**

**What.** The contribution is methodological. The study does not introduce new theoretical constructs for openness; those it draws on already exist in the literature.

1. **Methodological apparatus.** A framework that observes how agent teams deliberate and keeps auditable records.
2. **Propositions, where the records warrant them.** Those about agent teams can be tested with many runs. Those about firms are a further step and stand on their own evidence.
3. **Construct contestation as data.** Judge disagreement shows where a construct is contested. This applies only where a study runs the optional judges (§54).
4. **AI-domain operationalisation.** How to measure openness in AI is unsettled, so the study's rubric is one operationalisation and not the only one.

#### 24. **Add the 2024-2026 reference set the contribution framing requires.**

**What.** The reference set lives in the paper.
