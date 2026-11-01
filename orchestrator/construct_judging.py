"""Phase-5 construct-judge ensemble orchestrator.

Phase 5 is an optional last stage of a run (one complete simulated meeting and
debrief). A judge is a language model that scores the finished run against a rubric
(a scoring guide saying what to rate and how). It runs only with `--judge`, and this
scoring sits outside the proposal's method.

Builds four construct judges by default (one per provider, the company supplying the model,
in `providers.JUDGE_PROVIDERS`), runs them in parallel via `asyncio.gather` (Python's
way to run tasks side by side), aggregates their per-dimension scores into a
mean composite, and computes Krippendorff's α as the inter-rater
agreement statistic.

The orchestrator is study-agnostic (it works for any study folder under
`studies/`) — the construct being scored is
whatever the active study's `JudgmentRubric` defines (the default
``openness_maneuvering`` study scores openness; another study would
score whatever its rubric describes).

Method (see also `docs/05_methodological_invariants.md` and
`roles/construct_judge.py`):

  * Judge ensemble — different LLM (large language model) vendors. Controls for
    single-model bias. α across judges reports how far they agree.
  * Two-stage scoring per judge — qualitative summary first, then
    structured (fixed, named fields) Likert. Reduces post-hoc rationalisation of scores.
  * Composite = simple mean across the rubric's dimensions. Composite
    score across judges = simple mean of the per-judge composites.
  * Krippendorff's α — ordinal variant. Implemented in
    `_krippendorff_alpha_ordinal` below so the framework does not
    take on the `krippendorff` package (ready-made code) as a dependency.

What the judges see is constructed by `_build_judge_inputs(...)`:
artefacts (the roles' strategy documents) in full, public transcript only (private
scratchpads, or notes, and drafts excluded), observation summary, FieldNoter (the
researcher agent writing field notes) notes, debriefing (the researcher agent's
interview of the team) transcript.
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

try:
    from ..providers import JUDGE_PROVIDERS
    from ..studies import StudyConfig
    from ..roles.construct_judge import create_construct_judge_agent
    from ..roles.judge_schemas import (
        DimensionAssessment,
        InterRaterAgreement,
        ConstructAssessment,
        ConstructJudgmentBundle,
    )
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from providers import JUDGE_PROVIDERS  # type: ignore[no-redef]
    from studies import StudyConfig  # type: ignore[no-redef]
    from roles.construct_judge import create_construct_judge_agent  # type: ignore[no-redef]
    from roles.judge_schemas import (  # type: ignore[no-redef]
        DimensionAssessment,
        InterRaterAgreement,
        ConstructAssessment,
        ConstructJudgmentBundle,
    )

log = logging.getLogger(__name__)


# Same shape the rest of the orchestrators use.
RunnerFn = Callable[..., Awaitable]


# ===========================================================================
# PhaseHandler — the default extra phase a study can register
# ===========================================================================

class ConstructJudgingPhase:
    """The framework's default Phase 5 handler — rubric-anchored
    three-LLM-judge construct scoring.

    Implements the `PhaseHandler` protocol (here, the methods a handler must supply,
    not the debrief protocol) in `studies/base.py`.
    A study opts in by adding `ConstructJudgingPhase()` to its
    `StudyConfig.extra_phases` list AND supplying a `judgment_rubric`
    on the same config. A study without a rubric (or one that
    doesn't register this handler) simply doesn't get Phase 5.

    The handler is fully self-contained: it owns the orchestration
    (delegating to `run_construct_judging` below), the persisted
    folder layout, and the markdown (plain text with simple marks for headings and
    lists) rendering. Adding a *different*
    Phase 5 (e.g. a different scoring method, a member-checking
    follow-up, a counterfactual replay) means writing a new handler
    class — no framework changes.
    """

    name: str = "construct_judging"
    folder_prefix: str = "05_judging"

    def should_run(self, *, study, outputs) -> bool:
        """Run iff the study has a rubric AND Phase 4 didn't blow up.

        We refuse to score on a broken run: if `outputs.errors` is
        non-empty the deliberation / artefact / debriefing layers
        produced something the rubric judges can't reliably read,
        and a composite from that is misleading.
        """
        if study.judgment_rubric is None:
            return False
        if outputs.errors:
            return False
        # Inputs the judges need:
        if outputs.artefacts is None:
            return False
        if outputs.deliberation_log is None:
            return False
        if outputs.observation_summary is None:
            return False
        if outputs.debriefing_transcript is None:
            return False
        return True

    async def run(
        self,
        *,
        study,
        outputs,
        run_agent,
        company: str,
        industry_context: str,
        product_type: str,
    ):
        """Build + run the judge ensemble; return the bundle."""
        # `outputs.researcher_stream_field_notes` is set by
        # `run_research_session` before calling extra phases.
        field_notes = getattr(outputs, "researcher_stream_field_notes", None)
        return await run_construct_judging(
            study=study,
            company=company,
            industry_context=industry_context,
            product_type=product_type,
            deliberation_log=outputs.deliberation_log,
            artefacts=outputs.artefacts,
            observation_summary=outputs.observation_summary,
            debriefing_transcript=outputs.debriefing_transcript,
            field_notes=field_notes,
            run_agent=run_agent,
        )

    def persist(
        self,
        *,
        out_dir,
        result,
        write_json: bool,
    ) -> None:
        """Write the bundle to `<out_dir>/05_judging/`.

        Layout (.json files hold JSON, a plain-text format of named fields):
            05_judging/
              aggregate.{json,md}              ← cross-judge mean + α
              <judge_id>_assessment.{json,md}  ← per-judge output
              <provider>_error.txt             ← only when a judge failed;
                                                 carries repr(exc) +
                                                 traceback.format_exc()

        `result` is a `ConstructJudgmentBundle` instance (live model)
        OR an already-serialised dict (when persistence is re-driven
        from on-disk JSON via `burst_run_from_files`). The handler
        handles both.
        """
        import json
        # Local imports — keep `persist()` callable without dragging
        # the analysis layer in at module load.
        try:
            from ..analysis.persist_artefacts import (
                _render_judgment_aggregate_md,
                _render_judge_assessment_md,
            )
        except (ImportError, ValueError):  # pragma: no cover  (script-style)
            from analysis.persist_artefacts import (  # type: ignore[no-redef]
                _render_judgment_aggregate_md,
                _render_judge_assessment_md,
            )

        # Normalise to dict so we have one code path below.
        if hasattr(result, "model_dump"):
            bundle = result.model_dump(mode="json")
        else:
            bundle = result

        judging = out_dir / self.folder_prefix
        judging.mkdir(exist_ok=True)

        # Aggregate. The .md is always written; the .json is always
        # written too (independent of `write_json`). The `--no-json`
        # flag governs the *burst*-style JSON sub-files in other phase
        # folders — judge JSONs are the replay-enabling (replay: re-running a stage from
        # a saved run) artefact for
        # `analysis.replay_judges` and must always land regardless.
        # See DECISIONS §29 (entry 29 in `DECISIONS.md`) for the policy rationale.
        (judging / "aggregate.json").write_text(
            json.dumps(bundle, indent=2, default=str)
        )
        (judging / "aggregate.md").write_text(_render_judgment_aggregate_md(bundle))

        # Per-judge assessments — same policy as aggregate.json above.
        for a in bundle.get("assessments", []) or []:
            judge_id = a.get("judge_id", "unknown")
            (judging / f"{judge_id}_assessment.json").write_text(
                json.dumps(a, indent=2, default=str)
            )
            (judging / f"{judge_id}_assessment.md").write_text(
                _render_judge_assessment_md(a)
            )

        # Per-judge error files for any judges that didn't score
        # successfully. Empty `judge_errors` (the success case) yields
        # zero files written here — back-compatible with runs that
        # pre-date this field.
        for provider, error_text in (bundle.get("judge_errors") or {}).items():
            (judging / f"{provider}_error.txt").write_text(str(error_text))

        # Quote-verification (checking that a quoted phrase appears word for word in
        # the record it names) audit (v0.4). For each assessment with
        # sub_dimension_assessments, substring-check every
        # EvidenceQuote against its source_file relative to `out_dir`
        # (the run folder). Audit files land as
        # `<provider>_quote_audit.md`; the per-provider summary is
        # threaded into the bundle's `quote_verification_summary`
        # field so the aggregate report can surface fail rates.
        # v0.3 assessments (no sub_dimension_assessments) skip this
        # block cleanly — nothing to verify, no audit file.
        try:
            from ..analysis.quote_verification import (
                verify_quotes_in_assessment,
                render_quote_audit_md,
            )
        except (ImportError, ValueError):  # pragma: no cover  (script-style)
            from analysis.quote_verification import (  # type: ignore[no-redef]
                verify_quotes_in_assessment,
                render_quote_audit_md,
            )

        verification_summary: dict = {}
        for a in bundle.get("assessments", []) or []:
            judge_id = a.get("judge_id", "unknown")
            sub_dims = a.get("sub_dimension_assessments") or []
            if not sub_dims:
                continue
            report = verify_quotes_in_assessment(
                assessment=a, run_dir=out_dir,
            )
            (judging / f"{judge_id}_quote_audit.md").write_text(
                render_quote_audit_md(report)
            )
            verification_summary[judge_id] = {
                "n_total": report.n_total,
                "n_passed": report.n_passed,
                "n_failed": report.n_failed,
                "fail_rate": round(report.fail_rate, 4),
            }

        # Re-write aggregate.json + aggregate.md to carry the summary
        # if any verifications ran. Without this re-write the
        # aggregate file would lack the verification_summary the
        # bundle now records.
        if verification_summary:
            bundle["quote_verification_summary"] = verification_summary
            (judging / "aggregate.json").write_text(
                json.dumps(bundle, indent=2, default=str)
            )
            (judging / "aggregate.md").write_text(
                _render_judgment_aggregate_md(bundle)
            )


# ===========================================================================
# Public entry point (function form — usable by the handler or directly)
# ===========================================================================

async def run_construct_judging(
    *,
    study: StudyConfig,
    company: str,
    industry_context: str,
    product_type: str,
    deliberation_log: Any,
    artefacts: Any,
    observation_summary: Any,
    debriefing_transcript: Any,
    field_notes: Optional[List[str]],
    run_agent: RunnerFn,
    judge_providers: Optional[List[str]] = None,
) -> ConstructJudgmentBundle:
    """Run the multi-judge construct-scoring ensemble.

    Args:
        study: The active StudyConfig. Must have `judgment_rubric`
            set or this function raises.
        company, industry_context, product_type: Scenario context
            (rendered into the per-judge prompt for situational
            awareness — not used to bias the scoring).
        deliberation_log: The `DeliberationLog` from Phase 1.
        artefacts: The `ArtefactBundle` from Phase 2.
        observation_summary: The `ObservationSummary` from Phase 3.
        debriefing_transcript: The `DebriefingTranscript` from
            Phase 4.
        field_notes: The FieldNoter's running prose notes (free-form
            list of strings — typically `researcher_stream.field_notes`).
        run_agent: Per-agent runner — same signature as the other
            orchestrators use.
        judge_providers: Provider keys for the judges. Default uses
            `providers.JUDGE_PROVIDERS`.

    Returns:
        A `ConstructJudgmentBundle` with the judges' assessments (four by
        default) + aggregate statistics.

    Raises:
        ValueError: if the study has no `judgment_rubric`.
    """
    if study.judgment_rubric is None:
        raise ValueError(
            f"Study {study.slug!r} has no judgment_rubric — Phase 5 "
            f"(construct judging) cannot run for this study."
        )

    providers = list(judge_providers or JUDGE_PROVIDERS)
    if not providers:
        raise ValueError("No judge providers configured.")

    rubric = study.judgment_rubric
    dim_keys = [d.key for d in rubric.dimensions]

    log.info(
        "construct_judging.start providers=%s dimensions=%d",
        providers, len(dim_keys),
    )

    # Build the inputs once; every judge sees the same text.
    judge_prompt_inputs = _build_judge_inputs(
        company=company,
        industry_context=industry_context,
        product_type=product_type,
        deliberation_log=deliberation_log,
        artefacts=artefacts,
        observation_summary=observation_summary,
        debriefing_transcript=debriefing_transcript,
        field_notes=field_notes,
    )

    # Build one judge agent per provider.
    judges = {p: create_construct_judge_agent(provider=p, study=study) for p in providers}

    # Run all judges in parallel. They share no state (each has its
    # own LLM provider, own ADK (Agent Development Kit: Google's software for
    # building agents) session, meaning a stored conversation). asyncio.gather kicks them
    # off concurrently.
    #
    # Each `_one_judge` returns `(assessment, error_text)`. Exactly one
    # of the two is populated. The outer loop sorts these into
    # `assessments` (for the aggregator) and `judge_errors` (persisted
    # to `<provider>_error.txt` so post-mortem doesn't require re-
    # running the LLM call). `traceback.format_exc()` (Python's record of
    # where an error arose) is captured because some provider errors arrive
    # with an empty message. See
    # `tests/test_construct_judging.py::TestFailedJudgeCapture`.
    # Judge calls go through `safe_run_with_capture` from
    # `orchestrator.llm_retry` — the same helper the replay tool
    # uses. Retry-with-backoff (trying again, waiting longer each time) on
    # transient (temporary) errors (5xx, 429,
    # Server disconnected, etc.); non-transient errors short-
    # circuit. On exhaustion / non-transient failure the helper
    # returns `(None, error_text)` where error_text carries
    # `repr(exc) + traceback.format_exc()`, saved in the
    # `<provider>_error.txt` audit trail.
    try:
        from .llm_retry import safe_run_with_capture
    except (ImportError, ValueError):  # pragma: no cover  (script-style)
        from orchestrator.llm_retry import safe_run_with_capture  # type: ignore[no-redef]

    async def _one_judge(
        provider: str,
    ) -> Tuple[Optional[ConstructAssessment], Optional[str]]:
        raw, error_text = await safe_run_with_capture(
            run_agent,
            judges[provider],
            judge_prompt_inputs,
            provider=provider,
        )
        if error_text is not None:
            return None, error_text
        return _coerce_assessment(
            raw, provider=provider, dim_keys=dim_keys,
        ), None

    results = await asyncio.gather(*[_one_judge(p) for p in providers])

    assessments: List[ConstructAssessment] = []
    judge_errors: Dict[str, str] = {}
    for provider, (assessment, error_text) in zip(providers, results):
        if assessment is not None:
            assessments.append(assessment)
        elif error_text is not None:
            # `_one_judge` raised and we captured the text.
            judge_errors[provider] = error_text
        else:
            # `_coerce_assessment` returned None (parse / validation
            # failure) — those paths already log at ERROR level with
            # their own exc text. Record a marker error so the bundle
            # still surfaces which provider didn't score.
            judge_errors[provider] = (
                f"{provider}: assessment coercion returned None — see "
                f"prior ERROR-level log lines tagged "
                f"construct_judging.parse_failed / .validation_failed / "
                f".unexpected_type."
            )

    if not assessments:
        raise RuntimeError(
            "All judges failed. Bundle cannot be assembled. Check "
            "provider credentials + the judges' error logs. Captured "
            f"errors: {sorted(judge_errors.keys())}"
        )

    bundle = _aggregate(
        assessments=assessments,
        rubric_dim_keys=dim_keys,
        judge_errors=judge_errors,
    )
    log.info(
        "construct_judging.complete judges=%d failed=%d composite=%.2f alpha=%.2f",
        len(assessments), len(judge_errors), bundle.mean_composite,
        bundle.inter_rater_agreement.overall_alpha,
    )
    return bundle


# ===========================================================================
# Build the inputs the judges see
# ===========================================================================

def _build_judge_inputs(
    *,
    company: str,
    industry_context: str,
    product_type: str,
    deliberation_log: Any,
    artefacts: Any,
    observation_summary: Any,
    debriefing_transcript: Any,
    field_notes: Optional[List[str]],
) -> str:
    """Render every input the judges see as one prompt-ready string.

    Public transcript ONLY — private scratchpads and drafts are
    excluded by virtue of using `deliberation_log.events` (which is
    the public transcript via `DeliberationEvent`s) rather than
    SharedState's role_states.
    """
    parts: List[str] = []

    parts.append("SCENARIO CONTEXT")
    parts.append("================")
    parts.append(f"- Firm: {company}")
    parts.append(f"- Industry context: {industry_context}")
    parts.append(f"- Product type: {product_type}")
    parts.append("")

    # 1. Strategic artefacts (full text, all six roles)
    parts.append("STRATEGIC ARTEFACTS (6 ROLE DOCUMENTS)")
    parts.append("=====================================")
    if artefacts is not None and getattr(artefacts, "artefacts", None):
        for a in artefacts.artefacts:
            parts.append(f"\n## {a.role} — {a.title}")
            if a.key_challenges:
                parts.append("Key challenges:")
                for c in a.key_challenges:
                    parts.append(f"  - {c}")
            if a.main_decisions:
                parts.append("Main decisions:")
                for d in a.main_decisions:
                    parts.append(f"  - {d}")
            if a.key_tensions:
                parts.append("Key tensions:")
                for t in a.key_tensions:
                    parts.append(f"  - {t}")
            parts.append("\n" + (a.body or ""))
    else:
        parts.append("(no artefacts produced)")
    parts.append("")

    # 2. Public deliberation transcript
    parts.append("DELIBERATION TRANSCRIPT (PUBLIC events only)")
    parts.append("============================================")
    parts.append(
        "Each line is one public deliberation event. Private "
        "scratchpads and working drafts are NOT shown — you assess "
        "what the firm publicly enacted, not its hidden internal "
        "thinking."
    )
    parts.append("")
    if deliberation_log is not None:
        try:
            parts.append(deliberation_log.as_plain_transcript())
        except Exception:  # noqa: BLE001
            parts.append("(deliberation log could not be rendered)")
    else:
        parts.append("(no deliberation log captured)")
    parts.append("")

    # 3. Researcher's structured observation summary
    parts.append("RESEARCHER'S OBSERVATION SUMMARY")
    parts.append("================================")
    if observation_summary is not None:
        try:
            obs_json = observation_summary.model_dump_json(indent=2)
            parts.append("```json")
            parts.append(obs_json)
            parts.append("```")
        except Exception:  # noqa: BLE001
            parts.append(str(observation_summary))
    else:
        parts.append("(no observation summary)")
    parts.append("")

    # 4. Researcher's running field notes
    parts.append("RESEARCHER'S LIVE FIELD NOTES (mid-phase)")
    parts.append("=========================================")
    if field_notes:
        for i, note in enumerate(field_notes, 1):
            parts.append(f"### Field note {i}")
            parts.append(note)
            parts.append("")
    else:
        parts.append("(no live field notes captured)")
    parts.append("")

    # 5. Debriefing transcript
    parts.append("PANEL DEBRIEFING TRANSCRIPT")
    parts.append("===========================")
    if debriefing_transcript is not None and getattr(debriefing_transcript, "exchanges", None):
        for i, ex in enumerate(debriefing_transcript.exchanges, 1):
            utt = ex.utterance
            parts.append(f"### Exchange {i} (Area {utt.area_id})")
            parts.append(f"**Researcher**: {utt.text}")
            for r in ex.responses or []:
                marker = " (cross-talk)" if getattr(r, "is_cross_talk", False) else ""
                parts.append(f"**{r.role}**{marker}: {r.text}")
            parts.append("")
    else:
        parts.append("(no debriefing exchanges)")

    return "\n".join(parts)


# ===========================================================================
# Coerce one judge's raw return into an ConstructAssessment
# ===========================================================================

def _coerce_assessment(
    raw: Any,
    *,
    provider: str,
    dim_keys: List[str],
) -> Optional[ConstructAssessment]:
    """Normalise a judge's raw return into an `ConstructAssessment`.

    The provider is patched into `judge_id` after parsing — the
    judge's own self-reported id can be unreliable.
    """
    payload: Any
    if isinstance(raw, ConstructAssessment):
        payload = raw.model_dump()
    elif isinstance(raw, dict):
        payload = dict(raw)
    elif isinstance(raw, str):
        # Strip ```json … ``` fences and any prose framing — judges that
        # run on `json_object`-mode (any JSON is accepted, whatever its fields) providers
        # (DeepSeek, Ollama) are not
        # schema-enforced server-side, so the parser is the boundary.
        cleaned = _strip_json_envelope(raw)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            log.error(
                "construct_judging.parse_failed provider=%s exc=%s",
                provider, exc,
            )
            return None
    else:
        log.error(
            "construct_judging.unexpected_type provider=%s type=%s",
            provider, type(raw).__name__,
        )
        return None

    payload["judge_id"] = provider

    try:
        assessment = ConstructAssessment.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        log.error(
            "construct_judging.validation_failed provider=%s exc=%s",
            provider, exc,
        )
        return None

    # Sanity-check that the dimension keys match the rubric.
    actual_keys = {d.dimension for d in assessment.dimension_scores}
    expected_keys = set(dim_keys)
    if actual_keys != expected_keys:
        log.warning(
            "construct_judging.dim_mismatch provider=%s expected=%s got=%s",
            provider, sorted(expected_keys), sorted(actual_keys),
        )
        # Continue with whatever was returned — the aggregator handles
        # partial overlap gracefully.

    return assessment


def _strip_json_envelope(text: str) -> str:
    """Strip ```json … ``` fences and any prose framing around a JSON object.

    Symmetric helper to `artefact_collection._strip_json_envelope`.
    Tolerates the two common quirks seen on `json_object`-mode providers
    (DeepSeek, Ollama) where the model returns a fenced block or a
    leading/trailing prose sentence. If no JSON-looking content is
    found, returns the input unchanged.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if 0 <= first_brace < last_brace:
        return stripped[first_brace : last_brace + 1]
    return stripped


