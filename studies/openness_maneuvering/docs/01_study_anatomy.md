# Study anatomy — the openness study as a worked example

This file walks through the default study of the framework (the shared software in this repository), `studies/openness_maneuvering/`, field by field. It shows what each field of `StudyConfig` (the object holding a study's settings) is for, where the text was sourced, and how it ends up in the running prompts (the text sent to the language models during a run, one complete simulated meeting and debrief).

The same template applies to any future study (see `06_extending_to_new_studies.md`). Terms are defined in [`docs/GLOSSARY.md`](../../../docs/GLOSSARY.md).

## Identity

```python
name = "Strategic Maneuvering of Openness in Open Innovation Ecosystems"
slug = "openness_maneuvering"
version = "0.5.0"
```

The `slug` (a short name with no spaces) matches the sub-package directory (the study's folder of code) under `studies/`. The `--study openness_maneuvering` flag (an option added to a command) on the CLI (command-line interface: using a program by typing commands) resolves to this slug. The `version` is semver-formatted (numbered major.minor.patch); downstream analysis pins to an exact `study_version` when reproducing a run. Both `slug` and `version` are persisted (saved) in `00_meta.json`, the run's summary file (and in `manifest.json`, a file listing what produced a run, which the command line writes for each completed run).

## Research question

```
"How do firms maneuver openness to create and capture value?"
```

This text is the *only* place the framework gets the research question from. The Debriefer (the researcher agent, a language model given that role, when it interviews the team in the debrief) always reads it — it appears verbatim inside the Debriefer's `RESEARCH CONTEXT` block. With the default `embedded_observation=False`, the Observer and FieldNoter (the researcher agent when summarising and taking notes) never see it (`tests/test_methodological_invariants.py::TestObserverIsBlindToStudyFraming` enforces this); with `True` they do (`tests/test_observation_stance.py`). The panel (the six simulated executives being questioned) never sees it.

### Wording stability and design rationale

The current wording is the canonical text for `study.version` 0.5.0. Bumping the wording requires bumping `study.version` (so any prior run's `study_version` field unambiguously identifies which wording produced it). `tests/test_study_config.py::TestOpennessHistoricalContent` is the regression guard (an automatic check that a change has not broken something) against accidental drift.

The RQ (research question) does not name mechanisms (e.g. technological re-architecture, governance tuning) even though the v1.0 CrewAI pilot (the earlier study, built on different software) identified those as salient — keeping the RQ inductively open lets the new study rediscover, refine, supersede, or replace those mechanisms based on the four-channel field data (public, private, researcher and source records), rather than treating them as confirmed premises. It does name an outcome, to create and capture value: v0.5.0 restored that clause so the runs ask what the proposal asks, and the debrief still records other purposes (legitimacy, safety, ecosystem health) as findings (`DECISIONS.md` §43, numbered entry 43). The wording history is captured in the test docstring (the explanatory text at the top of a piece of code) at `tests/test_study_config.py::TestOpennessHistoricalContent`.

## Theoretical lens

```
"Inductive. Concepts are developed after the run from what the panel
did and said."
```

This text reaches the Debriefer, so it names no literature. The sensitising literature for the qualitative coding after the runs is selective revealing (Henkel 2006), dynamic capabilities (Teece, Pisano & Shuen 1997) and ecosystem shaping (Jacobides, Cennamo & Gawer 2018).

## Why a theoretical lens at all

Pure inductive ethnography is a useful aspiration but a practical impossibility — the researcher always brings *some* framing. The honest move is to (a) declare the lens up front, (b) keep it out of the data-collection prompts (Observer + FieldNoter), and (c) document it in the study config so reviewers can assess whether a finding is genuinely emergent from the data or a lens artefact.

### Reference list

The literature stays out of the prompt; it is for the coding after the runs. The supporting literature:

- Henkel, J. (2006). Selective revealing in open innovation processes. *Research Policy*, 35(7), 953–969.
- Teece, D. J., Pisano, G., & Shuen, A. (1997). Dynamic capabilities and strategic management. *Strategic Management Journal*, 18(7), 509–533.
- Jacobides, M. G., Cennamo, C., & Gawer, A. (2018). Towards a theory of ecosystems. *Strategic Management Journal*, 39(8), 2255–2276.

## Debriefer background block

```
"Anchor each probe on items that the panel ITSELF named — specific
products, processes, or decisions — in the panel's own words."
```

Optional study-specific guidance for the Debriefer. It must not say where to look for the construct: the framework's rules already bind the Debriefer to what the panel raised.

## Construct-specific forbidden vocabulary

```python
construct_forbidden_vocabulary = [
    "open", "closed", "open-source", "closed-source",
    "liberalization", "enclosure",
    "modular", "boundary",
    "value capture",
    "architectural leverage", "asset orchestration",
    "openness", "open-sourced", "open-sourcing",
    "open-weight", "open-weights",
    "proprietary", "disclose", "disclosure",
    "selective revealing", "outsider", "outsiders",
]
```

These are the words the *researcher* must NOT introduce in its probes (would steer the panellists toward the construct's vocabulary). They are merged at runtime (while the run is under way) with the universal `methodological_forbidden_vocabulary` (`strategy`, `strategic`, `shift`, `capability`) of the protocol (the debrief's rules and topics) to produce one list all three researcher shells (the set-ups of the researcher agent: observer, field noter and debriefer) are told to avoid. The researcher is not told which words come from which subset.

### Why each word is on this list

- `open` / `closed` / `open-source` / `closed-source` — direct construct vocabulary from the open-innovation literature.
- `liberalization` / `enclosure` — historical / political-economy framings of the construct (Boyle 2003 on the "second enclosure movement").
- `modular` / `boundary` — Henderson & Clark (1990) architectural-knowledge framings; loaded for this construct.
- `value capture` — Teece-style appropriability framing.
- `architectural leverage` / `asset orchestration` — Teece (2007) microfoundations of dynamic capabilities.
- `openness` / `open-sourced` / `open-sourcing` / `open-weight` / `open-weights` / `proprietary` / `disclose` / `disclosure` / `selective revealing` / `outsider` / `outsiders` — variants and near-synonyms added because the check matches whole words (`DECISIONS.md` §35).

Together: the words a researcher steeped in the literature would naturally reach for, all of which would prime the panellists if introduced in a probe.

## Flagged vocabulary (the spontaneous-use watch-list)

```python
flagged_vocabulary = [  # same words as the forbidden list by default
    "open", "closed", "open-source", "closed-source",
    "liberalization", "enclosure",
    "modular", "boundary",
    "value capture",
    "architectural leverage", "asset orchestration",
    "openness", "open-sourced", "open-sourcing",
    "open-weight", "open-weights",
    "proprietary", "disclose", "disclosure",
    "selective revealing", "outsider", "outsiders",
]
```

If a panellist uses any of these words **spontaneously** (i.e. unprompted by the researcher), the Observer logs the occurrence in `ObservationSummary.flagged_vocabulary_used` (a field of its summary) with the panellist's role and verbatim context. The FieldNoter quotes such uses in its notes. The list is presented with no explanation of why those particular words matter, and it is meant as a *capture mechanism*. So the Observer and FieldNoter are blind to the question by default, but they do see this list, and the words themselves can hint at the topic.

By default `flagged_vocabulary == construct_forbidden_vocabulary` because the construct's vocabulary is exactly what we want to capture if it emerges from the panel. A study could choose to flag a wider set (e.g. include "competitive advantage" as something to capture if mentioned, without forbidding the researcher from probing on it) or a narrower set.

## Scenario brief

```python
scenario_brief = "An AI firm operating in a competitive industry."
```

This one short sentence is meant to shape the firm's domain, but only CEO-led mode (one of five ways to run the team's discussion) uses it, in the CEO prompt (`agent.py::_compose_ceo_prompt`), as `Company: <name> (An AI firm operating in a competitive industry)`. The default concurrent mode (all six roles act at once) does not pass it to the team (`orchestrator/concurrent_mode.py::_compose_role_prompt`); there the AI domain comes from the firm's name and the direction hint below.

For an absorptive-capacity-in-alliances study, this might become "A pharmaceutical firm engaged in inter-firm R&D alliances." (See `studies/_test_alt/__init__.py` for an example.) That alone would not orient a default run toward alliance-management decisions: such a study must also write a strategic question that names the domain and leaves out `{direction_hint}`.

## Strategic question template

```python
strategic_question_template = (
    "What should we, as a leadership team, develop and bring to "
    "market next? The scope is {direction_hint}. Surface the "
    "directions worth considering given our industry context and "
    "firm position, evaluate them, converge on a recommendation, "
    "and then propose how to take it forward."
)
```

The `{direction_hint}` placeholder is filled per cell (one combination of firm, industry context and product type) by `run_research_session.py`, with framework text that is the same for every study:

- `product_type=Novel` → "a novel AI product direction — something the firm does not already offer"
- `product_type=Enhancement` → "an enhancement of the firm's existing AI offering"

The template is study-specific so a non-AI study can produce a non-AI question, as long as it leaves out `{direction_hint}`. For studies that need a richer template — multiple placeholders, conditional branches — the framework falls back to the literal template string if the format call (the step that fills the placeholders) fails; future studies can switch to a callable template (one written as code) if needed.

## Optional overrides

```python
role_factories_module = None
contexts_module = None
protocol_overlay = _DEBRIEFING_OVERLAY      # loaded from debriefing_overlay.yaml
judgment_rubric = _OPENNESS_RUBRIC          # the 7-D openness rubric
extra_phases = [ConstructJudgingPhase()]    # registers the construct-judge ensemble
rag_corpus_loader = (                       # importable callable resolving the firm's Vertex corpus
    "studies.openness_maneuvering.rag_loader:load_corpus"
)
```

The framework's default six TMT (top management team) roles (`roles/ceo_agent.py`, …) and the framework's default `context_definitions.py` (Dynamic/Stable × Novel/Enhancement axes) work fine for the openness study, so `role_factories_module` and `contexts_module` stay `None` (unset). Those two fields exist in the schema (the template of allowed fields) but are not yet wired in (planned, P2, a priority level in `ROADMAP.md`): nothing reads them, so no study can use them yet.

### `protocol_overlay`

`_DEBRIEFING_OVERLAY` (the study's own debrief topics, merged on top of the shared ones) is loaded from `studies/openness_maneuvering/debriefing_overlay.yaml` (YAML is a plain-text format for settings) at module load (when the study's code is read). It supplies five neutral thematic areas (D – differences in handling; E – who does the work; F – changes over time; G – what the firm gets and gives; H – position relative to others) layered over the framework's generic A / B / C / I / J. They do not map onto the dimensions of the rubric (a scoring guide), which only the judges (models that score a finished run) see after the run. The framework merges them in id order, with the closing area last, at debriefing time via the deep-merge contract (the rule for combining nested settings) documented in `02_design_decisions.md` §21. The overlay is **add-only** — it can extend `thematic_areas`, append a paragraph to `behavioural_rules`, or dict-merge (combine named settings) into `panel_format`, but it cannot remove framework-level rules or areas.

### `judgment_rubric`

`_OPENNESS_RUBRIC` is a `JudgmentRubric` (Pydantic model from `studies/base.py`; here a "model" is a Python template that checks fields, not a language model) carrying seven dimensions — `component_disclosure`, `process_openness`, `boundary_permeability_inbound`, `boundary_permeability_outbound`, `ecosystem_orchestration`, `value_capture_posture`, `temporal_openness_maneuvering` — each with low/mid/high anchor descriptions grounded in Henkel 2006 (selective revealing + dynamic), Chesbrough 2003 (open innovation), Dahlander & Gann 2010 (inbound/outbound openness taxonomy), Jacobides/Cennamo/Gawer 2018 (ecosystem orchestration), Teece 2007 (value capture posture), and Alexy/Henkel/Wallin 2013 (temporal sequencing). The rubric is what the construct-judge ensemble (the group of judge models) scores against; it's also what the sub-dimensional dictionary scorer (which counts words from fixed lists) decomposes into 26 sub-constructs (see [`02_subdimension_measurement_plan.md`](02_subdimension_measurement_plan.md)).

### `extra_phases`

Scoring is optional and not part of the method in the proposal. `ConstructJudgingPhase()` is a `PhaseHandler` (a piece of code that runs one extra stage; see `02_design_decisions.md` §20) that runs the four-model judge ensemble after Phase 4 (the debrief) when the CLI's `--judge` flag is set. The framework iterates `study.extra_phases` in order and runs each handler whose gate allows. A different study could register a different handler (or none); the construct-judge wiring is study-supplied, not framework-hardcoded.

### `rag_corpus_loader`

The dotted-path importable callable (the address of a piece of code) resolving the firm's RAG (retrieval-augmented generation: searching documents and adding the passages found to a model's prompt) corpus (document collection) when `--rag` is set. The openness study's loader (`studies/openness_maneuvering/rag_loader.py::load_corpus`) is read-only: it looks up the corpus in Vertex AI (Google's paid cloud service) by display name `openness_maneuvering__<Company>` via `vertex_corpus.find_corpus`, returns `None` when no corpus exists for this firm (a `--rag` run then exits with an error; build the corpus with `python -m rag.corpus_build`). Per-doc SHA256s (fingerprints computed from a file's contents) are extracted from each Vertex file's `description` field and surface in `07_rag/corpus_manifest.json` for reproducibility pinning. See [`02_design_decisions.md`](../../../docs/02_design_decisions.md) §23 for the Vertex AI RAG Engine vs local-RAG trade-off, and [`10_rag_repo_plan.md`](../../../docs/10_rag_repo_plan.md) for the full RAG layer.

## Panel composition

```python
panel_roles = ["CEO", "CTO", "COO", "CMO", "Product_Strategist", "Product_Designer"]
```

The default six TMT roles. The field is meant to let a study specify a different panel (`["CEO", "Head_of_RnD", "VP_Alliances", "General_Counsel"]` for an alliance-governance study), combined with `role_factories_module`, but neither is wired in yet (planned, P2). Every run uses these six roles.

## How the StudyConfig flows through the run

The diagram follows the study's settings from the typed command to the agents' prompts. The name `TMTSystemWithA2A` is historical: A2A (agent-to-agent, a method for agents to call each other over a network) was removed.

```
CLI: --study openness_maneuvering
  → studies.load_study("openness_maneuvering")
    → returns the STUDY: StudyConfig instance
      → run_research_session(study=STUDY, ...)
        ├── strategic_question = STUDY.strategic_question_template.format(...)
        ├── TMTSystemWithA2A.run_strategic_discussion(
        │     scenario_brief=STUDY.scenario_brief, ...)
        │   └── on the company line of each role's prompt
        ├── create_field_noter_agent(study=STUDY)
        │   └── prompt: merged forbidden vocab + flagged watch-list
        │       (no RQ unless embedded_observation; never the lens)
        ├── create_observer_agent(study=STUDY)
        │   └── prompt: merged forbidden vocab + flagged watch-list
        │       (no RQ unless embedded_observation; never the lens)
        ├── run_panel_debriefing(study=STUDY, ...)
        │   └── create_debriefer_agent(study=STUDY)
        │       └── prompt: RESEARCH CONTEXT block with
        │           STUDY.research_question + STUDY.theoretical_lens +
        │           STUDY.debriefer_background_block + anti-steering rule;
        │           merged forbidden vocab;
        │           merged thematic areas (framework A/B/C/I/J +
        │           STUDY.protocol_overlay → D/E/F/G/H)
        └── for handler in STUDY.extra_phases:   (construct judging only with --judge)
              if handler.should_run(...):
                  await handler.run(...)
                  handler.persist(out_dir)
              # ConstructJudgingPhase reads STUDY.judgment_rubric
```

The `StudyConfig` is the single point of customisation per research project. Everything else in the framework is study-agnostic.

## What gets persisted with a run

A run's summary file holds these fields, among others.

```jsonc
// results/runs/<run_id>/00_meta.json (partial)
{
  "study_slug": "openness_maneuvering",
  "study_version": "0.5.0",
  "research_question": "How do firms maneuver openness to create and capture value?",
  "embedded_observation": false,
  "code_commit": "…",
  …
}
```

`phases_captured` in `00_meta.json` names the `extra_phases` that ran; to reconstruct their handler IDs, check out the recorded commit (one saved version of the code) and load the study at that revision — `StudyConfig.extra_phase_ids_for_manifest()` returns the dotted-path handler IDs. (A future manifest may record those IDs inline; see `08_known_limitations.md`.)

A reviewer reproducing the run loads the same `studies.<slug>` package at the same `version` and re-runs. `study_slug` + `study_version` plus the recorded commit pin the exact framing that produced the output. See `07_reproducibility.md` for the full reproduction protocol.
