"""Provider abstraction for TMT (top management team) / researcher / judge agents.

This file decides which language model each agent (a language model given a name,
a role and instructions) uses. A provider is the company
or service that supplies a model, and "abstraction" means the rest of the code can
ask for a model without knowing who serves it.

Goals:
  - One env var (environment variable: a named setting held outside the code),
    TMT_PROVIDER, flips which LLM (large language model: a program trained on vast
    amounts of text to write likely continuations) the simulation runs on.
  - Latest model IDs from each vendor are auto-detected from env vars so
    we can adopt newer releases without touching code.
  - The observer (the researcher agent when it sums up what it saw; called
    qualitative researcher Phase 1 here, as that agent's own first step, and it is
    Phase 3 of a run) is pinned (always set) to Gemini Pro
    (Google's language model) for cross-provider comparability of observation summaries — the
    field notes are part of the dataset and must not vary by TMT backend (the model
    running the team).
  - The construct judges (models that score a finished run against a rubric, or
    scoring guide) are an ensemble (a group used together) of four (Gemini Pro,
    Claude, GPT and DeepSeek, from Google, Anthropic, OpenAI and DeepSeek) regardless
    of which provider ran the TMT.

Environment variables (all optional; defaults are the May-2026 frontier (newest and most capable)
IDs — see `_DEFAULTS` below for the canonical source of truth, which
this block mirrors but may drift from when a model ID is bumped without
this docstring being touched in lockstep):
  TMT_PROVIDER             one of: gemini_pro, gemini_flash, claude, openai,
                                   deepseek, groq, ollama
  TMT_GEMINI_PRO_MODEL     default: gemini-3.1-pro-preview
  TMT_GEMINI_FLASH_MODEL   default: gemini-3.5-flash
  TMT_CLAUDE_MODEL         default: anthropic/claude-opus-4-7
  TMT_OPENAI_MODEL         default: openai/gpt-5.4   (judges also
                                                       on gpt-5.4 —
                                                       see §32 of
                                                       `DECISIONS.md`)
  TMT_DEEPSEEK_MODEL       default: deepseek/deepseek-v4-flash
  TMT_GROQ_MODEL           default: groq/llama-4-maverick
  TMT_OLLAMA_MODEL         default: ollama_chat/qwen3.5:9b
  TMT_OLLAMA_BASE          default: http://localhost:11434

ADK (Agent Development Kit) is Google's ready-made software for building agents,
and LiteLLM is software that lets one program reach many providers' models in the
same way. Non-Gemini providers are routed through ADK's LiteLlm wrapper, which lets
us keep the same `LlmAgent` (ADK's agent type)/`Runner` (the part that hands a prompt
to an agent and collects the reply)/A2A (agent-to-agent, a removed network method
whose name survives) machinery.

DeepSeek and Groq (a company that hosts models released by others) are included as
lower-cost alternatives. Groq serves open-weight (trained numbers published so anyone
can run it) Llama (Meta's model) models. Both speak the OpenAI Chat
Completions protocol (a common format for model requests) via LiteLLM, so they need
only an API key (API, application programming interface: the agreed way one program
asks another for a service; the key is a secret code that identifies who is using it
and who pays; here `DEEPSEEK_API_KEY` / `GROQ_API_KEY` respectively) in the environment. Ollama is
software for running open-weight models on your own computer.

Gemini-on-Vertex AI
-------------------
The native Gemini providers (`gemini_pro`, `gemini_flash`, the pinned
observer, the gemini judge) can be routed through Vertex AI (Google's paid cloud
service offering models)
instead of
AI Studio (Google's simpler service, used with an API key) — useful when you're
spending Google Cloud (GCP, Google Cloud Platform: Google's rented computing
services) credits (e.g. EDU
grants) rather than an AI Studio key. The Gemini SDK (software development kit: a
company's toolkit for using its service) auto-detects
Vertex vs AI Studio via the standard Google env vars:

  GOOGLE_GENAI_USE_VERTEXAI=true   # flip to Vertex
  GOOGLE_CLOUD_PROJECT=<your-gcp-project-id>
  GOOGLE_CLOUD_LOCATION=global      # or your region (see note below)

Auth (proving to the service who you are) is via Application Default Credentials:

  gcloud auth application-default login
  gcloud config set project <your-gcp-project-id>

The framework (the shared software in this repository) has an
`enable_vertex(...)` helper that sets the three env vars in one call;
`run_research_session.py`'s `--vertex` flag (an option added to the command) is a
thin wrapper (a small layer over that helper).
`is_using_vertex()` reports the current routing for the replication
manifest (a file listing what produced a run). Non-Gemini providers (Claude, OpenAI,
DeepSeek, Groq, Ollama)
are unaffected by this switch — they continue to use their own APIs.

Region choice — `GOOGLE_CLOUD_LOCATION`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
For GA (generally available: finished, fully supported) Gemini models (2.5 Pro /
2.5 Flash) every regional endpoint (the web address for one geographic location)
works (`us-central1`, `us-east5`, `europe-west4`, etc.). For
**preview-tier Gemini 3.x models** (early releases the provider may still change
or withdraw: `gemini-3.1-pro-preview`,
`gemini-3-pro-preview`, etc.) Vertex serves them ONLY from
`location=global`; the regional endpoints return `404 NOT_FOUND` even
when the project's billing has access to the preview tier. This is a
Vertex routing distinction, NOT a credit-scope or allowlist issue —
verified against a Google Cloud project in May 2026.

Operational recommendation: set `GOOGLE_CLOUD_LOCATION=global` in your
`.env.local` (your private settings file; or pass `--vertex-location global` on the
CLI, the command line) when
running against any 3.x preview model. The setting is safe for GA
models too — they serve from `global` cleanly — so a single
`location=global` works for the whole framework's Gemini call surface.

Defaults are deliberately under-specified. Confirm and override at run
time via env so a model release between now and the study start is a
one-line change.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

log = logging.getLogger(__name__)

# Default model IDs. Override per env var (`TMT_<PROVIDER>_MODEL`).
# Current frontier-tier picks per vendor as of the active study (see
# `studies/openness_maneuvering/docs/03_frontier_sweep_plan.md` for the rationale). `openai` resolves to
# GPT-5.4 for the team and, through `JUDGE_MODEL_OVERRIDES` below, for the
# construct judge as well.
#
# Note on the Gemini Pro entry: Vertex AI catalogs the 3.1-pro tier
# as `gemini-3.1-pro-preview` until it goes GA. Calling
# `gemini-3.1-pro` returns 404 (verified May 2026). The default sticks
# with the `-preview` suffix until GA promotion; operators who want
# the prior GA flagship can override with
# `TMT_GEMINI_PRO_MODEL=gemini-2.5-pro` (also the recommended
# reproducibility-locked pin for replication packages).
_DEFAULTS = {
    "gemini_pro":   "gemini-3.1-pro-preview",
    "gemini_flash": "gemini-3.5-flash",
    "claude":       "anthropic/claude-opus-4-7",
    "openai":       "openai/gpt-5.4",
    "deepseek":     "deepseek/deepseek-v4-flash",
    "groq":         "groq/llama-4-maverick",
    "ollama":       "ollama_chat/qwen3.5:9b",
}

# Observer (researcher Phase 1) is pinned for comparability across TMT providers.
OBSERVER_PROVIDER = "gemini_pro"

# Default judge ensemble: optional scoring (`--judge`), not part of the method in
# the proposal. Order matters for reproducible logging in the Excel output.
#
# Four vendors, so that a score does not rest on one model. DeepSeek is there as a
# model of a different lineage from the other three; see DECISIONS §27.
JUDGE_PROVIDERS: tuple[str, ...] = ("gemini_pro", "claude", "openai", "deepseek")

# Per-provider model overrides for the construct-judge ensemble. When
# the judge ensemble needs a different model from the team-wide TMT
# resolution, this dict provides the override. Resolution order in
# `get_judge_model(provider)`:
#   1. env var `TMT_JUDGE_<PROVIDER>_MODEL` (e.g. `TMT_JUDGE_OPENAI_MODEL`)
#   2. this dict's per-provider entry
#   3. fall back to the team-wide `get_model(provider)` (i.e. `_DEFAULTS`)
#
# The OpenAI judge runs on GPT-5.4 through the Chat Completions API, which handles
# long judge prompts; DECISIONS §32 gives the reasons. To use another model for one
# run, set `TMT_JUDGE_OPENAI_MODEL`, and `TMT_JUDGE_OPENAI_TIMEOUT_S` if it needs
# longer to answer.
#
# The DeepSeek judge runs on `deepseek-reasoner`, an alias for DeepSeek's current
# reasoning model, so the model behind it can change without code edits. To pin one,
# set `TMT_JUDGE_DEEPSEEK_MODEL` (e.g. `deepseek/deepseek-r1`). The team side stays
# on `deepseek-v4-flash` (see `_DEFAULTS`), because its replies are mostly
# structured output (replies forced into fixed, named fields).
#
# The Claude and Gemini judges have no entry here and fall back to `_DEFAULTS`.
JUDGE_MODEL_OVERRIDES: dict[str, str] = {
    "openai":   "openai/gpt-5.4",
    "deepseek": "deepseek/deepseek-reasoner",
}


# Per-judge request-timeout overrides (seconds; how long our side waits before giving
# up). A reasoning model can take longer than the LiteLLM default to start replying on
# a long prompt, so the DeepSeek judge gets more time; see DECISIONS §30 and §32.
#
# The Gemini judge runs natively via the google-genai client (not
# LiteLLM) so the kwarg (the timeout setting passed along with the call) is harmless / ignored there.
#
# Resolution order (matches `get_judge_model`):
#   1. Env var `TMT_JUDGE_<PROVIDER>_TIMEOUT_S` (e.g.
#      `TMT_JUDGE_OPENAI_TIMEOUT_S=900` for a 15-minute ceiling on a
#      particularly large prompt).
#   2. `JUDGE_TIMEOUT_OVERRIDES[provider]` if defined.
#   3. None — use the LiteLLM / HTTPX default.
JUDGE_TIMEOUT_OVERRIDES: dict[str, int] = {
    "deepseek": 600,   # DeepSeek-R1 reasoning headroom (10 min)
    # OpenAI has no entry: its judge uses the default timeout (DECISIONS §32).
}


def _resolve_judge_timeout(provider: str) -> Optional[int]:
    """Resolve the request timeout (seconds) for a judge call.

    Returns None when no override is configured — LiteLLM / HTTPX use
    their default. Returns an integer otherwise; the caller passes it
    to the LiteLlm wrapper which forwards it to `litellm.acompletion`.
    """
    env_var = f"TMT_JUDGE_{provider.upper()}_TIMEOUT_S"
    env_override = os.environ.get(env_var)
    if env_override:
        try:
            return max(1, int(env_override))
        except (TypeError, ValueError):
            log.warning(
                "ignoring malformed %s=%r; falling back to "
                "JUDGE_TIMEOUT_OVERRIDES",
                env_var, env_override,
            )
    return JUDGE_TIMEOUT_OVERRIDES.get(provider)


def _model_id(key: str) -> str:
    env_var = f"TMT_{key.upper()}_MODEL"
    return os.environ.get(env_var, _DEFAULTS[key])


def _ollama_base() -> str:
    return os.environ.get("TMT_OLLAMA_BASE", "http://localhost:11434")


def get_model(name: Optional[str] = None) -> Any:
    """Return an ADK-compatible model spec for the given provider key.

    Args:
        name: One of `gemini_pro`, `gemini_flash`, `claude`, `openai`,
            `deepseek`, `groq`, `ollama`. If `None`, falls back to env
            var `TMT_PROVIDER` (default `gemini_pro`).

    Returns:
        Either a model-ID string (for native Gemini) or a `LiteLlm`
        wrapper (for Claude / OpenAI / Ollama). Either is accepted by
        `google.adk.agents.LlmAgent(model=...)`.
    """
    name = name or os.environ.get("TMT_PROVIDER", "gemini_pro")

    if name in {"gemini_pro", "gemini_flash"}:
        return _model_id(name)

    # Non-Gemini providers go through LiteLLM. Lazy import keeps the
    # google.adk dependency optional for code paths that only ever use
    # native Gemini models.
    from google.adk.models.lite_llm import LiteLlm  # noqa: PLC0415

    if name == "claude":
        return LiteLlm(model=_model_id("claude"))
    if name == "openai":
        return LiteLlm(model=_model_id("openai"))
    if name == "deepseek":
        return LiteLlm(model=_model_id("deepseek"))
    if name == "groq":
        return LiteLlm(model=_model_id("groq"))
    if name == "ollama":
        return LiteLlm(model=_model_id("ollama"), api_base=_ollama_base())

    raise ValueError(
        f"Unknown provider {name!r}. Choose one of: "
        f"gemini_pro, gemini_flash, claude, openai, deepseek, groq, ollama."
    )


def get_observer_model() -> Any:
    """Model spec for the researcher's silent-observer phase.

    Pinned to Gemini Pro regardless of TMT_PROVIDER so that observation
    summaries (field notes) are produced by a single model across the
    cross-provider robustness study. Differences in construct scores
    between TMT backends should come from the TMT, not from the observer.
    """
    return get_model(OBSERVER_PROVIDER)


def get_judge_model(provider: str) -> Any:
    """Resolve the model spec for one construct-judge agent.

    May differ from `get_model(provider)` when the judge ensemble needs
    a different model from the TMT side. Currently `deepseek` resolves to
    `deepseek-reasoner` here while the TMT side gets `deepseek-v4-flash`;
    `openai` resolves to GPT-5.4 on both sides.

    Resolution order (per axis):

      Model ID:
        1. Env var `TMT_JUDGE_<PROVIDER>_MODEL`.
        2. `JUDGE_MODEL_OVERRIDES[provider]` if defined.
        3. Fall back to `get_model(provider)` (the team-wide default).

      Request timeout (seconds, forwarded to litellm.acompletion):
        1. Env var `TMT_JUDGE_<PROVIDER>_TIMEOUT_S`.
        2. `JUDGE_TIMEOUT_OVERRIDES[provider]` if defined (currently
           DeepSeek, at 600s; see DECISIONS §30 and §32).
        3. None — LiteLLM / HTTPX default (~180s).

    The timeout kwarg is forwarded into the LiteLlm wrapper's
    `_additional_args` and from there to `litellm.acompletion(...)` at
    call time. Native Gemini (`gemini_pro` / `gemini_flash`) does not
    go through LiteLlm so the timeout is not applied — Gemini call-
    site timeouts are governed by `TMT_LLM_CALL_TIMEOUT_S` instead.
    """
    timeout = _resolve_judge_timeout(provider)
    # Convenience for the two LiteLlm-wrapper construction sites below:
    # threading kwargs through cleanly. Native Gemini bypasses all of
    # this (the model ID is just a string).
    extra_kwargs: dict[str, Any] = {}
    if timeout is not None:
        extra_kwargs["timeout"] = timeout

    env_var = f"TMT_JUDGE_{provider.upper()}_MODEL"
    env_override = os.environ.get(env_var)
    if env_override:
        if provider in {"gemini_pro", "gemini_flash"}:
            return env_override
        from google.adk.models.lite_llm import LiteLlm  # noqa: PLC0415
        if provider == "ollama":
            return LiteLlm(
                model=env_override, api_base=_ollama_base(), **extra_kwargs,
            )
        return LiteLlm(model=env_override, **extra_kwargs)

    override_model = JUDGE_MODEL_OVERRIDES.get(provider)
    if override_model:
        if provider in {"gemini_pro", "gemini_flash"}:
            return override_model
        from google.adk.models.lite_llm import LiteLlm  # noqa: PLC0415
        if provider == "ollama":
            return LiteLlm(
                model=override_model, api_base=_ollama_base(), **extra_kwargs,
            )
        return LiteLlm(model=override_model, **extra_kwargs)

    # Falling back to `get_model(provider)` — that path doesn't know
    # about the judge timeout, so reconstruct with the kwargs if we
    # have any to thread through. Skip the rebuild for Gemini (native).
    base_spec = get_model(provider)
    if not extra_kwargs:
        return base_spec
    if provider in {"gemini_pro", "gemini_flash"}:
        return base_spec  # native Gemini — timeout doesn't apply here
    from google.adk.models.lite_llm import LiteLlm  # noqa: PLC0415
    model_id = getattr(base_spec, "model", None) or _model_id(provider)
    api_base = _litellm_setting(base_spec, "api_base")
    kwargs = {"model": model_id, **extra_kwargs}
    if api_base:
        kwargs["api_base"] = api_base
    return LiteLlm(**kwargs)


def get_judge_models() -> dict[str, Any]:
    """Model specs for the four construct judges, keyed by provider name.

    Uses `get_judge_model(provider)` per judge so the ensemble honours
    `JUDGE_MODEL_OVERRIDES` + `TMT_JUDGE_<PROVIDER>_MODEL` env vars.
    """
    return {provider: get_judge_model(provider) for provider in JUDGE_PROVIDERS}


# ---------------------------------------------------------------------------
# Per-role overrides
# ---------------------------------------------------------------------------
#
# Default: every TMT role uses the provider named by `TMT_PROVIDER`.
# Per-role override: `TMT_PROVIDER_<ROLE>` (uppercase) overrides it for
# that role only. Lets you run a heterogeneous team (e.g. for ablation
# studies, which remove or swap one part to see its effect) while still defaulting to
# a uniform team for the main
# robustness study.

# Six TMT role names that this resolver knows about.
TMT_ROLE_NAMES: tuple[str, ...] = (
    "CEO", "CTO", "COO", "CMO", "Product_Strategist", "Product_Designer",
)


def get_role_provider(role: str) -> str:
    """Return the provider key for `role`, honouring per-role overrides.

    Lookup order:
      1. Env var `TMT_PROVIDER_<ROLE_UPPER>` (e.g. `TMT_PROVIDER_CEO`).
      2. Env var `TMT_PROVIDER` (the team-wide default).
      3. Hardcoded fallback `gemini_pro`.
    """
    per_role = os.environ.get(f"TMT_PROVIDER_{role.upper()}")
    if per_role:
        return per_role
    return os.environ.get("TMT_PROVIDER", "gemini_pro")


def get_role_model(role: str) -> Any:
    """Return an ADK model spec for `role`, honouring per-role overrides.

    This is the public entry point used by `roles/*_agent.py` factories (functions
    that build agents)
    to pick the model at construction time. Falls back to the team-wide
    `TMT_PROVIDER` when no per-role override is set.
    """
    return get_model(get_role_provider(role))


def snapshot_role_providers() -> dict[str, str]:
    """Return the resolved provider key for every TMT role, as a dict.

    Used by the replication-manifest writer to record exactly which
    provider each role was using during a run. Reading this AFTER a
    run started is the only reliable way to know — env vars may have
    been changed between runs.
    """
    return {role: get_role_provider(role) for role in TMT_ROLE_NAMES}


def snapshot_role_model_ids() -> dict[str, str]:
    """Return the resolved model ID string for every TMT role.

    For Gemini providers this is the bare model ID; for LiteLLM-wrapped
    providers (Claude / OpenAI / Ollama) it's the LiteLLM-prefixed ID.
    Either way it's a string suitable for logging in a manifest.
    """
    out: dict[str, str] = {}
    for role in TMT_ROLE_NAMES:
        spec = get_role_model(role)
        if isinstance(spec, str):
            out[role] = spec
        else:
            out[role] = getattr(spec, "model", str(spec))
    return out


# ---------------------------------------------------------------------------
# Structured-output adapter (per-provider capability routing)
# ---------------------------------------------------------------------------
#
# Background. ADK's `LlmAgent(output_schema=SomeModel)` (a schema is a template of
# the fields a reply must hold) causes the
# underlying LiteLLM wrapper to send
#   response_format={"type": "json_schema", "json_schema": {...}}
# to the upstream provider. Native Gemini, Claude, OpenAI, and Groq all
# accept that. DeepSeek-Chat (and Ollama servers depending on the model)
# do NOT — DeepSeek returns
#   BadRequestError: "This response_format type is unavailable now"
# and only accepts `{"type": "json_object"}` (or no response_format at
# all). This breaks Phase 1 of `run_research_session.py` for the
# `deepseek` provider key.
#
# Resolution. Classify each provider into one of two structured-output
# modes:
#
#   "schema"       — provider supports strict JSON schema enforcement.
#                    Set `output_schema` on the LlmAgent as usual; ADK
#                    + LiteLLM enforce server-side.
#
#   "json_object"  — provider supports only the weaker {"type":"json_
#                    object"} hint, or nothing at all. Omit
#                    `output_schema` from the LlmAgent so ADK doesn't
#                    inject the strict format, append the Pydantic
#                    (a Python tool that checks replies against a schema)
#                    schema rendered as a prompt-suffix block, and
#                    clone the LiteLlm wrapper with
#                    response_format={"type":"json_object"} so the
#                    provider still commits to returning JSON. The
#                    downstream parser (json.loads + Pydantic
#                    .model_validate) becomes the enforcement boundary
#                    — every parser already tolerates markdown fences
#                    and {"action": ...} wrapper-nesting for the same
#                    reason.
#
# Callers use `build_structured_agent(...)` instead of constructing an
# LlmAgent directly when they need structured output. Five sites use
# this: concurrent-mode role wrapper, artefact-collection role wrapper,
# observer agent, panel debriefer, and the construct judges.

STRUCTURED_OUTPUT_MODE_SCHEMA = "schema"
STRUCTURED_OUTPUT_MODE_JSON_OBJECT = "json_object"

# LiteLLM model-ID prefixes for providers that only support the weaker
# {"type": "json_object"} hint (or nothing). Anything not in this set
# is assumed to support strict json_schema. Bias is intentional:
# defaulting to "schema" means the framework keeps strict enforcement
# wherever the provider can honour it, and we only weaken when we
# know weakening is necessary.
_LITELLM_JSON_OBJECT_PREFIXES: frozenset[str] = frozenset({
    "deepseek",     # DeepSeek-Chat — explicitly errors on json_schema.
    "ollama_chat",  # Ollama — depends on the served model; safer to assume weak.
})


def classify_structured_output_mode(model_spec: Any) -> str:
    """Return the structured-output mode for an ADK model spec.

    Args:
        model_spec: Either a native-Gemini model-ID string (e.g.
            "gemini-2.5-pro") or a `LiteLlm` wrapper whose `.model`
            attribute is the prefixed LiteLLM model ID (e.g.
            "deepseek/deepseek-chat").

    Returns:
        `"schema"` if the provider supports strict json_schema
        enforcement, `"json_object"` if it only supports the weaker
        hint. Native Gemini strings always return `"schema"`. LiteLLM
        wrappers are classified by their model-ID prefix.
    """
    if isinstance(model_spec, str):
        return STRUCTURED_OUTPUT_MODE_SCHEMA
    model_id = getattr(model_spec, "model", None) or ""
    prefix = model_id.split("/", 1)[0] if "/" in model_id else model_id
    if prefix in _LITELLM_JSON_OBJECT_PREFIXES:
        return STRUCTURED_OUTPUT_MODE_JSON_OBJECT
    return STRUCTURED_OUTPUT_MODE_SCHEMA


def _litellm_setting(model_spec: Any, name: str) -> Any:
    """Read a setting from a LiteLlm wrapper.

    ADK keeps constructor settings such as `api_base` in `_additional_args`,
    not as attributes, so a plain `getattr` misses them.
    """
    value = getattr(model_spec, name, None)
    if value is not None:
        return value
    return (getattr(model_spec, "_additional_args", None) or {}).get(name)


def _wrap_litellm_with_json_object_format(model_spec: Any) -> Any:
    """Clone a LiteLlm wrapper with `response_format={"type":"json_object"}`.

    Preserves `model` and `api_base` so non-API-key providers (Ollama)
    keep their endpoint. If the installed ADK/LiteLLM doesn't accept
    `response_format` as a constructor kwarg, logs a warning and returns
    the original wrapper unchanged — the instruction-suffix path still
    gives the provider strong signal to emit JSON.
    """
    if isinstance(model_spec, str):
        return model_spec
    from google.adk.models.lite_llm import LiteLlm  # noqa: PLC0415
    model_id = getattr(model_spec, "model", None)
    if not model_id:
        return model_spec
    kwargs: dict[str, Any] = {"model": model_id}
    api_base = _litellm_setting(model_spec, "api_base")
    if api_base:
        kwargs["api_base"] = api_base
    kwargs["response_format"] = {"type": "json_object"}
    try:
        return LiteLlm(**kwargs)
    except TypeError as exc:
        log.warning(
            "LiteLlm constructor rejected response_format kwarg (%s); "
            "falling back to schema-in-prompt only for model %r.",
            exc, model_id,
        )
        return model_spec


def _format_schema_as_instruction_suffix(output_schema: Any) -> str:
    """Render a Pydantic model's JSON schema as a prompt-suffix block.

    Used in `json_object` mode where the LlmAgent is constructed
    without `output_schema`. The suffix tells the model what shape to
    produce; the parser validates server-side.
    """
    try:
        schema = output_schema.model_json_schema()
    except Exception:  # noqa: BLE001
        schema = {"title": getattr(output_schema, "__name__", "OutputSchema")}
    schema_json = json.dumps(schema, indent=2, sort_keys=True)
    schema_name = getattr(output_schema, "__name__", "the schema")
    return (
        "\n\nOUTPUT FORMAT (strict)\n"
        "----------------------\n"
        f"Return ONLY a single JSON object conforming exactly to the "
        f"`{schema_name}` JSON Schema below. No prose, no commentary, "
        f"no markdown code fences:\n\n"
        f"{schema_json}\n"
    )


def build_structured_agent(
    *,
    name: str,
    model: Any,
    instruction: str,
    description: str,
    output_schema: Any,
    **extra_agent_kwargs: Any,
) -> Any:
    """Construct an `LlmAgent` whose structured output matches the provider.

    This is the single seam every site that needs structured output
    should go through (concurrent-mode role wrapper, artefact agent,
    observer, panel debriefer, construct judges). Branches on
    `classify_structured_output_mode(model)`:

      - `"schema"`     → pin `output_schema=...` on the LlmAgent; ADK
                          + LiteLLM enforce strict JSON server-side.
      - `"json_object"` → omit `output_schema`, suffix the instruction
                          with the rendered JSON Schema, clone the
                          LiteLlm wrapper with `response_format=
                          {"type":"json_object"}`. The orchestrator's
                          existing `_coerce_action`-style parsers
                          enforce on the client side.

    Args:
        name / model / instruction / description: passed through to
            `LlmAgent` as usual.
        output_schema: Pydantic model class. Always passed in — the
            adapter decides how to apply it.
        **extra_agent_kwargs: Forwarded to `LlmAgent` (e.g. `tools=`).

    Returns:
        An `LlmAgent` instance, ready for ADK's Runner.
    """
    from google.adk.agents import LlmAgent  # noqa: PLC0415
    mode = classify_structured_output_mode(model)
    if mode == STRUCTURED_OUTPUT_MODE_SCHEMA:
        return LlmAgent(
            name=name,
            model=model,
            instruction=instruction,
            description=description,
            output_schema=output_schema,
            **extra_agent_kwargs,
        )
    suffixed_instruction = (
        instruction + _format_schema_as_instruction_suffix(output_schema)
    )
    wrapped_model = _wrap_litellm_with_json_object_format(model)
    return LlmAgent(
        name=name,
        model=wrapped_model,
        instruction=suffixed_instruction,
        description=description,
        **extra_agent_kwargs,
    )


# ---------------------------------------------------------------------------
# Vertex AI routing (Gemini-on-Vertex only — see module docstring)
# ---------------------------------------------------------------------------
#
# The Google GenAI SDK that backs every Gemini call in this framework
# auto-detects Vertex vs AI Studio from three env vars:
#
#   GOOGLE_GENAI_USE_VERTEXAI    truthy values: "1", "true", "True", "yes"
#   GOOGLE_CLOUD_PROJECT         e.g. "my-edu-credits-project"
#   GOOGLE_CLOUD_LOCATION        "global" (recommended) or any region
#                                (e.g. "us-central1"). See module
#                                docstring "Region choice" for why
#                                `global` is the recommended setting:
#                                Gemini 3.x preview models are served
#                                ONLY from the global endpoint; regional
#                                endpoints return 404 even when the
#                                project has billing access. `global`
#                                also serves the GA 2.5 family cleanly,
#                                so it works as a single setting for
#                                the framework's whole Gemini surface.
#
# The framework neither needs nor wants to wrap the SDK — these helpers
# only validate the config and surface the mode for the replication
# manifest. They are deliberately stateless reads of os.environ so a
# test can monkeypatch one var at a time.

_VERTEX_TRUTHY: frozenset[str] = frozenset({"1", "true", "yes", "on"})

# Env var that controls Vertex mode. We honour the official Google name
# (GOOGLE_GENAI_USE_VERTEXAI) so users with existing GCP workflows can
# just export it; the `--vertex` CLI flag is a convenience wrapper.
VERTEX_FLAG_ENV = "GOOGLE_GENAI_USE_VERTEXAI"
VERTEX_PROJECT_ENV = "GOOGLE_CLOUD_PROJECT"
VERTEX_LOCATION_ENV = "GOOGLE_CLOUD_LOCATION"


def is_using_vertex() -> bool:
    """Return True iff Gemini calls will be routed through Vertex AI.

    Reads `GOOGLE_GENAI_USE_VERTEXAI` from the env. Any of "1" / "true" /
    "yes" / "on" (case-insensitive) counts as enabled; anything else
    (including unset, "0", "false") means AI Studio.
    """
    raw = os.environ.get(VERTEX_FLAG_ENV, "").strip().lower()
    return raw in _VERTEX_TRUTHY


def get_vertex_project() -> Optional[str]:
    """Return the GCP project the SDK will bill, or None if unset."""
    val = os.environ.get(VERTEX_PROJECT_ENV, "").strip()
    return val or None


def get_vertex_location() -> Optional[str]:
    """Return the Vertex region (e.g. `us-central1`), or None if unset."""
    val = os.environ.get(VERTEX_LOCATION_ENV, "").strip()
    return val or None


def validate_vertex_config() -> None:
    """Raise `ValueError` if Vertex mode is on but project/location missing.

    Called from `run_research_session` at startup so misconfiguration
    fails fast with a clear message instead of producing an opaque
    auth error 30s into a Phase 1 LLM call.

    No-op if `GOOGLE_GENAI_USE_VERTEXAI` is not truthy — AI Studio is
    valid without project/location.
    """
    if not is_using_vertex():
        return
    project = get_vertex_project()
    location = get_vertex_location()
    missing: list[str] = []
    if not project:
        missing.append(VERTEX_PROJECT_ENV)
    if not location:
        missing.append(VERTEX_LOCATION_ENV)
    if missing:
        raise ValueError(
            f"Vertex AI mode is enabled ({VERTEX_FLAG_ENV} is truthy) but "
            f"required env var(s) are unset: {', '.join(missing)}. "
            f"Set them via `export {VERTEX_PROJECT_ENV}=<your-gcp-project>` "
            f"and `export {VERTEX_LOCATION_ENV}=global` (recommended; "
            f"required for Gemini 3.x preview models, also works for the "
            f"GA 2.5 family — see module docstring), then run "
            f"`gcloud auth application-default login` to authenticate."
        )


def enable_vertex(
    project: Optional[str] = None,
    location: Optional[str] = None,
) -> None:
    """Switch Gemini routing to Vertex AI for the rest of this process.

    Sets `GOOGLE_GENAI_USE_VERTEXAI=true` in `os.environ`. If `project`
    or `location` are passed they override the corresponding env vars;
    otherwise the existing env values are used. Either way, the function
    calls `validate_vertex_config()` at the end and raises if required
    config is still missing.

    Idempotent: safe to call multiple times.

    Args:
        project: GCP project ID. If None, leaves
            `GOOGLE_CLOUD_PROJECT` alone (errors via validation if
            unset).
        location: Vertex region. If None, leaves
            `GOOGLE_CLOUD_LOCATION` alone (errors via validation if
            unset).
    """
    os.environ[VERTEX_FLAG_ENV] = "true"
    if project is not None:
        os.environ[VERTEX_PROJECT_ENV] = project
    if location is not None:
        os.environ[VERTEX_LOCATION_ENV] = location
    validate_vertex_config()


def snapshot_vertex_config() -> dict[str, Any]:
    """Capture the active Vertex AI routing for the replication manifest.

    Always returns the same three-key dict so the manifest schema is
    stable across runs:

        {
            "enabled": bool,        # True if Vertex routing is active
            "project": Optional[str],  # GCP project (None if unset)
            "location": Optional[str], # region (None if unset)
        }

    Never raises — read-only snapshot suitable for use even when the
    framework is mis-configured (e.g. Vertex on without project).
    """
    return {
        "enabled": is_using_vertex(),
        "project": get_vertex_project(),
        "location": get_vertex_location(),
    }
