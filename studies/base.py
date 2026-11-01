"""StudyConfig — per-research-project configuration.

This file defines the template every study fills in: its research question,
scenario wording, word lists and optional extras. The shared software stays
the same from study to study, so a new study changes only these settings.

The simulation framework (the shared software in this repository) is one
engine that can host different research projects. Each project is a Python
(the programming language used here) sub-package, meaning a folder of code,
under `studies/<slug>/` (slug: a short name with no spaces), exporting a
module-level `STUDY: StudyConfig` from its `__init__.py`.

`StudyConfig` carries everything that varies between projects:

  * Research question + theoretical lens (the theory the study will
    analyse through). The Debriefer (the researcher agent, a language model
    given that role, when questioning the team) always gets both. The
    Observer and FieldNoter (the same agent when summarising and taking
    notes) never get the lens, and get the question only if the study sets
    `embedded_observation=True`. By default they are blind to both.
  * Construct-specific forbidden vocabulary (words the researcher agent
    must not use unless quoting a panellist, one of the six simulated
    executives when questioned; merged with the universal methodological
    list when the software runs).
  * Flagged vocabulary (a glossary watch-list — words to LOG verbatim
    if panellists use them spontaneously, but never to introduce in
    probes).
  * Scenario framing (e.g. "An AI firm operating in a competitive
    industry" vs "A biotech alliance partner with X").
  * Optional importable-module paths (the address of a Python file) for
    per-study role and context overrides. These are strings (plain text), not
    callables (code that can be run), so StudyConfig stays JSON-dumpable (savable as
    JSON, a plain-text format of named fields) for the replication manifest
    (the file listing what produced a run). Nothing reads these two paths
    yet (planned, P2).

Loading
-------
    from studies import load_study
    study = load_study("openness_maneuvering")

`load_study(slug)` imports `studies.<slug>` and returns its `STUDY`
attribute. Registration is by file presence — no central registry to
keep in sync.

Methodological invariants (enforced by `tests/test_methodological_invariants.py`)
---------------------------------------------------------------------------------
Invariants are rules that must always hold, and automatic tests check them.

* With the default `embedded_observation=False`, `research_question` and
  `theoretical_lens` must not appear in the Observer's or FieldNoter's
  rendered instruction (the standing text that tells a language model who it
  is and how to behave). With `True` the question appears there and the lens
  still does not (`tests/test_observation_stance.py`). The Debriefer gets both
  in its RESEARCH CONTEXT block, with the binding rule
  "may or may not be answered — do not steer; if absent, that absence
  is itself a finding."
* `construct_forbidden_vocabulary` items must appear in researcher
  instructions ONLY inside the forbidden-vocabulary list stanza —
  never in instructional prose elsewhere (would constitute a leak).
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Awaitable, Callable, List, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


DEFAULT_PANEL_ROLES: tuple[str, ...] = (
    "CEO", "CTO", "COO", "CMO", "Product_Strategist", "Product_Designer",
)


# ===========================================================================
# Phase handler protocol
# ===========================================================================
#
# A phase is a numbered stage of a run; a handler is the code for an
# optional extra one. "Protocol" here means a template for code, not the
# debrief protocol. The framework runs Phases 0-4 unconditionally. After
# Phase 4 it walks
# `StudyConfig.extra_phases` and invokes every handler whose
# `should_run()` returns True. Each handler owns its own LLM calls
# (LLM: large language model; a call is one prompt, the text sent to a model,
# and one reply back), made via the framework-injected runner (the part that
# sends prompts and collects replies), and its own persistence layout (how
# results are saved).
#
# This is the extension point that makes the framework genuinely
# study-agnostic: a study can register a member-checking phase, a
# policy-translation phase, a counterfactual replay phase, etc. without
# touching framework code. The default `openness_maneuvering` study
# registers `orchestrator.construct_judging.ConstructJudgingPhase` —
# the rubric-anchored judge ensemble (several models that each score a
# finished run against a rubric, or scoring guide) — but no other study has
# to.

@runtime_checkable
class PhaseHandler(Protocol):
    """Contract for an optional phase a study registers via
    `StudyConfig.extra_phases`.

    The framework calls these methods in order:

      1. `should_run(study, outputs)` — does this handler want to run
         on this particular session (one complete run)? Returns False
         to skip silently
         (e.g. when a required output is missing or a feature flag, a
         setting that turns something on, is off).
      2. `await run(...)` — execute. Returns whatever the phase
         produces (typically a Pydantic model, a record checked against a
         template by the Python tool Pydantic, or a dict, a set of named
         values). Framework
         treats the result as opaque.
      3. `persist(out_dir, result, write_json)` — write the result to
         disk inside the per-run folder. Markdown (plain text with simple
         marks for headings) is mandatory; JSON
         is optional via `write_json`.

    Handlers are also responsible for any error handling they want
    beyond the framework's top-level catch (which logs + records
    `<handler.name>_failed` in `outputs.errors`).
    """

    name: str
    """Short identifier — appears in logs as
    `research_session.phase_<name>_complete`, in error strings, and as
    the key for `ResearchSessionOutputs.extra_phase_results`."""

    folder_prefix: str
    """Folder name (with numeric prefix) under the per-run directory
    where this handler persists its outputs, e.g. `'05_judging'`.
    Different handlers should use different prefixes so the per-run
    folder has a stable ordering."""

    def should_run(self, *, study: "StudyConfig", outputs: Any) -> bool:
        """Return True iff this handler should execute on this run.

        `outputs` is the `ResearchSessionOutputs` instance carrying
        the Phase 1-4 results — handlers can inspect what came out of
        the earlier phases (e.g. skip judging if `outputs.errors` is
        non-empty, or skip a member-checking phase if the debriefing
        produced no exchanges).
        """
        ...

    async def run(
        self,
        *,
        study: "StudyConfig",
        outputs: Any,
        run_agent: Callable[..., Awaitable],
        company: str,
        industry_context: str,
        product_type: str,
    ) -> Any:
        """Execute the phase and return its result. The framework
        stores the return value at
        `ResearchSessionOutputs.extra_phase_results[self.name]`."""
        ...

    def persist(
        self,
        *,
        out_dir: Path,
        result: Any,
        write_json: bool,
    ) -> None:
        """Write `result` to `out_dir / self.folder_prefix / ...`.

        Conventions:
          * Markdown files must always be written.
          * JSON sub-files are written only when `write_json` is True.
          * The handler is responsible for the entire folder layout —
            file names, sub-structure, README inserts, etc.
        """
        ...


# ===========================================================================
# Judgment rubric — for the openness-judge ensemble (and any future
# rubric-anchored construct-scoring layer a study chooses to define).
# ===========================================================================

class RubricDimension(BaseModel):
    """One dimension of a multi-dimensional construct rubric.

    A rubric dimension is scored on a 1-7 Likert scale. The judges
    output a score per dimension PLUS evidence quotes PLUS a reasoning
    paragraph. The orchestrator (the code that runs a run's phases)
    aggregates the judges' scores
    into a composite + computes inter-rater agreement (Krippendorff's
    α) per dimension.
    """

    key: str = Field(
        ...,
        description=(
            "Filesystem-safe identifier (e.g. 'component_disclosure'). "
            "Used as the dict key in aggregate outputs and as the "
            "DimensionAssessment.dimension value the judges return."
        ),
    )
    name: str = Field(
        ...,
        description="Human-readable dimension name (e.g. 'Component disclosure').",
    )
    description: str = Field(
        ...,
        description=(
            "Two-three sentence description of what this dimension "
            "measures. Surfaces in the judge prompt verbatim."
        ),
    )
    anchor_low: str = Field(
        ...,
        description="What a score of 1 looks like (strongly closed end of the scale).",
    )
    anchor_mid: str = Field(
        ...,
        description="What a score of 4 looks like (mixed / situationally open).",
    )
    anchor_high: str = Field(
        ...,
        description="What a score of 7 looks like (strongly open end of the scale).",
    )
    literature: str = Field(
        "",
        description=(
            "Citation grounding for this dimension (e.g. "
            "'Henkel 2006 selective revealing'). Surfaces in the "
            "judge prompt for traceability."
        ),
    )


class JudgmentRubric(BaseModel):
    """A complete rubric for a study's primary construct.

    Drives the openness-judge ensemble: each judge scores every
    dimension on the 1-7 Likert, supplies evidence + reasoning, and
    the orchestrator computes the composite as the simple mean of
    per-dimension scores (per user direction).
    """

    name: str = Field(
        ...,
        description="Human-readable rubric name (e.g. 'Openness in Open Innovation Strategy').",
    )
    description: str = Field(
        ...,
        description=(
            "One-paragraph framing of what the rubric is measuring. "
            "Surfaces in the judge prompt as the construct under "
            "assessment."
        ),
    )
    dimensions: List[RubricDimension] = Field(
        ...,
        description=(
            "The dimensions of the construct. Each is scored "
            "independently on a 1-7 Likert. Composite = simple mean. "
            "Typically 3-7 dimensions; more dimensions diffuse the "
            "signal, fewer dimensions under-specify the construct."
        ),
    )
    scale_anchors: dict[int, str] = Field(
        default_factory=lambda: {
            1: "strongly low / strongly closed",
            4: "mixed / situationally open",
            7: "strongly high / strongly open",
        },
        description=(
            "Numeric scale → anchor text. The judge prompt embeds "
            "these alongside each dimension's specific anchors. "
            "Default uses the 1-4-7 anchoring convention for the "
            "openness study; a future rubric may use different scale "
            "endpoints."
        ),
    )


class StudyConfig(BaseModel):
    """Per-research-project configuration for the simulation framework.

    Every field that varies between studies (research question,
    theoretical lens, construct vocabulary, scenario brief, panel
    composition, registered extra phases) lives here. Researcher
    behaviour (note-taking style, voice continuity, panel format,
    methodological forbidden vocab) stays in the framework code.
    """

    # `extra_phases` carries live `PhaseHandler` instances. They are
    # behaviour, not data — opt out of Pydantic's structural validation
    # by allowing arbitrary types. The dump path
    # (`extra_phases_for_manifest()`) emits string identifiers so the
    # replication manifest stays JSON-clean.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # ---- Identity ---------------------------------------------------
    name: str = Field(
        ...,
        description=(
            "Human-readable study name, e.g. 'Strategic Maneuvering "
            "of Openness in Open Innovation Ecosystems'. Goes into "
            "manifest + 00_meta.json."
        ),
    )
    slug: str = Field(
        ...,
        description=(
            "Filesystem-safe identifier matching the sub-package "
            "directory name. Used by `--study <slug>` and for "
            "results/runs/<slug>_... folder naming."
        ),
    )
    # Semver: a three-part version number, such as 0.1.0.
    version: str = Field(
        "0.1.0",
        description=(
            "Semver. Persisted in the replication manifest so a "
            "downstream analysis can pin to exactly which study "
            "configuration produced a given run."
        ),
    )

    # ---- Research framing (Debriefer only) --------------------------
    research_question: str = Field(
        ...,
        description=(
            "The research question this study asks. The Debriefer always "
            "sees it, as a guide. The Observer and FieldNoter see it only "
            "when `embedded_observation` is True."
        ),
    )
    embedded_observation: bool = Field(
        False,
        description=(
            "How the researcher agent observes, which is a design choice. "
            "False (default): a separate observer, blind to the research "
            "question, so its notes are not shaped by what the study hopes "
            "to find. True: an embedded ethnographer, who knows the "
            "question while observing and can watch for what bears on it, "
            "at the risk of seeing what it expects. The panel never sees "
            "the question either way, and each run records the choice."
        ),
    )
    theoretical_lens: str = Field(
        ...,
        description=(
            "Description of the theoretical lens used for LATER "
            "ANALYSIS (e.g. 'selective revealing + dynamic "
            "capabilities + design-science ecosystem-shaping'). "
            "Surfaces in the Debriefer's RESEARCH CONTEXT block as "
            "background, never as a steer toward finding evidence. "
            "Free-form prose; cite the supporting literature in "
            "the same string for traceability."
        ),
    )
    debriefer_background_block: str = Field(
        "",
        description=(
            "Optional additional study-specific background prose "
            "the Debriefer should know (e.g. an industry primer). "
            "Surfaces inside the RESEARCH CONTEXT block alongside "
            "the research question and lens."
        ),
    )

    # ---- Methodological additions -----------------------------------
    construct_forbidden_vocabulary: List[str] = Field(
        default_factory=list,
        description=(
            "Study-specific words the researcher must NOT use in "
            "probes (because they would steer panellists toward the "
            "construct). Merged with the universal "
            "`methodological_forbidden_vocabulary` from the protocol "
            "YAML at runtime."
        ),
    )
    flagged_vocabulary: List[str] = Field(
        default_factory=list,
        description=(
            "Glossary watch-list. If a panellist uses any of these "
            "words SPONTANEOUSLY, the researcher logs them verbatim "
            "in `flagged_vocabulary_used`. The researcher never "
            "asks why these words; the watch-list is a capture "
            "mechanism, not a steering mechanism. Presented to "
            "Observer and FieldNoter as a finite list with no "
            "explanation of why the words matter."
        ),
    )

    # ---- Scenario framing -------------------------------------------
    # `scenario_brief` reaches the task prompt as `Company: <company> (<brief>)`;
    # the description below is older.
    scenario_brief: str = Field(
        "A firm operating in a competitive industry.",
        description=(
            "Short factual description of the kind of firm being "
            "simulated. Surfaces in the CEO/role prompts as 'You are "
            "the <role> of <company> (<scenario_brief>)'. Keeps the "
            "team's product choice bounded to the right domain "
            "without dictating a specific product."
        ),
    )
    strategic_question_template: Optional[str] = Field(
        None,
        description=(
            "Optional override for the default deliberation prompt. "
            "Python f-string-style format with named placeholders "
            "{product_type} and {direction_hint}. When None, the "
            "framework's built-in template is used."
        ),
    )

    # ---- Optional overrides (importable module paths, not callables) -
    role_factories_module: Optional[str] = Field(
        None,
        description=(
            "Importable dotted path to a module exposing a "
            "`ROLE_FACTORIES: dict[str, Callable]` mapping role name "
            "to factory function. None = use the framework's "
            "default `roles/*_agent.py` factories. We store the "
            "string (not the callable) so StudyConfig remains "
            "JSON-dumpable for the replication manifest."
        ),
    )
    contexts_module: Optional[str] = Field(
        None,
        description=(
            "Importable dotted path to a module overriding "
            "`roles/context_definitions.py`. None = use the default. "
            "Same rationale as `role_factories_module`."
        ),
    )
    # `roles/qualitative_researcher_agent._apply_study_overlay` merges this over
    # the protocol YAML; the description below is older.
    protocol_overlay: Optional[dict] = Field(
        None,
        description=(
            "Sparse dict that gets MERGED over the protocol YAML at "
            "load time. Lets a study add a thematic area or tweak "
            "the panel format without forking the YAML. Reserved "
            "for future use — the loader does not consume it yet."
        ),
    )

    # ---- Optional RAG-corpus loader ---------------------------------
    # RAG (retrieval-augmented generation): the software searches a corpus, a
    # collection of documents, and adds the passages found to an agent's prompt
    # before it writes. `--rag` is the command-line option that turns this on.
    # With `--rag`, a loader that returns None stops the run with an error, so a
    # grounded run never goes on without retrieval; the description below is older.
    rag_corpus_loader: Optional[str] = Field(
        None,
        description=(
            "Importable dotted path (e.g. 'studies.openness_maneuvering."
            "rag_loader:load_corpus' or 'studies.x.rag_loader.load_"
            "corpus') to a callable taking a company name and returning "
            "either a dict {'corpus_name': str, 'embedding_model': str, "
            "'documents': list[{display_name, sha256, source_uri}]} or "
            "None. None means 'no corpus for this firm; run without "
            "RAG'. When set AND the CLI's `--rag` flag is supplied, the "
            "framework resolves this at session start and threads a "
            "`RagSession` through the six role agents in phases 1, 2, "
            "and 4. The observer / field-noter / debriefer do NOT "
            "retrieve — see invariants I1–I3 + new I5 in "
            "`docs/10_rag_repo_plan.md`."
        ),
    )

    # ---- Default panel composition ----------------------------------
    # TMT: top management team, here the six simulated executives.
    # Nothing reads this field yet (planned, P2): every study uses the default
    # roles. The description below states the plan.
    panel_roles: List[str] = Field(
        default_factory=lambda: list(DEFAULT_PANEL_ROLES),
        description=(
            "Names of the roles in the TMT panel. Used when "
            "`role_factories_module` is None to pick which factories "
            "the framework calls. A different study might want "
            "different panel composition (e.g. a Head of R&D + VP "
            "Alliances for an alliance-management study)."
        ),
    )

    # ---- Construct-scoring rubric (optional) ------------------------
    # The panel has four judges by default (`providers.JUDGE_PROVIDERS`), is off by
    # default (`--judge`, or `analysis/replay_judges.py` after a run) and is not part
    # of the method in the proposal; the description below is older.
    judgment_rubric: Optional[JudgmentRubric] = Field(
        None,
        description=(
            "Rubric used by the multi-judge ensemble to score this "
            "study's primary construct (e.g. openness for the "
            "openness_maneuvering study). When supplied AND the study "
            "registers `ConstructJudgingPhase` in `extra_phases`, the "
            "framework runs Phase 5: three LLM judges read the run's "
            "artefacts + transcript + observation + debriefing and "
            "score each rubric dimension on a 1-7 Likert. See "
            "`orchestrator/construct_judging.py`."
        ),
    )

    # ---- Extra phases registered by the study -----------------------
    extra_phases: List[Any] = Field(
        default_factory=list,
        description=(
            "Live `PhaseHandler` instances the framework runs in order "
            "after Phase 4 (debriefing). Each handler decides for "
            "itself whether it wants to run on a given session (via "
            "`should_run()`) and how to persist its output. The "
            "default `openness_maneuvering` study registers "
            "`ConstructJudgingPhase()` here to opt into Phase 5; a "
            "future study could register a member-checking phase, a "
            "policy-translation phase, etc., without touching "
            "framework code. Excluded from `model_dump()` for the "
            "replication manifest — see `extra_phase_ids_for_manifest()`."
        ),
    )

    def extra_phase_ids_for_manifest(self) -> List[str]:
        """Dotted-path identifiers for each registered PhaseHandler.

        Used by the replication-manifest writer. `extra_phases` itself
        holds behaviour (live instances), so it can't be JSON-dumped
        directly; this method renders each handler as
        `<module>:<ClassName>` so a reviewer can resolve it back to
        the implementing class.
        """
        return [
            f"{type(h).__module__}:{type(h).__name__}"
            for h in self.extra_phases
        ]

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Dump as JSON-safe dict; replace `extra_phases` instances
        with their dotted-path identifiers so the manifest stays
        clean."""
        data = super().model_dump(**kwargs)
        if "extra_phases" in data:
            data["extra_phases"] = self.extra_phase_ids_for_manifest()
        return data


def load_study(slug: str) -> StudyConfig:
    """Import `<this-package>.<slug>` and return its module-level `STUDY`.

    The package prefix is read from `__package__` so the loader works
    correctly whether this module was imported as `studies.base` or as
    `<top-level-pkg>.studies.base` (the repository's conftest, the
    test set-up file, has a meta-path finder, a custom import step, that
    loads the codebase under a hyphenated top-level prefix).

    Raises:
        ModuleNotFoundError: if the study sub-package doesn't exist.
        AttributeError: if the sub-package's `__init__.py` doesn't
            export a `STUDY` attribute.
        TypeError: if `STUDY` doesn't quack like a StudyConfig
            (duck-typed, meaning judged by the fields it has rather than its
            declared type, since `isinstance` is unreliable across
            the conftest's parallel module hierarchies).
    """
    if not slug:
        raise ValueError("load_study(slug): slug must be non-empty")

    # `__package__` is e.g. 'studies' or '<top-level-pkg>.studies'
    # depending on how this module was imported. Load the study sub-
    # package from the SAME package context so the user's STUDY instance
    # is wired against the same StudyConfig class object.
    parent_pkg = __package__ or "studies"

    try:
        mod = importlib.import_module(f"{parent_pkg}.{slug}")
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            f"No study found at studies/{slug}/. "
            f"Expected `studies/{slug}/__init__.py` exporting `STUDY: StudyConfig`."
        ) from exc

    study = getattr(mod, "STUDY", None)
    if study is None:
        raise AttributeError(
            f"`studies.{slug}` exists but does not export `STUDY`. "
            f"Add `STUDY: StudyConfig = StudyConfig(...)` to its `__init__.py`."
        )

    # Duck-typed validation — the conftest meta-path finder loads this
    # module twice under different prefixes, so `isinstance(study,
    # StudyConfig)` is unreliable. Check for the required attributes
    # instead.
    required_attrs = ("name", "slug", "research_question", "theoretical_lens")
    for attr in required_attrs:
        if not hasattr(study, attr):
            raise TypeError(
                f"`studies.{slug}.STUDY` must be a StudyConfig-like "
                f"object with a `{attr}` attribute; got "
                f"{type(study).__name__}."
            )
    return study
