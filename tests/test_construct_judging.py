"""Tests for the Phase-5 construct-judge ensemble.

Covers:
  * Rubric schema (`RubricDimension`, `JudgmentRubric`) + the
    openness study's concrete seven-dimensional rubric (the rubric
    instance lives in `studies/openness_maneuvering/__init__.py`; the
    ensemble machinery exercised here is study-agnostic).
  * Per-judge schemas (`DimensionAssessment`, `ConstructAssessment`).
  * Bundle schema + cross-judge aggregation.
  * Krippendorff's α (ordinal) — agreement, disagreement, edge cases.
  * The judge prompt — rubric + methodology framing render correctly,
    and the prompt does not leak SCRATCHPAD content (judges see public
    transcript only).
  * The orchestrator's stub-runnable end-to-end path (no live LLM):
    given three pre-baked assessments, it aggregates correctly.
"""

from __future__ import annotations

import asyncio
import importlib

import pytest

PKG = "open-innovation-strategy"


def _judging():
    return importlib.import_module(f"{PKG}.orchestrator.construct_judging")


def _schemas():
    return importlib.import_module(f"{PKG}.roles.judge_schemas")


def _studies():
    return importlib.import_module(f"{PKG}.studies")


def _judge_agent():
    return importlib.import_module(f"{PKG}.roles.construct_judge")


# ===========================================================================
# 1. Rubric schema + openness rubric definition
# ===========================================================================

class TestOpennessRubric:
    def test_openness_study_has_a_rubric(self):
        s = _studies().load_study("openness_maneuvering")
        assert s.judgment_rubric is not None
        assert s.judgment_rubric.name

    def test_openness_rubric_has_seven_dimensions(self):
        s = _studies().load_study("openness_maneuvering")
        assert len(s.judgment_rubric.dimensions) == 7

    def test_dimensions_have_required_anchors_and_keys(self):
        s = _studies().load_study("openness_maneuvering")
        keys_seen: set[str] = set()
        for d in s.judgment_rubric.dimensions:
            assert d.key
            assert d.name
            assert d.description
            assert d.anchor_low
            assert d.anchor_mid
            assert d.anchor_high
            # Keys must be unique (used as map keys downstream).
            assert d.key not in keys_seen, f"duplicate key {d.key}"
            keys_seen.add(d.key)

    def test_dimensions_cover_construct_categories(self):
        """The seven dimensions name the construct surfaces grounded in
        Henkel 2006 (selective revealing + dynamic) / Chesbrough 2003
        (open innovation) / Jacobides 2018 (ecosystem) / Teece 2007
        (value capture) / Dahlander & Gann 2010 (inbound/outbound split)
        / Alexy, Henkel & Wallin 2013 (temporal maneuvering). Guard
        against drift to a smaller / less-grounded rubric."""
        s = _studies().load_study("openness_maneuvering")
        keys = {d.key for d in s.judgment_rubric.dimensions}
        assert keys == {
            "component_disclosure",
            "process_openness",
            "boundary_permeability_inbound",
            "boundary_permeability_outbound",
            "ecosystem_orchestration",
            "value_capture_posture",
            "temporal_openness_maneuvering",
        }

    def test_test_alt_study_has_no_rubric(self):
        """The synthetic alt study does NOT define a rubric — Phase 5
        should be unavailable for studies without one."""
        s = _studies().load_study("_test_alt")
        assert s.judgment_rubric is None


# ===========================================================================
# 2. Per-judge schemas
# ===========================================================================

class TestPerJudgeSchemas:
    def test_dimension_assessment_requires_score_1_to_7(self):
        sch = _schemas()
        # Valid
        ok = sch.DimensionAssessment(
            dimension="component_disclosure",
            score=5,
            reasoning="The firm released weights for the research tier.",
            evidence=["'we will publish the weights at the research tier'"],
            confidence="high",
        )
        assert ok.score == 5
        # Out of range
        with pytest.raises(Exception):
            sch.DimensionAssessment(
                dimension="component_disclosure", score=0,
                reasoning="x", evidence=[], confidence="low",
            )
        with pytest.raises(Exception):
            sch.DimensionAssessment(
                dimension="component_disclosure", score=8,
                reasoning="x", evidence=[], confidence="low",
            )

    def test_openness_assessment_composite_within_likert_range(self):
        sch = _schemas()
        ok = sch.ConstructAssessment(
            judge_id="gemini_pro",
            qualitative_summary="The firm shows mixed openness.",
            dimension_scores=[
                sch.DimensionAssessment(
                    dimension="x", score=4,
                    reasoning="midpoint", evidence=[], confidence="medium",
                ),
            ],
            composite_score=4.0,
            overall_confidence="medium",
            caveats="",
        )
        assert ok.composite_score == 4.0
        # Out of range composite
        with pytest.raises(Exception):
            sch.ConstructAssessment(
                judge_id="gemini_pro",
                qualitative_summary="x",
                dimension_scores=[],
                composite_score=8.0,
                overall_confidence="medium",
                caveats="",
            )


