# 11. Ethnography in silico

## What this framework actually is

This framework (the shared software in this repository, not a conceptual framework) is **not** a TMT (top management team) simulator that happens to log its outputs.

It is **a framework for observing teams of language-model agents (here, simulated executives) and keeping records that researchers code inductively**, with full provenance (a record of where each thing came from). It borrows ethnographic practice (observing in process, field notes, following surprises) and does not claim ethnography's warrant. Agents have no lived experience, stakes or shared history, and the fieldworker is a model, so the human analysts who read the full records, here the principal investigator (PI), hold interpretive authority (`DECISIONS.md` §54).

The distinction matters because it changes what the framework's outputs are and how a methods section describes them. Under the simulator framing, the deliberation transcript is a *result*. Under the ethnography-in-silico framing, the deliberation transcript is **field data** the PI codes inductively.

This document articulates the framing, audits where it is enforced in code, and lists what the PI gets that a conventional qualitative study cannot.

---

## 11.1 What "ethnography in silico" means

The framework borrows three commitments from ethnographic research:

1. **Observation in process.** The researcher agent reads along while the action happens, without taking part, and does not work from a retrospective summary. Notes are accumulated in real time; later analysis builds on those running notes rather than starting from cold.
2. **Inductive description.** Categories emerge from the field; the researcher does *not* enter with theoretical labels and look for instances. The data is the panel's own vocabulary (the panel being the simulated team under questioning), not the analyst's.
3. **Reflexive bracketing of bias.** Where the researcher cannot avoid bringing prior framing (and they always do bring some), the framing is declared explicitly. The theoretical lens is kept out of the observation protocol and surfaced only at the analysis stage; a study may give the observer the research question.

"In silico" simply means **the field and the field-worker are both LLM agents in a single computational loop** (LLM: large language model; an agent is a language model given a name, a role and instructions). The subjects (a synthetic six-role TMT) and the ethnographer (a researcher persona with three operational shells (set-ups of the same agent) — Observer / FieldNoter / Debriefer) co-exist inside the framework for the duration of a research session (one complete simulated meeting and debrief, also called a run).

The framework's contribution is methodological. It lets researchers apply inductive coding across many simulated conditions (5 firms × 4 cells × 2 RAG conditions × N replicates per cell). Here a cell is one combination of industry context and product type, and the two RAG (retrieval-augmented generation) conditions are with and without passages from a firm's documents added to the agents' prompts, the text sent to a model.

---

## 11.2 How the three ethnographic commitments are operationalised

A run moves through numbered phases: 1 deliberation, 2 strategy documents, 3 observation summary, 4 debrief. The researcher agent's three shells, or set-ups, are the FieldNoter (Phases 1 and 2), the Observer (Phase 3) and the Debriefer (Phase 4). An action is one move by a role in the deliberation. Code is cited as `file.py::function`.

### Commitment 1: Observation in process, not retrospective reading

**Where it lives in code.** `orchestrator/researcher_stream.py` + `roles/qualitative_researcher_agent.py::create_field_noter_agent`. The FieldNoter is invoked periodically *during* the TMT deliberation (`synth_every=10` actions by default) with the most recent batch of public events. It sees its earlier notes each time, and the Observer and Debriefer receive them all.

**Why this matters.** A researcher reading a 100-event transcript in one shot at Phase 3 produces summary-flavoured notes. A researcher taking notes *as the moments happen* captures nuance that compression loses — a CEO's half-formed objection that gets withdrawn, a CTO's reluctant agreement, an asymmetric attention to one component over another. By the time the Observer is invoked at Phase 3 for the structured `ObservationSummary` (its single structured account of the deliberation), its session (here, what its prompt carries) is already warm with the FieldNoter's running journal. The consolidation is "tighten the working notes into the structured schema" (a schema is a template of required fields), not a cold first read.

Tradition: Hine (2015) on the ethnographer-in-the-room; Charmaz (2014) chapters 2–3 on observation interleaved with note-taking.

### Commitment 2 — Inductive description, not theoretical coding

**Where it lives in code.** `roles/qualitative_researcher_agent.py::create_observer_agent` and `::create_field_noter_agent`. Both system prompts (standing text that tells a model who it is and how to behave) contain the same **observational-discipline rules**:

```
1. Record decisions, components, disagreements, role contributions, and
   alternatives USING THE PANEL'S OWN VOCABULARY. Do not paraphrase into
   your analytical categories. If they said 'the inference API', you
   write 'the inference API' — not 'the customer-facing service'.

2. Do NOT speculate beyond what the deliberation log contains.

3. Do NOT summarise the deliberation as theoretical categories. Just
   record what happened, in the panel's words.

4. Be ethnographic: anchor on what actually happened, quote the panel's
   own words where it sharpens the observation. Do not seek evidence of
   any particular construct; describe what you see.
```

These rules are baked into the LLM-researcher's instructions. They are not optional. The Observer's structured `ObservationSummary` schema enforces this further: there are fields for *decisions*, *components*, *disagreements*, *role contributions*, and *alternatives considered* — deliberately framed as observable behaviour, not as theoretical labels.

**Why this matters.** The single largest threat to inductive qualitative work is the researcher importing analytical categories prematurely. Charmaz (2014) chapter 4 calls this "forcing data into preconceived categories"; Glaser & Strauss (1967) treat it as the original grounded- theory cautionary tale. The observational-discipline rules above are the framework's explicit guardrail against this failure mode.

### Commitment 3 — Reflexive bracketing of researcher bias

**Where it lives in code.** `roles/qualitative_researcher_agent.py::_render_research_context` and the methodological-invariants tests (automatic checks of rules that must always hold) at `tests/test_methodological_invariants.py`.

The framework bifurcates the researcher persona into three operational shells with **asymmetric access** to the study's analytical framing:

| Shell | Sees research question? | Sees theoretical lens? | When invoked |
|---|---|---|---|
| Observer (Phase 3) | **No** by default | **No** | Once, structured ObservationSummary |
| FieldNoter (Phases 1 + 2) | **No** by default | **No** | Every ~10 events, free-form notes |
| Debriefer (Phase 4) | **Yes** | **Yes** | Each panel-interview turn |

By default the Observer and FieldNoter are deliberately **blind** to the study's research question and theoretical lens: they observe and describe without being told what the PI is ultimately looking for, although they do receive a list of words to avoid and to log. A study can instead choose embedded observation (`embedded_observation=True`), which gives them the question but never the lens. The Debriefer always sees the framing, and it uses the question as a guide for what to explore, under an explicit **anti-steering** rule:

> The panel may or may not produce material directly relevant to this
> research question. Follow the panel where they actually went in the
> deliberation. Do NOT steer them toward the research question. If the
> deliberation reveals nothing about the construct under study, that
> absence is itself a finding — note it; do not manufacture relevance.
>
> When you observe something interesting — surprising, puzzling, or
> unexplained — explore it, even if it leads away from the research
> question. Adjacent questions are welcome.

These rules constitute the framework's four methodological invariants (I1–I4) plus a fifth (I5) added by the RAG layer (the code that adds retrieved passages):

| # | Invariant | Code site |
|---|---|---|
| I1 | Observer is BLIND to RQ (research question) + lens, unless the study chooses embedded observation (then it knows the RQ, never the lens) | `create_observer_agent` |
| I2 | FieldNoter is BLIND to RQ + lens, on the same terms | `create_field_noter_agent` |
| I3 | Debriefer sees RQ + lens; it uses the question as a guide and does not steer. If the team does not raise a topic, it is told to treat that as a finding; researchers establish it from the log | `_render_research_context` |
| I4 | Prompts written for the team carry none of the study's listed words, apart from everyday uses of "open" such as "Open ASKs" and "open questions". Retrieved passages can carry them, because they are the firm's own words. In the researcher's own prompts, outside the block stating the question and lens, listed words appear only in the forbidden-vocab block (words the researcher may not use) | protocol YAML (debrief rules in a plain-text format) + study overlays (a study's own debrief topics) |
| I5 | Retrieval queries (the text a document search uses) never contain the RQ. In the debrief, a role's query includes the researcher's question, so its framing can affect which passages return; every query and passage is logged | `rag/queries.py` |

Each invariant has a test, run with `scripts/run_tests.sh`: I1–I3 are parametric (repeated for each) over the studies in `STUDY_SLUGS`, a fixed tuple (a list that does not change); I4 runs on the openness study and I5 on two named studies. There is no CI (continuous integration: automatic testing of every change), so the tests catch a regression (something that worked breaking) when someone runs them. Detail: `docs/05_methodological_invariants.md`.

**Why this matters.** The LLM-researcher's prompt-level blindness can be tested: the methodological invariants are inspectable code paths. A test shows what a prompt contains, not what the model brings from training (see 11.5).

