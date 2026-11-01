"""Replication manifest for one research session.

A manifest is a file listing what produced something. This code writes a structured
snapshot of EVERYTHING a reviewer would need to reproduce a run (also called a
research session: one complete simulated meeting and debrief):

  * `models_used` — model ID + provider (the company supplying the model) for every
    agent, a language model given a role and instructions (CEO/CTO/…
    + observer, the researcher agent summing up, + judges, the models scoring a
    finished run).
  * `prompts_used` — the exact instruction string each agent was
    built with (for the system prompt, the standing text telling a model who it is
    and how to behave) and the run's strategic
    question if any.
  * `run_config` — company, industry_context, product_type,
    launch_year, deliberation_config dump, the settings for the team's discussion
    (mode; convergence, the rule that ends it; seeds, which fix its random choices).
  * `git_provenance` — commit SHA (the fingerprint naming an exact saved code version in
    git, the tool that keeps the code's history) + dirty flag (whether unsaved changes
    existed) + branch name (the line of work).
  * `env_snapshot` — relevant `TMT_*` (TMT: top management team) env vars, the named
    settings held outside the code (API keys, the secret codes showing who pays for
    a service, redacted) + Python version (the programming language used) + key
    package (bundle of ready-made code) versions.
  * `timing` — started_at / finished_at.

API-KEY REDACTION
-----------------
Anything containing the substrings KEY, TOKEN, SECRET, PASSWORD,
CREDENTIAL, AUTH (case-insensitive) is replaced with the literal
string `"<redacted>"`. Tests verify this. The manifest is intended
to be PR-attached (PR: pull request, a proposed set of code changes) /
reviewer-shared, so leaks would be a real
security issue.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Schema (a template saying which fields a record must contain)
# ---------------------------------------------------------------------------

class ReplicationManifest(BaseModel):
    """All the metadata needed to reproduce one research session.

    Stored as `manifest.json` inside the per-run folder (alongside the
    other JSON (plain-text structured data) streams from `persist_artefacts`). The structure is
    deliberately small enough to scan visually but complete enough that
    a reviewer can re-run with the same inputs.
    """

    schema_version: str = "1"
    run_id: str
    company: str
    industry_context: str
    product_type: str
    launch_year: int
    started_at: str
    finished_at: Optional[str] = None

    # Which study configuration was active. The slug (a short name with no spaces)
    # + version together pin a run to an exact StudyConfig (research question,
    # lens, the theory a study analyses through,
    # construct-vocabulary, scenario brief). A downstream analysis can
    # `studies.load_study(slug)` and assert `.version == study_version`
    # to confirm reproducibility.
    study_slug: str = ""
    study_version: str = ""

    # Configuration of the deliberation itself.
    research_question: str = ""
    strategic_question: str = ""
    product_description: str = ""
    deliberation_config: Dict[str, Any] = Field(default_factory=dict)

    # Models: every agent that emitted text in this run.
    models_used: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Map from agent name (e.g. 'CEO', 'CTO', 'observer', "
            "'debriefer') to the resolved model ID string."
        ),
    )
    providers_used: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Map from agent name to the resolved provider key (e.g. "
            "'gemini_pro', 'claude', 'openai'). Per-role overrides "
            "show up here."
        ),
    )

    # The exact instruction strings each agent was constructed with.
    prompts_used: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Agent name → system instruction string. Lets a reviewer "
            "see WHAT each agent was told before any user-turn prompt."
        ),
    )

    # Git / commit provenance.
    git_provenance: Dict[str, Any] = Field(default_factory=dict)

    # SHA-256 (a short fingerprint computed from a file's contents) of the files that
    # set what agents are told, by path.
    protocol_hashes: Dict[str, str] = Field(default_factory=dict)

    # Environment snapshot (API keys redacted).
    env_snapshot: Dict[str, Any] = Field(default_factory=dict)

    # Vertex AI (Google's paid cloud service) routing for Gemini (Google's language
    # model) calls. {"enabled": bool, "project":
    # Optional[str], "location": Optional[str]}. Captured even when
    # disabled so the manifest is unambiguous about which mode the run
    # used (AI Studio, Google's direct route to Gemini, vs. Vertex with EDU
    # credits, for instance).
    vertex_config: Dict[str, Any] = Field(default_factory=dict)

    # RAG (retrieval-augmented generation: searching documents and adding the
    # passages found to a prompt) corpus (document collection) configuration
    # for this run. {"enabled": bool,
    # "corpus_resource_name": Optional[str], "embedding_model": str,
    # "top_k": int, "documents": list[{display_name, sha256,
    # source_uri}]}. Captured even when RAG is disabled (so the
    # manifest is unambiguous about which condition this run was: with-
    # RAG or without). When enabled, the per-document SHA256s pin which
    # corpus content was indexed at run time — corpus state lives in
    # Google Vertex AI RAG Engine (Google's paid service that stores a corpus and runs
    # the searches), not in git.
    rag_config: Dict[str, Any] = Field(default_factory=dict)

    # Framework-default model IDs at run time. Snapshot of
    # `providers._DEFAULTS` plus the judge-side overrides. Distinct
    # from `models_used`: the latter records the *resolved* model ID
    # per agent (which honours every env-var + per-role override),
    # while this records what the framework's defaults WERE at the
    # commit_sha of this run. Useful when reading old manifests — lets
    # a reviewer tell whether a given run used the framework default
    # for that commit or an explicit override.
    default_models: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Snapshot of `providers._DEFAULTS` + judge-model overrides "
            "at run time. One entry per provider key (gemini_pro, "
            "gemini_flash, claude, openai, deepseek, groq, ollama) "
            "plus 'judge_openai' / 'judge_<provider>' for any judge-"
            "side override entries from `JUDGE_MODEL_OVERRIDES`."
        ),
    )


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

_SENSITIVE_SUBSTRINGS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")
_REDACTED = "<redacted>"


def redact_env(env: Dict[str, str]) -> Dict[str, str]:
    """Return a copy of `env` with sensitive values masked.

    A key is sensitive if its NAME contains any of:
      KEY, TOKEN, SECRET, PASSWORD, CREDENTIAL, AUTH
    (case-insensitive). The value is replaced with '<redacted>';
    presence in the manifest is preserved so the reviewer can see
    *that* an API key was present even if not what it was.
    """
    out: Dict[str, str] = {}
    for name, value in env.items():
        upper = name.upper()
        if any(s in upper for s in _SENSITIVE_SUBSTRINGS):
            out[name] = _REDACTED
        else:
            out[name] = value
    return out


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

def snapshot_git_provenance(repo_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Capture git commit SHA + dirty flag + branch for the repo.

    Best-effort: if `git` is unavailable or this isn't a git repo, the
    returned dict has `available=False` and the other fields are None.
    """
    repo = repo_dir or Path(__file__).resolve().parent.parent

    def _run(args: list[str]) -> Optional[str]:
        try:
            out = subprocess.run(
                args, cwd=str(repo), capture_output=True, text=True,
                timeout=5, check=False,
            )
            if out.returncode != 0:
                return None
            return out.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    commit = _run(["git", "rev-parse", "HEAD"])
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    status = _run(["git", "status", "--porcelain"])

    return {
        "available": commit is not None,
        "commit_sha": commit,
        "branch": branch,
        "dirty": bool(status) if status is not None else None,
        "dirty_files_count": (
            len([l for l in status.splitlines() if l.strip()])
            if status else 0
        ),
        "repo_path": str(repo),
    }