# ===========================================================================
# 3. Krippendorff's α (ordinal)
# ===========================================================================

class TestKrippendorffAlphaOrdinal:
    def test_perfect_agreement_is_one(self):
        j = _judging()
        # Three judges, three items, all identical → α = 1.0
        alpha = j._krippendorff_alpha_ordinal([[5, 6, 7], [5, 6, 7], [5, 6, 7]])
        assert alpha == 1.0

    def test_maximum_disagreement_is_negative(self):
        j = _judging()
        # Three judges, two items, opposing extremes → α < 0
        alpha = j._krippendorff_alpha_ordinal([[1, 7], [7, 1], [1, 7]])
        assert alpha < 0

    def test_two_raters_two_items_returns_finite_value(self):
        j = _judging()
        # Edge case: two raters, two items, partial agreement
        alpha = j._krippendorff_alpha_ordinal([[3, 5], [4, 5]])
        # Just check it's finite (not NaN) and within reasonable bounds.
        assert alpha == alpha  # not NaN
        assert -1.0 <= alpha <= 1.0

    def test_single_rater_returns_nan(self):
        j = _judging()
        alpha = j._krippendorff_alpha_ordinal([[5, 5, 5]])
        # NaN comparison: NaN != NaN
        assert alpha != alpha

    def test_mismatched_item_count_returns_nan(self):
        j = _judging()
        alpha = j._krippendorff_alpha_ordinal([[5, 5, 5], [5, 5]])
        assert alpha != alpha

    def test_zero_total_variance_returns_one(self):
        """When every rating across all items is the same, observed
        and expected disagreement are both zero → return 1.0."""
        j = _judging()
        alpha = j._krippendorff_alpha_ordinal([[4, 4], [4, 4], [4, 4]])
        assert alpha == 1.0


class TestOneItemAgreement:
    def test_full_agreement_is_one(self):
        j = _judging()
        assert j._one_item_agreement([5, 5, 5]) == 1.0

    def test_max_disagreement_is_near_zero(self):
        j = _judging()
        # Three judges, one at 1 and two at 7: not the absolute extreme
        # but close to it.
        ag = j._one_item_agreement([1, 7, 7])
        assert ag < 0.5  # well below full agreement

    def test_single_rater_returns_nan(self):
        j = _judging()
        ag = j._one_item_agreement([5])
        assert ag != ag


# ===========================================================================
# 4. Bundle aggregation
# ===========================================================================

class TestAggregate:
    # Canonical 7-dim rubric keys (rubric v0.2).
    _RUBRIC_KEYS = (
        "component_disclosure",
        "process_openness",
        "boundary_permeability_inbound",
        "boundary_permeability_outbound",
        "ecosystem_orchestration",
        "value_capture_posture",
        "temporal_openness_maneuvering",
    )

    def _three_assessments(self, scores_by_judge=None):
        """Build three assessments sharing the seven-dim openness rubric.

        `scores_by_judge` is an optional mapping judge_id → dict[dim, score].
        Default: same score (4) for every dim by every judge.
        """
        sch = _schemas()
        if scores_by_judge is None:
            scores_by_judge = {
                jid: {k: 4 for k in self._RUBRIC_KEYS}
                for jid in ("gemini_pro", "claude", "openai")
            }
        assessments = []
        for jid, scores in scores_by_judge.items():
            dim_assessments = [
                sch.DimensionAssessment(
                    dimension=k, score=v,
                    reasoning="auto", evidence=[], confidence="medium",
                )
                for k, v in scores.items()
            ]
            composite = sum(scores.values()) / len(scores)
            assessments.append(sch.ConstructAssessment(
                judge_id=jid,
                qualitative_summary="auto",
                dimension_scores=dim_assessments,
                composite_score=composite,
                overall_confidence="medium",
                caveats="",
            ))
        return assessments

    def _rubric_dim_keys(self):
        return list(self._RUBRIC_KEYS)

    def test_aggregate_perfect_agreement(self):
        j = _judging()
        bundle = j._aggregate(
            assessments=self._three_assessments(),
            rubric_dim_keys=self._rubric_dim_keys(),
        )
        assert bundle.mean_composite == 4.0
        assert bundle.inter_rater_agreement.overall_alpha == 1.0
        # All five per-dim means are exactly 4.
        for v in bundle.per_dimension_means.values():
            assert v == 4.0

    def test_aggregate_with_disagreement(self):
        j = _judging()
        bundle = j._aggregate(
            assessments=self._three_assessments(scores_by_judge={
                "gemini_pro": {k: 2 for k in self._rubric_dim_keys()},
                "claude":     {k: 4 for k in self._rubric_dim_keys()},
                "openai":     {k: 6 for k in self._rubric_dim_keys()},
            }),
            rubric_dim_keys=self._rubric_dim_keys(),
        )
        assert bundle.mean_composite == pytest.approx(4.0)
        # α is lower than perfect — variance exists
        assert bundle.inter_rater_agreement.overall_alpha < 1.0

    def test_aggregate_records_judges_used(self):
        j = _judging()
        bundle = j._aggregate(
            assessments=self._three_assessments(),
            rubric_dim_keys=self._rubric_dim_keys(),
        )
        assert set(bundle.judges_used) == {"gemini_pro", "claude", "openai"}

    def test_consensus_dimension_scores_are_rounded_means(self):
        j = _judging()
        bundle = j._aggregate(
            assessments=self._three_assessments(scores_by_judge={
                "gemini_pro": {k: 5 for k in self._rubric_dim_keys()},
                "claude":     {k: 5 for k in self._rubric_dim_keys()},
                "openai":     {k: 6 for k in self._rubric_dim_keys()},
            }),
            rubric_dim_keys=self._rubric_dim_keys(),
        )
        # Mean per dim = 16/3 ≈ 5.333 → round to 5
        for k, v in bundle.consensus_dimension_scores.items():
            assert v == 5


