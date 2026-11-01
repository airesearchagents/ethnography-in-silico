# Openness maneuvering study: documentation

Documentation specific to the first study built on the framework (the shared software in this repository): ethnography in silico (agents simulate a team, a researcher agent observes and debriefs them, and human researchers code the records) applied to how firms maneuver the openness of their digital assets. Framework-level documentation lives in [`docs/`](../../../docs/README.md): architecture, workflow, invariants (rules that must always hold), reproducibility and the RAG layer (retrieval-augmented generation: searching documents and adding the passages found to a model's prompt). Terms are defined in [`docs/GLOSSARY.md`](../../../docs/GLOSSARY.md).

1. [**Study anatomy**](01_study_anatomy.md). The study as a worked example: what each `StudyConfig` (the study's settings) field holds and how it reaches the prompts (the text sent to the language models).
2. [**Sub-dimensional measurement plan**](02_subdimension_measurement_plan.md). Archived plan from an earlier design; scoring is optional and not part of the method. The sub-dimensions of the openness rubric (a scoring guide), three-channel scoring (public, private, researcher) and Method A (anchored dictionary: counting words from fixed lists tied to a concept).
3. [**Frontier-model execution sweep**](03_frontier_sweep_plan.md). Archived plan from an earlier design. The cross-vendor run design (a sweep, or planned set of runs, across the most capable models of several companies) and its cost model.

Study code lives alongside these documents: `__init__.py` (the `StudyConfig`), `debriefing_overlay.yaml` (the study's own debrief topics), `subdimension_lexicon.py` (its word lists) and `rag_loader.py` (which finds a firm's documents).
