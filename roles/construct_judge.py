"""Construct-judge agent factory.

This file builds a judge: a language model that scores a finished run against a
rubric (a scoring guide saying what to rate and how). Judges run only with the
`--judge` flag (an option added to a command), and this scoring sits outside the
proposal's method. A factory is a function that builds something, here an agent.

Each judge in the ensemble is an `LlmAgent` (the agent type in ADK,
Google's Agent Development Kit) whose instruction (the standing part of the
prompt, which is the text sent to a model) embeds the rubric verbatim + the methodological framing
("write the qualitative summary first, then score") + the
output-schema enforcement (`ConstructAssessment`, the template of fields the reply must fill).

The orchestrator (the code that runs each stage of a run; here
`orchestrator/construct_judging.py`) builds four
judges by default, one per provider (the company or service supplying a model) in `providers.JUDGE_PROVIDERS` — and runs
them in parallel via `asyncio.gather`. Each judge sees the same
inputs (artefacts + public transcript + observation summary +
field notes + debriefing, each explained under the heading below). Their `ConstructAssessment` outputs
are aggregated by the orchestrator.

The judge factory is study-agnostic: the *construct* it scores is
whatever the active study's `JudgmentRubric` defines (e.g. openness
under the default ``openness_maneuvering`` study).

Inputs the judge sees
---------------------
* The 6 strategy artefacts (the paper each role writes in Phase 2) in full
* The deliberation (Phase 1, the team's discussion) transcript (PUBLIC events
  only — SPEAK, ASK public-echo, ANSWER public: the moves that add to the
  transcript, put a question to a colleague, and reply to one). Private
  SCRATCHPADs and DRAFTs (a role's notes and document draft) are NOT in the
  judge's view.
* The qualitative researcher's (the agent that watches and questions the team)
  `ObservationSummary` (its single structured account of the deliberation)
* The qualitative researcher's running field notes (FieldNoter
  outputs from Phases 1+2)
* The full debriefing (Phase 4, when the researcher interviews the team) transcript

The PRIVATE scratchpads (per-role internal notes) are deliberately
EXCLUDED — the judge assesses what was publicly enacted and what
the panel said, not the firm's hidden internal thinking.
"""

from __future__ import annotations

from typing import Optional

from google.adk.agents import LlmAgent

try:
    from ..providers import build_structured_agent, get_judge_model
    from ..studies import StudyConfig
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from providers import build_structured_agent, get_judge_model  # type: ignore[no-redef]
    from studies import StudyConfig  # type: ignore[no-redef]

from .judge_schemas import ConstructAssessment


# v0.4 (version 0.4 of the rubric) sub-dimensional scoring (a sub-dimension is one
# of 26 narrow items within the rubric's seven dimensions) depends on the openness study's
# sub-dimension lexicon (the study's list of those items, with marker words). The judge prompt's STAGE 2A block embeds the
# full 26-sub-dim taxonomy via `render_sub_dimensions_for_prompt`.
# Studies that don't ship a sub-dimension lexicon fall back to the
# v0.3 parent-only path (the earlier rubric version, which scores only the main
# dimensions: no STAGE 2A; the prompt skips the sub-dim
# sections cleanly).
try:
    from ..studies.openness_maneuvering.subdimension_lexicon import (
        render_sub_dimensions_for_prompt,
        all_sub_dimension_keys,
    )
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    try:
        from studies.openness_maneuvering.subdimension_lexicon import (  # type: ignore[no-redef]
            render_sub_dimensions_for_prompt,
            all_sub_dimension_keys,
        )
    except ImportError:
        render_sub_dimensions_for_prompt = None  # type: ignore[assignment]
        all_sub_dimension_keys = None  # type: ignore[assignment]


def _study_has_subdim_lexicon(study) -> bool:
    """v0.4 sub-dim scoring activates iff (if and only if) the study has a sub-dim
    lexicon. Today only `openness_maneuvering` qualifies; other studies
    keep the v0.3 parent-only path."""
    return (
        render_sub_dimensions_for_prompt is not None
        and all_sub_dimension_keys is not None
        and study.slug == "openness_maneuvering"
    )


# Percent → Likert (a numbered rating scale, here 1 to 7) anchor table — kept identical to `judge_schemas.
# _ANCHOR_THRESHOLDS` and embedded verbatim into the prompt so the
# judge has the table on screen rather than having to remember it.
_PERCENT_TO_LIKERT_TABLE = """\
    |   % range  | Qualitative anchor | Likert |
    |  0  -  14  | near-absent        |   1    |
    | 15  -  28  | minimal            |   2    |
    | 29  -  42  | partial            |   3    |
    | 43  -  56  | moderate           |   4    |
    | 57  -  70  | substantial        |   5    |
    | 71  -  85  | comprehensive      |   6    |
    | 86  - 100  | exemplary          |   7    |
"""