# ===========================================================================
# 5. Judge agent prompt
# ===========================================================================

class TestJudgeAgentPrompt:
    def test_factory_requires_a_rubric(self):
        ja = _judge_agent()
        s = _studies().load_study("_test_alt")  # no rubric
        with pytest.raises(ValueError) as exc:
            ja.create_construct_judge_agent(provider="gemini_pro", study=s)
        assert "judgment_rubric" in str(exc.value)

    def test_prompt_embeds_rubric_dimensions(self):
        ja = _judge_agent()
        s = _studies().load_study("openness_maneuvering")
        agent = ja.create_construct_judge_agent(provider="gemini_pro", study=s)
        instr = agent.instruction
        # Every dimension name appears verbatim
        for d in s.judgment_rubric.dimensions:
            assert d.key in instr
            assert d.name in instr
            assert d.anchor_low in instr
            assert d.anchor_high in instr

    def test_prompt_describes_two_stage_methodology(self):
        ja = _judge_agent()
        s = _studies().load_study("openness_maneuvering")
        agent = ja.create_construct_judge_agent(provider="gemini_pro", study=s)
        instr = agent.instruction
        # The two-stage framing is the central methodological claim.
        assert "STAGE 1" in instr
        assert "STAGE 2" in instr
        assert "qualitative_summary FIRST" in instr or "qualitative_summary first" in instr.lower()

    def test_prompt_states_evidence_anchoring_rule(self):
        ja = _judge_agent()
        s = _studies().load_study("openness_maneuvering")
        agent = ja.create_construct_judge_agent(provider="gemini_pro", study=s)
        instr = agent.instruction
        # The evidence-anchoring rule is what makes scores auditable.
        assert "EVIDENCE-ANCHORING RULE" in instr or "evidence" in instr.lower()
        assert "verbatim" in instr.lower()

    def test_prompt_excludes_private_scratchpads(self):
        """The judges must see PUBLIC content only, not the firm's
        private scratchpads."""
        ja = _judge_agent()
        s = _studies().load_study("openness_maneuvering")
        agent = ja.create_construct_judge_agent(provider="gemini_pro", study=s)
        instr = agent.instruction
        # Either "private scratchpads NOT included" phrasing or
        # equivalent — the prompt must make the exclusion explicit.
        assert "scratchpad" in instr.lower()
        assert "NOT" in instr or "not " in instr.lower()


# ===========================================================================
# 6. Silent-failure capture — regression coverage for the GPT-5.5-pro
#    Meta-2032 incident where `construct_judging.judge_failed
#    provider=openai exc=` rendered an empty exception line and the
#    failure went unnoticed in the logs. The fix in `_one_judge`
#    captures `repr(exc)` + `traceback.format_exc()` and threads them
#    through to the bundle so they survive into persisted output.
# ===========================================================================