def snapshot_env(prefix_filter: str = "TMT_") -> Dict[str, str]:
    """Capture relevant env vars (TMT_* by default), redacting secrets.

    Only env vars whose name starts with `prefix_filter` are captured.
    All values are passed through `redact_env` so anything that looks
    like a credential is masked.
    """
    raw = {k: v for k, v in os.environ.items() if k.startswith(prefix_filter)}
    # Also include the API-key envs that we want a reviewer to KNOW
    # were set (even though we redact their values).
    for k in (
        "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY", "GROQ_API_KEY",
    ):
        if k in os.environ:
            raw[k] = os.environ[k]
    # Vertex AI / Google Cloud config — values are NOT secrets, but
    # they tell the reviewer whether the run hit AI Studio or Vertex.
    # The flag + project + location are captured verbatim (not
    # redacted) so they're useful for reproduction.
    for k in (
        "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
    ):
        if k in os.environ:
            raw[k] = os.environ[k]
    return redact_env(raw)


def snapshot_python_and_packages() -> Dict[str, Any]:
    """Capture Python version + a few key package versions."""
    info: Dict[str, Any] = {
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "packages": {},
    }
    for pkg in ("pydantic", "google-adk", "google-genai", "litellm",
                "anthropic", "openai"):
        try:
            # importlib.metadata is the modern way; some pkgs use
            # different distribution names.
            from importlib.metadata import version, PackageNotFoundError
            try:
                info["packages"][pkg] = version(pkg)
            except PackageNotFoundError:
                info["packages"][pkg] = None
        except ImportError:  # pragma: no cover  (Python <3.8 only)
            info["packages"][pkg] = None
    return info


