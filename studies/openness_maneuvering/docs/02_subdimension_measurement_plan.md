# Sub-Dimensional Openness Measurement Plan

**Status.** Archived plan from an earlier design, kept for the record. The method in the proposal is human coding of the records; word-based scoring (`--subdimension-scores`) and judge scoring (`--judge`) are optional, off by default and not part of it. For the current plan see [`ROADMAP.md`](../../../ROADMAP.md).

This is the methodological design document for the openness study's sub-dimensional measurement layer. **Method A** (anchored dictionary scoring: counting words and phrases from fixed lists tied to each concept) is implemented end-to-end: the lexicon (the word lists) at `studies/openness_maneuvering/subdimension_lexicon.py`, the scorer at `analysis/text_measures/dictionary.py`, private-channel persistence (saving each role's hidden notes, draft and inbox) on the run folder, and the `--subdimension-scores` CLI flag (an option added to a typed command) that writes `06_subdimension_scores/{headline,headline_by_role,per_subdimension,per_dimension}.csv` (CSV: plain-text tables that any spreadsheet can open) + a markdown summary (plain text with simple formatting marks). **Method B** (embedding-anchored similarity, `sentence-transformers`; an embedding is a list of numbers standing for a text's meaning) and **Method C / G** (cross-run topic discovery with BERTopic, an automatic topic-modelling tool, needs ≥10 accumulated runs) are deferred. This document is the methodological rationale behind the citable instruments. Terms are defined in [`docs/GLOSSARY.md`](../../../docs/GLOSSARY.md).

**Scope.** What numbers to compute, on which text, with which methods, in which output shape — across **three channels (kinds of record: public + private + researcher), 7 dimensions, 26 sub-dimensions, 2 measurement methods, per-role attribution where the source is role-attributable**.
**Out of scope:** Public-vs-private *gap* analysis (we report the numbers separately; comparing them is later work).

---

## 9.1 Motivation

The optional Phase 5 ensemble (the group of judge models that score a finished run: `gemini_pro` + `claude` + `openai` when this was written, with `deepseek` added later, `DECISIONS.md` §27) scores the simulation against the 7-dimensional rubric (scoring guide) defined in `studies/openness_maneuvering/__init__.py` (rubric v0.2 — split `boundary_permeability` into inbound/outbound per Dahlander & Gann 2010 and added `temporal_openness_maneuvering` per Henkel 2006 / Alexy, Henkel & Wallin 2013). Each LLM (large language model) judge collapses 2–5 latent sub-constructs per dimension into one Likert score (a numbered rating scale, 1–7). Two consequences:

1. **Construct opacity.** When a judge returns `component_disclosure = 5`, we can't tell whether it's because the firm openly released model weights (sub-construct 1a), because it granted a permissive license (sub-construct 1c), or because the judge averaged over a mixed signal.
2. **Inter-judge instability.** On the Anthropic / Dynamic / Novel / 2032 run, Krippendorff's α came in at −0.04 — essentially zero agreement. We suspect this is driven by the three judges integrating sub-construct signals with different implicit weights, not by genuine construct ambiguity.

A sub-dimensional, text-grounded measurement layer gives us:

- **Transparency.** Every score traces to a sub-construct and to evidence sentences.
- **Reproducibility.** A dictionary-based or embedding-anchored method runs identically on the same text every time; no inter-judge noise.
- **Asymmetric resolution.** Some sub-constructs are highly lexicalised (expressed in set words, e.g. license names); others are not (e.g. value-capture intent). The plan is explicit about which sub-dimensions are measurable to what fidelity.

This layer **does not replace** the LLM-judge ensemble. The judges keep producing dimension-level scores; the text-based measures produce sub-dimension-level scores. Convergence between the two is itself a methodological result.

---

## 9.2 Channels

Per the instruction of the principal investigator (the lead researcher), the simulation produces **three distinct signal channels** and all three are reported separately. The public/private gap is **not** computed here — it is a separable research question.

### 9.2.1 Public channel (firm-enacted commitments)

This is what the LLM-judge ensemble largely consumes (see `orchestrator/construct_judging.py::_build_judge_inputs`) — minus the field notes (the running notes of the researcher agent, a language model set up to observe the team), which are broken out into their own channel (§9.2.3). The public channel represents what the firm has *publicly committed to* during the simulated deliberation (Phase 1, the team's discussion):

| § | Source | File / data structure | Size per run (~) | Role-attributable? |
|---|---|---|---|---|
| P1 | 6 strategic artefacts (the strategy documents each role writes) | `ArtefactBundle.artefacts` (Phase 2 output) | 50 KB | YES (each artefact carries `role`) |
| P2 | Public deliberation transcript | `DeliberationLog.events` (Phase 1 output, public-only) | 45 KB | YES (each event carries `role`) |
| P3 | Observation summary | `ObservationSummary` (Phase 3 output) | 6 KB | NO (researcher's structured summary) |
| P5 | Debriefing transcript (the researcher agent's interview of the team) | `DebriefingTranscript.exchanges` (Phase 4 output) | 175 KB | PARTIAL (each response inside an exchange carries `role`; the exchange itself is initiated by the researcher) |

### 9.2.2 Private channel (firm-internal deliberation)

The private channel is the firm's **internal deliberation state** — held in `SharedState.role_states[role]` during Phase 1 and saved to `06_private_channel/` in the run folder. (§9.6.1 records how that was planned.) Working drafts (Q2) are part of this channel: the final draft IS the public artefact's precursor, but at deliberation time it was strictly private to the authoring role.

| § | Source | File / data structure | Role-attributable? | Notes |
|---|---|---|---|---|
| Q1 | Per-role scratchpads (private notes) | `RoleState.scratchpad: List[str]` ([`concurrent_mode.py`](../../../orchestrator/concurrent_mode.py)) | YES | Every `SCRATCHPAD` action (one move by a role in the discussion) appends one note. Accumulates across the role's turns. |
| Q2 | Per-role working drafts | `RoleState.draft: str` ([`concurrent_mode.py`](../../../orchestrator/concurrent_mode.py)) | YES | Only the **latest** draft is preserved — `DRAFT` actions REPLACE, not append. |
| Q3 | Inbox (the private questions and answers a role receives from colleagues) content — private answers | `DirectedMessage` with `answer_visibility="private"` | YES (sender + recipient) | Private answers go only to the asker's inbox, not the public transcript. |
| Q4 | Inbox content — questions | `DirectedMessage(kind="ASK")` | YES (sender + recipient) | The text of the question. ASKs (questions put to one colleague) are publicly echoed, so the question text is also in the public channel — but here we attribute it to the asking role rather than to the transcript. |

#### Roster note on working drafts (Q2)

The framework persists only the *final* draft each role committed to before Phase 2. We do **not** have an iteration history of how the draft evolved — the granular DRAFT-replacement events are not logged. This is a flagged limitation (see §9.8 decision 5): the orchestrator (the code that runs the phases) could be extended to append `DraftSnapshot(timestamp, role, body)` records to `SharedState`, but for the first version we accept only the final snapshot.

### 9.2.3 Researcher channel (researcher-interpreted observation)

The running notes of the FieldNoter (the researcher agent while the team deliberates) are the **researcher's** interpretation of the deliberation in real time. They are produced by a researcher-role agent, not by the TMT (top management team: the six role agents), and they encode interpretation rather than firm commitment. They therefore form their own channel.

| § | Source | File / data structure | Size per run (~) | Role-attributable? |
|---|---|---|---|---|
| R1 | Live field notes (researcher's running prose) | `field_notes` list (researcher stream) | varies (often 10–30 KB) | NO (FieldNoter agent is not a firm role) |

Holding the researcher channel apart from the public channel preserves a clean methodological boundary: a sentence like *"the team showed little hesitation about open-sourcing the eval harness"* is the researcher's read on the panel, and conflating it with the panel's own artefacts would contaminate the firm-commitment signal. The LLM judges in `_build_judge_inputs` currently see this content alongside P1–P5; the sub-dimensional measurement layer treats it as a separate signal source.

---

## 9.3 Sub-dimension framework

The 7 rubric dimensions in `studies/openness_maneuvering/__init__.py` are decomposed into 26 sub-dimensions below. Each sub-dimension has:

- A short construct definition.
- **Pro-openness markers** — phrases / patterns (regular expressions, or regexes: written patterns for finding text, in which `.*` means any text in between) that move the score up.
- **Anti-openness markers** — phrases / patterns that move it down.
- A **measurability rating** — H (high), M (medium), L (low) — for how reliably text alone can score it.

### 9.3.1 Dimension 1 — Component disclosure (Henkel 2006, selective revealing)

| Sub | Name | Construct | Pro-openness markers | Anti-openness markers | M |
|---|---|---|---|---|---|
| 1a | Asset class disclosed | *Which* technical asset is opened: weights, training data, methods, evaluation code, API (the way other programs reach a service) surface | `release.*weights`, `open-source.*model`, `training data.*public`, `eval(?:uation)?.*code.*public`, `model card`, `dataset card` | `proprietary weights`, `closed.*model`, `internal.*data`, `unreleased`, `kept proprietary` | **H** |
| 1b | Depth of disclosure | Full vs partial vs staged vs abstract-only | `full(?:y)? open(?:-source)?`, `complete release`, `every (?:weight|checkpoint)` | `partial(?:ly)? open`, `staged release`, `gated access`, `approved researchers only`, `summary only`, `paper only` | H |
| 1c | License regime | Research-only / non-commercial / permissive (MIT, Apache 2.0) / restrictive commercial | `MIT licen[cs]e`, `Apache(?:[- ]2\.0)?`, `permissive licen[cs]e`, `BSD`, `CC[- ]BY` | `non-commercial`, `research(?:-| )only`, `proprietary licen[cs]e`, `enterprise licen[cs]e`, `royalty`, `restrictions on use` | H |
| 1d | Temporal posture | Immediate vs delayed vs conditional vs never | `release(?:d)? today`, `available now`, `on (?:launch|day one)` | `embargo`, `delayed release`, `after (?:GA|launch)`, `subject to.*review`, `never (?:open|release)` | M |

Total: **4 sub-dimensions, all medium-high measurability**.

### 9.3.2 Dimension 2 — Process openness (Chesbrough 2003, inbound open innovation, OI)

| Sub | Name | Construct | Pro-openness markers | Anti-openness markers | M |
|---|---|---|---|---|---|
| 2a | External code contribution | External developers can submit PRs (pull requests: proposed code changes) / contribute upstream (to the original project) | `pull request`, `contributor`, `CLA` (contributor licen[cs]e agreement), `community contribution`, `upstream(?:ing)?` | `internal contributors only`, `no external commits`, `closed development` | M |
| 2b | Public governance / RFC | Roadmap, design docs, RFC (request for comments: a public design proposal) process all public | `public roadmap`, `open RFC`, `design doc(?:ument)? in public`, `community vote` | `internal roadmap`, `closed-door design`, `confidential strategy` | M |
| 2c | Academic / research partnership | Joint research, residencies, fellowships | `joint research`, `academic partner`, `residency programme`, `visiting (?:researcher|scientist)`, `fellowship` | `no external research`, `internal R&D only` | M |
| 2d | Open development practice | Public issue tracker, Slack/Discord/forum, working in the open | `working in the open`, `public issue tracker`, `community (?:slack|discord|forum)`, `transparent development` | `internal jira`, `private slack`, `closed beta` | M |

Total: **4 sub-dimensions, all medium measurability** — surface markers exist, but distinguishing genuine openness from "open-washing" requires LLM judgment.

### 9.3.3 Dimension 3 — Boundary permeability (broad OI literature)

| Sub | Name | Construct | Pro-openness markers | Anti-openness markers | M |
|---|---|---|---|---|---|
| 3a | Publication intensity | Peer-reviewed papers, preprints, tech reports | `(?:peer[- ]reviewed )?paper`, `pre[- ]print`, `arxiv`, `technical report`, `we (?:publish|published)`, `NeurIPS`, `ICML`, `ACL` | `do not publish`, `unpublished`, `internal report only` | H |
| 3b | Talent flow | Hiring from + losing to competitors; dual affiliations | `hired from`, `joined from`, `dual(?:-| )affiliat`, `joint appointment`, `sabbatical at` | `non-compete`, `garden leave`, `restricted post-employment` | M |
| 3c | Public presence | Conference talks, podcasts, public posts by employees | `keynote`, `conference talk`, `podcast`, `public talk`, `tech talk` | `no external speaking`, `media-trained`, `pre-approved comms` | M |
| 3d | NDA / IP enforcement | NDA strictness, trade-secret framing, litigation | `(?:trade )?secret`, `non[- ]disclosure`, `confidential`, `IP enforcement`, `patent (?:claim|portfolio)` | `no NDA`, `open IP policy`, `dedicated to public domain` | M |

Total: **4 sub-dimensions, one high and three medium**.

### 9.3.4 Dimension 4 — Ecosystem orchestration (Jacobides, Cennamo & Gawer 2018)

| Sub | Name | Construct | Pro-openness markers | Anti-openness markers | M |
|---|---|---|---|---|---|
| 4a | Developer programs | SDKs (toolkits from a company for using its service), dev relations, hackathons, grants | `SDK`, `developer (?:program|relations|advocacy)`, `hackathon`, `developer grant`, `startup program` | `no developer programme`, `internal-only SDK` | M |
| 4b | Partner / complementor incentives | Revenue share, marketplaces, certified-partner programs | `partner program`, `marketplace`, `revenue share`, `app store`, `certified partner` | `direct sales only`, `no marketplace`, `pipeline (?:not|isn'?t) ecosystem` | M |
| 4c | Standards-body participation | W3C, ISO, IEEE, industry consortia | `W3C`, `IEEE`, `ISO`, `working group`, `standards body`, `consortium`, `MLCommons` | `proprietary standard`, `our own standard`, `no standards involvement` | M |
| 4d | Hub-vs-node framing | Linguistic posture: platform/ecosystem/complementors vs pipeline/competitor | `platform`, `ecosystem`, `complementor`, `coordinate`, `orchestrate` | `pipeline`, `direct competitor`, `we own the (?:full )?stack`, `vertical(?:ly)? integrated` | M |

Total: **4 sub-dimensions, all medium**. 4d is the most paraphrase-prone; dictionary alone is brittle.

### 9.3.5 Dimension 5 — Value capture posture (Teece 2007)

| Sub | Name | Construct | Pro-participation markers | Pro-control markers | M |
|---|---|---|---|---|---|
| 5a | Primary monetisation mechanism | Direct sales / per-token / subscription / freemium / open-with-services / platform fee | `freemium`, `usage[- ]based`, `consumption pricing`, `open core`, `services revenue`, `platform fee`, `marketplace fee` | `enterprise (?:tier|licen[cs]e)`, `seat licen[cs]e`, `per[- ]seat`, `premium tier`, `pricing power` | M |
| 5b | IP enforcement intensity | Patents, trade secrets, litigation framing | `(?:dedicated to|in the) public domain`, `we don'?t patent`, `defensive only` | `patent portfolio`, `patent claim`, `injunction`, `infringe`, `we (?:will )?sue`, `cease and desist` | M |
| 5c | Network-effect framing | Explicit mention of network effects, two-sided markets | `network effect`, `two[- ]sided market`, `multi[- ]sided platform`, `the more (?:users|developers).*the more` | (no clean negative markers — absence is the signal) | L |
| 5d | Switching cost / lock-in | Proprietary formats, exclusive partnerships, vendor lock-in | `interoperab(?:le|ility)`, `portab(?:le|ility)`, `data export`, `no lock[- ]in` | `lock[- ]in`, `switching cost`, `proprietary format`, `exclusive partnership`, `non[- ]portable` | L |
| 5e | Indirect monetisation | Data-network effects, ecosystem rents, complementor fees | `data network effect`, `ecosystem (?:rents|fees)`, `we monetise the (?:network|ecosystem)` | `direct (?:sales|revenue) only`, `no indirect monetisation` | L |

Total: **5 sub-dimensions, two medium and three low**. This is the dimension where the dictionary method is weakest — strategic intent is highly paraphrasable. Method B (embedding) is essential here.

### 9.3.6 Summary

**26 sub-dimensions total**: 4 + 4 + 2 + 4 + 4 + 5 + 3 across the 7 dimensions (`component_disclosure`, `process_openness`, `boundary_permeability_inbound`, `boundary_permeability_outbound`, `ecosystem_orchestration`, `value_capture_posture`, `temporal_openness_maneuvering`). Distribution by measurability (final count after the lexicon was carefully constructed in `studies/openness_maneuvering/subdimension_lexicon.py`):

- **High (H):** 4 — asset_class_disclosed, depth_of_disclosure, license_regime (in D1), publication_intensity (in D3)
- **Medium (M):** 14
- **Low (L):** 3 — network_effect_framing, switching_cost_lockin, indirect_monetisation (all in D5)

(Earlier sketches said 5 / 13 / 3; the careful lexicon walks temporal_posture back from H to M because when-language is paraphrasable in ways that what/how/license-language is not.)

The methodology should report the measurability rating alongside the score so a reviewer knows where to apply scepticism.

---

## 9.4 Measurement methods

Two methods produce per-sub-dimension scores. A third method (topic modelling) is **discovery-only** and does not contribute to scores.

### 9.4.1 Method A — Anchored dictionary scoring

For each sub-dimension, the lexicon in §9.3 defines pro-openness markers `P` and anti-openness markers `A`.

**Algorithm.** For each text span `s` (sentence-level after standard tokenisation, or splitting text into sentences and words):

1. Match each pattern from `P` and `A` against `s`. Patterns are regex (case-insensitive, lemmatised, or reduced to base word forms, where the regex permits).
2. Apply a **negation window of ±3 tokens (here, words)**: if a negation token (`not`, `no`, `never`, `don't`, `doesn't`, `without`) appears within the window of a hit, the polarity flips. So `"we are not proprietary"` registers as a pro-openness hit on sub-dimension 1c, not anti.
3. Count: `n_pro(s)`, `n_anti(s)` per sub-dimension.

**Per-document score for sub-dimension `j`:**

```
raw_j = sum_s n_pro_j(s) - sum_s n_anti_j(s)
density_j = raw_j / total_sentences_in_doc
```

**Per-channel score for sub-dimension `j`:**

```
score_A_j(channel) = sum over docs in channel of density_j weighted by doc-length
```

Output is a real number in roughly `[-1, +1]`. Positive ⇒ pro-openness signal exceeds anti-openness signal in that channel for that sub-dimension. Magnitude is **not** Likert — do not convert.

**Pros / cons.**

- ✅ Fully transparent — every hit can be cited back to the source span.
- ✅ Sub-second runtime per document.
- ✅ The lexicons themselves become a citable methodological artefact.
- ❌ Brittle to paraphrase: "we will keep the model behind closed doors" doesn't match `proprietary weights`.
- ❌ Lexicon construction is labour-intensive and biases-prone — must be peer-reviewed.

### 9.4.2 Method B — Embedding-anchored similarity

For each sub-dimension, we expand the rubric anchors (currently 2 sentences each in `studies/openness_maneuvering/__init__.py`) into 3–5 **exemplar passages** drawn from the literature, the rubric author's own examples, or canonical industry artefacts (Llama 2 release blog, OpenAI's "GPT-4 technical report", Stability AI's Stable Diffusion launch, etc.).

**Anchor structure (extended).** For each sub-dimension we maintain three exemplar sets:

```yaml
component_disclosure_1a:
  anchor_low_exemplars:
    - "All model weights, training data, and evaluation code are firm-confidential."
    - "We share research findings only via peer-reviewed papers; no artefacts are released."
  anchor_high_exemplars:
    - "We release full model weights under Apache 2.0, the complete pre-training dataset under CC-BY, and our evaluation harness on GitHub."
    - "Llama 2 7B / 13B / 70B weights, tokenizer, and inference code are available for commercial and research use."
```

**Algorithm.** Use `sentence-transformers/all-MiniLM-L6-v2` (an embedding model: CPU-friendly, meaning it needs no special chips, 22 MB, well-validated). For each text span `s`:

1. Embed `s` → `e_s` (384-dim vector: a list of 384 numbers).
2. Embed each exemplar in `anchor_low_exemplars` → average → `e_low`. Same for high → `e_high`.
3. Compute `delta_j(s) = cos(e_s, e_high) - cos(e_s, e_low)`, where `cos` is cosine similarity (how alike two lists of numbers are; near 1 means very alike).
4. **Relevance filter:** keep `s` for sub-dimension `j` only if `max(cos(e_s, e_high), cos(e_s, e_low)) > τ` where `τ ≈ 0.30` (sentence must be topically related; otherwise it contributes noise).

**Per-document score:**

```
score_B_j(doc) = mean over kept s of delta_j(s)
```

**Per-channel score:**

```
score_B_j(channel) = length-weighted mean of score_B_j(doc) across docs in channel
```

Output is again roughly `[-1, +1]`, comparable to Method A but with different sources of error.

**Pros / cons.**

- ✅ Captures paraphrase and topical proximity.
- ✅ Same model runs on every sub-dimension — no lexicon labour per sub.
- ❌ Embedding similarity sometimes latches onto topical proximity rather than openness valence (a sentence saying "weights are proprietary" might be more similar to an `anchor_high` exemplar that *also* talks about weights than to an `anchor_low` exemplar that talks about R&D processes).
- ❌ Model is a black box — can't be cited back to a transparent rule.

### 9.4.3 Method C — Topic modelling (discovery / validation only)

Run **BERTopic** (UMAP + HDBSCAN, which compress embeddings and group similar ones, on sentence-transformer embeddings) on the **pooled** corpus (here, the collected run text) across all runs in a study (e.g. all 4 cells, or combinations of industry context and product type, from `tests/integration/test_cells_live.py` × however many replication runs).

- Output: a list of discovered topics with representative keywords and a per-topic prevalence per run.
- Use: **manually map** each discovered topic to one of the 26 sub-dimensions (one-time exercise per study) and ensure the mapping has good coverage. If a sub-dimension has no associated topic in the corpus, the LLM judges' scores on that sub-dimension are noise (the panel never talked about it).
- Does **not** contribute to the per-run score.

Topic modelling at single-run scale is unreliable (BERTopic typically wants ≥500 documents; one run produces ~150 sentences in the public channel). **C is a cross-run, study-wide validation step**, not a per-run number.

### 9.4.4 Why no LLM scoring at the sub-dimension level?

Two reasons:

1. **Inter-judge variance compounds with sub-dimensions.** If three judges disagree at the dimension level, asking them to break their score into 4-5 sub-dimensions multiplies the error.
2. **Construct contamination.** The judges already produce one score per dimension and provide verbatim evidence. Adding a sub-dimensional LLM pass would be both expensive (~$3/run instead of $1) and methodologically redundant with the dictionary + embedding methods that are already grounded in the rubric anchors.

If a later study needs sub-dimensional LLM scores, that's a clean extension — a sixth phase added to the orchestrator.

---

## 9.5 Output schema

Every run produces three CSVs at `results/runs/<run_id>/06_subdimension_scores/`. The schema (the template of fields) carries the four key dimensions: **channel × role × sub-dimension × method**. Role is `_ALL` for the channel-level aggregate and for sources that are not role-attributable (the observation summary, the field notes).

### 9.5.1 `per_subdimension.csv` — the raw measurement layer

One row per `(channel, role, dimension, sub_dimension, method)`:

```
channel,role,dimension,sub_dimension,method,score,n_relevant_sentences,measurability,evidence_top_3
public,CEO,component_disclosure,asset_class_disclosed,dict,0.62,5,H,"...; ...; ..."
public,CTO,component_disclosure,asset_class_disclosed,dict,0.81,11,H,"...; ...; ..."
public,_ALL,component_disclosure,asset_class_disclosed,dict,0.42,18,H,"...; ...; ..."
public,_ALL,component_disclosure,asset_class_disclosed,embed,0.55,42,H,"...; ...; ..."
private,CEO,component_disclosure,asset_class_disclosed,dict,0.18,3,H,"..."
private,_ALL,component_disclosure,asset_class_disclosed,dict,0.12,4,H,"..."
researcher,_ALL,component_disclosure,asset_class_disclosed,dict,0.30,7,H,"..."
...
```

Columns:

| Column | Meaning |
|---|---|
| `channel` | `public` / `private` / `researcher` |
| `role` | One of `CEO`, `CTO`, `COO`, `CMO`, `Product_Strategist`, `Product_Designer` for role-attributable rows; `_ALL` for the channel-level aggregate and for non-role-attributable sources (observation summary in public; all of researcher channel) |
| `dimension` | one of the 5 rubric dimension keys |
| `sub_dimension` | one of the 26 sub-dimension keys |
| `method` | `dict` or `embed` |
| `score` | real-valued, approximately `[-1, +1]` |
| `n_relevant_sentences` | how many sentences contributed (relevance threshold passed) |
| `measurability` | `H` / `M` / `L` from §9.3 |
| `evidence_top_3` | top 3 highest-scoring sentences in this `(channel, role)` slice for this sub-dimension, semicolon-joined |

For the public channel this yields **roughly 21 × 2 × 6 = 252 per-role rows + 21 × 2 = 42 `_ALL` rows = 294 rows**. Private channel: same shape, slightly fewer relevant sentences. Researcher channel: only `_ALL` rows (42 total) since field notes are not role-attributed.

### 9.5.2 `per_dimension.csv` — sub-dimensions aggregated up

One row per `(channel, role, dimension, method, aggregation)`:

| Column | Meaning |
|---|---|
| `channel`, `role`, `dimension`, `method` | as above |
| `aggregation` | `uniform` (each sub-dimension weighted equally — headline) or `measurability_weighted` (H=3, M=2, L=1 — appendix) |
| `score` | aggregated sub-dimension score |
| `n_sub_dimensions_with_signal` | how many sub-dimensions in this dimension had `n_relevant_sentences > 0` |
| `weakest_sub` / `strongest_sub` | the sub-dimensions with the min / max score |

Per the §9.8 decision on aggregation: BOTH `uniform` and `measurability_weighted` rows are written. The headline table uses `uniform`; the supplementary appendix shows `measurability_weighted` for sensitivity analysis.

### 9.5.3 `headline.csv`: channel-level results table

Channel-level aggregates only (`role = _ALL`, `aggregation = uniform`). One row per dimension; six columns for the channel × method cross:

```
                                 public_dict   public_embed   private_dict   private_embed   researcher_dict   researcher_embed
component_disclosure                +0.42         +0.55          +0.12          +0.20            +0.30             +0.41
process_openness                    +0.18         +0.31          -0.05          +0.04            +0.22             +0.27
boundary_permeability               +0.05         +0.12          +0.18          +0.22            +0.11             +0.15
ecosystem_orchestration             -0.11        -0.04          -0.20         -0.18            -0.08             -0.05
value_capture_posture               -0.33        -0.21          -0.45         -0.32            -0.29             -0.18
```

### 9.5.4 `headline_by_role.csv` — appendix-grade per-role breakout

Same shape as `headline.csv` but with rows expanded by role. Lets a reader see e.g. that `component_disclosure` in the public channel is driven mainly by the CTO and Product Designer, while `value_capture_posture` is driven by the CEO and CMO. This is methodologically additive and goes in the supplementary materials.

---

## 9.6 Implementation plan

Phases A to G here are steps in building this measurement, not the numbered phases of a run. Strict dependency order. Each phase is independently committable (can be saved to the code history on its own).

### 9.6.1 Phase A — Persist the private channel

**Currently:** `burst_run` writes only the public channel artefacts. The private channel (scratchpads, drafts, inbox) lives in `SharedState` during Phase 1 and is **garbage-collected** (cleared from working memory) when the run ends.

**Change required:**

1. `concurrent_mode.run_concurrent_mode` returns `shared` (`SharedState`) already — we just need to surface it past `run_research_session` into the result object.
2. Add a new field `ResearchSessionOutputs.private_state: Optional[PrivateChannelDump]` carrying:
   - per-role scratchpad lists (Q1)
   - per-role final drafts (Q2)
   - all `DirectedMessage` instances with sender + recipient + `answer_visibility` preserved (Q3 + Q4)
3. Extend `analysis/persist_artefacts.burst_run` to write:
   - `<run_id>/06_private_channel/{ROLE}_scratchpad.md`
   - `<run_id>/06_private_channel/{ROLE}_draft.md`
   - `<run_id>/06_private_channel/inbox_final.md` — one section per role with their full inbox (including private answers)

The persisted format must preserve role attribution (since per-role provenance is now part of the output schema — see §9.5 / §9.8 decision 4).

**Effort estimate:** small — half a day. No new dependencies (other software that must be installed).

**Tests:** `tests/test_private_channel_persist.py` — assert that scratchpad entries, drafts, and inbox messages each make it out of the worktree (the working copy of the code) with `role` (or sender/recipient) attribution intact.

### 9.6.2 Phase B — Sub-dimension lexicon module

**Add:** `studies/openness_maneuvering/subdimension_lexicon.py`

```python
SUBDIMENSION_LEXICON: dict[str, dict[str, list[str]]] = {
    "asset_class_disclosed": {
        "parent_dimension": "component_disclosure",
        "pro_openness": [r"release.*weights", r"open[- ]source.*model", ...],
        "anti_openness": [r"proprietary weights", r"closed.*model", ...],
        "measurability": "H",
    },
    ...
}
```

Lexicon is **the** methodological artefact — should be reviewed by the research team before any scoring run. Versioned in the study config.

**Effort estimate:** 1–2 days for careful lexicon construction, **with literature support**. Each pattern should be defensible from a published source (Henkel 2006, Chesbrough 2003, Teece 2007, Jacobides/Cennamo/Gawer 2018, etc.) or from a canonical industry artefact (cited explicitly in comments).

**Tests:** `tests/test_subdimension_lexicon.py` — assert lexicon shape, regex validity, no orphan patterns.

### 9.6.3 Phase C — Anchored exemplar expansion

**Add to** `studies/openness_maneuvering/__init__.py`: extend `RubricDimension` with `anchor_low_exemplars: list[str]` and `anchor_high_exemplars: list[str]` (3–5 each per sub-dimension).

Exemplars should be **real-world** when possible — paragraphs from Llama 2 / 3 release announcements, OpenAI's GPT-4 technical report, Stability AI's posts, Mistral's release notes, Anthropic's responsible scaling docs, Google's MLCommons participation — annotated for which sub-dimension they exemplify.

**Effort estimate:** 1–2 days. This is also a citable methodological artefact.

### 9.6.4 Phase D — Method A (dictionary scoring) implementation

**Add:** `analysis/text_measures/dictionary.py`

Pure-Python; uses `re` + `nltk`-sentence-tokeniser (standard text-matching and sentence-splitting tools). No new heavy dependencies. Iterates over the three channels (public / private / researcher) and per-role slices, writes the four CSVs described in §9.5 (`per_subdimension.csv`, `per_dimension.csv`, `headline.csv`, `headline_by_role.csv`).

**Effort estimate:** 2.5 days including per-role iteration + tests.

**Tests:** `tests/test_dictionary_method.py` — synthetic text spans for each sub-dimension; assert that scores move in the expected direction; assert that role-attributed rows sum (length-weighted) to the `_ALL` row within tolerance.

### 9.6.5 Phase E — Method B (embedding-anchored) implementation

**Add:** `analysis/text_measures/embedding.py`

Uses `sentence-transformers` (new dependency, ~100 MB on first download). Falls back gracefully if the package is not installed (run Method A only). Same per-channel × per-role iteration as Phase D. Ships with `τ = 0.30` (see §9.8 decision 6); the threshold is a module-level constant exposed for the pre-submission calibration step.

**Effort estimate:** 2.5 days.

**Tests:** `tests/test_embedding_method.py` — assert directionality, then a snapshot test (comparing results with a saved copy) against a fixed run output to catch model-update drift.

### 9.6.6 Phase F — CLI wiring + reporting

**Add:** `--subdimension-scores` flag to `run_research_session.py` (analogous to `--judge`). When set, runs the dictionary + embedding scoring after Phase 5 and writes the three CSVs.

**Add:** `analysis/report_subdimensions.py` — converts the CSVs into a markdown summary at `06_subdimension_scores/README.md`.

**Effort estimate:** 1 day.

### 9.6.7 Phase G — Method C (topic modelling, validation only)

**Add:** `analysis/text_measures/topic_validation.py`

Cross-run script (a short program, not per-run) that pools all runs in a study, runs BERTopic, and prints the discovered topics + the analyst's mapping. Output: a one-page markdown report for the appendix.

**Effort estimate:** 2 days. Only valuable once you have ≥10 runs.

---

## 9.7 Honest limitations

Documented so they don't surprise the reviewer.

1. **Strategic intent is often not lexicalised.** Particularly for value capture (D5), a firm can describe an exclusionary monetisation posture using only neutral economic language. Method A will undercount these. Method B helps but is not perfect. **The "L" measurability sub-dimensions should carry an explicit confidence-interval note in the paper.**

2. **The deliberation is short.** A 16-minute concurrent deliberation produces ~150 sentences in the public channel and ~50 in the private channel. Small samples mean high variance on the embedding method. **Aggregate across runs whenever possible** — the per-cell average is more stable than the per-run number.

3. **Topic modelling is unreliable at single-run scale.** Method C is study-level, not run-level.

4. **The lexicon is biased by the framework author's reading of the literature.** This is methodologically transparent (the lexicon is in the repo, peer-reviewable) but it is not neutral. **Mitigation:** publish the lexicon as a supplementary artefact and invite challenge.

5. **The private channel can be very thin.** If a role declares DONE (finished) quickly, its scratchpad may have only 2–3 notes. Length-weighted averages mitigate but cannot eliminate this. Report `n_relevant_sentences` so the reviewer can see when a score is built on thin evidence.

6. **Working drafts are only the final snapshot.** Pre-final drafts are not preserved by the orchestrator. If the iteration history matters, the orchestrator needs extending (see §9.2.2 note on Q2).

7. **The dictionary and embedding methods are not independent.** Both ultimately ground in the same rubric anchors. If the anchor framing is wrong, both methods inherit the error. The LLM judges are at least drawn from different model families and may diverge usefully from the text methods — preserve them as a third triangulation source.

---

## 9.8 Decisions (resolved by the principal investigator)

The six methodological choices below are **resolved** and locked into the plan. The original options and tradeoffs are kept here.

1. **Field-notes channel attribution. → Channel R (researcher).** ✅ *Decided.*
   The FieldNoter's `field_notes` are split off into a third channel R (researcher), distinct from the firm's public commitments. This preserves a clean methodological boundary: a sentence like *"the team showed little hesitation about open-sourcing the eval harness"* is the researcher's interpretation, not the panel's, and is reported as such. The LLM-judge ensemble in `_build_judge_inputs` continues to receive all three channels as input (no change there); the sub-dimensional measurement layer reports them separately.

2. **Working drafts attribution. → Private channel.** ✅ *Decided.*
   A role's working DRAFT (Q2) is part of the private channel. At deliberation time it was strictly invisible to peers; it becomes the precursor to the Phase 2 artefact but is not itself a public commitment. The public artefact (P1) is the public commitment; the draft (Q2) is its private precursor. Treating the draft as private means private-channel comparisons are conservative — more text in the private pile — but the channel boundary is unambiguous.

3. **Sub-dimension weighting. → Uniform headline, measurability-weighted appendix.** ✅ *Decided.*
   The headline `headline.csv` aggregates sub-dimensions into the parent dimension using a uniform mean (each sub-dimension weighted equally). The supplementary `per_dimension.csv` carries **both** the uniform aggregation and a measurability-weighted aggregation (H = 3, M = 2, L = 1) so that a reviewer can verify that the substantive conclusion does not depend on the implicit weighting choice.

4. **Per-role provenance. → Yes for all channels where roles are attributable.** ✅ *Decided.*
   The output schema (§9.5) carries a `role` column on every row. Public channel: roles derived from `ArtefactBundle.artefacts[*].role` and `DeliberationEvent.role`. Private channel: roles derived from `SharedState.role_states.keys()` and `DirectedMessage.sender / recipient`. Researcher channel: role is `_ALL` since field notes are produced by the FieldNoter agent and are not role-attributable. Channel-level aggregates use `role = _ALL`. This makes role-level analyses (e.g. *which roles drive which sub-dimensions?*) a trivial group-by (a simple grouping step) in the analysis layer.

5. **Iteration history of drafts. → No for the first version; flagged as a known limitation.** ✅ *Decided.*
   The orchestrator is **not** modified to log every `DRAFT` action. Only the final draft per role is persisted. The "did roles converge toward openness or away from it over the deliberation?" longitudinal analysis is deferred to a future paper that would justify extending `SharedState` to append `DraftSnapshot(timestamp, role, body)` records. See §9.7 limitation 6.

6. **Cross-cell pooling for the embedding-method relevance threshold. → Ship τ = 0.30; calibrate before use.** ✅ *Decided.*
   The implementation ships with `τ = 0.30` as a defensible default (a common threshold in similar work). Before Method B numbers are reported, a **calibration step** is added to the timeline: hand-code a 200-sentence validation set across the rubric (yes/no for "is this sentence about sub-dimension X"), pick the τ that maximises F1 (a score balancing false alarms and misses) against the codes, and re-run the full pipeline at the calibrated τ. The calibration is itself published as a methodological supplement.

---

## 9.9 Estimated total effort

| Phase | Days | Notes |
|---|---|---|
| A — private-channel persistence (incl. role attribution) | 0.5 | Prerequisite; no new deps |
| B — sub-dimension lexicon | 1.5 | Methodological artefact; research-team review |
| C — anchor exemplar expansion | 1.5 | Methodological artefact; literature-grounded |
| D — Method A (dictionary, per-role × per-channel) | 2.5 | Pure-Python implementation; writes all four CSVs |
| E — Method B (embedding, per-role × per-channel) | 2.5 | Adds sentence-transformers dependency; ships τ = 0.30 |
| F — CLI + reporting | 1.0 | Mirrors existing `--judge` pattern |
| G — Method C (topic modelling) | 2.0 | Cross-run; only valuable at ≥10 runs |
| τ calibration (§9.8 decision 6) | 0.5 | Hand-code 200 sentences; recompute Method B |
| **Total** | **~12 days** | One reviewer-shareable methodological appendix + working code |

Phases A–F deliver the full per-run output (`headline.csv` + the role-broken-out `headline_by_role.csv` + `per_subdimension.csv` + `per_dimension.csv`). Phase G is the study-level appendix that can wait until enough runs accumulate. The τ calibration is bundled in the timeline so Method B numbers reflect a calibrated threshold.

---

## 9.10 What this plan deliberately does **not** include

So the scope is explicit and renegotiable:

- **No gap analysis.** Per the PI (principal investigator): report public, private, and researcher numbers separately; the public-vs-private gap is separate work.
- **No replacement of the LLM-judge ensemble.** Phase 5 keeps running as before; the judges continue to receive all three channels as input.
- **No new study-level constructs.** The 7 dimensions and the rubric anchors stay as defined in `studies/openness_maneuvering/__init__.py`.
- **No human-coded validation set yet.** Bundled as the calibration step in the timeline (§9.8 decision 6), not as part of the first methodological draft.
- **No regression analysis or hypothesis testing.** This plan is about producing the measurement layer. Downstream statistical analysis is a separate piece of work.
- **No draft iteration history.** Final draft only, per §9.8 decision 5. The orchestrator is not modified to log every `DRAFT` action.

---

## 9.11 Next step

The six §9.8 decisions are resolved. The implementation order is:

1. **PI confirms the sub-dimension framework in §9.3** (the 26 sub-dimensions and their lexicon seeds) — this is the last sticky methodological choice before code lands.
2. **Phase A (private-channel persistence)** lands as the first PR — pure infrastructure, no methodological commitment. Includes role attribution for Q1–Q4 per §9.8 decision 4.
3. **Phases B + C (lexicon + exemplars)** land as a second PR for research-team review BEFORE any scoring code runs against real text — these are the citable methodological artefacts.
4. **Phases D + E + F (methods + CLI + reporting)** land as a third PR with tests and a small end-to-end run on the existing Anthropic / Dynamic / Novel / 2032 output. The PR demonstrates all four CSVs (`per_subdimension.csv`, `per_dimension.csv`, `headline.csv`, `headline_by_role.csv`) plus the markdown summary at `06_subdimension_scores/README.md`.
5. **τ calibration** (§9.8 decision 6) once a small hand-coded validation set exists.
6. **Phase G (topic modelling)** lands once cross-run corpus is large enough (≥10 runs).