class TestFailedJudgeCapture:
    _RUBRIC_KEYS = (
        "component_disclosure",
        "process_openness",
        "boundary_permeability_inbound",
        "boundary_permeability_outbound",
        "ecosystem_orchestration",
        "value_capture_posture",
        "temporal_openness_maneuvering",
    )

    def _one_assessment(self, judge_id: str):
        sch = _schemas()
        dim_assessments = [
            sch.DimensionAssessment(
                dimension=k, score=4,
                reasoning="auto", evidence=[], confidence="medium",
            )
            for k in self._RUBRIC_KEYS
        ]
        return sch.ConstructAssessment(
            judge_id=judge_id,
            qualitative_summary="auto",
            dimension_scores=dim_assessments,
            composite_score=4.0,
            overall_confidence="medium",
            caveats="",
        )

    # --- Schema-level back-compat -----------------------------------------

    def test_bundle_judge_errors_defaults_to_empty_dict(self):
        """Pre-existing run JSON files (no `judge_errors` field) must
        still load — the field defaults to `{}` so deserialising older
        bundle JSON doesn't raise."""
        sch = _schemas()
        # Build a minimal bundle without supplying judge_errors.
        iraa = sch.InterRaterAgreement(
            overall_alpha=1.0,
            per_dimension_alpha={k: 1.0 for k in self._RUBRIC_KEYS},
            n_judges=2,
            n_dimensions=7,
        )
        bundle = sch.ConstructJudgmentBundle(
            assessments=[
                self._one_assessment("gemini_pro"),
                self._one_assessment("claude"),
            ],
            mean_composite=4.0,
            per_dimension_means={k: 4.0 for k in self._RUBRIC_KEYS},
            consensus_dimension_scores={k: 4 for k in self._RUBRIC_KEYS},
            inter_rater_agreement=iraa,
            judges_used=["gemini_pro", "claude"],
        )
        assert bundle.judge_errors == {}

    # --- Aggregator wiring -------------------------------------------------

    def test_aggregate_threads_judge_errors_into_bundle(self):
        """`_aggregate` now accepts a `judge_errors` dict and the
        captured text round-trips into the bundle field."""
        j = _judging()
        bundle = j._aggregate(
            assessments=[
                self._one_assessment("gemini_pro"),
                self._one_assessment("claude"),
            ],
            rubric_dim_keys=list(self._RUBRIC_KEYS),
            judge_errors={
                "openai": (
                    "openai: BadRequestError('json_schema not supported')"
                    "\n\nTraceback (most recent call last):\n  ..."
                ),
            },
        )
        assert "openai" in bundle.judge_errors
        assert "BadRequestError" in bundle.judge_errors["openai"]
        assert "Traceback" in bundle.judge_errors["openai"]
        # judges_used still reflects only the successful providers.
        assert set(bundle.judges_used) == {"gemini_pro", "claude"}

    def test_aggregate_backcompat_when_no_errors_argument_passed(self):
        """Existing callsites that don't pass `judge_errors` still work
        — the default is `None` which materialises as `{}` on the bundle."""
        j = _judging()
        bundle = j._aggregate(
            assessments=[
                self._one_assessment("gemini_pro"),
                self._one_assessment("claude"),
                self._one_assessment("openai"),
            ],
            rubric_dim_keys=list(self._RUBRIC_KEYS),
        )
        assert bundle.judge_errors == {}

    # --- Persistence writes the error file --------------------------------

    def test_persist_writes_error_txt_for_each_failed_judge(self, tmp_path):
        """`<provider>_error.txt` lands in `05_judging/` alongside the
        successful judges' assessment files."""
        j = _judging()
        sch = _schemas()
        iraa = sch.InterRaterAgreement(
            overall_alpha=1.0,
            per_dimension_alpha={k: 1.0 for k in self._RUBRIC_KEYS},
            n_judges=2,
            n_dimensions=7,
        )
        bundle = sch.ConstructJudgmentBundle(
            assessments=[
                self._one_assessment("gemini_pro"),
                self._one_assessment("claude"),
            ],
            mean_composite=4.0,
            per_dimension_means={k: 4.0 for k in self._RUBRIC_KEYS},
            consensus_dimension_scores={k: 4 for k in self._RUBRIC_KEYS},
            inter_rater_agreement=iraa,
            judges_used=["gemini_pro", "claude"],
            judge_errors={
                "openai": (
                    "openai: BadRequestError('json_schema unsupported')"
                    "\n\nTraceback ...\n  at line 42 ..."
                ),
            },
        )
        phase = j.ConstructJudgingPhase()
        phase.persist(out_dir=tmp_path, result=bundle, write_json=False)
        error_file = tmp_path / "05_judging" / "openai_error.txt"
        assert error_file.exists()
        text = error_file.read_text()
        assert "BadRequestError" in text
        assert "Traceback" in text
        # Successful judges still get their assessment.md files.
        assert (tmp_path / "05_judging" / "gemini_pro_assessment.md").exists()
        assert (tmp_path / "05_judging" / "claude_assessment.md").exists()

    def test_persist_writes_no_error_files_when_every_judge_succeeded(
        self, tmp_path
    ):
        """When the bundle's `judge_errors` is empty, no error file is
        written — preserves the existing on-disk shape for the happy path."""
        j = _judging()
        sch = _schemas()
        iraa = sch.InterRaterAgreement(
            overall_alpha=1.0,
            per_dimension_alpha={k: 1.0 for k in self._RUBRIC_KEYS},
            n_judges=2,
            n_dimensions=7,
        )
        bundle = sch.ConstructJudgmentBundle(
            assessments=[
                self._one_assessment("gemini_pro"),
                self._one_assessment("claude"),
            ],
            mean_composite=4.0,
            per_dimension_means={k: 4.0 for k in self._RUBRIC_KEYS},
            consensus_dimension_scores={k: 4 for k in self._RUBRIC_KEYS},
            inter_rater_agreement=iraa,
            judges_used=["gemini_pro", "claude"],
        )
        phase = j.ConstructJudgingPhase()
        phase.persist(out_dir=tmp_path, result=bundle, write_json=False)
        # No *_error.txt files at all.
        error_files = list((tmp_path / "05_judging").glob("*_error.txt"))
        assert error_files == []

    # --- Aggregate.md surfaces failures -----------------------------------

    def test_aggregate_md_lists_failed_judges(self):
        """The human-readable aggregate.md must surface failed judges
        so a PI eyeballing the file sees that some judges didn't score
        — not silently averaged-over."""
        from analysis.persist_artefacts import _render_judgment_aggregate_md

        bundle_dict = {
            "judges_used": ["gemini_pro", "claude"],
            "mean_composite": 4.0,
            "per_dimension_means": {k: 4.0 for k in self._RUBRIC_KEYS},
            "consensus_dimension_scores": {k: 4 for k in self._RUBRIC_KEYS},
            "inter_rater_agreement": {
                "overall_alpha": 1.0,
                "per_dimension_alpha": {k: 1.0 for k in self._RUBRIC_KEYS},
                "n_judges": 2,
                "n_dimensions": 7,
            },
            "assessments": [],
            "judge_errors": {
                "openai": "openai: BadRequestError(...)\n\nTraceback ...",
            },
        }
        md = _render_judgment_aggregate_md(bundle_dict)
        assert "Failed judges" in md
        assert "openai" in md
        # The render points the reader at the per-provider error files
        # generically (`<provider>_error.txt`) rather than spelling out
        # each one — keeps a single render path even with N failures.
        assert "_error.txt" in md

    def test_aggregate_md_omits_failed_section_when_no_errors(self):
        """Happy path renders without the failure section — no false
        positives when every judge scored."""
        from analysis.persist_artefacts import _render_judgment_aggregate_md

        bundle_dict = {
            "judges_used": ["gemini_pro", "claude", "openai"],
            "mean_composite": 4.0,
            "per_dimension_means": {k: 4.0 for k in self._RUBRIC_KEYS},
            "consensus_dimension_scores": {k: 4 for k in self._RUBRIC_KEYS},
            "inter_rater_agreement": {
                "overall_alpha": 1.0,
                "per_dimension_alpha": {k: 1.0 for k in self._RUBRIC_KEYS},
                "n_judges": 3,
                "n_dimensions": 7,
            },
            "assessments": [],
            "judge_errors": {},
        }
        md = _render_judgment_aggregate_md(bundle_dict)
        assert "Failed judges" not in md

    # --- Orchestrator end-to-end: a raising run_agent populates the
    #     judge_errors field instead of silently dropping the provider.

    def test_run_construct_judging_captures_exception_repr_and_traceback(
        self, monkeypatch, caplog,
    ):
        """The headline regression test — a `run_agent` that raises an
        empty-message exception (the GPT-5.5-pro failure mode) must
        produce a populated `judge_errors[provider]` entry containing
        both `repr(exc)` (so the exception class is visible even when
        `str(exc)` is empty) and `traceback.format_exc()` (so the
        callsite is visible for post-mortem).
        """
        import logging

        j = _judging()

        # 1. Monkeypatch the judge-agent factory so we don't need real
        #    provider credentials to drive the orchestrator path. The
        #    `_one_judge` closure only uses `agent` as the value it
        #    passes to `run_agent`; a sentinel object suffices.
        monkeypatch.setattr(
            j, "create_construct_judge_agent",
            lambda provider, study: object(),
        )

        # 2. The `run_agent` we inject: raises an empty-message
        #    exception for `gemini_pro`, returns a valid coerced
        #    payload for `claude`. Mirrors the Meta-2032 incident
        #    where one provider erupted with bare `str(exc) == ""`.
        class _EmptyMessageProviderError(Exception):
            def __str__(self):
                return ""  # the exact pathology that produced `exc=`

        async def fake_run_agent(*, agent, prompt):
            # Tag the failing provider by inspecting the prompt? No —
            # we don't have provider context here. Instead we drive
            # ordering: first call raises, second returns valid data.
            if not hasattr(fake_run_agent, "_call_count"):
                fake_run_agent._call_count = 0
            fake_run_agent._call_count += 1
            if fake_run_agent._call_count == 1:
                raise _EmptyMessageProviderError()
            # Return a valid ConstructAssessment-shaped dict.
            return {
                "judge_id": "ignored",  # patched to provider name in _coerce
                "qualitative_summary": "ok",
                "dimension_scores": [
                    {"dimension": k, "score": 4, "reasoning": "ok",
                     "evidence": [], "confidence": "medium"}
                    for k in self._RUBRIC_KEYS
                ],
                "composite_score": 4.0,
                "overall_confidence": "medium",
                "caveats": "",
            }

        s = _studies().load_study("openness_maneuvering")
        # The judge retry path now lives in `safe_run_with_capture`
        # (in orchestrator.llm_retry) — that's where the warning lands.
        caplog.set_level(
            logging.WARNING,
            logger="open-innovation-strategy.orchestrator.llm_retry",
        )

        bundle = asyncio.run(j.run_construct_judging(
            study=s,
            company="TestCorp", industry_context="Dynamic",
            product_type="Novel",
            deliberation_log=None, artefacts=None,
            observation_summary=None, debriefing_transcript=None,
            field_notes=None,
            run_agent=fake_run_agent,
            judge_providers=["gemini_pro", "claude"],
        ))

        # The failed provider is exactly one of the two — gather order is
        # preserved by zip with the `providers` list, so gemini_pro fails.
        assert "gemini_pro" in bundle.judge_errors
        error_text = bundle.judge_errors["gemini_pro"]
        # The exact GPT-5.5-pro pathology: `str(exc)` is empty, but
        # `repr(exc)` carries the class name and the captured traceback
        # carries the callsite.
        assert "_EmptyMessageProviderError" in error_text
        assert "Traceback" in error_text
        # Successful judge still scored.
        assert bundle.judges_used == ["claude"]
        # The log line from `safe_run_with_capture` carries the repr
        # — accepts either the new shared-helper format or any future
        # format that still names the failing exception class.
        warnings = [
            r for r in caplog.records
            if "_EmptyMessageProviderError" in r.getMessage()
        ]
        assert warnings, (
            "log line should carry repr(exc), not the empty str(exc) that "
            "caused the original Meta-2032 silent-failure"
        )