# ---------------------------------------------------------------------------
# Manifest builder
# ---------------------------------------------------------------------------

def snapshot_protocol_hashes(study_slug: str = "") -> Dict[str, str]:
    """Hash the protocol (the debrief's rules and topics), debrief overlay (a study's
    own added topics), roles, scenarios and phases."""
    root = Path(__file__).resolve().parent.parent
    files = [
        "protocols/ethnographic_protocol.yaml",
        "roles/context_definitions.py",
        "roles/qualitative_researcher_agent.py",
        "orchestrator/concurrent_mode.py",
        "orchestrator/artefact_collection.py",
        "orchestrator/panel_debriefing.py",
        "orchestrator/role_memory.py",
        "rag/prompt_inject.py",
        "rag/queries.py",
    ]
    if study_slug:
        files += [
            f"studies/{study_slug}/__init__.py",
            f"studies/{study_slug}/debriefing_overlay.yaml",
        ]
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in files
        if (root / name).exists()
    }


def build_replication_manifest(
    *,
    run_id: str,
    company: str,
    industry_context: str,
    product_type: str,
    launch_year: int,
    started_at: str,
    finished_at: Optional[str] = None,
    study_slug: str = "",
    study_version: str = "",
    research_question: str = "",
    strategic_question: str = "",
    product_description: str = "",
    deliberation_config: Optional[Dict[str, Any]] = None,
    models_used: Optional[Dict[str, str]] = None,
    providers_used: Optional[Dict[str, str]] = None,
    prompts_used: Optional[Dict[str, str]] = None,
    git_provenance: Optional[Dict[str, Any]] = None,
    env_snapshot: Optional[Dict[str, Any]] = None,
    vertex_config: Optional[Dict[str, Any]] = None,
    rag_config: Optional[Dict[str, Any]] = None,
    default_models: Optional[Dict[str, str]] = None,
    include_git: bool = True,
    include_env: bool = True,
) -> ReplicationManifest:
    """Assemble a ReplicationManifest from the run's metadata + snapshots.

    Each top-level field is either passed in (preferred) or snapshotted
    fresh at call time. The caller is responsible for filling
    `models_used` / `providers_used` / `prompts_used` because those
    depend on the live agent objects.
    """
    if git_provenance is None and include_git:
        git_provenance = snapshot_git_provenance()
    if env_snapshot is None and include_env:
        env_payload = {"env_vars": snapshot_env()}
        env_payload.update(snapshot_python_and_packages())
        env_snapshot = env_payload
    if vertex_config is None:
        try:
            from ..providers import snapshot_vertex_config
        except (ImportError, ValueError):  # pragma: no cover  (script-style)
            from providers import snapshot_vertex_config  # type: ignore[no-redef]
        vertex_config = snapshot_vertex_config()
    if default_models is None:
        # Snapshot `providers._DEFAULTS` + the judge-side override dict
        # at call time. Captures what the framework's defaults WERE for
        # this run's commit_sha — a reviewer reading the manifest can
        # then tell whether the resolved per-agent models match the
        # default (no override active) or diverge.
        try:
            from ..providers import _DEFAULTS as _PROVIDER_DEFAULTS
            from ..providers import JUDGE_MODEL_OVERRIDES as _JUDGE_OVERRIDES
        except (ImportError, ValueError):  # pragma: no cover  (script-style)
            from providers import _DEFAULTS as _PROVIDER_DEFAULTS  # type: ignore[no-redef]
            from providers import JUDGE_MODEL_OVERRIDES as _JUDGE_OVERRIDES  # type: ignore[no-redef]
        default_models = dict(_PROVIDER_DEFAULTS)
        # Surface judge-side overrides under `judge_<provider>` keys
        # so they sit alongside the team-wide defaults in one dict.
        for prov, model in _JUDGE_OVERRIDES.items():
            default_models[f"judge_{prov}"] = model

    return ReplicationManifest(
        run_id=run_id,
        company=company,
        industry_context=industry_context,
        product_type=product_type,
        launch_year=launch_year,
        started_at=started_at,
        finished_at=finished_at,
        study_slug=study_slug,
        study_version=study_version,
        research_question=research_question,
        strategic_question=strategic_question,
        product_description=product_description,
        deliberation_config=deliberation_config or {},
        models_used=models_used or {},
        providers_used=providers_used or {},
        prompts_used=prompts_used or {},
        git_provenance=git_provenance or {},
        env_snapshot=env_snapshot or {},
        vertex_config=vertex_config or {},
        rag_config=rag_config or {},
        default_models=default_models or {},
    )


