# 8. Known limitations

This file lists what the framework (the shared software in this repository) explicitly does NOT claim, and the methodological caveats a reviewer should keep in mind when assessing findings produced on it. Terms are also explained in the [glossary](GLOSSARY.md).

The goal is to surface the framework's epistemic boundaries rather than hide them. Every limitation listed here is also an invitation — most are routes for future methodological development.

## Limitations of the LLM-as-researcher paradigm

### Limit 1. The qualitative researcher is a large language model

The Observer, FieldNoter, and Debriefer (one language model, the researcher agent, while it summarises, takes notes and questions the team) are all LLM (large language model) instances. This is a methodological choice with consequences no prompt-level safeguard (a rule written into the text, or prompt, sent to a model) can remove:

- **Pre-training bias.** The LLM has read the strategy / management literature. "Open innovation", "value capture", "absorptive capacity", "dynamic capabilities" are all in its training data (the text it learned from, before we use it). Even with prompt-level blindness to the research question (`05_methodological_invariants.md`), the model's prior associations colour what it notices. The framework cannot make the LLM forget what it read.
- **Reasoning opacity.** A human qualitative researcher can articulate why they noticed something in the field. An LLM cannot — at least not at the level of evidentiary detail a peer reviewer would require. The framework persists (saves) each response, but not the prompt that produced it (the prompts are in the code at the recorded commit, the saved version of the code, and `example_runs/prompts_as_run/` holds a copy for the published runs), and it does not persist the model's internal reasoning.
- **Stochastic outputs (involving chance).** Two runs (a run is one complete simulated meeting and debrief) of the same scenario (one firm, industry context and product type) with the same study config (settings) will produce different transcripts. Reproducibility (`07_reproducibility.md`) is sample-from-same-distribution, not exact replay.

What the framework controls for: prompt-level priming, vocabulary leakage, post-hoc-vs-live observation distinction. What it cannot control for: anything baked into the LLM's training.

### Limit 2. The TMT is also LLMs

The six TMT (top management team) roles are LLM instances. A "deliberation" is therefore a multi-agent (several language models, each given a name and a role) LLM-on-LLM exchange. This is what the framework studies — it does not claim the LLM TMT *is* a real TMT.

External validity to real TMTs is bounded by:

- LLMs lack tacit knowledge, organisational context, career incentives, interpersonal history, and the lived political reality of an executive committee.
- LLMs over-produce text. A real CTO might respond to a strategic question with a five-word objection; an LLM CTO will write 300 words.
- LLMs are agreeable by training. Without the cross-talk (roles joining in after a first reply) + PASS-biased (PASS is a reply meaning the agent has nothing to add) opt-in safeguards (`02_design_decisions.md` §3), every role would tend to agree with whichever role spoke last.

The framework is best understood as a study of **how LLM agents deliberate as a TMT under a given prompt regime**. It observes agents, not people, and does not assume that agent patterns match those of real TMTs. Because agents learn from human text and reason from firms' documents, their deliberation can suggest explanations researchers would not otherwise see. Propositions come at two levels. Those about agent teams can be tested with many runs. Those about firms are a further step: researchers derive them from agent patterns, and they stand on their own evidence, such as archival or public data on events after the models' training cutoff (the date their training text ends), so the test is not circular. A failed firm-level test rejects that proposition; it does not refute what agents did, and a passed test does not validate the agents.

## Limitations of the methodological safeguards

### Limit 3. Forbidden-vocabulary guard is regex-based

`roles/forbidden_vocab.py::check_utterance` (the part named `check_utterance` in that file) matches forbidden words (words the researcher agent must not use) via word-boundary regex (a written pattern for finding text, here whole words). It catches:

- Exact word occurrences (`open`, `value capture`)
- Multi-token (multi-word) entries with hyphens or spaces (`open-source`, `value capture`)

It does NOT catch:

- **Semantic paraphrases (rewordings with the same meaning).** "How publicly accessible was the inference API?" (an API is how one program asks another for a service; here, access to a model) carries the openness construct without using the forbidden word `open`. The guard passes; the priming has still happened.
- **Connotation.** "Was the API revealed or kept proprietary?" probes the same construct via Henkel's terminology, which is not on the forbidden list.

