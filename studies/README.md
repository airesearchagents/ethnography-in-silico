# Create your own study

A **study** is one research question run on the framework (the shared software in this repository). It lives in its own folder, `studies/<slug>/` (a slug is a short name with no spaces), and supplies everything specific to that question: the question and lens (the theory the study will analyze through), the scenario (the setting of one simulated meeting and debrief, called a run: one firm, one industry context, one product type), the vocabulary the researcher agent (a language model set up to observe and question the team) must avoid, the topics for the debrief (that agent's interview of the team), and optionally its own document corpus (a collection of documents). Per-study roles and scenario definitions are planned but not yet wired in (connected to the running code; see below).

The framework (everything outside `studies/`) stays the same for every study. **To add a study, you should not need to edit framework code.** If you find you must, note it so the framework can be extended properly.

The worked example is `studies/openness_maneuvering/`, documented in [`openness_maneuvering/docs/01_study_anatomy.md`](openness_maneuvering/docs/01_study_anatomy.md). The full guide, with a complete code example, is [`docs/06_extending_to_new_studies.md`](../docs/06_extending_to_new_studies.md). Terms are defined in [`docs/GLOSSARY.md`](../docs/GLOSSARY.md).

## Five steps

**1. Create the folder.** Type these commands in a terminal (the window in which commands are typed).

```bash
mkdir studies/my_study
touch studies/my_study/__init__.py
```

The folder name is the study's slug: lowercase, with underscores.

**2. Define the study.** In `__init__.py` (the study's main file, written in Python, this project's programming language), create one `StudyConfig` object (a bundle of the study's settings) named `STUDY` (see the fields below). [`docs/06_extending_to_new_studies.md`](../docs/06_extending_to_new_studies.md) has a complete example you can copy.

**3. Check that it loads.**

```bash
python3 -c "from studies import load_study; print(load_study('my_study').name)"
```

**4. Run the safeguard tests on it.** These tests check that the researcher agent cannot see your research question while observing, and that the debriefer (the researcher agent in the debrief) gets the question with its anti-steering rule (not to lead agents toward what the study hopes to find). They run on a fixed list of studies, so add your slug to `STUDY_SLUGS` in `tests/test_methodological_invariants.py` and run:

```bash
scripts/run_tests.sh tests/test_methodological_invariants.py
```

With `embedded_observation=True` (the researcher agent knows the question while observing), `test_research_question_text_not_in_observer_instruction` and `test_research_question_text_not_in_field_noter_instruction` fail as expected; the rest must pass, and `tests/test_observation_stance.py` checks the embedded prompts.

Adding the slug does not cover two other checks. The test that construct words stay out of the debriefer's instructions runs only on `openness_maneuvering`, and the test that retrieval queries (the searches made in a corpus) leave out the question (`tests/test_rag_persistence.py`) names its own two studies. Extend them by hand for now; tests that discover studies automatically are planned (P2, a priority level in `ROADMAP.md`).

**5. Preview it for free, then run one scenario.** A dry run uses your real prompts with a stand-in for the model. It makes no model calls, costs nothing, reports the calls and tokens in each phase and an estimated cost, and saves every prompt for you to read.

```bash
python -m analysis.dry_run --study my_study --save-prompts <folder>
```

The next command calls real language models and costs money.

```bash
python3 run_research_session.py --study my_study --company <Firm> --industry-context Dynamic --product-type Novel
```

The items starting `--` are flags (options added to a command). The records appear under `results/runs/<run_id>/`. To see what a run makes, read the run folder's `README.md`.

## What a study sets

Required:

| Field | What it is |
|---|---|
| `name`, `slug` | Name and folder name. |
| `research_question` | Your question. The debriefer always sees it, as a guide for what to explore, with instructions not to steer the panel (the six simulated executives) and never to share the question. The observer and field noter (the researcher agent when summarizing and taking notes) see it only if `embedded_observation` is True. The panel never sees it. |
| `theoretical_lens` | The theory you will use in analysis. The debriefer sees it, marked as being for later analysis and not for its questions. The observer and field noter never see it. |

Usually set:

| Field | What it is |
|---|---|
| `version` | A version number, 0.1.0 unless you set it. Raise it whenever you change the study; it is recorded with every run. |
| `scenario_brief` | One sentence on the kind of organization simulated, for example "A pharmaceutical firm engaged in multiple R&D alliances." It appears on the company line of each role's prompt (the text sent to the language model). Without it, the prompt uses a generic line about a firm in a competitive industry. |
| `construct_forbidden_vocabulary` | Words the researcher agent must not introduce in its questions or notes, because they would steer the team toward your construct. The observer and field noter see this list even when they are blind to the question. |
| `flagged_vocabulary` | Words to log if agents use them unprompted. The observer and field noter see this list too. |
| `strategic_question_template` | The decision task the team deliberates. It can use `{product_type}` and `{direction_hint}` (slots filled in for each run). `{direction_hint}` is fixed framework text that says "AI" ("a novel AI product direction — something the firm does not already offer", or "an enhancement of the firm's existing AI offering"), so a study outside AI should leave it out. If omitted, a built-in task is used, which includes that text. |
| `debriefer_background_block` | Extra background for the debriefer, for example an industry primer. |

Optional:

| Field | What it is |
|---|---|
| `embedded_observation` | How the researcher observes. False (default): the observer and field noter are blind to the research question. True: embedded, they know it and can watch for what bears on it, at the risk of seeing what they expect. Either way they never see the lens, the debriefer knows the question and the panel does not. Each run records the choice. |
| `panel_roles` and `role_factories_module` | Meant for a different team: which roles take part, and a module (a Python file with one job) in your study folder that builds them. **In the schema (the template of fields a study may set) but not yet wired in (planned, P2):** nothing reads them, so every run uses the six-person top management team: CEO, CTO, COO, CMO, product strategist, product designer. |
| `contexts_module` | Meant for different scenario definitions, from a module in your study folder. **In the schema but not yet wired in (planned, P2):** nothing reads it. |
| `protocol_overlay` | Extra debrief topics, added to `protocols/ethnographic_protocol.yaml` (the shared debrief rules and topics). Topic ids must be letters from D to H. |
| `rag_corpus_loader` | Where each organization's documents come from, for grounded runs (`--rag`, retrieval-augmented generation: agents get passages from those documents). |
| `extra_phases` | Additional steps after the debrief. For example, the openness study can add a scoring panel; it is optional and specific to that study. |

## What you can and cannot change today

- **Team composition:** not yet. `panel_roles` and `role_factories_module` exist in the schema but are not wired in (planned, P2).
- **Scenarios:** not yet. `contexts_module` exists in the schema but is not wired in (planned, P2). `--industry-context` accepts only `Dynamic` or `Stable` and `--product-type` only `Novel` or `Enhancement`, and a typo fails. A study with other dimensions can only reuse these labels, and the text they add to prompts comes from `roles/context_definitions.py`.
- **Domain:** framework code still says "AI" in `{direction_hint}`, so a study outside AI must write its own `strategic_question_template` without that placeholder.
- **Deliberation workflow:** not yet per study. The framework has five modes (concurrent, round-robin, CEO-led, random initiator, parallel-then-discuss), and runs use the concurrent mode (all six roles act at once) by default.
- **Number of repeats per scenario:** run the command repeatedly; a batch runner (a tool for starting many runs in one go) is planned. `scripts/run_frontier_sweep.sh` is an older sweep that scores every run and is not part of the method.

Making all of these settable from one declarative study file (a settings file rather than code), with a template study and a command-line tool (used by typing commands) to create and validate studies, is planned. See [`ROADMAP.md`](../ROADMAP.md).

## Rules that keep the method sound

1. **Keep your research question and construct words out of instructions.** They belong only in the fields above, which the framework routes safely.
2. **Unless you choose embedded observation, do not give the observer or field noter your question,** even indirectly through role descriptions or the scenario brief.
3. **Raise `version`** whenever you change anything, so runs can be traced to the exact setup.
4. **Keep documents out of git (the tool that keeps the repository's shared history).** List them in a source list instead (see [`rag_corpora/README.md`](../rag_corpora/README.md)).
