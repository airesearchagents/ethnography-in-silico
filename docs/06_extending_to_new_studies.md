# 6. Extending the framework to a new study

This file walks through adding a new research project to the framework (the shared software in this repository). The whole exercise is a single file of Python (the project's programming language), plus one line in a test list (the studies the automatic checks cover); no framework code needs to change, within the limits noted below. Terms are also explained in the [glossary](GLOSSARY.md).

## When to add a new study

Add a new study when any of these change:

- The research question
- The theoretical lens / analytical framing for later coding
- The construct-specific vocabulary (words to avoid in the questions of the researcher agent, the language model that watches and questions the team; words to flag if panellists, the simulated executives when questioned, use them spontaneously)
- The scenario brief (what kind of firm is being simulated)
- The strategic-question template for the deliberation (the simulated team's discussion)

Do NOT add a new study for:

- A different company, industry context, or product type — these are CLI knobs (options typed on the command line: `--company`, `--industry-context`, `--product-type`)
- A different deliberation mode (how the roles take turns) — that's the setting `DeliberationConfig.discussion_mode`
- A different LLM (large language model, the program that writes each agent's text) — that's `TMT_PROVIDER` (a setting held outside the code; TMT means top management team) / per-role overrides

## Minimal recipe (5 minutes)

### 1. Create the study sub-package

A sub-package is a folder of Python code. These commands, typed in a terminal (the window where commands are typed), create the folder and an empty file. `absorptive_capacity` is the study's slug, a short name with no spaces.

```bash
mkdir -p studies/absorptive_capacity
touch studies/absorptive_capacity/__init__.py
```

### 2. Fill in the StudyConfig

`studies/absorptive_capacity/__init__.py`, the file that holds the study's settings (`StudyConfig` is the template for them):

```python
"""Study: Absorptive Capacity in Inter-firm R&D Collaborations.

How firms develop and deploy absorptive capacity (Cohen & Levinthal 1990)
for knowledge inflows from inter-firm R&D alliances. Theoretical
framing draws on Cohen & Levinthal's seminal work plus inter-firm
governance literature (Williamson 1991) and knowledge-similarity
boundary conditions (Lane & Lubatkin 1998).
"""

from __future__ import annotations

from ..base import StudyConfig


STUDY: StudyConfig = StudyConfig(
    name="Absorptive Capacity in Inter-firm R&D Collaborations",
    slug="absorptive_capacity",
    version="0.1.0",

    research_question=(
        "How do firms develop and deploy absorptive capacity for "
        "knowledge inflows from inter-firm R&D collaborations."
    ),

    theoretical_lens=(
        "Absorptive capacity (Cohen & Levinthal 1990) — the firm's "
        "ability to recognise, assimilate, and apply external "
        "knowledge. Inter-firm governance under uncertainty "
        "(Williamson 1991). Knowledge-similarity boundary "
        "conditions on absorptive effectiveness (Lane & Lubatkin "
        "1998)."
    ),

    debriefer_background_block=(
        "Anchor probes on specific collaboration episodes the panel "
        "itself named — partnership relationships, knowledge "
        "inflows, assimilation steps the team described. The "
        "construct lives in how the firm actually engaged with "
        "external knowledge; do not invent engagement that did not "
        "appear in the deliberation."
    ),

    construct_forbidden_vocabulary=[
        "absorptive", "assimilation", "spillover",
        "complementarity", "appropriability",
        "knowledge stock", "absorptive capacity",
    ],

    flagged_vocabulary=[
        "absorptive", "assimilation", "spillover",
        "complementarity", "appropriability",
        "knowledge stock", "absorptive capacity",
    ],

    scenario_brief=(
        "A pharmaceutical firm engaged in multiple R&D alliances."
    ),

    strategic_question_template=(
        "As a pharmaceutical firm, what should we do next with our "
        "R&D alliances, given our current portfolio? "
        "Surface the options worth considering, evaluate them, and "
        "propose what to do next."
    ),
)
```

That's it. The framework picks the study up automatically. The task above names no construct word and does not ask the team to converge, because either can come back as a finding (see L1 and L16 in [`LEARNINGS.md`](LEARNINGS.md)).

**Limits for a study outside AI.** The template above leaves out `{direction_hint}` and names the domain itself, for two reasons:

- `{direction_hint}` is fixed framework text, whatever the study: "a novel AI product direction — something the firm does not already offer" or "an enhancement of the firm's existing AI offering" (`run_research_session.py::run_research_session`, where `::` points to a part inside a file). The built-in task used when `strategic_question_template` is omitted includes it too.
- `scenario_brief` appears on the company line of each role's prompt (the text sent to a language model to get one reply).

The roles and the scenario text also stay as they are, whatever the study (see "not yet wired in" below). So this example still simulates the framework's six executives under its `Dynamic` / `Stable` and `Novel` / `Enhancement` scenario text.

### 3. Verify it loads

```bash
python3 -c "from studies import load_study; print(load_study('absorptive_capacity').name)"
# Absorptive Capacity in Inter-firm R&D Collaborations
```

### 4. Preview it with a free dry run

A dry run uses your real prompts with a stand-in for the model. It makes no model calls, costs nothing and takes a few seconds. It reports the calls and tokens in each phase, the largest call and an estimated cost at list prices, and saves every prompt so you can read what the team and the researcher agent will receive.

```bash
python -m analysis.dry_run --study absorptive_capacity --save-prompts <folder>
```

### 5. Run a smoke

A smoke run is a quick first run to confirm that nothing breaks outright. It calls real language models and costs money.

```bash
python3 run_research_session.py \
  --study absorptive_capacity \
  --company Pfizer \
  --industry-context Dynamic \
  --product-type Novel \
  --out-dir results/runs/absorptive_capacity_smoke \
  --max-exchanges 15 \
  --log-level INFO
```

The framework:
- Loads `studies.absorptive_capacity.STUDY`
- Builds the six-role TMT, passing along `scenario_brief`
- Generates the strategic question from the template, filling in any placeholders
- Threads the study through every phase (numbered stage of a run)
- Persists (saves) `study_slug` + `study_version` in `00_meta.json`, the run's summary file

The methodological-invariant tests (automatic checks of rules that must always hold, numbered I1 to I5) run on the studies listed in `STUDY_SLUGS` in `tests/test_methodological_invariants.py`, a fixed tuple (a list set in advance), so add your slug to it and run `scripts/run_tests.sh tests/test_methodological_invariants.py`. They check that the Observer and FieldNoter (the researcher agent while it summarises what it saw and writes notes) remain blind to the study's research question and lens, and that the RESEARCH CONTEXT block of the Debriefer (the researcher agent while it questions the team) contains the study's framing under the standard anti-steering rule (do not lead the team toward the research question). With `embedded_observation=True`, `test_research_question_text_not_in_observer_instruction` and `test_research_question_text_not_in_field_noter_instruction` fail as expected; the rest must pass, and `tests/test_observation_stance.py` checks the embedded prompts. The construct-word check (I4) runs only on `openness_maneuvering`, and the check on retrieval queries, the text used to search a firm's documents (I5), names its own two studies, so extend those by hand for now.

## What does NOT need to change

The 5-minute recipe above touches `studies/<slug>/__init__.py` and adds your slug to `STUDY_SLUGS`. Nothing in `roles/`, `orchestrator/`, `agent.py`, `analysis/` or `protocols/` is modified.

This is the portability claim of the framework today: the question, lens, vocabulary, decision task and debrief topics are the study's; the team, the scenario text and the `{direction_hint}` wording are not yet.

## When you need more than a single file

The extension points that work today are the protocol overlay, the judgment rubric with extra phases, and the RAG corpus loader. An overlay is a study's own debrief topics, added to the shared ones; a rubric is a scoring guide; RAG (retrieval-augmented generation) means searching a document collection, or corpus, and adding the passages found to a model's prompt. Per-study roles and contexts are planned:

### Per-study role factories (not yet wired in)

`panel_roles` and `role_factories_module` (role factories are the code that builds each agent) exist in the `StudyConfig` schema (the template of required fields), but nothing outside the schema tests reads them. Every run builds the standard six TMT roles from `roles/*_agent.py`, so setting these fields changes nothing today. Wiring them in is planned (P2, a priority level; see `ROADMAP.md`).

The intended design: a study that needs different TMT roles (e.g. a Head of R&D + VP Alliances instead of CMO + Product Designer for a study on alliance governance) would create `studies/<slug>/roles.py` exporting a `ROLE_FACTORIES: dict[str, Callable]`, and set `role_factories_module="studies.<slug>.roles"` (string, not callable — keeps the manifest, the file listing what produced a run, JSON-dumpable, or savable as plain text) and `panel_roles=[...]`.

### Per-study context definitions (not yet wired in)

`contexts_module` also exists only in the schema. Every run takes its scenario text from `roles/context_definitions.py`, and `--industry-context` and `--product-type` accept only `Dynamic` / `Stable` and `Novel` / `Enhancement` (a typo fails). Wiring it in is planned (P2).

The intended design: a study that needs a different scenario axis (e.g. "alliance type" × "knowledge similarity") would create `studies/<slug>/contexts.py` exporting `get_industry_context_guidance` and `get_product_type_guidance` with the same signatures (the inputs they take) as `roles/context_definitions.py`, and set `contexts_module="studies.<slug>.contexts"`.

### Per-study protocol overlay

The framework-level `protocols/ethnographic_protocol.yaml` (the debrief's rules and topics, in YAML, a plain-text settings format) carries five **generic** thematic areas (A — decision anchoring, B — counterfactuals, C — disagreement and resolution, I — context sensitivity, J — reflection and unresolved). A study can supply **construct-anchored** areas via `protocol_overlay` — either an inline dict (named settings written in the file) or, more commonly, a path to a YAML file shipped inside the study sub-package:

```python
from pathlib import Path
import yaml

_OVERLAY_PATH = Path(__file__).parent / "debriefing_overlay.yaml"
_OVERLAY: dict = yaml.safe_load(_OVERLAY_PATH.read_text())

STUDY = StudyConfig(
    …
    protocol_overlay=_OVERLAY,
)
```

The overlay's shape (see `studies/openness_maneuvering/debriefing_overlay.yaml` for the worked example):

```yaml
thematic_areas_overlay:
  - id: D                                # added to framework A/B/C/I/J; use a letter from D to H
    name: Differences in handling
    purpose: …
    stems:
      - "You handled [X] and [Y] differently. Walk me through how that came about."
      - …
  - id: E
    …

behavioural_rules_additions: |           # appended as a separate paragraph below the framework rules
    When a panellist contradicts themselves, probe deeper.

panel_format_additions:                  # dict-merged into the framework's panel_format
    max_probe_chain_depth: 7
```

The merge is performed by `roles/qualitative_researcher_agent.py::_apply_study_overlay`. It is **add-only**: an overlay can extend, but cannot delete framework-level areas or rules. Unknown overlay keys are silently ignored, so the contract is forward-compatible (older code still runs with newer overlays). Study area ids must be letters from D to H: the debriefer's `area_id` field accepts only A to J, and the framework uses the rest. A reused id renders twice, because the overlay adds areas and does not merge them by id. See `02_design_decisions.md` §21 for the full rationale and `tests/test_protocol_overlay.py` for the enforced semantics.

Write construct-anchored areas in **construct-neutral language**. Probe what the panel actually did with components, processes, or relationships — never name the construct's own vocabulary in the area stems (that vocabulary belongs in `construct_forbidden_vocabulary`).

### Per-study judgment rubric + extra phases

Scoring is optional and not part of the method in the proposal. If your study wants to run a construct-judge ensemble, several models that score a run against a rubric (or any other post-Phase-4 scoring, after the debrief), fill in the placeholders below:

```python
from studies.base import StudyConfig, JudgmentRubric, RubricDimension
from orchestrator.construct_judging import ConstructJudgingPhase

_MY_RUBRIC = JudgmentRubric(
    name="Absorptive capacity",
    description="…",
    dimensions=[
        RubricDimension(
            key="absorptive_assimilation",
            name="Absorptive assimilation",
            description="…",
            anchor_low="…",
            anchor_mid="…",
            anchor_high="…",
            literature="Cohen & Levinthal 1990",
        ),
        …
    ],
)

STUDY = StudyConfig(
    …
    judgment_rubric=_MY_RUBRIC,
    extra_phases=[ConstructJudgingPhase()],   # opts into --judge
)
```

`extra_phases` is a list of `PhaseHandler` instances, small pieces of code that each run one extra stage (`studies/base.py::PhaseHandler`). The framework runs each handler in order after Phase 4. Two patterns are common:

1. **Reuse `ConstructJudgingPhase`** with a different `judgment_rubric` — the construct-judge ensemble works for any study with a rubric set.
2. **Author your own handler** by implementing the `PhaseHandler` protocol (here, a template in code). The protocol asks for all of these: `name`, `folder_prefix`, `should_run(*, study, outputs)`, `async run(...)` and `persist(*, out_dir, result, write_json)`. A handler without `should_run` stops the run with an error after the paid phases. Useful for non-LLM scoring layers, custom validation phases, or any post-deliberation phase that needs to read the run's outputs.

`StudyConfig.extra_phase_ids_for_manifest()` renders each handler as a `<module>:<ClassName>` identifier; the replication manifest does not embed those IDs directly today (`phases_captured` in `00_meta.json` names the phases that ran; for their IDs, a reviewer checks out the recorded commit, or restores that saved version of the code, and loads the study at that revision). See `tests/test_phase_handlers.py` for the contract.

### Per-study RAG corpus loader

To ground a new study's TMT deliberation in firm-specific source documents when `--rag` (the option that turns on document search) is set (grounding means giving agents real documents so their text can be traced to sources; it is unrelated to grounded theory):

```python
# studies/<slug>/rag_loader.py
import re
from typing import Optional

CORPUS_DISPLAY_NAME_PATTERN = "<slug>__{company}"
_SHA_RE = re.compile(r"sha256=([0-9a-fA-F]+)")

def load_corpus(company: str) -> Optional[dict]:
    """Resolve the Vertex AI RAG corpus for this company, if it exists.

    Read-only: does NOT auto-create. With `--rag`, the framework treats
    None as an error and stops; build the corpus first with
    `python -m rag.corpus_build`.
    """
    from rag import vertex_corpus
    display_name = CORPUS_DISPLAY_NAME_PATTERN.format(company=company)
    corpus_name = vertex_corpus.find_corpus(display_name)
    if not corpus_name:
        return None
    documents = []
    for record in vertex_corpus.list_files_in_corpus(corpus_name):
        # The build tool writes each file's fingerprint into `description`;
        # `docs/07_reproducibility.md` compares the `sha256` field.
        match = _SHA_RE.search(record.get("description") or "")
        documents.append({**record, "sha256": match.group(1) if match else ""})
    return {
        "corpus_name": corpus_name,
        "embedding_model": vertex_corpus.DEFAULT_EMBEDDING_MODEL,
        "documents": documents,
    }
```

Then on the `StudyConfig`:

```python
STUDY = StudyConfig(
    ...
    rag_corpus_loader="studies.<slug>.rag_loader:load_corpus",
)
```

The PI (principal investigator, the human running the study) then drops documents under `rag_corpora/<Company>/` (per the layout in `rag_corpora/README.md`) and builds the corpora with:

```bash
python -m rag.corpus_build --all-firms --study <slug>
```

Set `RAG_LOCATION` to a region (the geographic location of the rented computers) first: the build prints the region's tier (price level) for RAG Engine, Google's paid service that stores documents and searches them, and refuses Scaled, the dearer tier, unless you pass `--allow-scaled`, and the store (the corpus as loaded into Google's service) bills while it exists ([`10_rag_repo_plan.md`](10_rag_repo_plan.md) § Cost). A `--rag` run will then thread retrieval through Phases 1 / 2 / 4, and exits with an error for a firm whose corpus the loader cannot resolve. Detail: [`docs/10_rag_repo_plan.md`](10_rag_repo_plan.md) (the full RAG layer) and [`docs/11_ethnography_in_silico.md`](11_ethnography_in_silico.md) §11.4 (what the source channel adds to the field record).

## What a run records

After the run, `results/runs/<run_id>/00_meta.json` will contain:

```jsonc
{
  …
  "study_slug": "absorptive_capacity",
  "study_version": "0.1.0",
  "research_question": "How do firms develop and deploy absorptive capacity…",
  …
}
```

The CLI writes `manifest.json` into each run folder. See [`07_reproducibility.md`](07_reproducibility.md).

A reviewer can `import studies; assert studies.load_study('absorptive_capacity').version == '0.1.0'` (a short Python check) and confirm the framing version matches.

## Versioning your study

Bump `version` when you change any of:

- `research_question`
- `theoretical_lens`
- `debriefer_background_block`
- `construct_forbidden_vocabulary`
- `flagged_vocabulary`
- `strategic_question_template`
- `embedded_observation`

Use semver (semantic versioning, numbered major.minor.patch): bump minor for additions, major for breaking changes (a construct word removed, or the RQ rewritten). Existing runs persist `study_version=0.1.0`; new runs persist whatever is in the file at run time.

## What about ablation across studies

Ablation means changing or removing one part to see the effect. If you want to compare two construct framings of the same panel (e.g. "openness" vs "selective revealing"):

1. Create two studies — `openness_maneuvering` and `selective_revealing` — with the same scenario brief + roles but different RQ + lens + construct vocabulary.
2. Run the same `(company, industry_context, product_type)` cell (one combination of firm, industry context and product type) against each study.
3. Use `analysis.compare_runs.render_report(...)` to produce a side-by-side report.

The Observer and FieldNoter prompts will differ only in their respective word lists (the merged forbidden list and the flagged-vocab watch-list). The Debriefer prompts will differ in the RESEARCH CONTEXT block. Everything else — the deliberation, the artefacts (each role's strategy documents) — is identical (apart from LLM nondeterminism, the chance differences between any two replies).