# ---------------------------------------------------------------------------
# Convenience: capture from a live TMTSystemWithA2A (the team's software; A2A,
# agent-to-agent, is a removed method that survives in this name)
# ---------------------------------------------------------------------------

def capture_from_system(
    system: Any,
    *,
    run_id: str,
    started_at: str,
    finished_at: Optional[str] = None,
    research_question: str = "",
    strategic_question: str = "",
    product_description: str = "",
    deliberation_config: Optional[Dict[str, Any]] = None,
    extra_agents: Optional[Dict[str, Any]] = None,
    rag_session: Optional[Any] = None,
    study_slug: str = "",
    study_version: str = "",
) -> ReplicationManifest:
    """Build a manifest from a TMTSystemWithA2A instance.

    Reads:
      - The 6 TMT role agents' models + instructions from `system.agents`.
      - The team-wide provider resolution from `providers.snapshot_role_providers`.
      - `extra_agents`: optionally pass {'observer': observer_agent,
                                          'debriefer': debriefer_agent}
        so their models / prompts are captured too.

    Doesn't require running the deliberation — can be called pre- or
    post-run.
    """
    try:
        from ..providers import snapshot_role_providers
    except (ImportError, ValueError):  # pragma: no cover  (script-style)
        from providers import snapshot_role_providers  # type: ignore[no-redef]

    models_used: Dict[str, str] = {}
    providers_used: Dict[str, str] = dict(snapshot_role_providers())
    prompts_used: Dict[str, str] = {}

    for role_name, agent in (system.agents or {}).items():
        models_used[role_name] = _model_id(agent)
        prompts_used[role_name] = getattr(agent, "instruction", "") or ""

    for name, agent in (extra_agents or {}).items():
        models_used[name] = _model_id(agent)
        prompts_used[name] = getattr(agent, "instruction", "") or ""

    rag_config_dict: Optional[Dict[str, Any]] = None
    if rag_session is not None and hasattr(rag_session, "manifest_dict"):
        rag_config_dict = rag_session.manifest_dict()

    manifest = build_replication_manifest(
        run_id=run_id,
        company=system.company,
        industry_context=system.industry_context,
        product_type=system.product_type,
        launch_year=system.current_year,
        started_at=started_at,
        finished_at=finished_at,
        research_question=research_question,
        strategic_question=strategic_question,
        product_description=product_description,
        deliberation_config=deliberation_config,
        models_used=models_used,
        providers_used=providers_used,
        prompts_used=prompts_used,
        rag_config=rag_config_dict,
        study_slug=study_slug,
        study_version=study_version,
    )
    manifest.protocol_hashes = snapshot_protocol_hashes(study_slug)
    # Run folders get published, so leave out what identifies the machine or
    # the cloud project. Neither is needed to repeat a run.
    manifest.git_provenance.pop("repo_path", None)
    manifest.env_snapshot.get("env_vars", {}).pop("GOOGLE_CLOUD_PROJECT", None)
    manifest.env_snapshot.pop("python_executable", None)
    if manifest.vertex_config.get("project"):
        manifest.vertex_config["project"] = "(not recorded)"
    manifest.rag_config = json.loads(
        re.sub(r"projects/[^/\"]+/", "projects/<project>/", json.dumps(manifest.rag_config))
    )
    return manifest


def _model_id(agent: Any) -> str:
    """Pull a stable model ID string from an LlmAgent.

    For native Gemini agents `agent.model` is a string. For LiteLLM-
    wrapped agents (LiteLLM lets one program reach many providers' models in the
    same way; here Claude / OpenAI / Ollama, which runs models on your own
    computer) `agent.model` is a
    `LiteLlm` instance whose `.model` attribute is the string.
    """
    spec = getattr(agent, "model", None)
    if spec is None:
        return ""
    if isinstance(spec, str):
        return spec
    return getattr(spec, "model", str(spec))


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def write_manifest(manifest: ReplicationManifest, out_dir: Path) -> Path:
    """Write `manifest.json` into the per-run folder. Returns the path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "manifest.json"
    p.write_text(manifest.model_dump_json(indent=2))
    return p
