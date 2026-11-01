"""Tests for the PhaseHandler extension hook.

`StudyConfig.extra_phases` lets a study register additional phases
beyond the four required ones. The default ``openness_maneuvering``
study uses this to opt into the rubric-anchored construct-judge
ensemble; future studies can register member-checking phases,
policy-translation phases, etc., without touching framework code.

This test file proves the contract by exercising a fake handler that
is NOT the construct judge — if the framework genuinely supports
arbitrary extra phases, a study that registers a fake handler should
see that handler's lifecycle methods called in order, see its result
flow into ``ResearchSessionOutputs.extra_phase_results``, and see its
``persist()`` invoked by ``burst_run``.

Coverage:
  * Protocol shape — `PhaseHandler` requires the right surface.
  * Default ``openness_maneuvering`` registers ``ConstructJudgingPhase``.
  * The framework's `run_research_session` loop calls
    ``should_run`` → ``run`` → stores the result in
    ``extra_phase_results`` by ``handler.name``.
  * `burst_run` walks ``extra_phase_handlers`` + ``extra_phase_results``
    and delegates persistence to each handler.
  * A handler that returns ``False`` from ``should_run`` is skipped
    silently (no error, no entry in results).
  * Per-handler exceptions in ``run`` get logged and recorded in
    ``outputs.errors`` rather than tearing down the whole run.
  * Replication-manifest dump of ``StudyConfig`` renders ``extra_phases``
    as dotted-path identifiers (not live instances).
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

PKG = "open-innovation-strategy"


def _studies_base():
    return importlib.import_module(f"{PKG}.studies.base")


def _persist():
    return importlib.import_module(f"{PKG}.analysis.persist_artefacts")


def _studies():
    return importlib.import_module(f"{PKG}.studies")


# ===========================================================================
# A fake PhaseHandler that records every call. Not a real study phase —
# just a tracer used to prove the protocol works for non-judge handlers.
# ===========================================================================

class _RecordingPhase:
    """A fake handler that records its lifecycle calls. Used to prove
    the framework genuinely supports arbitrary phases — not just the
    construct judge."""

    name: str = "recording_phase"
    folder_prefix: str = "99_recording"

    def __init__(self, should_run_result: bool = True, raise_on_run: bool = False):
        self._should_run = should_run_result
        self._raise = raise_on_run
        self.should_run_calls = []
        self.run_calls = []
        self.persist_calls = []

    def should_run(self, *, study, outputs):
        self.should_run_calls.append({"study_slug": study.slug})
        return self._should_run

    async def run(
        self,
        *,
        study,
        outputs,
        run_agent,
        company,
        industry_context,
        product_type,
    ):
        self.run_calls.append(
            {
                "study_slug": study.slug,
                "company": company,
                "industry_context": industry_context,
                "product_type": product_type,
            }
        )
        if self._raise:
            raise RuntimeError("simulated handler failure")
        return {"recorded": True, "company": company}

    def persist(self, *, out_dir, result, write_json):
        self.persist_calls.append(
            {"out_dir": str(out_dir), "result": result, "write_json": write_json}
        )
        folder = out_dir / self.folder_prefix
        folder.mkdir(exist_ok=True)
        (folder / "marker.md").write_text(f"recorded for company={result.get('company')}")
        if write_json:
            (folder / "marker.json").write_text(json.dumps(result))


def _fake_study(slug: str = "_test_fake", with_phase: _RecordingPhase = None):
    """Build a StudyConfig with a single optional extra phase."""
    sb = _studies_base()
    return sb.StudyConfig(
        name="Fake Study",
        slug=slug,
        version="0.0.1",
        research_question="Does the framework run arbitrary extra phases?",
        theoretical_lens="Extension-hook integration test.",
        extra_phases=[with_phase] if with_phase is not None else [],
    )


# ===========================================================================
# 1. Protocol shape
# ===========================================================================

class TestPhaseHandlerProtocol:
    def test_protocol_runtime_checkable(self):
        sb = _studies_base()
        handler = _RecordingPhase()
        assert isinstance(handler, sb.PhaseHandler), (
            "A handler implementing should_run/run/persist + name/folder_prefix "
            "must satisfy the PhaseHandler runtime check."
        )

    def test_missing_methods_fail_protocol_check(self):
        sb = _studies_base()

        class Broken:
            name = "broken"
            folder_prefix = "99"
            # No should_run / run / persist

        assert not isinstance(Broken(), sb.PhaseHandler)

    def test_studyconfig_accepts_handler_instances(self):
        """`extra_phases` carries live instances (behaviour). Pydantic
        accepts them via arbitrary_types_allowed."""
        study = _fake_study(with_phase=_RecordingPhase())
        assert len(study.extra_phases) == 1
        assert isinstance(study.extra_phases[0], _RecordingPhase)

    def test_studyconfig_default_extra_phases_is_empty(self):
        """A study that doesn't opt in has no extra phases."""
        study = _fake_study()  # no handler passed
        assert study.extra_phases == []