# ===========================================================================
# 7. Four-judge ensemble — PR-B adds DeepSeek as the 4th, lineage-
#    distinct judge. These tests verify the ensemble configuration
#    and that the judge agent factory builds the DeepSeek judge with
#    the right model (deepseek-reasoner) and the right structured-
#    output mode (json_object, the DeepSeek API rejects strict
#    json_schema response_format).
# ===========================================================================

class TestFourJudgeEnsemble:
    def test_default_judge_providers_now_includes_deepseek(self):
        """PR-B extends the default ensemble from 3 to 4 providers.
        Order matters for reproducible logging; DeepSeek lands LAST
        so existing per-cell Excel rows don't shift columns."""
        import importlib
        p = importlib.import_module(f"{PKG}.providers")
        assert "deepseek" in p.JUDGE_PROVIDERS
        assert p.JUDGE_PROVIDERS[-1] == "deepseek", (
            "deepseek must land last in the tuple — earlier positions "
            "would shift the column order of historical per-cell "
            "judging exports."
        )
        assert len(p.JUDGE_PROVIDERS) == 4

    def test_deepseek_judge_model_override_resolves_to_reasoner(self):
        """The judge ensemble uses `deepseek-reasoner` (R-family alias
        — auto-routes to DeepSeek's current frontier reasoner) while
        the TMT-side default stays on `deepseek-chat-v4`. Operators
        can override via env var TMT_JUDGE_DEEPSEEK_MODEL."""
        import importlib
        p = importlib.import_module(f"{PKG}.providers")
        assert p.JUDGE_MODEL_OVERRIDES.get("deepseek") == "deepseek/deepseek-reasoner"
        # Resolved model spec must wrap the reasoner alias, not the
        # chat default.
        spec = p.get_judge_model("deepseek")
        # LiteLlm wrapper; verify .model attribute carries the reasoner ID.
        model_id = getattr(spec, "model", None)
        assert model_id == "deepseek/deepseek-reasoner"

    def test_env_var_override_for_deepseek_judge(self, monkeypatch):
        """Pinning a specific R-family version for a reproducibility
        snapshot must work."""
        import importlib
        p = importlib.import_module(f"{PKG}.providers")
        monkeypatch.setenv("TMT_JUDGE_DEEPSEEK_MODEL", "deepseek/deepseek-r1")
        spec = p.get_judge_model("deepseek")
        model_id = getattr(spec, "model", None)
        assert model_id == "deepseek/deepseek-r1"

    def test_deepseek_judge_routes_through_json_object_mode(self):
        """DeepSeek's API rejects strict json_schema response_format
        (the Session §1 incident motivating the per-provider adapter).
        The judge must build in `json_object` mode so the assessment
        coercer's `_strip_json_envelope` path handles the wrapped
        output. `classify_structured_output_mode` is the contract."""
        import importlib
        p = importlib.import_module(f"{PKG}.providers")
        deepseek_spec = p.get_judge_model("deepseek")
        mode = p.classify_structured_output_mode(deepseek_spec)
        assert mode == p.STRUCTURED_OUTPUT_MODE_JSON_OBJECT, (
            f"DeepSeek judge must use json_object mode, got {mode!r}. "
            "If this fails, the per-provider adapter's "
            "_LITELLM_JSON_OBJECT_PREFIXES set has drifted away from "
            "DeepSeek's actual response_format support."
        )

    def test_construct_judge_factory_builds_deepseek(self):
        """`create_construct_judge_agent(provider='deepseek', ...)`
        must produce a working LlmAgent — the openness rubric needs to
        embed in the instruction, the deepseek-reasoner model has to
        bind, no exception."""
        ja = _judge_agent()
        s = _studies().load_study("openness_maneuvering")
        agent = ja.create_construct_judge_agent(provider="deepseek", study=s)
        assert agent.name == "ConstructJudge_deepseek"
        # Rubric dimensions land in the instruction (same contract the
        # other judges meet).
        instr = agent.instruction
        for d in s.judgment_rubric.dimensions:
            assert d.key in instr

    def test_aggregator_handles_four_judge_assessments(self):
        """The aggregator was previously exercised with 3 judges.
        Verify N=4 produces a coherent α + composite without surprises
        — same code paths, just one more judge in the ratings matrix."""
        j = _judging()
        sch = _schemas()
        # Build 4 assessments with deliberately staggered scores so α
        # is computable and < 1.0 (some variance across raters).
        assessments = []
        scores_per_judge = {
            "gemini_pro": 4, "claude": 5,
            "openai": 4,     "deepseek": 5,
        }
        for jid, base_score in scores_per_judge.items():
            dim_assessments = [
                sch.DimensionAssessment(
                    dimension=k, score=base_score,
                    reasoning="auto", evidence=[], confidence="medium",
                )
                for k in TestAggregate._RUBRIC_KEYS
            ]
            assessments.append(sch.ConstructAssessment(
                judge_id=jid,
                qualitative_summary="auto",
                dimension_scores=dim_assessments,
                composite_score=float(base_score),
                overall_confidence="medium",
                caveats="",
            ))
        bundle = j._aggregate(
            assessments=assessments,
            rubric_dim_keys=list(TestAggregate._RUBRIC_KEYS),
        )
        assert len(bundle.judges_used) == 4
        assert set(bundle.judges_used) == {
            "gemini_pro", "claude", "openai", "deepseek",
        }
        assert bundle.inter_rater_agreement.n_judges == 4
        # Mean composite is the simple cross-judge mean: (4+5+4+5)/4 = 4.5
        assert bundle.mean_composite == pytest.approx(4.5)


