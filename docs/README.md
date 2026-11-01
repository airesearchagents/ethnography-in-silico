# Framework documentation

This folder is the go-to place for understanding how the simulation framework (shared software that any study can use, not a conceptual framework) is built and how it carries qualitative research forward. [`GLOSSARY.md`](GLOSSARY.md) explains the terms used throughout.

## What is this framework?

**A method for conducting qualitative ethnography on synthetic subjects (simulated by AI, not real people).** A team of language-model agents deliberates while a researcher agent observes, keeps field notes and then debriefs them, and every run is saved as linked text records. The root [`README.md`](../README.md) has the overview and quickstart.

## How to read these docs

File numbers show the order in which documents were written, not a reading order. Numbers 04, 09 and 12 moved into the study (`DECISIONS.md` §34), and 13 is unused. Pick the route that fits you.

### Reviewing the method (about an hour)

1. [`../README.md`](../README.md): the overview, and what the records can and cannot show.
2. [`LEARNINGS.md`](LEARNINGS.md): what the pilot (the earlier study that preceded this framework, built on other software, CrewAI) and prototype runs (four test runs simulating one firm, not study results) taught us, and what researchers should do about it. Start with its summary table.
3. [**5. Methodological invariants**](05_methodological_invariants.md): the five rules (I1 to I5) that keep the research question from steering agents, and how they are tested.
4. [**8. Known limitations**](08_known_limitations.md): what the framework can and cannot evidence.
5. [`REPRODUCE.md`](REPRODUCE.md): how to reproduce the openness study, where to find the pilot, and the cheapest test for each question.
6. [`../example_runs/`](../example_runs/README.md): records of four prototype runs, with a walkthrough of one.

For the reasoning behind the method, read [**11. Ethnography in silico**](11_ethnography_in_silico.md): what the framework is for, where the three ethnographic commitments live in code, the four channels of field data, and the auditing steps a qualitative reviewer can apply to any run folder.

### Adding a study

1. [`../studies/README.md`](../studies/README.md): how to create your own study.
2. [**6. Extending to new studies**](06_extending_to_new_studies.md): how to add `studies/<slug>/` (slug: a short name with no spaces) without touching the framework, and the limits on this.
3. [**Study anatomy**](../studies/openness_maneuvering/docs/01_study_anatomy.md): the openness study as a worked example, and how each part ends up in the prompts.

A new study keeps its own documents under `studies/<slug>/docs/`. For the first study, see [`studies/openness_maneuvering/docs/`](../studies/openness_maneuvering/docs/README.md).

### Changing the code

1. [**1. Architecture**](01_architecture.md): component map, dependency graph (which parts rely on which), what each module owns.
2. [**3. Simulation workflow**](03_simulation_workflow.md): what happens when you run `python3 run_research_session.py`, with the code paths for each phase.
3. [**7. Reproducibility**](07_reproducibility.md): the replication manifest (a file recording what produced a run), folder layout and API-key (a secret code that identifies who is using a service and who pays) redaction. Start with its short version at the top.
4. [**10. RAG-grounded TMT deliberation**](10_rag_repo_plan.md): the retrieval (document search) layer, if you will use `--rag`. RAG is retrieval-augmented generation: searching documents and adding the passages found to a prompt. TMT is a top management team.
5. [**2. Design decisions**](02_design_decisions.md): 24 numbered decisions, for reference. Its table of contents groups them by theme.

### Design history

These record earlier plans. Where they differ from the code, the code is right.

- [**14. Virtual ethnography field protocol**](14_virtual_ethnography_field_protocol.md): the design document behind the researcher agent (draft v2, May 2026).
- [**Sub-dimensional measurement plan**](../studies/openness_maneuvering/docs/02_subdimension_measurement_plan.md): for the optional scoring, which is not part of the method.
- [**Frontier-model execution sweep**](../studies/openness_maneuvering/docs/03_frontier_sweep_plan.md): a planned set of runs across several companies' newest models, not carried out.

## Verifiability

Every methodological claim in these documents points to:

- **A code file**, usually `relative/path.py::function`, where the behaviour is implemented.
- **A test file**, `tests/test_xxx.py`, where the behaviour is enforced.

You can audit any claim by reading the cited file. If a claim and the code diverge, the code is the source of truth and the document is wrong.

## Honest framing

This is a research framework that uses large language models in two distinct researcher roles: as the TMT members being studied, and as the qualitative ethnographer studying them. Both are methodological choices with consequences for what the framework can and cannot evidence. The framework's design tries to make those choices visible, contestable, and reproducible, not to hide them. See `08_known_limitations.md` for what we explicitly do *not* claim.

## Other documents

- [`../DECISIONS.md`](../DECISIONS.md): numbered decision log, split into framework and study parts, with an index at the top. It records what was decided and why; the code-cross-referenced design rationale is in `02_design_decisions.md`.
- [`../ROADMAP.md`](../ROADMAP.md): what is built and what is planned.