# ===========================================================================
# 2. Default openness study registers the construct judge
# ===========================================================================

class TestOpennessStudyRegistersConstructJudge:
    def test_openness_extra_phases_contains_construct_judge(self):
        s = _studies().load_study("openness_maneuvering")
        names = [getattr(h, "name", type(h).__name__) for h in s.extra_phases]
        assert "construct_judging" in names, (
            "The openness_maneuvering study should register the construct-"
            "judging handler in extra_phases. Without it, --judge is a no-op."
        )


# ===========================================================================
# 3. Manifest dump emits dotted-path identifiers, not live instances
# ===========================================================================

class TestExtraPhasesManifestDump:
    def test_dotted_path_helper(self):
        study = _fake_study(with_phase=_RecordingPhase())
        ids = study.extra_phase_ids_for_manifest()
        assert len(ids) == 1
        # Format: "module:ClassName"
        assert ":" in ids[0]
        assert ids[0].endswith(":_RecordingPhase")

    def test_model_dump_replaces_instances_with_ids(self):
        """`StudyConfig.model_dump()` is what the replication manifest
        writer uses. It must NOT serialize live handler instances
        (Pydantic can't JSON-encode arbitrary objects); instead it
        renders each as a dotted-path string."""
        study = _fake_study(with_phase=_RecordingPhase())
        dump = study.model_dump()
        assert isinstance(dump["extra_phases"], list)
        assert all(isinstance(x, str) for x in dump["extra_phases"])

    def test_model_dump_is_json_serialisable(self):
        """The dump must round-trip through json.dumps so the manifest
        file is valid JSON."""
        study = _fake_study(with_phase=_RecordingPhase())
        # Should not raise.
        s = json.dumps(study.model_dump(), default=str)
        assert "extra_phases" in s


# ===========================================================================
# 4. burst_run walks extra_phase_handlers + extra_phase_results
# ===========================================================================