# ===========================================================================
# Aggregation
# ===========================================================================

def _aggregate(
    *,
    assessments: List[ConstructAssessment],
    rubric_dim_keys: List[str],
    judge_errors: Optional[Dict[str, str]] = None,
) -> ConstructJudgmentBundle:
    """Compute the cross-judge mean composite + per-dimension means +
    Krippendorff's α at parent-dim AND sub-dim granularity.

    `judge_errors` carries any per-provider failures captured during
    the parallel judge run so they survive into the persisted bundle.
    Defaults to `{}` when every judge scored successfully — back-
    compatible with the existing test fixtures and `replay_judges`
    callsite that don't pass it.

    v0.4 dual-granularity α (PR-D commit 4/6):

    * Parent-dimension α — the v0.3 path; unchanged.
    * Sub-dimension (one narrow item within a rubric dimension) α — computed
      when ≥1 judge provides
      `sub_dimension_assessments`. Per-sub-dim α uses
      `_one_item_agreement` because each sub-dim is one item × N
      raters (same edge case as the existing per-parent-dim α). The
      sub-dim alphas surface exactly where the construct contests
      across judges — DECISIONS §23 claim 3.
    """
    # Per-judge composite is already computed by each judge; the
    # mean composite is the simple mean across judges.
    composites = [a.composite_score for a in assessments]
    mean_composite = sum(composites) / len(composites)

    # Per-dimension means: average each dimension's score across the
    # judges that scored it.
    per_dim_scores: dict[str, list[int]] = {key: [] for key in rubric_dim_keys}
    for a in assessments:
        for d in a.dimension_scores:
            if d.dimension in per_dim_scores:
                per_dim_scores[d.dimension].append(d.score)

    per_dimension_means: dict[str, float] = {}
    consensus: dict[str, int] = {}
    for key, scores in per_dim_scores.items():
        if scores:
            mean = sum(scores) / len(scores)
            per_dimension_means[key] = round(mean, 3)
            consensus[key] = round(mean)
        else:
            per_dimension_means[key] = float("nan")
            consensus[key] = 4  # default to mid anchor if nothing

    # Inter-rater agreement.
    alpha_overall = _krippendorff_alpha_ordinal(
        [
            [d.score for d in sorted(a.dimension_scores, key=lambda x: x.dimension)]
            for a in assessments
        ]
    )

    per_dim_alpha: dict[str, float] = {}
    for key in rubric_dim_keys:
        col = [per_dim_scores[key]] if per_dim_scores[key] else []
        # Krippendorff's α for one item × N raters is undefined; we
        # compute a simple variance-based proxy: 1 - var / max_var.
        if col and col[0] and len(col[0]) >= 2:
            per_dim_alpha[key] = _one_item_agreement(col[0])
        else:
            per_dim_alpha[key] = float("nan")

    # --- v0.4 sub-dimensional rollup ---------------------------------
    #
    # Collect every judge's per-sub-dim percent score keyed by
    # sub_dimension_key. Each judge's assessment may either populate
    # `sub_dimension_assessments` (v0.4) or leave it empty (v0.3). The
    # sub-dim layer activates only if ≥1 judge supplied entries.
    per_sub_pct_lists: dict[str, list[float]] = {}
    for a in assessments:
        for sd in getattr(a, "sub_dimension_assessments", []) or []:
            per_sub_pct_lists.setdefault(sd.sub_dimension_key, []).append(
                float(sd.score_pct)
            )

    per_sub_dim_means_pct: dict[str, float] = {}
    per_sub_dim_means_likert: dict[str, int] = {}
    per_sub_dim_alpha: dict[str, float] = {}
    # Import here to avoid a hot-path import cost when no sub-dim
    # layer is in play (the back-compat case).
    try:
        from ..roles.judge_schemas import percent_to_likert as _pct_to_lk
    except (ImportError, ValueError):  # pragma: no cover  (script-style)
        from roles.judge_schemas import percent_to_likert as _pct_to_lk  # type: ignore[no-redef]

    for sub_key, pct_scores in per_sub_pct_lists.items():
        if not pct_scores:
            continue
        mean_pct = sum(pct_scores) / len(pct_scores)
        per_sub_dim_means_pct[sub_key] = round(mean_pct, 2)
        per_sub_dim_means_likert[sub_key] = _pct_to_lk(mean_pct)
        # α per sub-dim: same one-item-N-rater path as per-parent-dim
        # alpha — each sub-dim is one item × N raters. Use the
        # judges' Likert back-bin values for the agreement
        # computation so the math is dimensionless (percent and
        # Likert give different α magnitudes for the same data;
        # Likert keeps the statistic comparable to v0.3 numbers).
        if len(pct_scores) >= 2:
            likert_scores = [_pct_to_lk(s) for s in pct_scores]
            per_sub_dim_alpha[sub_key] = _one_item_agreement(likert_scores)
        else:
            per_sub_dim_alpha[sub_key] = float("nan")

    iraa = InterRaterAgreement(
        overall_alpha=alpha_overall,
        per_dimension_alpha=per_dim_alpha,
        per_sub_dimension_alpha=per_sub_dim_alpha,
        n_judges=len(assessments),
        n_dimensions=len(rubric_dim_keys),
        n_sub_dimensions=len(per_sub_dim_means_pct),
    )

    return ConstructJudgmentBundle(
        assessments=assessments,
        mean_composite=round(mean_composite, 3),
        per_dimension_means=per_dimension_means,
        consensus_dimension_scores=consensus,
        per_sub_dimension_means_pct=per_sub_dim_means_pct,
        per_sub_dimension_means_likert=per_sub_dim_means_likert,
        inter_rater_agreement=iraa,
        judges_used=[a.judge_id for a in assessments],
        judge_errors=dict(judge_errors or {}),
    )


