"""Tests for the judge replay tool (`analysis.replay_judges`).

The tool re-runs failed or selected construct judges against a
previously-completed run's persisted markdown artefacts and re-
aggregates the bundle. It exists to recover from silent-judge-failure
incidents (the Meta-2032 OpenAI case PR-A hardened) and to extend an
existing run to a larger judge ensemble (e.g. once PR-B adds DeepSeek
as the 4th judge, we may want to score historical runs against the
augmented ensemble without re-running the simulation).

Coverage in this module:

* Prompt assembly from md: every persisted phase artefact lands in
  the reconstructed prompt with the same section headers the live
  orchestrator emits.
* Judge-state discovery: ``assessed`` (JSON+md) vs ``failed`` (error
  file present) vs ``absent`` (md-only or missing).
* Study version locking: replay refuses across-version drift unless
  explicitly overridden.
* Replay-all path: every provider re-scored from scratch (the
  Meta-2032 recovery path for runs without companion JSON).
* Targeted replay path: only specified providers re-scored; existing
  JSON assessments carried through into the new aggregate.
* The CLI argument parser: shape only — no end-to-end LLM invocation.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest

PKG = "open-innovation-strategy"


def _replay():
    return importlib.import_module(f"{PKG}.analysis.replay_judges")


def _schemas():
    return importlib.import_module(f"{PKG}.roles.judge_schemas")


def _studies():
    return importlib.import_module(f"{PKG}.studies")


# ===========================================================================
# Fixtures — synthetic run directories
# ===========================================================================

_RUBRIC_KEYS = (
    "component_disclosure",
    "process_openness",
    "boundary_permeability_inbound",
    "boundary_permeability_outbound",
    "ecosystem_orchestration",
    "value_capture_posture",
    "temporal_openness_maneuvering",
)


def _make_one_assessment(judge_id: str, score: int = 4) -> dict:
    """Build a ConstructAssessment-shaped dict for a fake judge."""
    return {
        "judge_id": judge_id,
        "qualitative_summary": f"fake summary for {judge_id}",
        "dimension_scores": [
            {
                "dimension": k, "score": score,
                "reasoning": f"auto-{judge_id}", "evidence": [],
                "confidence": "medium",
            }
            for k in _RUBRIC_KEYS
        ],
        "composite_score": float(score),
        "overall_confidence": "medium",
        "caveats": "",
    }


def _make_run_dir(
    tmp_path: Path, *,
    study_version: str = "0.3.0",
    pre_existing_assessments_json: dict | None = None,
    pre_existing_assessments_md_only: list[str] | None = None,
    error_providers: list[str] | None = None,
) -> Path:
    """Build a synthetic run folder with `00_meta.json` + minimal md
    artefacts. Optionally seed `05_judging/` with existing JSON / md /
    error files to drive different state-discovery branches.
    """
    run_dir = tmp_path / "FakeFirm_Dynamic_Novel_synthetic"
    run_dir.mkdir()
    (run_dir / "00_meta.json").write_text(json.dumps({
        "run_id": run_dir.name,
        "company": "FakeFirm",
        "industry_context": "Dynamic",
        "product_type": "Novel",
        "research_question": "test",
        "study_slug": "openness_maneuvering",
        "study_version": study_version,
        "started_at": "2026-01-01T00:00:00",
        "finished_at": "2026-01-01T00:01:00",
    }))
    # Minimal phase artefacts so prompt assembly succeeds.
    (run_dir / "02_strategy_documents").mkdir()
    for role in ("CEO", "CTO"):
        (run_dir / "02_strategy_documents" / f"{role}_strategy.md").write_text(
            f"# {role} strategy\n\nbody text"
        )
    (run_dir / "01_deliberation").mkdir()
    (run_dir / "01_deliberation" / "interaction_log.md").write_text(
        "### [0] CEO\n\nopening remark"
    )
    (run_dir / "03_researcher").mkdir()
    (run_dir / "03_researcher" / "observation_summary.md").write_text(
        "## summary\n\nthe panel discussed openness"
    )
    (run_dir / "04_interview").mkdir()
    (run_dir / "04_interview" / "transcript.md").write_text(
        "### Exchange 1\n\n**Researcher**: how did you approach this?"
    )

    judging = run_dir / "05_judging"
    judging.mkdir()
    for provider, payload in (pre_existing_assessments_json or {}).items():
        (judging / f"{provider}_assessment.json").write_text(
            json.dumps(payload, indent=2)
        )
        (judging / f"{provider}_assessment.md").write_text(
            f"# {provider} render"
        )
    for provider in (pre_existing_assessments_md_only or []):
        (judging / f"{provider}_assessment.md").write_text(
            f"# {provider} md-only render"
        )
    for provider in (error_providers or []):
        (judging / f"{provider}_error.txt").write_text(
            f"{provider}: ExampleError(...)\n\nTraceback ..."
        )

    return run_dir


# ===========================================================================
# Prompt assembly
# ===========================================================================

class TestPromptAssembly:
    def test_assembled_prompt_includes_every_section_header(self, tmp_path):
        r = _replay()
        run_dir = _make_run_dir(tmp_path)
        prompt = r.assemble_judge_prompt_from_md(run_dir)
        # The judge prompt's five sections must all appear so the
        # replay-judge sees the same structural layout as the live ones.
        assert "SCENARIO CONTEXT" in prompt
        assert "STRATEGIC ARTEFACTS" in prompt
        assert "DELIBERATION TRANSCRIPT" in prompt
        assert "RESEARCHER'S OBSERVATION SUMMARY" in prompt
        assert "PANEL DEBRIEFING TRANSCRIPT" in prompt

    def test_assembled_prompt_carries_scenario_context_from_meta(self, tmp_path):
        r = _replay()
        run_dir = _make_run_dir(tmp_path)
        prompt = r.assemble_judge_prompt_from_md(run_dir)
        assert "FakeFirm" in prompt
        assert "Dynamic" in prompt
        assert "Novel" in prompt

    def test_assembled_prompt_includes_all_role_strategy_docs(self, tmp_path):
        r = _replay()
        run_dir = _make_run_dir(tmp_path)
        prompt = r.assemble_judge_prompt_from_md(run_dir)
        # Every role's strategy md must be present (verbatim render).
        assert "# CEO strategy" in prompt
        assert "# CTO strategy" in prompt

    def test_assembled_prompt_includes_deliberation_log_verbatim(self, tmp_path):
        r = _replay()
        run_dir = _make_run_dir(tmp_path)
        prompt = r.assemble_judge_prompt_from_md(run_dir)
        assert "### [0] CEO" in prompt

    def test_missing_meta_raises_clear_error(self, tmp_path):
        r = _replay()
        run_dir = tmp_path / "no_meta"
        run_dir.mkdir()
        with pytest.raises(FileNotFoundError) as exc:
            r.assemble_judge_prompt_from_md(run_dir)
        assert "00_meta.json" in str(exc.value)


# ===========================================================================
# Judge-state discovery
# ===========================================================================

class TestDiscoverJudgeState:
    def test_json_plus_md_counts_as_assessed(self, tmp_path):
        r = _replay()
        run_dir = _make_run_dir(
            tmp_path,
            pre_existing_assessments_json={
                "gemini_pro": _make_one_assessment("gemini_pro"),
            },
        )
        state = r.discover_judge_state(run_dir)
        assert state["gemini_pro"] == "assessed"

    def test_md_only_counts_as_absent(self, tmp_path):
        r = _replay()
        run_dir = _make_run_dir(
            tmp_path,
            pre_existing_assessments_md_only=["claude"],
        )
        state = r.discover_judge_state(run_dir)
        assert state["claude"] == "absent"

    def test_error_file_counts_as_failed(self, tmp_path):
        r = _replay()
        run_dir = _make_run_dir(
            tmp_path,
            error_providers=["openai"],
        )
        state = r.discover_judge_state(run_dir)
        assert state["openai"] == "failed"

    def test_json_overrides_lingering_error_file(self, tmp_path):
        """A successful re-run shouldn't get buried by a stale error
        file from a previous attempt."""
        r = _replay()
        run_dir = _make_run_dir(
            tmp_path,
            pre_existing_assessments_json={
                "openai": _make_one_assessment("openai"),
            },
            error_providers=["openai"],
        )
        state = r.discover_judge_state(run_dir)
        assert state["openai"] == "assessed"

    def test_unparseable_json_falls_back_to_absent(self, tmp_path):
        """A `<provider>_assessment.json` that doesn't validate as a
        ConstructAssessment shouldn't pass as 'assessed' — replay would
        produce a garbage aggregate."""
        r = _replay()
        run_dir = _make_run_dir(tmp_path)
        (run_dir / "05_judging" / "deepseek_assessment.json").write_text(
            '{"not": "a valid ConstructAssessment"}'
        )
        state = r.discover_judge_state(run_dir)
        assert state["deepseek"] == "absent"


# ===========================================================================
# Study-version locking
# ===========================================================================

class TestVersionLocking:
    def test_replay_refuses_when_versions_mismatch(self, tmp_path):
        r = _replay()
        run_dir = _make_run_dir(tmp_path, study_version="0.99.0-impossible")

        with pytest.raises(ValueError) as exc:
            asyncio.run(r.replay_judges(
                run_dir=run_dir,
                providers_to_replay=["gemini_pro"],
                rerun_all=False,
                allow_version_mismatch=False,
                runner=_make_fake_runner({"gemini_pro": "gemini_pro"}),
            ))
        assert "version mismatch" in str(exc.value).lower()

    def test_replay_allows_mismatch_when_explicitly_opted_in(self, tmp_path):
        """`--allow-version-mismatch` is the override for cross-schema
        replay. Available; not recommended."""
        r = _replay()
        # Use the active study's actual version in the meta so the
        # standard path works, then we toggle one branch via the flag.
        s = _studies().load_study("openness_maneuvering")
        run_dir = _make_run_dir(tmp_path, study_version="0.99.0-impossible")

        # Force-replay with override; tolerate the LLM-runner call by
        # injecting a fake.
        bundle = asyncio.run(r.replay_judges(
            run_dir=run_dir,
            providers_to_replay=["gemini_pro"],
            rerun_all=False,
            allow_version_mismatch=True,
            runner=_make_fake_runner({"gemini_pro": "gemini_pro"}),
        ))
        # The replay produced an assessment despite the version skew.
        assert len(bundle.assessments) >= 1


# ===========================================================================
# Test runner — a fake `(agent, prompt) -> str` that returns a fixed
# ConstructAssessment-shaped JSON per provider, so we can exercise the
# orchestrator path without invoking any LLM.
# ===========================================================================

def _make_fake_runner(provider_judge_id_map: dict[str, str]):
    """`provider_judge_id_map` keys are agent names, values are the
    judge_id to embed in the returned assessment."""

    async def fake(*, agent, prompt: str) -> str:
        agent_name = getattr(agent, "name", "") or ""
        # Agent name shape: "ConstructJudge_<provider>" per
        # `roles/construct_judge.py`. Extract the provider key.
        for provider in provider_judge_id_map:
            if provider in agent_name:
                payload = _make_one_assessment(provider, score=5)
                return json.dumps(payload)
        # Fallback: a parseable but provider-agnostic assessment.
        return json.dumps(_make_one_assessment("unknown"))

    return fake


# ===========================================================================
# Replay-all path — the Meta-2032 recovery scenario
# ===========================================================================

class TestReplayAll:
    def test_rerun_all_rescores_every_configured_provider(self, tmp_path):
        r = _replay()
        run_dir = _make_run_dir(
            tmp_path,
            study_version=_studies().load_study("openness_maneuvering").version,
            pre_existing_assessments_md_only=["gemini_pro", "claude"],
            error_providers=["openai"],
        )
        bundle = asyncio.run(r.replay_judges(
            run_dir=run_dir,
            rerun_all=True,
            runner=_make_fake_runner({
                p: p for p in ("gemini_pro", "claude", "openai")
            }),
            # Restrict to a small known set so the test doesn't depend on
            # the exact JUDGE_PROVIDERS list.
            providers_to_replay=["gemini_pro", "claude", "openai"],
        ))
        scored = {a.judge_id for a in bundle.assessments}
        assert scored == {"gemini_pro", "claude", "openai"}

    def test_rerun_all_overwrites_existing_assessment_files(self, tmp_path):
        """After --rerun-all the existing _assessment.json on disk
        reflects the replay, not the original score."""
        r = _replay()
        s = _studies().load_study("openness_maneuvering")
        run_dir = _make_run_dir(
            tmp_path, study_version=s.version,
            pre_existing_assessments_json={
                "gemini_pro": _make_one_assessment("gemini_pro", score=1),
            },
        )
        # Sanity check the original on-disk score is 1.
        orig = json.loads(
            (run_dir / "05_judging" / "gemini_pro_assessment.json").read_text()
        )
        assert orig["composite_score"] == 1.0

        asyncio.run(r.replay_judges(
            run_dir=run_dir,
            rerun_all=True,
            runner=_make_fake_runner({"gemini_pro": "gemini_pro"}),
            providers_to_replay=["gemini_pro"],
        ))

        replayed = json.loads(
            (run_dir / "05_judging" / "gemini_pro_assessment.json").read_text()
        )
        # The fake runner returns score=5; the replay overwrote 1.
        assert replayed["composite_score"] == 5.0


# ===========================================================================
# Targeted replay — preserves existing JSON-assessed judges
# ===========================================================================

class TestTargetedReplay:
    def test_targeted_replay_carries_existing_json_judges_through(self, tmp_path):
        """When `gemini_pro` is JSON-assessed and we replay only
        `openai`, the new bundle's α + composite reflect both
        gemini_pro (carried through) and openai (newly replayed)."""
        r = _replay()
        s = _studies().load_study("openness_maneuvering")
        run_dir = _make_run_dir(
            tmp_path, study_version=s.version,
            pre_existing_assessments_json={
                "gemini_pro": _make_one_assessment("gemini_pro", score=3),
            },
            error_providers=["openai"],
        )
        bundle = asyncio.run(r.replay_judges(
            run_dir=run_dir,
            providers_to_replay=["openai"],
            rerun_all=False,
            runner=_make_fake_runner({"openai": "openai"}),
        ))
        scored = {a.judge_id for a in bundle.assessments}
        assert scored == {"gemini_pro", "openai"}

    def test_targeted_replay_refuses_when_existing_judge_is_md_only(
        self, tmp_path,
    ):
        """A targeted replay against a run that has md-only existing
        assessments must fail loudly — the aggregator would silently
        drop them otherwise. The user gets pointed at `--rerun-all`."""
        r = _replay()
        s = _studies().load_study("openness_maneuvering")
        run_dir = _make_run_dir(
            tmp_path, study_version=s.version,
            pre_existing_assessments_md_only=["gemini_pro", "claude"],
            error_providers=["openai"],
        )
        with pytest.raises(RuntimeError) as exc:
            asyncio.run(r.replay_judges(
                run_dir=run_dir,
                providers_to_replay=["openai"],
                rerun_all=False,
                runner=_make_fake_runner({"openai": "openai"}),
            ))
        assert "rerun-all" in str(exc.value)

    def test_targeted_replay_persists_new_aggregate_md(self, tmp_path):
        """After replay the aggregate.md gets overwritten with the new
        judges_used + α."""
        r = _replay()
        s = _studies().load_study("openness_maneuvering")
        run_dir = _make_run_dir(
            tmp_path, study_version=s.version,
            pre_existing_assessments_json={
                "gemini_pro": _make_one_assessment("gemini_pro", score=4),
                "claude":     _make_one_assessment("claude", score=4),
            },
            error_providers=["openai"],
        )
        # Pre-existing aggregate.md should be absent (the fixture
        # doesn't create one); after replay it must land.
        agg_path = run_dir / "05_judging" / "aggregate.md"
        assert not agg_path.exists()

        asyncio.run(r.replay_judges(
            run_dir=run_dir,
            providers_to_replay=["openai"],
            rerun_all=False,
            runner=_make_fake_runner({"openai": "openai"}),
        ))

        assert agg_path.exists()
        text = agg_path.read_text()
        # All three judges must be represented now.
        assert "gemini_pro" in text
        assert "claude" in text
        assert "openai" in text


# ===========================================================================
# CLI argument parsing
# ===========================================================================

class TestCLI:
    def test_required_run_dir(self):
        r = _replay()
        with pytest.raises(SystemExit):
            r._parse_cli_args([])  # missing --run-dir

    def test_providers_parses_comma_separated(self):
        r = _replay()
        args = r._parse_cli_args([
            "--run-dir", "/tmp/x",
            "--providers", "openai,deepseek",
        ])
        # The CLI keeps it as a string; main() splits on comma.
        assert args.providers == "openai,deepseek"

    def test_rerun_all_flag(self):
        r = _replay()
        args = r._parse_cli_args(["--run-dir", "/tmp/x", "--rerun-all"])
        assert args.rerun_all is True

    def test_no_json_flag(self):
        r = _replay()
        args = r._parse_cli_args(["--run-dir", "/tmp/x", "--no-json"])
        assert args.no_json is True

    def test_allow_version_mismatch_flag(self):
        r = _replay()
        args = r._parse_cli_args([
            "--run-dir", "/tmp/x", "--allow-version-mismatch",
        ])
        assert args.allow_version_mismatch is True


# ===========================================================================
# Persist policy — judge JSONs always land regardless of write_json
# ===========================================================================

class TestPersistAlwaysWritesJudgeJson:
    """PR-A's policy change: `ConstructJudgingPhase.persist()` now
    always writes the per-judge JSON files and aggregate.json, so the
    replay tool can always re-aggregate. Used to be gated by the
    `write_json` flag; that gate has moved to the burst-style sub-
    files in other phase folders."""

    def test_persist_writes_assessment_json_when_write_json_false(
        self, tmp_path,
    ):
        cj = importlib.import_module(f"{PKG}.orchestrator.construct_judging")
        sch = _schemas()
        iraa = sch.InterRaterAgreement(
            overall_alpha=1.0,
            per_dimension_alpha={k: 1.0 for k in _RUBRIC_KEYS},
            n_judges=1, n_dimensions=7,
        )
        a = sch.ConstructAssessment(
            judge_id="gemini_pro",
            qualitative_summary="ok",
            dimension_scores=[
                sch.DimensionAssessment(
                    dimension=k, score=4, reasoning="ok",
                    evidence=[], confidence="medium",
                )
                for k in _RUBRIC_KEYS
            ],
            composite_score=4.0, overall_confidence="medium", caveats="",
        )
        bundle = sch.ConstructJudgmentBundle(
            assessments=[a],
            mean_composite=4.0,
            per_dimension_means={k: 4.0 for k in _RUBRIC_KEYS},
            consensus_dimension_scores={k: 4 for k in _RUBRIC_KEYS},
            inter_rater_agreement=iraa,
            judges_used=["gemini_pro"],
        )
        phase = cj.ConstructJudgingPhase()
        # Pass write_json=False — judge JSONs must STILL land.
        phase.persist(out_dir=tmp_path, result=bundle, write_json=False)
        assert (tmp_path / "05_judging" / "aggregate.json").exists()
        assert (tmp_path / "05_judging" / "gemini_pro_assessment.json").exists()
        assert (tmp_path / "05_judging" / "aggregate.md").exists()
        assert (tmp_path / "05_judging" / "gemini_pro_assessment.md").exists()
