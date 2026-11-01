# 5. Methodological invariants

This file documents the rules the framework (the shared software in this repository) enforces to keep the qualitative researcher inductive — and the tests (automatic checks of the code) that make those rules contestable rather than aspirational. An invariant is a rule that must always hold. The qualitative researcher here is an agent, a language model given a role, set up three ways: the Observer and FieldNoter watch and take notes, and the Debriefer questions the team, called the panel.

## The five invariants

| # | Invariant | Where enforced | Checked by |
|---|---|---|---|
| I1 | The study sets whether the **Observer** sees the research question, or RQ (see below). It never sees the study's theoretical lens, which is for later analysis | `roles/qualitative_researcher_agent.py::create_observer_agent` | `tests/test_methodological_invariants.py`, `tests/test_observation_stance.py` |
| I2 | The study sets whether the **FieldNoter** sees the research question (see below). It never sees the study's theoretical lens | `roles/qualitative_researcher_agent.py::create_field_noter_agent` | `tests/test_methodological_invariants.py`, `tests/test_observation_stance.py` |
| I3 | The **Debriefer** sees the question as a guide. Its questions explore it through what the team did, and each records its link to the question. The team never sees the question or the link. It may follow surprises and record new questions. If the team does not raise a topic, the debriefer is told to treat that as a finding; no field records it, so researchers establish it from the log | `roles/qualitative_researcher_agent.py::_render_research_context` | `tests/test_methodological_invariants.py`, `tests/test_no_construct_steering.py` |
| I4 | Prompts (text sent to a model) we write for the team carry none of the study's listed words (its `construct_forbidden_vocabulary`), apart from everyday uses of "open" in a role's inbox and action template ("Open ASKs", meaning questions colleagues sent it, and "open questions") and in the modes not yet used ("open discussion"), and no worked examples that suggest a strategy. Retrieved passages can carry them, because they are the firm's own words ([L13, L14](LEARNINGS.md)). The debriefer's own prompt contains the research question, and it may use a listed word only after a panelist has. Outside its `RESEARCH CONTEXT` block, its instructions carry listed words only in the forbidden-vocabulary (words the researcher may not use) block | `protocols/ethnographic_protocol.yaml::behavioural_rules`; thematic areas written in neutral words | `tests/test_no_construct_steering.py`, and `TestConstructWordsDoNotLeakIntoProse` in `tests/test_methodological_invariants.py` |
| I5 | Retrieval queries (the text a document search uses, when `--rag` gives roles passages from a firm's documents) never contain the research question. In the debrief, a role's query does include the researcher's question, so its framing can affect which passages return; every query and passage is logged | `rag/queries.py::build_role_turn_query`, `::build_artefact_query`, `::build_panellist_query` | `tests/test_rag_persistence.py::TestInvariantI5NoQueryLeakAcrossStudies` |

These five together are the methodological backbone of the framework. `scripts/run_tests.sh` runs their tests. The tests of I1 to I3 repeat for each study in `STUDY_SLUGS`: the real `openness_maneuvering` study and `_test_alt`, a synthetic study with completely different vocabulary, so the rules are not tied to the default study. The tests of I4 cover the openness study only, and part of its word list: they miss bare "open", "closed" and "modular", among others, and one helper can never fail. Stricter tests are planned (P1). The test of I5 names those same two studies and covers the three query builders.

For the methodological framing of why these invariants exist at all (observation, with records that human researchers code inductively, rather than a "TMT simulator with an observer"; TMT: top management team), see [`11_ethnography_in_silico.md`](11_ethnography_in_silico.md).

## Blind or embedded: a design choice

A study chooses (`embedded_observation` in `studies/base.py`; `DECISIONS.md` §51). Ethnographers normally enter the field with a question, and fieldworkers who do not know it are rare, so the openness study's main runs (a run is one complete simulated meeting and debrief) will use embedded observation. The four prototype runs (test runs on one firm, used to learn about the method) used the default.

- **Blind, the default.** A separate observer does not know the research question, so its notes are not shaped by what the study hopes to find. It may also miss what bears on the question.
- **Embedded.** The observer knows the question and can watch for what bears on it, at the risk of seeing what it expects. It still does not see the theoretical lens.

Either way the debriefer knows the question, the panel never does, and the researcher does not intervene. Each run's `00_meta.json` (its summary file) records the choice. The rest of this file describes the default.

Blindness is partial. A blind observer still receives the study's word list, which hints at the topic, and its model has read the same literature. Comparing blind and embedded observers on the same deliberation is a test worth running.

## Why blindness, methodologically

The framework's qualitative-research stance follows the **inductive / grounded-theory tradition** (Glaser & Strauss 1967; Charmaz 2014; Strauss & Corbin 1998). The core claim of that tradition is that categories should *emerge* from the data rather than being imposed on it. The single largest threat to that claim is **confirmation bias**: the researcher, knowing what they are looking for, sees it everywhere.

In a human-researcher field study, the conventional safeguards are reflexivity (the researcher writes about their own biases), peer debriefing, member checking, and triangulation. In an LLM-researcher framework (LLM: large language model), the analogous safeguard available to us is *prompt isolation*: keep the research question out of the data-collection prompt.

The Observer and FieldNoter prompts therefore contain:

- The scenario context (firm, year, industry, product type) — for situational awareness.
- The merged forbidden-vocabulary list — a methodological rule, presented without saying which words belong to which subset.
- The study's `flagged_vocabulary` watch-list — a capture mechanism for spontaneous panellist use, presented as "if any of these specific words are used by panellists, log them — do not interpret why".
- The observational discipline rules (record in the panel's own vocabulary; do not paraphrase into analytical categories; differentiate the roles; do not speculate beyond what the deliberation contains).

They contain NO reference to:

- The study's research question.
- The study's theoretical lens.
- Why the forbidden-vocab and flagged-vocab lists matter analytically, although the words themselves hint at the topic.
- Any other study-specific analytical framing.

This is what we call *blindness*. It is verified by the test class `TestObserverIsBlindToStudyFraming` (which checks that no prefix of `study.research_question` or `study.theoretical_lens` appears in the Observer instruction) and the analogous `TestFieldNoterIsBlindToStudyFraming`. A test class is a group of related tests, a prefix is an opening stretch of text, and an agent's instruction is the standing text that tells it who it is and how to behave.

## Why the Debriefer is NOT blind

The Debriefer's job is to ask follow-up questions of a TMT that has just deliberated. To do that intelligibly, the Debriefer needs to know what the study is about — otherwise its questions cannot be relevance-driven. Pure blindness for the Debriefer would produce questions that drift off-topic.

So the Debriefer DOES see the study's research question and theoretical lens, inside the `RESEARCH CONTEXT` block built by `_render_research_context(study)`. The block is structured deliberately:

```
RESEARCH CONTEXT (your starting point, not a checklist)
-------------------------------------------------------
This deliberation is being run as part of a study that starts from:

  Research question:
    {study.research_question}

  Theoretical lens (for later analysis, NOT for your questioning):
    {study.theoretical_lens}

  Additional background:
    {study.debriefer_background_block}

HOW TO USE THE RESEARCH QUESTION
--------------------------------
You work as an inductive qualitative researcher. The research question
is a guiding post: your questions are there to explore it, through the
things the panel actually did. Among the decisions, disagreements and
arrangements in the deliberation, prefer those that could teach you
something about it. It is not a rule for what to capture, and it may
itself be revised after this debriefing. For each question, record in
`research_question_link` how it could help, or mark it `adjacent` if you
are following something else. The panel never sees that field.

Never state, paraphrase, or hint at the research question to the panel.
Ask about what they did, in their words, without suggesting an answer.

The panel may or may not produce material directly relevant to this
research question. Follow the panel where they actually went in the
deliberation. Do NOT steer them toward the research question. If the
deliberation reveals nothing about the construct under study, that
absence is itself a finding — note it; do not manufacture relevance.

You are exploring a field, not administering an interview. When you
observe something interesting — surprising, puzzling, or unexplained —
explore it, even if it leads away from the research question. Adjacent
questions are welcome. Pay particular attention to what familiar
accounts of how firms decide would not lead you to expect: that may be
a new phenomenon, not an error. When an exchange raises a question
worth studying that the research question does not cover, record it in
`emerging_question`. The panel never sees that field. Record as many as
you find, and keep pursuing them in later questions.

Anchor each probe on items that were CONSEQUENTIAL in the deliberation
(decisions actually made, disagreements actually surfaced, items the
panel actually contested). A surprising item that does not relate to the
research question can still earn a question.
```

The Debriefer works as an inductive researcher: the question says where to begin, not what to capture. The research question can be revised between runs by the researchers, using the `emerging_question` entries saved in `04_interview/transcript.md`. The two binding phrases — "may or may not" and "do not steer / absence is itself a finding" — encode the framework's stance on what the Debriefer should do with the research question. The rule is "follow what the panel actually surfaced, and report it whether or not it matches the research question", not "find evidence of the construct".

`tests/test_methodological_invariants.py::TestDebrieferSeesStudyFramingButNonSteering` enforces both that the RQ and lens texts appear in the Debriefer instruction AND that the anti-steering phrases appear.

## The forbidden / flagged vocabulary distinction

Both the Observer and the FieldNoter see *two* vocabulary lists:

| List | Source | Role | Surfaced as |
|---|---|---|---|
| **Forbidden vocabulary** | `methodological_forbidden_vocabulary` (protocol YAML: the debrief's rules, in a plain-text format) + `study.construct_forbidden_vocabulary` (study config), merged | Words the researcher must NOT use in its own prose unless quoting a panellist verbatim | "Do NOT introduce any of these words in your own writing: …" |
| **Flagged vocabulary** | `study.flagged_vocabulary` (study config) | Words to LOG verbatim if a panellist uses them spontaneously | "If any panellist uses any of these specific words spontaneously, log the use in `flagged_vocabulary_used` … Do not interpret why these words might matter." |

The methodological reason for the distinction: the forbidden list is a *behavioural rule for the researcher* (don't introduce loaded vocab); the flagged list is a *capture trigger for the data* (if loaded vocab emerges from the panel, that's data — log it). Without the second list we would lose the ability to detect when the panel itself uses construct-specific vocabulary unprompted, which is a methodologically meaningful signal.

By default the two lists are identical (every construct word is both forbidden for the researcher and flagged for capture), but they can diverge — a study could flag "competitive advantage" as something to capture without forbidding the researcher from probing on it.

## The "construct words may only appear in the forbidden-vocab block" rule (I4)

This section covers the debriefer's side of I4. Construct-specific words may appear in the rendered Debriefer prompt ONLY inside the dedicated `FORBIDDEN VOCABULARY` list or inside the `RESEARCH CONTEXT` block (where the research question and lens are stated verbatim). They may NOT appear in instructional prose elsewhere — including in any thematic areas the study contributes via `StudyConfig.protocol_overlay`.

The protocol YAML enforces this by construction:

- The framework-level `behavioural_rules` block refers to the forbidden-vocabulary section by reference ("see FORBIDDEN VOCABULARY section below; treat it as binding") rather than inlining specific construct words.
- The framework-level thematic areas (A — decision anchoring, B — counterfactuals, C — disagreement and resolution, I — context sensitivity, J — reflection and unresolved) are study-agnostic and construct-neutral by construction.
- Study-supplied overlay (merged on top of the shared protocol) thematic areas (e.g. the openness study's D — differences in handling, E — who does the work, F — changes over time, G — what the firm gets and gives, H — position relative to others) are written in construct-*neutral* language. They must not name the construct or paraphrase it, and `tests/test_no_construct_steering.py` checks this — see `studies/openness_maneuvering/debriefing_overlay.yaml` for the worked example.

`tests/test_methodological_invariants.py::TestConstructWordsDoNotLeakIntoProse` enforces this with a regex-based (regex: a written pattern for finding text) leak detector: for each word in `study.construct_forbidden_vocabulary`, it scans the Debriefer instruction outside the forbidden-vocab block + outside the RESEARCH CONTEXT block, and fails if any match is found.

## How the invariants are tested

- `tests/test_methodological_invariants.py`: the blindness and debriefer test classes run on each study in `STUDY_SLUGS`. `TestStudySwapBehaviour` compares the two studies, and `TestConstructWordsDoNotLeakIntoProse` runs on the openness study.
- `tests/test_observation_stance.py`: blind is the default, and an embedded observer and field noter get the question and never the lens.
- `tests/test_no_construct_steering.py`: steering wording stays out of the team's prompts and the debrief topics, and the debriefer treats the question as a guide. It covers only the openness study so far.
- `tests/test_rag_persistence.py::TestInvariantI5NoQueryLeakAcrossStudies`: queries from the three builders leave out the question and lens.

To cover a new study, add its slug (short folder name) to `STUDY_SLUGS` in the test file, which adds runs of the blindness and debriefer classes. A study with embedded observation fails `test_research_question_text_not_in_observer_instruction` and `test_research_question_text_not_in_field_noter_instruction` as expected; the rest must pass.

To read what the team actually receives, `python -m analysis.dry_run --save-prompts <folder>` saves every prompt, with no model calls and no cost. Search those files for your study's words.

## Limitations these invariants do NOT address

The blindness invariants reduce *one* class of bias — prompt-level priming of the LLM toward construct-relevant categories. They do NOT address:

1. **Pre-training bias.** The LLM has read the strategy literature. "Open innovation", "value capture", and "selective revealing" are all in its training data (the text it learned from before we use it). Even with prompt blindness, the model's prior associations colour what it notices. We don't have a good lever for this; we document it.
2. **Researcher-as-LLM bias.** The framework uses an LLM as the qualitative researcher. That is itself a methodological choice with consequences that no prompt-level safeguard removes.
3. **Construct-vocabulary leakage through the panel.** If the TMT roles use openness vocabulary in their own deliberation (which a strategy-aware LLM is likely to do), that vocabulary then enters the researcher's session (here, what its prompts carry) via the live event stream. The researcher's discipline is to quote the panel's vocabulary back (since it emerged from the panel) rather than introduce it — but the construct is now *in the room*, even though the researcher didn't put it there.
4. **Flagged-vocabulary capture is interpretive.** The Observer is told "if a panellist uses any of these words spontaneously, log them". The Observer LLM makes the spontaneity judgement; we have not replaced that with a deterministic (same input, same result) regex pass. A reasonable future improvement is to add a post-hoc regex check over the deliberation log (reusing `roles/forbidden_vocab.py::check_utterance`) so the spontaneous-use detection is deterministic. Logged in `08_known_limitations.md`.

What the invariants *do* claim is that, conditional on running an LLM as researcher, the framework does not additionally bias the LLM by telling it what to look for. The framework's contribution to inductive fidelity is the bound we control; the rest is in the LLM itself.

## How to extend the invariants

Adding a new methodological rule:

1. Implement the rule in the relevant agent factory (code that builds an agent) or orchestrator (code that runs the phases).
2. Add a test to `tests/test_methodological_invariants.py`, parametric over the existing study fixtures, asserting the rule.
3. If the rule depends on a study's content (e.g. "the lens text must be at least 200 chars"), encode the assertion against `study.theoretical_lens` etc.
4. Document the rule in this file with a citation if it's grounded in the methodology literature.

The invariants file is the cheapest way to keep the framework's methodological commitments honest — they fail loudly when violated rather than degrading silently.