def create_construct_judge_agent(
    *,
    provider: str,
    study: StudyConfig,
) -> LlmAgent:
    """Build one construct-judge LlmAgent for the given provider.

    The agent's `instruction` embeds the study's `JudgmentRubric`
    verbatim (so each dimension's anchors are explicit), the
    two-stage scoring methodology ("write qualitative summary first,
    then score against it"), and the evidence-anchoring requirement
    (every dimension score needs 1-3 verbatim quotes).

    Args:
        provider: Provider key for `providers.get_judge_model` (e.g.
            'gemini_pro', 'claude', 'openai'). Determines which LLM (large language model)
            backs this judge. `get_judge_model` may resolve to a
            different model from the team-wide `get_model(provider)`
            when `JUDGE_MODEL_OVERRIDES` or the `TMT_JUDGE_<PROVIDER>_
            MODEL` env var (environment variable: a named setting held outside the code) asks for one. Currently the DeepSeek judge runs
            on `deepseek-reasoner` while DeepSeek on the TMT side (top management team, the six role agents) uses `deepseek-v4-flash`.
        study: The study config — must have `judgment_rubric` set.
            The rubric's name, description, dimensions, and scale
            anchors are all rendered into the judge prompt.

    Returns:
        An ADK `LlmAgent` with `output_schema=ConstructAssessment`.

    Raises:
        ValueError: if the study has no `judgment_rubric`.
    """
    if study.judgment_rubric is None:
        raise ValueError(
            f"Study {study.slug!r} has no judgment_rubric — cannot "
            f"build a construct judge for it. Add a `JudgmentRubric` "
            f"to the study config or skip Phase 5."
        )

    rubric = study.judgment_rubric

    # Render the rubric for the prompt.
    dim_blocks = []
    for d in rubric.dimensions:
        block = (
            f"  DIMENSION: {d.key} — {d.name}\n"
            f"    What it measures: {d.description}\n"
            f"    Anchor at 1 (low): {d.anchor_low}\n"
            f"    Anchor at 4 (mid): {d.anchor_mid}\n"
            f"    Anchor at 7 (high): {d.anchor_high}\n"
        )
        if d.literature:
            block += f"    Literature: {d.literature}\n"
        dim_blocks.append(block)
    dimensions_block = "\n".join(dim_blocks)

    scale_anchors_block = "\n".join(
        f"    {n} = {anchor}" for n, anchor in sorted(rubric.scale_anchors.items())
    )

    # Comma-separated dimension keys for the schema enforcement reminder.
    dimension_keys = ", ".join(repr(d.key) for d in rubric.dimensions)

    # v0.4 sub-dimensional scoring blocks. Only landed when the study
    # has a sub-dim lexicon (`openness_maneuvering`); other studies
    # see a v0.3-shaped prompt with no STAGE 2A.
    use_subdim_scoring = _study_has_subdim_lexicon(study)
    if use_subdim_scoring:
        subdim_rendered = render_sub_dimensions_for_prompt()
        subdim_count = len(all_sub_dimension_keys())
        subdim_taxonomy_block = (
            f"\nSUB-DIMENSIONAL TAXONOMY (v0.4 — {subdim_count} sub-dimensions)\n"
            f"================================================================\n"
            f"Each of the {len(rubric.dimensions)} parent dimensions decomposes "
            f"into 2-5 named sub-dimensions. The {subdim_count}-sub-dimension "
            f"taxonomy below is the level you score at; the parent-dimension "
            f"Likert is a rollup of the children.\n\n"
            f"{subdim_rendered}\n"
        )
        # Sub-dim list for the schema-enforcement reminder near the end
        # of the prompt.
        subdim_keys_str = ", ".join(repr(k) for k in all_sub_dimension_keys())
    else:
        subdim_taxonomy_block = ""
        subdim_count = 0
        subdim_keys_str = ""

    # STAGE 2A — sub-dimensional percent scoring. Only emitted for
    # studies with a sub-dim lexicon. Otherwise the prompt skips
    # straight to the v0.3 parent-dim Likert.
    if use_subdim_scoring:
        stage_2a_block = f"""
STAGE 2A — sub_dimension_assessments ({subdim_count} entries, one per sub-dim):
  For EACH of the {subdim_count} sub-dimensions listed in the
  SUB-DIMENSIONAL TAXONOMY block above:
    * Pick a score_pct on a 0-100 scale. 0 = the firm shows none of
      this sub-dimension in the inputs; 100 = the firm shows it
      comprehensively. Common practice: multiples of 5 (so 0, 5, 10,
      15, ...). The continuous scale lets you express finer gradations
      than the Likert allows.
    * Derive `likert_back_binned` from the table below (must match
      score_pct exactly via the anchor thresholds):

{_PERCENT_TO_LIKERT_TABLE}
    * Set `qualitative_anchor` to the anchor name matching the Likert
      back-bin (one of: near-absent / minimal / partial / moderate /
      substantial / comprehensive / exemplary).
    * Set `parent_dimension` to the parent-dimension key from the
      SUB-DIMENSIONAL TAXONOMY heading the sub-dim sits under.
    * Write 3-5 sentences of `reasoning` connecting the score to your
      Stage-1 qualitative analysis. Name the specific decisions /
      components / moments the score reflects.
    * Supply `evidence_quotes` — see EVIDENCE QUOTING CONTRACT below.
    * Set `confidence` (low / medium / high) based on how much the
      inputs say about this sub-dimension specifically.
"""

        stage_2b_label = "STAGE 2B"
        stage_2b_block = f"""
STAGE 2B — dimension_scores ({len(rubric.dimensions)} entries, parent-dim rollup):
  For EACH of the {len(rubric.dimensions)} parent dimensions
  ({dimension_keys}), produce a `DimensionAssessment`:
    * `score`: the mean of children's `likert_back_binned` values
      rounded to the nearest integer 1-7. The aggregator double-
      checks this math; emit your own rollup so we see whether the
      math agrees.
    * `reasoning`: 2-3 sentences synthesising the children. What is
      the parent-dimension story across its sub-dimensions?
    * `evidence`: 1-3 short verbatim quotes drawn from the children's
      `evidence_quotes`. Pick the quotes that anchor the parent-dim
      story best.
    * `confidence`: roll up from the children — if most are 'high',
      the parent is 'high'; if mixed, 'medium'; if mostly 'low' the
      parent is 'low'.
"""
    else:
        stage_2a_block = ""
        stage_2b_label = "STAGE 2"
        stage_2b_block = f"""
STAGE 2 — dimension_scores (one entry per dimension):
  For EACH of the {len(rubric.dimensions)} dimensions {dimension_keys}:
    * Pick a Likert score 1-7. Read the anchor descriptions above
      and place the firm against them. The integer score should
      reflect where the firm sits, not what you wish it were.
    * Write 2-4 sentences of reasoning grounded in your Stage-1
      analysis. Reference the specific evidence you cited.
    * Include 1-3 verbatim quotes from the inputs in the `evidence`
      list. Each quote should be short enough to be auditable
      (under ~200 chars).
    * Assign a confidence rating (low/medium/high) based on how
      much evidence the inputs gave you for this dimension.
"""

    # EVIDENCE QUOTING CONTRACT — only landed under v0.4 sub-dim path.
    # The v0.3 path's evidence-anchoring rule (below) is unchanged.
    if use_subdim_scoring:
        evidence_quoting_block = """
EVIDENCE QUOTING CONTRACT (binding under v0.4 sub-dimensional scoring)
======================================================================
Every `evidence_quotes` entry on every SubDimensionAssessment must:

  * Quote VERBATIM from one of the run's persisted markdown files.
    The admissible source files are:
      - 01_deliberation/interaction_log.md  (public deliberation)
      - 02_strategy_documents/<role>_strategy.md  (the six artefacts)
      - 03_researcher/observation_summary.md  (observer summary)
      - 04_interview/transcript.md  (panel debriefing)
    DO NOT quote external knowledge — the firm's public news, your
    training-time priors about the firm, prior literature. The
    aggregator post-hoc substring-checks every quote against its
    `source_file`; failures land in `<provider>_quote_audit.md`.

  * Set `source_file` to the relative path inside the run folder
    (e.g. `"01_deliberation/interaction_log.md"`).

  * Set `source_role` (optional) to the role name when the quote
    comes from a specific TMT member.

  * Keep the quote ≤300 characters — point at a specific sentence or
    short passage, do not dump a paragraph.

Quantity rule:
  * If score_pct > 14 (any non-near-absent score): ≥2 quotes required.
    The minimum two quotes anchor the auditability claim — a reviewer
    can resolve at least two independent textual sources for any
    positive score.
  * If score_pct ≤ 14 (near-absent): one demonstrating-the-absence
    quote (a passage where the team touched the topic but did not
    take a position), OR zero quotes with explicit `reasoning` text
    stating "no evidence found in the inputs".
"""
    else:
        evidence_quoting_block = ""

    # Stage-3 block — composite + overall confidence + caveats. Under
    # v0.4 the composite is the simple mean of the parent-dim
    # likert_back_binned values (same as v0.3 composite math, just
    # derived through the rollup path, which averages sub-dimension scores up to their parent).
    stage_3_block = """
STAGE 3 — composite + overall confidence + caveats:
  * composite_score: the simple mean of your parent-dimension Likert
    scores. Round to two decimals if non-integer.
  * overall_confidence: synthesise from the per-dimension
    confidences. If two dimensions are 'low' and three are 'high',
    'medium' is reasonable.
  * caveats: any meta-level note about what you could not assess
    or where the inputs constrained your judgement. Honest
    uncertainty is more useful than false precision.
"""

    instruction = f"""You are an independent expert reviewer assessing the firm's
posture on the construct under study. You did NOT participate in the
firm's deliberation or the panel debriefing — you are reading them
as an outside evaluator who has access to the firm's public outputs
plus the ethnographer's field notes.

CONSTRUCT UNDER ASSESSMENT
==========================
{rubric.name}

{rubric.description}

WHAT YOU WILL RECEIVE
=====================
Each invocation gives you, as text in the user message:
  * The six strategic artefacts produced by the firm's TMT (one per role).
  * The PUBLIC deliberation transcript (every public utterance, in
    order). Private scratchpads and working drafts are NOT included
    — you are assessing what the firm publicly enacted, not its
    hidden internal thinking.
  * The qualitative researcher's `ObservationSummary` (structured
    field notes).
  * The qualitative researcher's running field notes (live prose
    notes taken during the deliberation).
  * The full panel-debriefing transcript (researcher probes + role
    responses).

RUBRIC
======
You assess the firm on {len(rubric.dimensions)} parent dimensions. Under
v0.4 each parent decomposes into 2-5 sub-dimensions; sub-dimensions
are scored natively on a 0-100 percent scale and the parent-dimension
Likert is the rollup of the children. Scale anchors below apply to
the parent Likert; the percent → Likert anchor table for sub-dim
scoring lives in STAGE 2A.

Scale anchors (parent-dimension Likert 1-7):
{scale_anchors_block}

Per-dimension anchors:

{dimensions_block}
{subdim_taxonomy_block}
METHODOLOGY — MULTI-STAGE SCORING
=================================
Your output is a single `ConstructAssessment` JSON object. The
critical ordering: you MUST write the qualitative_summary FIRST,
then score the sub-dimensions, then roll up to parent dimensions.
The structured numerical work follows your free-form analysis, not
the other way around.

STAGE 1 — qualitative_summary (~3 paragraphs):
  Read all inputs end-to-end. Write a free-form qualitative analysis
  of how the firm's choices reflect the construct under study. Cite
  specific decisions, components, products, IP, processes, or
  moments by name (using the firm's own vocabulary). Identify
  asymmetries — where some pieces were treated differently from
  others. Note absences too: if the firm's deliberation barely
  touched a dimension, say so. Do NOT yet assign numbers.

  Discipline rules for Stage 1:
    * Quote the panel and the artefacts verbatim where it sharpens
      the observation; put quotes in single-quotes.
    * Do not introduce theoretical vocabulary the firm itself did
      not use. Reflect the firm's framing, not the literature's.
    * If you cannot tell from the inputs, say so explicitly. Do not
      speculate.
{stage_2a_block}{stage_2b_block}{stage_3_block}{evidence_quoting_block}
EVIDENCE-ANCHORING RULE (binding under v0.3 parent-dim scoring)
===============================================================
Every parent-dimension score that is not exactly 4 (the mid anchor)
MUST have at least one verbatim evidence quote on the
DimensionAssessment. A score with no evidence is a score that
cannot be audited; do not produce one. A score of 4 may have no
evidence iff your reasoning explicitly states "the inputs did not
provide grounds to move from the mid anchor in either direction".
Under v0.4 sub-dim scoring (STAGE 2A) the binding contract is the
EVIDENCE QUOTING CONTRACT above (≥2 quotes per non-near-absent
sub-dim); this v0.3 rule applies to the parent-dim rollup output.

OUTPUT
======
Return ONLY a single JSON object conforming to the
`ConstructAssessment` schema.
  * `dimension_scores` list MUST have exactly {len(rubric.dimensions)}
    entries (one per parent dimension), with `dimension` values
    matching: {dimension_keys}.
  * `sub_dimension_assessments` list MUST have exactly {subdim_count}
    entries (one per sub-dimension), with `sub_dimension_key` values
    matching: {subdim_keys_str}. Leave this field empty ONLY if this
    study has no sub-dimension lexicon (the prompt's SUB-DIMENSIONAL
    TAXONOMY block is absent above).
No prose outside the JSON.
"""

    return build_structured_agent(
        name=f"ConstructJudge_{provider}",
        model=get_judge_model(provider),
        instruction=instruction,
        description=(
            f"Construct judge ({provider}). Reads a completed run's "
            f"artefacts + transcript + observation summary + field "
            f"notes + debriefing, then produces a rubric-anchored "
            f"ConstructAssessment with per-dimension Likert scores "
            f"and evidence quotes."
        ),
        output_schema=ConstructAssessment,
    )