---

## 11.3 What live observation gives the PI

The framework persists the entire field-research session to a browseable folder under `results/runs/<run_id>/`. A human PI **can** (and should) read this folder as field data. Interpretation rests with the PI.

In the layout below, `.md` files are Markdown (MD: plain text with simple marks for headings and lists), `.json` and `.jsonl` files hold data as named fields in plain text, a commit is one saved change in the code's history, `--rag` and `--judge` are options added to a command, a manifest lists what produced something, the corpus is the firm's public documents, and a construct judge is a model that scores a finished run against a rubric. Per `docs/03_simulation_workflow.md`, the layout is:

```
results/runs/<run_id>/
├── 00_meta.json                  # run identity + scenario + study version + models + code commit
├── 01_deliberation/
│   ├── interaction_log.md        # full Phase 1 public transcript + citation
│   │                               footnotes when --rag was on
│   └── role_scratchpads/         # each role's private notes
├── 02_strategy_documents/
│   └── <Role>_strategy.md        # each role's final strategic memo + citations
├── 03_researcher/
│   ├── observation_summary.md    # the Observer's structured field notes
│   └── field_notes.md            # the FieldNoter's running notes
├── 04_interview/
│   └── transcript.md             # the Debriefer ↔ panel exchanges + citations
├── 05_judging/                   # (opt-in via --judge) construct-judge ensemble
├── 06_subdimension_scores/       # (opt-in) anchored-dictionary sub-dim scores
├── 06_private_channel/           # each role's notes, draft and inbox
├── 07_rag/                       # (--rag only) corpus manifest + retrieval log
│   ├── corpus_manifest.json
│   ├── retrieval_log.jsonl       # full passages retrieved per LLM call, with
│   │                               shown_chars (how much the role saw)
│   └── README.md
└── README.md                     # index of the folder
```

The PI's qualitative-coding workflow against this folder mirrors what they would do with conventional field data:

1. **Open the deliberation MD** as a single readable transcript. The live citation footnotes (when `--rag` was on) make every firm-history-grounded claim auditable inline — equivalent to an interview transcript where every reference to "what we said last year" is footnoted to the actual prior statement.
2. **Open the observation summary MD** as the ethnographer's structured field notes. The PI can compare what the LLM-researcher noticed against their own reading of the deliberation — the disagreement is itself data.
3. **Open the interview transcript MD** as the panel-debriefing data. Each answer is logged to its role. Each call's prompt carries that role's record of the earlier phases (`orchestrator/role_memory.py`), so when the Debriefer asks the CTO about a decision the CTO made, the CTO has that record to draw on. The answer is still new text written now, not a memory (L3 in `docs/LEARNINGS.md`).
4. **Open `07_rag/retrieval_log.jsonl`** to see, per LLM call, which firm-history excerpts were retrieved for each role agent — even those it did NOT cite. Each entry keeps the full passage plus `shown_chars`; the role saw that much of it, which is all of it by default. This is access no human-subjects study can give a reviewer, though the model's training data (the text it learned from) stays out of view.

What this lets the PI report: every claim in the methods section about "the panel's actual reasoning" is traceable to a specific event, in a specific role's session, with a specific information context. The model's own reasoning stays opaque (`docs/08_known_limitations.md`).

---

## 11.4 The four-channel field record

Under the ethnography-in-silico framing, the framework gives the PI **four distinct channels of field data** per run. Distinguishing them matters because conflating them would conflate firm-commitments, internal deliberation, researcher-interpretation, and source-of-knowledge:

| Channel | What | Where it lives |
|---|---|---|
| **Public** | What the firm publicly committed to during the simulated deliberation | `01_deliberation/interaction_log.{json,md}` (events with `kind=speak`, `ask_public_echo`, `answer_public`); `02_strategy_documents/<Role>_strategy.{json,md}` |
| **Private** | The firm's internal deliberation — scratchpads, working drafts, inbox messages never visible to peers | `06_private_channel/` (`<Role>_scratchpad.md`, `<Role>_draft.md`, `inbox_final.md`, `private_state.json`); `01_deliberation/role_scratchpads/<Role>_scratchpad.md` |
| **Researcher** | The FieldNoter's interpretation of the deliberation in real time — the researcher's read, not the firm's commitment | `03_researcher/observation_summary.md` + `03_researcher/field_notes.md`, the prose accumulated during Phases 1 + 2 |
| **Source** | The firm's published history that informed individual role-utterances (when `--rag` was on) — which excerpts were retrieved and which were cited | `07_rag/retrieval_log.jsonl` + `07_rag/corpus_manifest.json` + citation footnotes inline in every per-phase MD |