# ===========================================================================
# Krippendorff's α (ordinal variant) — implemented directly to avoid
# taking on the `krippendorff` package as a dependency.
# ===========================================================================

def _krippendorff_alpha_ordinal(ratings: List[List[int]]) -> float:
    """Compute Krippendorff's α for ordinal data.

    `ratings` is a list of N judges, each a list of M items they
    scored. All judges must have rated all items (no missing data).

    Returns α in roughly [-1.0, 1.0]. α = 1 → perfect agreement, α =
    0 → agreement at chance level, α < 0 → systematic disagreement.

    Reference: Krippendorff (2011) Computing Krippendorff's Alpha-
    Reliability. http://repository.upenn.edu/asc_papers/43/
    """
    n_judges = len(ratings)
    if n_judges < 2:
        return float("nan")
    n_items = len(ratings[0])
    if n_items == 0 or any(len(r) != n_items for r in ratings):
        return float("nan")

    # Observed disagreement: average squared ordinal distance between
    # ratings of the same item.
    obs_disagreement = 0.0
    n_pairs = 0
    for i in range(n_items):
        scores_for_item = [r[i] for r in ratings]
        for j in range(len(scores_for_item)):
            for k in range(j + 1, len(scores_for_item)):
                obs_disagreement += (scores_for_item[j] - scores_for_item[k]) ** 2
                n_pairs += 1
    obs_disagreement = obs_disagreement / n_pairs if n_pairs else 0.0

    # Expected disagreement: variance under random pairing across all
    # ratings.
    all_scores = [s for r in ratings for s in r]
    n_all = len(all_scores)
    exp_disagreement = 0.0
    if n_all >= 2:
        total = 0.0
        for i in range(n_all):
            for j in range(i + 1, n_all):
                total += (all_scores[i] - all_scores[j]) ** 2
        exp_disagreement = total / ((n_all * (n_all - 1)) / 2)

    if exp_disagreement == 0:
        # No variation across all ratings — perfect agreement.
        return 1.0
    return 1.0 - (obs_disagreement / exp_disagreement)


def _one_item_agreement(scores: List[int]) -> float:
    """Simple agreement proxy for a single item rated by N judges.

    Defined as 1 - (var / max_var) where var is the sample variance
    of `scores` and max_var is the maximum possible variance on a 1-7
    Likert. Returns 1.0 when all judges agree, decreases toward 0 as
    disagreement grows.

    Used as a per-dimension proxy because Krippendorff's α is only
    well-defined over multiple items.
    """
    if len(scores) < 2:
        return float("nan")
    mean = sum(scores) / len(scores)
    var = sum((s - mean) ** 2 for s in scores) / len(scores)
    # Max variance on 1-7 Likert with len(scores) raters is achieved
    # when half are at 1 and half at 7 (or vice versa). Compute it:
    n = len(scores)
    half_lo = n // 2
    half_hi = n - half_lo
    extreme = ([1] * half_lo) + ([7] * half_hi)
    extreme_mean = sum(extreme) / n
    max_var = sum((s - extreme_mean) ** 2 for s in extreme) / n
    if max_var == 0:
        return 1.0
    return max(0.0, 1.0 - var / max_var)