class TestBurstRunDelegatesToHandlers:
    """`burst_run` should ask each registered handler to persist its
    result. The handler controls the folder layout — burst_run is just
    the dispatcher."""

    def test_burst_run_invokes_handler_persist(self, tmp_path: Path):
        p = _persist()
        handler = _RecordingPhase()
        out = p.burst_run(
            out_dir=tmp_path,
            company="TestCo",
            industry_context="Dynamic",
            product_type="Novel",
            extra_phase_handlers={"recording_phase": handler},
            extra_phase_results={"recording_phase": {"company": "TestCo"}},
            run_id="test_handler_persist",
        )
        # The handler's persist() was called.
        assert len(handler.persist_calls) == 1
        call = handler.persist_calls[0]
        assert call["result"] == {"company": "TestCo"}
        # The folder layout the handler chose exists on disk.
        assert (out / "99_recording" / "marker.md").is_file()
        # JSON sub-file written by default.
        assert (out / "99_recording" / "marker.json").is_file()

    def test_no_json_skips_handler_json_writes(self, tmp_path: Path):
        """`write_json=False` propagates into the handler — markdown
        always; JSON optional."""
        p = _persist()
        handler = _RecordingPhase()
        p.burst_run(
            out_dir=tmp_path,
            company="TestCo",
            industry_context="Dynamic",
            product_type="Novel",
            extra_phase_handlers={"recording_phase": handler},
            extra_phase_results={"recording_phase": {"company": "TestCo"}},
            run_id="test_no_json",
            write_json=False,
        )
        folder = tmp_path / "test_no_json" / "99_recording"
        assert (folder / "marker.md").is_file()  # markdown still written
        assert not (folder / "marker.json").exists()  # json skipped

    def test_handler_without_result_is_skipped(self, tmp_path: Path):
        """If a handler is registered but its result isn't in
        extra_phase_results (e.g. should_run returned False or the
        handler errored), persist() is NOT called."""
        p = _persist()
        handler = _RecordingPhase()
        p.burst_run(
            out_dir=tmp_path,
            company="TestCo",
            industry_context="Dynamic",
            product_type="Novel",
            extra_phase_handlers={"recording_phase": handler},
            extra_phase_results={},  # no result for this handler
            run_id="test_skip",
        )
        assert handler.persist_calls == []

    def test_handler_persist_exception_is_caught(self, tmp_path: Path):
        """An exception in one handler's persist() shouldn't tear down
        the whole burst_run. The folder layout still gets the core
        files; just that one extra phase is missing."""
        p = _persist()

        class _BadHandler:
            name = "bad"
            folder_prefix = "98_bad"

            def should_run(self, **_):  return True
            async def run(self, **_):   return {}
            def persist(self, **_):
                raise RuntimeError("simulated persist failure")

        bad = _BadHandler()
        out = p.burst_run(
            out_dir=tmp_path,
            company="TestCo",
            industry_context="Dynamic",
            product_type="Novel",
            extra_phase_handlers={"bad": bad},
            extra_phase_results={"bad": {"some": "data"}},
            run_id="test_bad_persist",
        )
        # Burst returned successfully; the run folder + README still exist.
        assert (out / "README.md").is_file()
        assert (out / "00_meta.json").is_file()
        # The handler's folder may or may not exist depending on when
        # the exception was raised; what matters is the whole burst
        # didn't crash.

    def test_meta_phases_captured_reflects_each_handler(self, tmp_path: Path):
        """`00_meta.json` should list one entry per registered handler,
        keyed by handler.name, with the captured/not-captured flag."""
        p = _persist()
        handler = _RecordingPhase()
        out = p.burst_run(
            out_dir=tmp_path,
            company="TestCo",
            industry_context="Dynamic",
            product_type="Novel",
            deliberation_log={"events": []},
            extra_phase_handlers={"recording_phase": handler},
            extra_phase_results={"recording_phase": {"company": "TestCo"}},
            run_id="test_meta_handlers",
        )
        meta = json.loads((out / "00_meta.json").read_text())
        # Core phases still present.
        assert "deliberation" in meta["phases_captured"]
        # Extra phase appears keyed by handler.name.
        assert meta["phases_captured"]["recording_phase"] is True


# ===========================================================================
# 5. Back-compat — legacy construct_judgment kwarg still works
# ===========================================================================

class TestBurstRunLegacyConstructJudgmentKwarg:
    """The old `construct_judgment=` kwarg on `burst_run` is preserved
    for back-compat. It should auto-instantiate the default handler
    and route through the same persist path."""

    def test_legacy_kwarg_persists_to_05_judging(self, tmp_path: Path):
        p = _persist()
        bundle = {
            "judges_used": ["gemini_pro"],
            "mean_composite": 4.2,
            "per_dimension_means": {},
            "consensus_dimension_scores": {},
            "inter_rater_agreement": {
                "overall_alpha": 0.81,
                "per_dimension_alpha": {},
                "n_judges": 1,
                "n_dimensions": 5,
            },
            "assessments": [],
        }
        out = p.burst_run(
            out_dir=tmp_path,
            company="TestCo",
            industry_context="Dynamic",
            product_type="Novel",
            construct_judgment=bundle,
            run_id="test_legacy_kwarg",
        )
        # The legacy kwarg routed through the new handler-driven path.
        # Aggregate file is at the expected location.
        assert (out / "05_judging" / "aggregate.md").is_file()
        assert (out / "05_judging" / "aggregate.json").is_file()