The optional sub-dimensional measurement layer (not part of the method; it counts words from fixed lists; `analysis/text_measures/dictionary.py`
+ `studies/openness_maneuvering/docs/02_subdimension_measurement_plan.md`) scores public, private, and researcher channels **separately** for exactly this reason — a sentence in the field notes saying "the team showed little hesitation about open-sourcing" is the researcher's read, not the panel's, and the analysis has to be honest about which channel each claim originates in.

The RAG layer (`docs/10_rag_repo_plan.md`) adds the source channel: every citation a role makes to retrieved firm-history is now traceable to a verbatim quote + the doc + the chunk (a piece cut from a document for searching) it came from. The PI's methods section can now cite, for any role's claim, the document the role agent was shown, the part of the document it relied on, and the substring-verified quote (checked to appear word for word in the document).

---

## 11.5 What this framework does NOT claim

Honest caveats per `docs/08_known_limitations.md`:

1. **The LLM-researcher is still an LLM.** Pre-training bias colours what the FieldNoter notices. The framework's contribution is reducing *prompt-level* priming via the blindness invariants — not eliminating the deeper bias from the LLM's training corpus. We declare this as a limitation rather than pretending the framework solves it.
2. **The synthetic TMT is also LLMs.** A "deliberation" is a multi-agent LLM exchange. The framework studies how LLMs simulate TMT deliberation; it does not claim the LLM TMT *is* a real TMT. The framework does not assume external validity to human TMTs, and it does not demonstrate it.
3. **The researcher cannot articulate its own reasoning.** A human ethnographer can explain why they noticed something; an LLM ethnographer cannot, at least not at the evidentiary level a peer reviewer would require. The framework persists responses, but not the prompts (they are in the code at the recorded commit, and `example_runs/prompts_as_run/` holds a copy for the published runs) or internal reasoning chains.
4. **The methodological invariants are necessary, not sufficient.** The blindness rules constrain prompt-level priming. They do not constrain the LLM's deeper associative behaviour. Tests verify the rules hold; they do not verify that the rules are *enough*.

These caveats are why the framework's per-run output is presented as *field data the PI codes inductively*, not as *results the framework produces*. The PI's analytical judgement is the final stage; the framework feeds it disciplined, provenance-rich field material at study scale.

---

## 11.6 How to read this framework's outputs as a qualitative reviewer

If you are reviewing a paper that used this framework, here is the auditing protocol:

1. **Check the methodological invariants.** Run `scripts/run_tests.sh tests/test_methodological_invariants.py tests/test_observation_stance.py tests/test_no_construct_steering.py tests/test_rag_persistence.py` at the commit in `00_meta.json` (`code_commit`). The first three files check I1–I4; I5 is checked by `TestInvariantI5NoQueryLeakAcrossStudies` in the last. All must pass.
2. **Check `00_meta.json`'s `study_slug` + `study_version`.** Confirm they match the framing the paper reports. The study config is `studies/<slug>/__init__.py` at that version. The slug is the study's short folder name.
3. **Read the Observer's `observation_summary.md`** as the ethnographer's structured field notes. Do they read as inductive description, or as theoretical-category coding? (Look for panel-vocabulary verbatim quotes vs analyst-vocabulary abstractions.)
4. **Read the deliberation `interaction_log.md`.** Compare what you see to the Observer's summary. Disagreement between your read and the LLM-researcher's read is itself reportable.
5. **If `07_rag/` exists, sample `retrieval_log.jsonl`.** Pick three citations from the strategy documents and verify (a) the document appears in the retrieval log under the right role, (b) the cited quote is a substring of the part of a retrieved chunk the role saw (the first `shown_chars` characters of its `text`), (c) the quote-verification section of the `python -m analysis.compare_rag` report flags no fabrications for those citations.
6. **Read `DECISIONS.md`** + `docs/02_design_decisions.md` for the methodological commitments behind the run.

The framework's job is to make this audit cheap. Every claim the paper makes about "what the panel actually said" or "what the firm's past position was" should resolve to a specific file, specific event index, specific citation, in a specific commit of the framework code. That traceability is what the framework offers: every step from field data to coded category can be reviewed. It does not supply what a human fieldworker brings, which is why human analysts hold interpretive authority.