# ===========================================================================
# 8. v0.4 judge prompt — sub-dimensional scoring + evidence quoting
#    PR-D commit 3/6: STAGE 2A block (sub-dim percent scoring),
#    EVIDENCE QUOTING CONTRACT (≥2 quotes from persisted md, source_file
#    attribution), STAGE 2B parent-dim rollup. Studies without a sub-dim
#    lexicon (slug != "openness_maneuvering") see the v0.3 single-stage
#    prompt with no STAGE 2A.
# ===========================================================================

class TestJudgePromptV04SubDimensional:
    def _openness_instruction(self) -> str:
        ja = _judge_agent()
        s = _studies().load_study("openness_maneuvering")
        agent = ja.create_construct_judge_agent(provider="gemini_pro", study=s)
        return agent.instruction

    def test_sub_dimensional_taxonomy_block_present(self):
        instr = self._openness_instruction()
        assert "SUB-DIMENSIONAL TAXONOMY" in instr, (
            "the v0.4 prompt must surface the 26-sub-dim taxonomy so "
            "the judge sees what they are scoring at the sub-dim level"
        )
        # 26-sub-dim count lands in the header.
        assert "26 sub-dimensions" in instr

    def test_every_subdim_key_lands_in_prompt(self):
        """All 26 sub-dim keys must appear verbatim in the prompt —
        the judge cannot score what it doesn't see."""
        ja = _judge_agent()
        s = _studies().load_study("openness_maneuvering")
        agent = ja.create_construct_judge_agent(provider="gemini_pro", study=s)
        from studies.openness_maneuvering.subdimension_lexicon import (
            OPENNESS_SUBDIMENSION_LEXICON,
        )
        for key in OPENNESS_SUBDIMENSION_LEXICON:
            assert key in agent.instruction, (
                f"sub-dim key {key!r} missing from judge prompt — the "
                f"judge would skip it"
            )

    def test_stage_2a_block_describes_percent_scoring(self):
        instr = self._openness_instruction()
        assert "STAGE 2A" in instr
        assert "sub_dimension_assessments" in instr
        # 0-100 percent scale must be explicit.
        assert "0-100" in instr
        assert "multiples of 5" in instr

    def test_percent_to_likert_table_embedded(self):
        """Full anchor table (7 descriptors) must be in the prompt so
        the judge can derive `likert_back_binned` + `qualitative_anchor`
        consistently."""
        instr = self._openness_instruction()
        for anchor in (
            "near-absent", "minimal", "partial", "moderate",
            "substantial", "comprehensive", "exemplary",
        ):
            assert anchor in instr, (
                f"anchor {anchor!r} missing from the percent → Likert "
                f"table in the prompt"
            )
        # Threshold breakpoints visible (14 at bucket 1 upper bound;
        # 85 at bucket 6 upper bound).
        assert "14" in instr
        assert "85" in instr

    def test_stage_2b_rollup_block_present(self):
        instr = self._openness_instruction()
        assert "STAGE 2B" in instr
        assert "rollup" in instr.lower()
        # Mean-of-children math is the contract.
        assert "mean of children" in instr.lower() or "mean" in instr.lower()

    def test_evidence_quoting_contract_block(self):
        instr = self._openness_instruction()
        assert "EVIDENCE QUOTING CONTRACT" in instr
        # Source-file attribution mandatory.
        assert "source_file" in instr
        # Four admissible source files named.
        assert "01_deliberation/interaction_log.md" in instr
        assert "02_strategy_documents/" in instr
        assert "03_researcher/observation_summary.md" in instr
        assert "04_interview/transcript.md" in instr
        # External-knowledge prohibition explicit.
        assert (
            "DO NOT quote external knowledge" in instr
            or "training-time priors" in instr
        )
        # ≥2 quotes for non-near-absent — accept either rendering.
        assert "≥2 quotes" in instr or "2 quotes" in instr

    def test_evidence_quoting_300_char_cap_mentioned(self):
        instr = self._openness_instruction()
        assert "≤300" in instr or "300 characters" in instr

    def test_output_section_names_subdim_field_and_count(self):
        """OUTPUT section spells out the 26-entry
        sub_dimension_assessments requirement so the judge knows the
        schema contract."""
        instr = self._openness_instruction()
        assert "sub_dimension_assessments" in instr
        assert "26 entries" in instr or "26 sub-dimensions" in instr

    def test_v04_path_only_activates_for_openness_study(self):
        """`_study_has_subdim_lexicon` is the gate. Only the
        openness_maneuvering study activates the v0.4 path; other
        studies see the v0.3 prompt."""
        ja = _judge_agent()
        s_openness = _studies().load_study("openness_maneuvering")
        assert ja._study_has_subdim_lexicon(s_openness)

    def test_subdim_count_matches_lexicon(self):
        """If someone adds or removes a sub-dimension, the prompt's
        count must follow. Catches lexicon ↔ prompt drift."""
        ja = _judge_agent()
        s = _studies().load_study("openness_maneuvering")
        agent = ja.create_construct_judge_agent(provider="gemini_pro", study=s)
        from studies.openness_maneuvering.subdimension_lexicon import (
            OPENNESS_SUBDIMENSION_LEXICON,
        )
        actual_count = len(OPENNESS_SUBDIMENSION_LEXICON)
        assert f"{actual_count} sub-dimensions" in agent.instruction

    def test_v03_evidence_anchoring_rule_still_present(self):
        """The v0.3 EVIDENCE-ANCHORING RULE block is preserved (it
        applies to the parent-dim rollup output even under v0.4).
        Existing test `test_prompt_states_evidence_anchoring_rule`
        still passes; this asserts the rule lives alongside the new
        v0.4 EVIDENCE QUOTING CONTRACT, not instead of it."""
        instr = self._openness_instruction()
        assert "EVIDENCE-ANCHORING RULE" in instr
        # Both blocks present.
        assert "EVIDENCE QUOTING CONTRACT" in instr