A future improvement is an LLM-based semantic guard (a small classifier, a program that assigns a label to text, checking whether a probe is construct-priming). The framework does not currently ship this.

### Limit 4. Flagged-vocabulary capture is LLM-mediated

The Observer is told "if a panellist uses any of these words spontaneously, log them in `flagged_vocabulary_used`". (A panellist is one of the six role agents in the debrief, the researcher agent's interview of the team.) The Observer LLM is the one making the spontaneity judgement and the verbatim-context extraction.

A reasonable future improvement is to add a post-hoc deterministic (fixed-rule, with no chance involved) regex pass over the deliberation log (the saved record of the team's discussion) that captures every flagged-word use independent of the Observer's interpretive read. The two captures could then be cross-validated. The framework does not currently ship this; the field `analysis/...` is where it would live.

### Limit 5. Construct vocabulary in the panel's mouth is still construct vocabulary

If the TMT roles use openness-construct vocabulary in their own deliberation (which a strategy-aware LLM is likely to do), the construct is now *in the room* — even though the researcher didn't put it there. The researcher's discipline is to quote the panel's vocabulary back (since it emerged from the panel) rather than introduce it — but the data is influenced.

The framework cannot prevent this; it can only document it. The `flagged_vocabulary_used` log is the auditable trail of when construct vocabulary entered via the panel.

### Limit 6. Long runs need a model with a large context window

Each debrief prompt carries the whole deliberation, the documents and the debrief so far, about 35,000 tokens (small pieces of text, often about three-quarters of a word) at most for a grounded run (one given a firm's documents) with 20 exchanges (a question and its replies). On models with smaller context windows (the most text a model can take in during one call), this becomes a constraint. The framework does not summarise this material.

### Limit 7. Construct-vocabulary measurement is method-A only

The openness study ships **Method A** (dictionary-based sub-dimensional scoring, counting listed words for narrow items within each dimension, `analysis/text_measures/dictionary.py`) for the construct-validity layer. The methodological plan (`studies/openness_maneuvering/docs/02_subdimension_measurement_plan.md`) specifies three additional candidate methods that are **deferred**:

- **Method B** — sentence-transformer embedding similarity (comparing lists of numbers that stand for a text's meaning). Less brittle than dictionary lookup on paraphrases; requires the `sentence-transformers` dependency (an extra package of code).
- **Method C / G** — BERTopic (software that groups texts into topics automatically) cross-run topic discovery. Surfaces themes the dictionary + embedding methods would miss because they were never in the prototype set; only valuable once ≥10 runs accumulate.
- **Pre-submission τ calibration** (setting a cut-off, τ) for Method B's cosine-similarity threshold (cosine similarity scores how alike two such lists of numbers are) against a human-coded validation set.

Until Methods B/G ship, the text-grounded construct-validity statement rests on the dictionary's regex lexicon (fixed word list) alone. That's a known floor on paraphrase robustness; the cross-vendor α statistic (Krippendorff's measure of agreement) of the LLM-judge ensemble (models that score a finished run against a scoring guide) is the complementary axis the dictionary cannot provide. Both scoring tools are optional, specific to the openness study and not part of the method in the proposal, in which human researchers read and code the records.

## Limitations of the study design

### Limit 8. The synthetic TMT is one TMT per cell

A real qualitative study runs interviews with multiple subjects. Here, each cell of the 2×2 design × 5 firms = 20 cells produces one TMT deliberation per LLM provider (the company supplying a model) per run. Even with several models and repeated runs, the unit count is small for any quantitative inference.

The framework is designed for **mode finding** (what patterns emerge across cells / providers) rather than **effect-size estimation**. Statistical claims should be hedged accordingly.

### Limit 9. The scenario design is bounded

The 2×2 of `industry_context` (Dynamic / Stable) × `product_type` (Novel / Enhancement) covers four scenario combinations. Real TMTs face many more. `StudyConfig.contexts_module` exists in the schema (the template of a study's settings) for replacing `roles/context_definitions.py` per study, but it is not yet wired in (planned, P2; P1 to P3 are priority levels in `ROADMAP.md`), so every study uses these axes.

A future study using a fundamentally different scenario taxonomy (e.g. "alliance type" × "knowledge similarity" for an absorptive-capacity study) will need that wiring first.

### Limit 10. No human in the loop

The framework runs fully autonomously: no human qualitative researcher intervenes between phases. A real ethnography would have the PI (principal investigator) iterating on the protocol, the question stems, the analytical framing. This framework does NOT have that — the PI's intervention is by editing the study config + the protocol YAML (the debrief's rules and topics, in a plain-text settings file) between runs, not within a run.

This is a deliberate design choice for reproducibility (a fully scripted run can be re-run; a human-in-the-loop run cannot). It is a limitation for inductive depth (a human ethnographer would notice things the LLM doesn't and adapt the probes accordingly).

## Limitations of the framework infrastructure

### Limit 11. Single-process ADK

All agents run in one Python process (one running program in the project's programming language), through the in-process delegation of ADK (Agent Development Kit, Google's software for building agents) rather than network A2A (agent-to-agent calls over a network). CPU contention (programs competing for the computer's processor) is not a concern for LLM-bound work, but a stuck loop in one role can stall the whole deliberation. The wall-clock (elapsed-time) and action-count caps are the safety net; they do not detect "slowly producing useless output" — only "running too long".

### Limit 12. No structured trace of LLM-internal reasoning

The framework persists the final response per call, but not the prompt itself (see Limit 1). It does NOT persist the LLM's chain-of-thought (working-out text, where supported), the intermediate function-call decisions inside `transfer_to_agent` chains (agents handing work to one another), or the raw token-level probabilities (the chances the model gave each next piece of text). Reviewers asking "why did the CEO choose to consult the COO at this moment?" have only the final SPEAK / ASK text (public remarks and questions to a colleague) to work with.

### Limit 13. The replication manifest does not include the protocol YAML content or extra-phase IDs

`manifest.json` (the file listing what produced a run) and `00_meta.json` (the run's summary file) record `study_slug` + `study_version`, and the manifest hashes (records a fingerprint computed from the contents of) the protocol, the study's overlay, the role definitions and the prompts' source files, so drift between two runs shows up. They do not record the dotted-path identifiers (names that point to code) of the `extra_phases`, the optional stages after the debrief, that ran. Runs A to D predate the manifest; `example_runs/short_check/` has one. Reviewers should check the recorded commit (`code_commit` in `00_meta.json`, or a manifest's `git_provenance.commit_sha`) and `git diff <old_commit> <new_commit> -- protocols/ethnographic_protocol.yaml studies/<slug>/` (a command that shows changes between two versions) when comparing runs across commits. The `extra_phases` that ran can be reconstructed by checking out the commit and calling `StudyConfig.extra_phase_ids_for_manifest()`.

### Limit 14. Test coverage is unit-heavy

The unit-test suite (small automatic checks that cost nothing) covers the framework's components in isolation. The live integration cells (tests that call real models; `tests/integration/test_cells_live.py` — six provider cells) exercise the full pipeline end-to-end but are gated on the `--run-live` option + `GOOGLE_API_KEY`, the secret code for Google's service, and cost real money to run (measured full-run figures are in `03_simulation_workflow.md` § Total cost shape). There is no continuous integration (tests that run automatically on each change), for the live pipeline or the unit tests: both are run by hand, with `scripts/run_tests.sh`.

This means: a refactor (a rewrite of code that keeps its behaviour) that breaks unit tests is caught when someone runs them; a refactor that subtly degrades the quality of the *live* LLM outputs (e.g. a prompt change that makes the LLM agree with itself more) is not caught until the next manual smoke (a quick first run to confirm nothing breaks). The methodological-invariants tests, which check rules that must always hold (parametric over study fixtures, meaning repeated for each prepared study), reduce this risk but do not eliminate it.

### Limit 15. RAG retrieval is vendor-locked to Google Vertex AI

The RAG (retrieval-augmented generation: searching a document collection and adding the passages found to a model's prompt) layer (`docs/10_rag_repo_plan.md`) is implemented against Google Vertex AI RAG Engine (Google's paid service that stores documents and searches them). A reviewer without access to GCP (Google Cloud Platform) cannot reproduce a `--rag` run (one with document search on) end-to-end; they can only verify the per-doc SHA256s (fingerprints computed from each file's contents) in `07_rag/corpus_manifest.json` against re-sourced documents. The trade-off and the rationale are recorded in `docs/02_design_decisions.md` §23 + `DECISIONS.md` §8. A port to a local backend (software on your own computer: sentence-transformers + Chroma) is feasible — `rag.vertex_corpus` is the only Vertex-specific module — and would let the framework run air-gapped (with no internet connection). This is planned (P1).

### Limit 16. Citation accuracy depends on the LLM populating `citations[]` honestly

The framework's per-role structured outputs (replies forced into fixed, named fields) include a `citations: List[Citation]` field that role agents populate when they draw on retrieved excerpts (`docs/02_design_decisions.md` §23). Quote verification in the comparison harness, a small program that runs a comparison (`analysis/compare_rag.py`), checks word for word every cited quote against the passages retrieved for that document — catches fabrications where the quote is not in them. But it does not catch the converse failure: a role agent that *does* use retrieved material to inform a claim but neglects to populate `citations[]` for it. We have no schema-level enforcement that "any claim influenced by a retrieved chunk MUST have a citation" (a chunk is a passage cut from a document) — the LLM either complies with the prompt instruction or it doesn't. Verified citations are honest; absence of citations is not a guarantee that retrieval didn't influence the output.

A possible mitigation is a parallel "anchored-claim discovery" pass on the deliberation transcript that searches for retrieval-grounded phrasings using the dictionary scorer's lexicon machinery. Not in scope today.

### Limit 17. The five-firm RAG corpus set is the PI's choice, not a representative sample

The framework commits a fixed per-firm folder structure for OpenAI, Meta, Alphabet, Anthropic, and HuggingFace under `rag_corpora/`. These five firms span closed-research (OpenAI, Anthropic, Alphabet) and open-weight (publishing their models' trained numbers; Meta, HuggingFace) postures so the openness construct has within-sample variance — but the choice is a methodological judgement, not a representative sample of the AI-industry population. A study using these five firms is a **mode-finding** study on this specific corpus (document collection), not a population estimate. The conclusion of any such study should be hedged accordingly: "across these five firms" rather than "in the AI industry".

## What the framework explicitly does not claim

To be unambiguous, the framework does NOT claim:

1. That LLM-produced TMT deliberations are representative of real TMT deliberations.
2. That LLM-produced qualitative research is equivalent to human qualitative research.
3. That patterns observed in LLM deliberations would replicate with human subjects.
4. That the framework's findings can be quantitatively generalised.
5. That two runs of the same configuration produce the same content.
6. That the construct vocabulary cannot enter the data — only that the researcher does not introduce it.
7. That the methodological-invariants tests are sufficient — they are necessary but the LLM may still produce biased outputs that the prompt does not constrain.

What the framework DOES claim:

1. That the methodological invariants (`05_methodological_invariants.md`) hold for the studies the tests cover, as checked by tests run with `scripts/run_tests.sh`: I1–I3 (rules numbered in `05_methodological_invariants.md`) for each study listed in `STUDY_SLUGS` in `tests/test_methodological_invariants.py`, a fixed tuple (a list set in advance), so a new study must be added to it; I4 for `openness_maneuvering`; I5 for `openness_maneuvering` and `_test_alt` (an invented study used for testing).
2. That the per-run output (transcripts, artefacts or strategy documents, observation summary, debriefing) is faithfully captured and can be re-rendered for review.
3. That the study framing is decoupled from the researcher behaviour — a new RQ (research question) + lens (the study's theory) can be substituted without modifying any prompt-level researcher code.
4. That each run records its study version, scenario, per-role models, researcher provider and code commit in `00_meta.json`, and that the prompts can be read from the code at that commit. Every completed command-line run also writes a fuller replication manifest (providers, file hashes, packages) to `manifest.json`. Runs A to D predate the recorded commit, the researcher provider and the manifest, and only run D records per-role models.
5. That the framework's behavioural choices (concurrent deliberation, live ethnography, blindness rules) are documented and grounded.

The boundary between (1)–(5) above and what the framework cannot claim is the boundary that should be cited in any paper using the framework.
