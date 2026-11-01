"""Pydantic schemas for the multi-judge construct-scoring ensemble.

A judge is a language model that scores a finished run against a rubric (a scoring
guide saying what to rate and how). A schema is a template saying which fields a
record must contain, and Pydantic is a Python tool that checks records against it.
This file fixes the form of the judges' scores.

The Phase-5 (an optional extra stage after the debrief) construct-judge ensemble (see
`orchestrator/construct_judging.py`) runs four LLM (large language model) judges by default over a
completed run's artefacts (each role's strategy document) + transcript + observation + debriefing.
Each judge produces a `ConstructAssessment`; the orchestrator
aggregates them into a `ConstructJudgmentBundle` with cross-judge
mean + per-dimension Krippendorff's α (a measure of agreement among coders, where
1 is perfect and 0 is chance).

The schemas are study-agnostic — the *construct* being scored is
whatever the active study's `JudgmentRubric` defines. The default
``openness_maneuvering`` study defines openness; another study could
register its own rubric (e.g. absorptive capacity, ambidexterity)
and reuse this same machinery.

Schemas
-------
* `DimensionAssessment` — one judge's score + reasoning + evidence
  for one rubric dimension.
* `ConstructAssessment` — one judge's full output: qualitative summary
  (Stage 1) + dimension scores (Stage 2) + composite + caveats.
* `ConstructJudgmentBundle`: the judges' assessments + aggregate
  statistics (means, inter-rater agreement).

Methodological choices encoded here
-----------------------------------
* Two-stage scoring: Stage 1 is free-form qualitative analysis; Stage
  2 is structured per-dimension scoring. The judge must write the
  qualitative summary FIRST, then score against it. Reduces
  "vibes-based" scoring (cf. Charmaz 2014 on memoing-before-coding).
* Evidence anchoring: every dimension score requires 1-3 verbatim
  quotes from the inputs. A reviewer can audit any score by
  resolving the quotes.
* Per-dimension confidence: low/medium/high. Surfaces uncertainty
  rather than hiding it in a single composite.
* Composite = simple mean across dimensions (per user direction, the user being the human researcher).
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ===========================================================================
# Score conversion — percent ↔ Likert + qualitative anchor
# ===========================================================================
#
# PR-D (PR, or pull request: a proposed set of changes) moves the construct
# scoring from a coarse 1-7 Likert (a numbered rating scale) to a
# native 0-100 percent scale, with a Likert back-bin (the percent score converted
# back to the 1-7 scale) computed for
# reviewer-compatible reporting. The user's argument: openness is a
# continuous construct between fully closed (0%) and fully open
# (100%), and the continuum is hard to visualise on a 7-point Likert.
# Keeping both lets the analysis pipeline (the scripts that process run records) report whichever the
# reader expects (percent for the continuous-construct story; Likert
# for direct comparison against the field's standard convention).
#
# Anchor thresholds (inclusive at the lower bound):
#
#   |   % range  | Qualitative anchor | Likert |
#   |  0  -  14  | near-absent        |   1    |
#   | 15  -  28  | minimal            |   2    |
#   | 29  -  42  | partial            |   3    |
#   | 43  -  56  | moderate           |   4    |
#   | 57  -  70  | substantial        |   5    |
#   | 71  -  85  | comprehensive      |   6    |
#   | 86  - 100  | exemplary          |   7    |
#
# The thresholds 14.5 / 28.5 / 42.5 / 56.5 / 70.5 / 85.5 divide the
# 0-100 range into seven approximately-equal buckets. The first and
# last buckets are slightly wider (15 each) than the middle buckets
# (14 each) — a deliberate asymmetry that gives "near-absent" and
# "exemplary" enough room to absorb extreme scores without
# bouncing into the adjacent anchor on small numerical jitter.

QualitativeAnchor = Literal[
    "near-absent", "minimal", "partial", "moderate",
    "substantial", "comprehensive", "exemplary",
]
"""Seven anchored descriptors mapped onto the percent → Likert scale."""

_ANCHOR_THRESHOLDS: tuple[tuple[float, int, str], ...] = (
    (14.5, 1, "near-absent"),
    (28.5, 2, "minimal"),
    (42.5, 3, "partial"),
    (56.5, 4, "moderate"),
    (70.5, 5, "substantial"),
    (85.5, 6, "comprehensive"),
    (float("inf"), 7, "exemplary"),
)
"""(upper-bound, likert, anchor) tuples driving `percent_to_likert` and
`percent_to_anchor`. Inclusive-upper convention: a score with
`score_pct < upper_bound` lands in that bucket. The final bucket's
upper bound is `inf` so every valid percent falls somewhere."""


def percent_to_likert(score_pct: float) -> int:
    """Convert a 0-100 percent score to a 1-7 Likert back-bin.

    Out-of-range inputs are clamped (negative → 1; > 100 → 7) rather
    than raising — judges occasionally emit `100.5` or similar
    arithmetic-edge values, and a clamp is more forgiving than a
    validation failure on every cell.
    """
    if score_pct <= 0:
        return 1
    for upper, likert, _anchor in _ANCHOR_THRESHOLDS:
        if score_pct < upper:
            return likert
    return 7  # unreachable in practice — the inf bucket catches everything


def percent_to_anchor(score_pct: float) -> QualitativeAnchor:
    """Convert a 0-100 percent score to the matching qualitative anchor."""
    if score_pct <= 0:
        return "near-absent"
    for upper, _likert, anchor in _ANCHOR_THRESHOLDS:
        if score_pct < upper:
            return anchor  # type: ignore[return-value]
    return "exemplary"


# ===========================================================================
# Evidence quote — verbatim text from a run's persisted markdown (saved plain-text records with simple marks for headings and lists)
# ===========================================================================

class EvidenceQuote(BaseModel):
    """One verbatim quote backing a sub-dimension score.

    The judge must quote EXCLUSIVELY from the run's persisted markdown
    artefacts (deliberation transcript / role strategy documents /
    observation summary / debriefing transcript). External knowledge —
    the judge's training-time priors about the firm, the public news
    about the firm's posture, etc. — is not admissible. The
    `source_file` attribution makes that contract auditable: every
    quote is later substring-checked against the named file (see
    `analysis/quote_verification.py` in PR-D commit 5).

    The 300-character cap keeps quotes auditable at a glance and
    prevents a judge from dumping a paragraph as "evidence" when
    they should be pointing at a specific sentence.
    """

    source_file: str = Field(
        ...,
        description=(
            "Relative path inside the run folder, e.g. "
            "'01_deliberation/interaction_log.md' or "
            "'02_strategy_documents/CEO_strategy.md'. Must be one of "
            "the persisted markdown artefacts — external sources are "
            "not admissible."
        ),
    )
    source_role: Optional[str] = Field(
        None,
        description=(
            "Optional role attribution when the quote comes from a "
            "specific TMT member (e.g. 'CTO' when quoting a "
            "deliberation event or strategy document). Helps with the "
            "qualitative coding pass — the human PI can read which "
            "panellist said what without re-opening the source file."
        ),
    )
    quote: str = Field(
        ...,
        max_length=300,
        description=(
            "Verbatim text copied from `source_file`, ≤300 characters. "
            "Must substring-match the source file at scoring time. "
            "Quotes that fail the substring check are flagged in "
            "`<provider>_quote_audit.md` for the PI to review — they "
            "are not auto-discarded (the judge may have lightly "
            "normalised whitespace), but they are surfaced."
        ),
    )


# ===========================================================================
# Sub-dimensional assessment — the v0.4 (version 0.4 of the rubric) fine-grained scoring unit (one of 26 narrow items within the rubric's seven dimensions)
# ===========================================================================

class SubDimensionAssessment(BaseModel):
    """One judge's score + reasoning + evidence for one **sub-dimension**.

    The openness rubric v0.3 had 7 parent dimensions each scored on a
    coarse 1-7 Likert with 1-3 evidence quotes. v0.4 decomposes each
    parent into 2-5 sub-dimensions (26 in total — see
    `studies/openness_maneuvering/subdimension_lexicon.py`), with each
    sub-dimension scored natively on a 0-100 percent scale and backed
    by ≥2 verbatim evidence quotes sourced exclusively from the run's
    persisted markdown.

    The parent-dimension scores stay computable as a rollup (mean of
    children's `score_pct`); the aggregator computes both granularities
    and the per-sub-dim Krippendorff's α surfaces exactly where the
    construct contests — directly supporting DECISIONS §23's
    "construct contestation as data" claim.

    Methodological note. ≥2 evidence quotes is the minimum required
    for a score that moves away from "near-absent" (i.e. score_pct
    > 14). A score of "near-absent" (score_pct ≤ 14) may carry 1
    quote demonstrating the absence — a passage where the team
    discussed the topic but did not take a position — or 0 quotes
    with reasoning that explicitly states "no evidence found in the
    inputs". Mandating ≥2 for non-absent scores anchors the
    auditability claim: a reviewer can resolve at least two
    independent textual sources for any positive score.
    """

    sub_dimension_key: str = Field(
        ...,
        description=(
            "The snake_case key from `OPENNESS_SUBDIMENSION_LEXICON` "
            "(e.g. 'outbound_publication_intensity'). Must match an "
            "entry in the lexicon exactly."
        ),
    )
    parent_dimension: str = Field(
        ...,
        description=(
            "The parent `RubricDimension.key` this sub-dimension rolls "
            "up into (e.g. 'boundary_permeability_outbound'). Must "
            "match the `parent_dimension` field of the corresponding "
            "lexicon entry — the aggregator checks this and refuses "
            "to roll up mismatched assessments."
        ),
    )
    score_pct: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description=(
            "Native score on a 0-100 percent scale: 0 = fully absent / "
            "fully closed for this sub-dimension, 100 = fully present / "
            "fully open. Continuous (judges may emit any float in the "
            "range; common practice is multiples of 5)."
        ),
    )
    likert_back_binned: int = Field(
        ...,
        ge=1,
        le=7,
        description=(
            "Likert 1-7 back-bin of `score_pct` via the anchor table "
            "in `judge_schemas.percent_to_likert`. Reviewer-facing "
            "reporting can use either scale; the aggregator computes "
            "α on both."
        ),
    )
    qualitative_anchor: QualitativeAnchor = Field(
        ...,
        description=(
            "Qualitative descriptor matching the `score_pct` bucket: "
            "near-absent (1) / minimal (2) / partial (3) / moderate "
            "(4) / substantial (5) / comprehensive (6) / exemplary "
            "(7). Tied to `likert_back_binned` by construction."
        ),
    )
    reasoning: str = Field(
        ...,
        description=(
            "3-5 sentences justifying the score. References the "
            "evidence quotes by paraphrase and connects them to the "
            "sub-dimension's definition. Does NOT use construct-loaded "
            "vocabulary the firm itself did not use."
        ),
    )
    evidence_quotes: List[EvidenceQuote] = Field(
        ...,
        description=(
            "Verbatim evidence backing the score, sourced exclusively "
            "from the run's persisted markdown artefacts. ≥2 quotes "
            "required when score_pct > 14 (i.e. any non-'near-absent' "
            "score). 'near-absent' scores may carry 1 demonstrating-"
            "the-absence quote or 0 with explicit 'no evidence found' "
            "reasoning. The post-hoc verifier in "
            "`analysis/quote_verification.py` (PR-D commit 5) "
            "substring-checks every quote against its `source_file` "
            "and produces a per-judge audit file."
        ),
    )
    confidence: Literal["low", "medium", "high"] = Field(
        ...,
        description=(
            "How confidently this sub-dimension can be scored from the "
            "inputs. 'low' = the deliberation barely touches it; "
            "'medium' = some evidence; 'high' = explicit evidence "
            "across multiple sources."
        ),
    )


# ===========================================================================
# Stage-2 structured scoring (parent-dimension level, meaning the main dimensions; v0.3 legacy, the earlier rubric version)
# ===========================================================================

class DimensionAssessment(BaseModel):
    """One judge's score + reasoning + evidence for one rubric dimension."""

    dimension: str = Field(
        ...,
        description=(
            "The `RubricDimension.key` this assessment is for "
            "(e.g. 'component_disclosure'). Must match a key in the "
            "study's rubric exactly."
        ),
    )
    score: int = Field(
        ...,
        ge=1,
        le=7,
        description=(
            "Likert score: 1 (strongly low / strongly closed) to 7 "
            "(strongly high / strongly open). The judge must select "
            "an integer; no half-points."
        ),
    )
    reasoning: str = Field(
        ...,
        description=(
            "2-4 sentences justifying the score. References specific "
            "decisions, components, or moments from the inputs. Does "
            "NOT use construct-loaded vocabulary the firm itself did "
            "not use."
        ),
    )
    evidence: List[str] = Field(
        default_factory=list,
        description=(
            "1-3 verbatim quotes from the artefacts, transcript, or "
            "observation summary that ground the score. Each quote "
            "should be short enough to be auditable (under ~200 chars) "
            "and traceable to a source."
        ),
    )
    confidence: Literal["low", "medium", "high"] = Field(
        ...,
        description=(
            "How confidently this dimension can be scored from the "
            "inputs. 'low' = the deliberation/artefacts barely touch "
            "this dimension; 'medium' = some evidence; 'high' = "
            "explicit evidence across multiple sources."
        ),
    )


# ===========================================================================
# Per-judge full output
# ===========================================================================

# The panel has four judges by default (`providers.JUDGE_PROVIDERS`). This class's
# docstring and field descriptions reach the judge models through the output schema,
# so they change only with the code; where they say three, read four.
class ConstructAssessment(BaseModel):
    """One judge's complete output: Stage-1 qualitative summary +
    Stage-2 per-dimension scores + aggregate composite + caveats.

    Each of the three judges produces exactly one instance per run.
    The framework (the shared software in this repository) persists them under `05_judging/<judge_id>_assessment.{json,md}`
    in the per-run folder.
    """

    judge_id: str = Field(
        ...,
        description=(
            "Provider key of the LLM that produced this assessment "
            "(e.g. 'gemini_pro', 'claude', 'openai'). Lets the "
            "aggregator distinguish the three judges."
        ),
    )
    qualitative_summary: str = Field(
        ...,
        description=(
            "Stage-1 free-form qualitative analysis (~3 paragraphs). "
            "Discusses how the firm's choices reflect the construct "
            "WITHOUT yet assigning numbers. Forces the judge to "
            "ground its later scoring in stated evidence."
        ),
    )
    dimension_scores: List[DimensionAssessment] = Field(
        ...,
        description=(
            "Stage-2 structured scoring at the **parent-dimension** "
            "level: one entry per rubric dimension. The count and "
            "`dimension` keys MUST match the study's "
            "`JudgmentRubric.dimensions` exactly. Under v0.4 these are "
            "derived as rollups (mean of children's `score_pct` "
            "back-binned to Likert 1-7) but the field stays load-"
            "bearing so v0.3 fixtures + the recovered Meta-2032 "
            "bundle continue to validate. New runs populate it from "
            "`sub_dimension_assessments` automatically."
        ),
    )
    sub_dimension_assessments: List[SubDimensionAssessment] = Field(
        default_factory=list,
        description=(
            "Stage-2 structured scoring at the **sub-dimension** level. "
            "Empty for v0.3 runs (back-compat) — those only carry "
            "parent-dimension Likert scores. v0.4+ runs populate this "
            "with 26 entries (one per sub-dimension in "
            "`OPENNESS_SUBDIMENSION_LEXICON`); each entry has a "
            "0-100 percent score + Likert back-bin + qualitative "
            "anchor + reasoning + ≥2 evidence quotes sourced "
            "exclusively from the run's persisted markdown. The "
            "aggregator computes Krippendorff's α at both "
            "granularities — the per-sub-dim α surfaces exactly where "
            "the construct contests across judges (DECISIONS §23 "
            "claim 3)."
        ),
    )
    composite_score: float = Field(
        ...,
        ge=1.0,
        le=7.0,
        description=(
            "Simple mean of the per-dimension scores. The judge "
            "computes this on the fly; the orchestrator can also "
            "recompute as a consistency check."
        ),
    )
    overall_confidence: Literal["low", "medium", "high"] = Field(
        ...,
        description=(
            "How confidently the overall construct can be scored "
            "from the run's inputs. Aggregates the per-dimension "
            "confidences; the judge can over-ride if e.g. some "
            "dimensions are well-evidenced and others are not."
        ),
    )
    caveats: str = Field(
        "",
        description=(
            "What the judge could not assess confidently and why. "
            "Surfaces uncertainty rather than averaging it away in "
            "the composite."
        ),
    )


# ===========================================================================
# Cross-judge aggregate
# ===========================================================================

class InterRaterAgreement(BaseModel):
    """Krippendorff's α across the judges, overall + per dimension.

    α interpretation thresholds (Krippendorff 2004):
      * α >= 0.80 — reliable for substantive conclusions
      * 0.67 <= α < 0.80 — tentative conclusions only
      * α < 0.67 — not reliable; report as exploratory

    Per-dimension α exposes which dimensions the judges agreed
    on vs disagreed on. The overall α is the α over all (judge ×
    dimension) ratings.
    """

    overall_alpha: float = Field(
        ...,
        description=(
            "Krippendorff's α over all (judge × dimension) ratings "
            "treated as one ordinal data set. Range -1.0 to 1.0; "
            "thresholds in the class docstring."
        ),
    )
    # Four raters by default (`providers.JUDGE_PROVIDERS`); the description below is older.
    per_dimension_alpha: Dict[str, float] = Field(
        default_factory=dict,
        description=(
            "α computed separately per dimension. With only three "
            "raters per dimension, per-dimension α is noisier than "
            "overall α — use mainly to spot dimensions where judges "
            "strongly disagree."
        ),
    )
    per_sub_dimension_alpha: Dict[str, float] = Field(
        default_factory=dict,
        description=(
            "α per sub-dimension under v0.4. Keyed by sub_dimension_key "
            "(e.g. 'outbound_publication_intensity'). Empty for v0.3 "
            "runs that don't ship sub-dim assessments. The per-sub-dim "
            "α surfaces precisely where the construct contests across "
            "judges — directly supporting DECISIONS §23 claim 3 "
            "(construct contestation as data)."
        ),
    )
    n_judges: int = Field(
        ...,
        description="Number of judges in the ensemble (typically 3 or 4).",
    )
    n_dimensions: int = Field(
        ...,
        description="Number of rubric (parent) dimensions scored.",
    )
    n_sub_dimensions: int = Field(
        0,
        description=(
            "Number of sub-dimensions scored. 0 for v0.3 runs (no "
            "sub-dim layer); 26 for v0.4 openness runs."
        ),
    )


class ConstructJudgmentBundle(BaseModel):
    """Aggregate output of the judge ensemble for one run.

    Persisted as `05_judging/aggregate.{json,md}` in the per-run
    folder. The individual judge assessments live alongside as
    `05_judging/<judge_id>_assessment.{json,md}`.
    """

    # Four judges by default (`providers.JUDGE_PROVIDERS`); the description below is older.
    assessments: List[ConstructAssessment] = Field(
        ...,
        description=(
            "The three (or more) individual judge assessments. The "
            "framework default is 3 (gemini_pro, claude, openai); a "
            "future study could use a larger ensemble."
        ),
    )
    mean_composite: float = Field(
        ...,
        ge=1.0,
        le=7.0,
        description=(
            "Mean composite score across judges. This is the "
            "headline construct score for the run."
        ),
    )
    per_dimension_means: Dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Mean parent-dimension Likert (1-7) across judges. Lets a "
            "reader see which parent dimensions drive the headline "
            "composite."
        ),
    )
    consensus_dimension_scores: Dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Per-dimension consensus score, computed as the rounded "
            "mean across judges. Used for downstream reporting that "
            "wants discrete Likert values rather than fractional "
            "means."
        ),
    )
    per_sub_dimension_means_pct: Dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Mean `score_pct` across judges for each sub-dimension "
            "under v0.4. Keyed by sub_dimension_key (e.g. "
            "'outbound_publication_intensity'). The continuous 0-100 "
            "view of the construct that the Likert hides. Empty for "
            "v0.3 runs without sub-dim assessments."
        ),
    )
    per_sub_dimension_means_likert: Dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Mean `score_pct` back-binned to Likert 1-7 for reviewer-"
            "compatible reporting. Computed as "
            "`percent_to_likert(mean_pct)` per sub-dimension. Empty "
            "for v0.3 runs."
        ),
    )
    inter_rater_agreement: InterRaterAgreement = Field(
        ...,
        description=(
            "Krippendorff's α, overall + per dimension. See "
            "InterRaterAgreement docstring for interpretation."
        ),
    )
    judges_used: List[str] = Field(
        ...,
        description=(
            "Provider keys of the judges in the ensemble (e.g. "
            "['gemini_pro', 'claude', 'openai']). Captured here so "
            "the bundle is self-describing. This list reflects judges "
            "that scored successfully — see `judge_errors` for any "
            "that failed."
        ),
    )
    judge_errors: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Failures captured per provider during the parallel "
            "judge run, keyed by provider name. Value is the captured "
            "exception text (repr + traceback) so post-mortem doesn't "
            "require re-running. Empty when every configured judge "
            "scored successfully. The persistence layer writes each "
            "entry to `05_judging/<provider>_error.txt` alongside the "
            "successful judges' assessment files."
        ),
    )
    quote_verification_summary: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description=(
            "Per-judge quote-verification summary populated by the "
            "v0.4 persistence layer (`ConstructJudgingPhase.persist`). "
            "Keyed by provider name; value is "
            "{n_total, n_passed, n_failed, fail_rate}. Empty for v0.3 "
            "bundles (no sub-dim assessments) and for runs without a "
            "persistence pass that invoked the verifier. The full "
            "per-quote audit lives in `05_judging/<provider>_quote_"
            "audit.md`."
        ),
    )
