"""Re-run failed or selected construct judges on a previously-completed run.

A judge is a language model that scores a finished run (one complete simulated
meeting and debrief) against a rubric, a scoring guide. This file repeats that scoring
without repeating the simulation.

When a single judge in the Phase-5 (the optional judge scoring) ensemble (the group
of judges) silently fails (the GPT-5.5-pro Meta-2032 incident hardened by PR-A; a PR,
or pull request, is a proposed set of code changes), or when a new judge
is added to the ensemble after a run is complete and we want to score
the historical run against the augmented ensemble without re-running
the full ~45-minute simulation, this module replays *only* the
specified judges against the run's persisted md (Markdown: plain text with simple
marks) artefacts (saved records) and re-aggregates (combines the scores again).

The replay locks the study_version recorded in the run's `00_meta.json`
— refuses to replay a v0.3.0 run under v0.4.0 code (or vice versa)
without `--allow-version-mismatch`. That guards against silent
schema (the template of fields in a record) drift polluting cross-run α (Krippendorff's
alpha: agreement among the judges) statistics: a 0.4.0 sub-dimension-
percent assessment is not comparable to a 0.3.0 parent-dimension Likert
assessment.

Usage
-----
    python -m analysis.replay_judges --run-dir <path>

    Optional:
      --providers openai           Re-run only these providers, the companies
                                   supplying the models (comma sep)
      --rerun-all                  Re-run every judge (cheapest path when
                                   the existing assessments don't have
                                   companion JSON (plain-text structured data) files — see Recovery
                                   from --no-json runs below)
      --allow-version-mismatch     Replay across study_version change
      --no-rate-limit              Skip the provider-scoped throttle (the pacing
                                   that keeps calls under a provider's cap)
                                   (only safe for one-judge replays)

Recovery from --no-json runs
----------------------------
Runs persisted with `--no-json` (an option that leaves out JSON copies of a run's
records, and the default for the openness-maneuvering 20-cell study, where a cell
is one mix of firm, industry context and product type) have markdown assessment files (`<provider>_assessment.md`)
but no companion JSON. The aggregator (the step that combines judges' scores) needs
typed (checked against a template) `ConstructAssessment` objects to compute α, and md
is a render-not-source artefact (a display copy; parsing it back is fragile). For
these runs, replay defaults to `--rerun-all` —
costs ~$5 to re-score the existing judges plus the missing one(s), but
produces a clean recovered bundle.

PR-A's companion change in `orchestrator/construct_judging.py`
(`ConstructJudgingPhase.persist`) makes JSON judge-assessment files
land *always* (independent of the `--no-json` burst flag). Runs
captured under PR-A or later support targeted replay (`--providers
openai` re-runs only the missing one, leaving the existing assessments
untouched).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

try:
    from ..providers import JUDGE_PROVIDERS
    from ..studies import StudyConfig, load_study
    from ..roles.construct_judge import create_construct_judge_agent
    from ..roles.judge_schemas import ConstructAssessment, ConstructJudgmentBundle
    from ..orchestrator.construct_judging import (
        ConstructJudgingPhase,
        _aggregate,
        _coerce_assessment,
    )
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from providers import JUDGE_PROVIDERS  # type: ignore[no-redef]
    from studies import StudyConfig, load_study  # type: ignore[no-redef]
    from roles.construct_judge import create_construct_judge_agent  # type: ignore[no-redef]
    from roles.judge_schemas import (  # type: ignore[no-redef]
        ConstructAssessment, ConstructJudgmentBundle,
    )
    from orchestrator.construct_judging import (  # type: ignore[no-redef]
        ConstructJudgingPhase,
        _aggregate,
        _coerce_assessment,
    )


log = logging.getLogger(__name__)

# Callable signature accepted for the runner (the software part that hands a prompt to
# an agent and collects the reply): `run_agent(agent=..., prompt=...)`.
# Tests inject a fake; production uses `_make_default_runner` below.
RunnerFn = Callable[..., Awaitable[str]]


# ===========================================================================
# Prompt assembly — reconstruct the judge prompt from persisted md
# ===========================================================================

def assemble_judge_prompt_from_md(run_dir: Path) -> str:
    """Rebuild the judge prompt string from a run's persisted markdown.

    Mirrors `orchestrator/construct_judging._build_judge_inputs` section
    ordering and headers so the replay-judge sees an input
    structurally equivalent to what the original judges saw. The
    *content* is identical (the md is a verbatim render of the typed
    artefacts); the section bookends are reproduced explicitly here
    rather than parsing the md back into typed objects (which would
    be fragile and is unnecessary — the judge only needs a string).

    The reconstructed prompt is not byte-identical to the original
    one because the original used typed object renders (e.g.
    `observation_summary.model_dump_json(indent=2)`) while replay reads
    the rendered markdown. The methodological claim is content-
    equivalence, not byte-equivalence. See DECISIONS.md §29 (numbered entry 29) for the
    rationale and what it does / doesn't claim.
    """
    meta_path = run_dir / "00_meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(
            f"{meta_path} missing — replay needs the run's 00_meta.json "
            f"to recover scenario context."
        )
    meta = json.loads(meta_path.read_text())

    parts: List[str] = []

    parts.append("SCENARIO CONTEXT")
    parts.append("================")
    parts.append(f"- Firm: {meta.get('company', 'unknown')}")
    parts.append(f"- Industry context: {meta.get('industry_context', 'unknown')}")
    parts.append(f"- Product type: {meta.get('product_type', 'unknown')}")
    parts.append("")

    # 1. Strategic artefacts.
    parts.append("STRATEGIC ARTEFACTS (6 ROLE DOCUMENTS)")
    parts.append("=====================================")
    strat_dir = run_dir / "02_strategy_documents"
    if strat_dir.exists():
        # Sort by role for reproducibility — the original render iterated
        # `artefacts.artefacts` which is arbitrary order; sorted-by-filename
        # is more deterministic across replays.
        for md_path in sorted(strat_dir.glob("*_strategy.md")):
            parts.append(f"\n{md_path.read_text()}")
    else:
        parts.append("(no artefacts produced)")
    parts.append("")

    # 2. Public deliberation transcript.
    parts.append("DELIBERATION TRANSCRIPT (PUBLIC events only)")
    parts.append("============================================")
    parts.append(
        "Each line is one public deliberation event. Private "
        "scratchpads and working drafts are NOT shown — you assess "
        "what the firm publicly enacted, not its hidden internal "
        "thinking."
    )
    parts.append("")
    delib_path = run_dir / "01_deliberation" / "interaction_log.md"
    if delib_path.exists():
        parts.append(delib_path.read_text())
    else:
        parts.append("(no deliberation log captured)")
    parts.append("")

    # 3. Observation summary.
    parts.append("RESEARCHER'S OBSERVATION SUMMARY")
    parts.append("================================")
    obs_path = run_dir / "03_researcher" / "observation_summary.md"
    if obs_path.exists():
        parts.append(obs_path.read_text())
    else:
        parts.append("(no observation summary)")
    parts.append("")

    # 4. Live field notes. The md persistence pre-PR-A didn't surface
    #    these as a standalone file (they were inlined into the observer
    #    summary). For older runs this section will be empty; replay
    #    judges still see the field-note content via the observer
    #    summary, which is what they saw originally.
    parts.append("RESEARCHER'S LIVE FIELD NOTES (mid-phase)")
    parts.append("=========================================")
    parts.append("(field notes folded into observer summary above)")
    parts.append("")

    # 5. Debriefing transcript.
    parts.append("PANEL DEBRIEFING TRANSCRIPT")
    parts.append("===========================")
    debrief_path = run_dir / "04_interview" / "transcript.md"
    if debrief_path.exists():
        parts.append(debrief_path.read_text())
    else:
        parts.append("(no debriefing exchanges)")

    return "\n".join(parts)


# ===========================================================================
# Discover which judges already scored / failed / are missing
# ===========================================================================

def discover_judge_state(run_dir: Path) -> Dict[str, str]:
    """Return per-provider state: ``assessed`` / ``failed`` / ``absent``.

    ``assessed`` — `<provider>_assessment.json` exists AND parses to a
        valid ConstructAssessment (i.e. is round-trippable for replay
        aggregation). An md-only assessment counts as ``absent`` here
        because the aggregator needs typed objects to compute α.

    ``failed``   — `<provider>_error.txt` exists (PR-A captured the
        failure). The provider was attempted but didn't score.

    ``absent``   — neither — either the provider was never invoked, or
        its assessment was persisted as md only (no companion JSON).
    """
    judging = run_dir / "05_judging"
    state: Dict[str, str] = {}
    if not judging.exists():
        return state

    json_files = list(judging.glob("*_assessment.json"))
    md_files = list(judging.glob("*_assessment.md"))
    err_files = list(judging.glob("*_error.txt"))

    for jf in json_files:
        provider = jf.name.removesuffix("_assessment.json")
        # Probe that the JSON actually loads to a ConstructAssessment.
        try:
            payload = json.loads(jf.read_text())
            ConstructAssessment.model_validate(payload)
            state[provider] = "assessed"
        except Exception:  # noqa: BLE001
            # Treat as failed-to-load — replay will overwrite.
            state[provider] = "absent"

    # md-only providers (no JSON) → absent for replay purposes.
    for mf in md_files:
        provider = mf.name.removesuffix("_assessment.md")
        if provider not in state:
            state[provider] = "absent"

    for ef in err_files:
        provider = ef.name.removesuffix("_error.txt")
        # An error file overrides absent / md-only: the provider was
        # attempted and failed. Don't overwrite ``assessed`` though —
        # an error file lingering from a previous run shouldn't bury
        # a successful re-run.
        if state.get(provider) != "assessed":
            state[provider] = "failed"

    return state


# ===========================================================================
# Default ADK (Agent Development Kit: Google's software for building agents) runner —
# used in production; tests inject a fake
# ===========================================================================

async def _make_default_runner() -> RunnerFn:
    """Build an `(agent, prompt) -> str` runner backed by ADK + LiteLLM (software
    that lets one program reach many providers' models in the same way).

    A single InMemorySessionService is reused across the per-judge
    calls — fine because each judge is invoked once with a fresh
    session (a stored conversation re-sent to the model, here starting empty).
    """
    from google.adk.sessions import InMemorySessionService  # noqa: PLC0415
    from google.adk.runners import Runner  # noqa: PLC0415
    from google.genai import types  # noqa: PLC0415

    session_service = InMemorySessionService()

    async def run_agent(*, agent: Any, prompt: str) -> str:
        session = await session_service.create_session(
            app_name="replay_judges", user_id="replay",
        )
        runner = Runner(
            agent=agent,
            app_name="replay_judges",
            session_service=session_service,
        )
        msg = types.Content(role="user", parts=[types.Part(text=prompt)])
        chunks: List[str] = []
        async for event in runner.run_async(
            user_id="replay",
            session_id=session.id,
            new_message=msg,
        ):
            content = getattr(event, "content", None)
            if content is None or not hasattr(content, "parts"):
                continue
            for part in content.parts or []:
                t = getattr(part, "text", None)
                if t:
                    chunks.append(t)
        return "\n".join(chunks).strip()

    return run_agent


# ===========================================================================
# The replay function
# ===========================================================================

async def replay_judges(
    *,
    run_dir: Path,
    study: Optional[StudyConfig] = None,
    providers_to_replay: Optional[List[str]] = None,
    rerun_all: bool = False,
    allow_version_mismatch: bool = False,
    write_json: bool = True,
    runner: Optional[RunnerFn] = None,
) -> ConstructJudgmentBundle:
    """Replay selected (or all) judges on a previously-completed run.

    Args:
        run_dir: The run folder containing 00_meta.json + the persisted
            phase artefacts.
        study: The StudyConfig to use for judge agents. Default: load
            from `00_meta.json::study_slug`.
        providers_to_replay: Subset of judge providers to replay. If
            None, every provider currently in `failed`/`absent` state
            gets replayed. Mutually compatible with `rerun_all`.
        rerun_all: When True, ignore the per-provider state and replay
            every provider in the ensemble (effectively re-running all
            judges). Required for runs without companion `_assessment.
            json` files (pre-PR-A `--no-json` runs).
        allow_version_mismatch: When False (the default) the replay
            refuses to run if `00_meta.json::study_version` differs from
            the active study's `version`. Set True to override.
        write_json: Forwarded to `ConstructJudgingPhase.persist`. The
            judge-assessment JSON files always land regardless (PR-A
            policy); this controls the burst-style JSON sub-files.
        runner: Async callable `(agent, prompt) -> str`. Default builds
            an ADK + LiteLLM-backed runner.

    Returns:
        The re-aggregated ConstructJudgmentBundle.
    """
    # 1. Load run metadata + lock study version.
    meta_path = run_dir / "00_meta.json"
    meta = json.loads(meta_path.read_text())
    study_slug = meta.get("study_slug")
    run_study_version = meta.get("study_version")
    if study_slug is None or run_study_version is None:
        raise ValueError(
            f"{meta_path} missing study_slug / study_version — "
            f"cannot lock replay schema. Pass --allow-version-mismatch "
            f"to override (NOT recommended for analysis-grade replay)."
        )

    if study is None:
        study = load_study(study_slug)
    if study.version != run_study_version and not allow_version_mismatch:
        raise ValueError(
            f"Study version mismatch: run captured under "
            f"{run_study_version!r}, current code at {study.version!r}. "
            f"Replay would mix schemas and pollute the α statistic. "
            f"Pass --allow-version-mismatch to override only when you "
            f"genuinely intend the cross-version comparison."
        )

    # 2. Discover which providers need replay.
    state = discover_judge_state(run_dir)
    if providers_to_replay is None:
        if rerun_all:
            providers_to_replay = list(JUDGE_PROVIDERS)
        else:
            providers_to_replay = [
                p for p, st in state.items() if st in ("failed", "absent")
            ]
            # Also include any configured provider not seen in state
            # (i.e. never attempted).
            for p in JUDGE_PROVIDERS:
                if p not in state:
                    providers_to_replay.append(p)

    if not providers_to_replay:
        log.info(
            "replay_judges: every configured judge is already in 'assessed' "
            "state — nothing to do. Pass --rerun-all to re-score them anyway."
        )
        # Rebuild the bundle from existing JSON without invoking any
        # LLM (large language model) — useful when only the aggregator changed.
        existing = _load_existing_assessments(run_dir, provider_filter=None)
        return _reaggregate(
            study=study, existing_assessments=existing,
            run_dir=run_dir, write_json=write_json,
        )

    # 3. Refuse to run if existing judges have md-only assessments and
    #    `--rerun-all` was not passed (we'd produce an aggregator that
    #    silently drops the existing judges).
    if not rerun_all:
        for p, st in state.items():
            if st == "absent" and (run_dir / "05_judging" / f"{p}_assessment.md").exists():
                raise RuntimeError(
                    f"Provider {p!r} has an md-only assessment "
                    f"(`{p}_assessment.md` exists but `{p}_assessment.json` "
                    f"does not). This run was persisted before PR-A's "
                    f"always-write-judge-JSON policy. Re-aggregation "
                    f"requires typed assessments; pass --rerun-all to "
                    f"re-score every judge from scratch (cost: ~$5)."
                )

    # 4. Assemble the prompt.
    prompt = assemble_judge_prompt_from_md(run_dir)
    log.info(
        "replay_judges: assembled prompt from md (size=%d chars), replaying providers=%s",
        len(prompt), providers_to_replay,
    )

    # 5. Resolve the runner.
    if runner is None:
        runner = await _make_default_runner()

    rubric = study.judgment_rubric
    if rubric is None:
        raise ValueError(
            f"Study {study.slug!r} has no judgment_rubric — Phase 5 "
            f"(construct judging) is not applicable for this study."
        )
    dim_keys = [d.key for d in rubric.dimensions]

    # 6. Run each provider sequentially via the shared
    #    `safe_run_with_capture` helper. This is the same path
    #    `orchestrator.construct_judging.run_construct_judging` uses
    #    for live judging — retry-with-backoff (trying a failed call again, waiting
    #    longer each time) on transient errors,
    #    captured `repr(exc) + traceback` on failure. Consolidated
    #    after the Meta-2032 v0.4 replay surfaced that the previous
    #    bare `runner(...)` call here bypassed the retry loop that
    #    PR-76 added inside `_one_judge`, so the replay path got
    #    single-shot failure semantics even on transient errors that
    #    a live judge run would have retried.
    #
    #    Sequential rather than parallel — keeps the rate-limit
    #    picture simple for the small N typical of replay
    #    (1-2 providers in targeted mode, 3-4 with --rerun-all).
    try:
        from ..orchestrator.llm_retry import safe_run_with_capture
    except (ImportError, ValueError):  # pragma: no cover  (script-style)
        from orchestrator.llm_retry import safe_run_with_capture  # type: ignore[no-redef]

    new_assessments: List[ConstructAssessment] = []
    judge_errors: Dict[str, str] = {}
    for provider in providers_to_replay:
        log.info("replay_judges: invoking %s", provider)
        agent = create_construct_judge_agent(provider=provider, study=study)
        raw, error_text = await safe_run_with_capture(
            runner, agent, prompt, provider=provider,
        )
        if error_text is not None:
            judge_errors[provider] = error_text
            log.warning(
                "replay_judges: %s failed during replay (see "
                "<provider>_error.txt for repr(exc) + traceback)",
                provider,
            )
            continue
        assessment = _coerce_assessment(raw, provider=provider, dim_keys=dim_keys)
        if assessment is None:
            judge_errors[provider] = (
                f"{provider}: assessment coercion returned None — see prior "
                f"ERROR-level log lines."
            )
            continue
        new_assessments.append(assessment)

    # 7. Combine with any existing JSON-recoverable assessments (when
    #    not --rerun-all). For --rerun-all, new_assessments IS the full
    #    ensemble.
    if rerun_all:
        all_assessments = new_assessments
    else:
        # Existing JSON-recoverable assessments are the providers in
        # state ``assessed`` that we did NOT replay.
        not_replayed_assessed = [
            p for p, st in state.items()
            if st == "assessed" and p not in providers_to_replay
        ]
        existing = _load_existing_assessments(
            run_dir, provider_filter=not_replayed_assessed,
        )
        all_assessments = existing + new_assessments

    if not all_assessments:
        raise RuntimeError(
            f"Replay produced no usable assessments — every replayed "
            f"provider failed. Errors: {judge_errors!r}"
        )

    # 8. Re-aggregate + persist.
    bundle = _aggregate(
        assessments=all_assessments,
        rubric_dim_keys=dim_keys,
        judge_errors=judge_errors,
    )
    _persist_bundle(bundle=bundle, run_dir=run_dir, write_json=write_json)

    log.info(
        "replay_judges: complete judges=%d failed=%d composite=%.2f alpha=%.2f",
        len(bundle.assessments), len(bundle.judge_errors),
        bundle.mean_composite, bundle.inter_rater_agreement.overall_alpha,
    )
    return bundle


def _load_existing_assessments(
    run_dir: Path, *, provider_filter: Optional[List[str]],
) -> List[ConstructAssessment]:
    """Load `<provider>_assessment.json` files into typed objects.

    `provider_filter=None` loads every JSON-recoverable assessment;
    a list restricts to those providers.
    """
    judging = run_dir / "05_judging"
    out: List[ConstructAssessment] = []
    for jf in sorted(judging.glob("*_assessment.json")):
        provider = jf.name.removesuffix("_assessment.json")
        if provider_filter is not None and provider not in provider_filter:
            continue
        try:
            payload = json.loads(jf.read_text())
            out.append(ConstructAssessment.model_validate(payload))
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "replay_judges: failed to load existing %s assessment exc=%r",
                provider, exc,
            )
    return out


def _reaggregate(
    *,
    study: StudyConfig,
    existing_assessments: List[ConstructAssessment],
    run_dir: Path,
    write_json: bool,
) -> ConstructJudgmentBundle:
    """No-LLM re-aggregation — used when every provider is already
    in `assessed` state and the caller only wants the aggregator output
    refreshed (e.g. after the α-computation logic changed)."""
    rubric = study.judgment_rubric
    assert rubric is not None  # caller checked
    dim_keys = [d.key for d in rubric.dimensions]
    bundle = _aggregate(
        assessments=existing_assessments,
        rubric_dim_keys=dim_keys,
        judge_errors={},
    )
    _persist_bundle(bundle=bundle, run_dir=run_dir, write_json=write_json)
    return bundle


def _persist_bundle(
    *, bundle: ConstructJudgmentBundle, run_dir: Path, write_json: bool,
) -> None:
    """Persist the bundle via the same `ConstructJudgingPhase.persist`
    path the live orchestrator uses — keeps replay output shape
    identical to fresh-run output."""
    phase = ConstructJudgingPhase()
    phase.persist(out_dir=run_dir, result=bundle, write_json=write_json)


# ===========================================================================
# CLI (command-line interface: using a program by typing commands)
# ===========================================================================

def _parse_cli_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m analysis.replay_judges",
        description=(
            "Re-run failed or selected construct judges on a "
            "previously-completed run. Locks the run's study_version "
            "to prevent silent cross-schema pollution of α statistics."
        ),
    )
    p.add_argument(
        "--run-dir", required=True, type=Path,
        help="Path to the run folder (contains 00_meta.json + phase artefacts).",
    )
    p.add_argument(
        "--providers", default=None,
        help=(
            "Comma-separated provider keys to replay. Default: every "
            "provider currently in 'failed' or 'absent' state. Example: "
            "--providers openai,deepseek"
        ),
    )
    p.add_argument(
        "--rerun-all", action="store_true",
        help=(
            "Re-run every judge from scratch (ignore the per-provider "
            "state). Required for runs persisted before PR-A's always-"
            "write-judge-JSON policy."
        ),
    )
    p.add_argument(
        "--allow-version-mismatch", action="store_true",
        help=(
            "Allow replay even when 00_meta.json::study_version differs "
            "from the active study's version. NOT RECOMMENDED — see the "
            "module docstring for the methodological reason."
        ),
    )
    p.add_argument(
        "--no-json", action="store_true",
        help=(
            "Skip the burst-style JSON sub-files (mirrors the same flag on "
            "`run_research_session.py`). Per-judge assessment JSONs still "
            "land — they are PR-A's always-on replay-enabling artefacts."
        ),
    )
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    args = _parse_cli_args(argv)
    providers = (
        [p.strip() for p in args.providers.split(",")]
        if args.providers else None
    )
    bundle = asyncio.run(replay_judges(
        run_dir=args.run_dir,
        providers_to_replay=providers,
        rerun_all=args.rerun_all,
        allow_version_mismatch=args.allow_version_mismatch,
        write_json=not args.no_json,
    ))
    print(
        f"Replay complete: judges={len(bundle.assessments)} "
        f"failed={len(bundle.judge_errors)} "
        f"composite={bundle.mean_composite:.2f} "
        f"alpha={bundle.inter_rater_agreement.overall_alpha:.2f}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
