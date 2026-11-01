"""Unit tests for `providers.build_structured_agent` and its helpers.

Background. ADK's `LlmAgent(output_schema=...)` causes the underlying
LiteLLM wrapper to send `response_format={"type":"json_schema",
"json_schema":{...}}` to the upstream provider. Strict-schema providers
(native Gemini, Anthropic, OpenAI, Groq) accept that; DeepSeek and
Ollama do not. The adapter classifies each provider and routes
accordingly:

  schema mode      → pin `output_schema` on the agent as before.
  json_object mode → omit `output_schema`, append the JSON Schema to
                     the instruction as text, clone the LiteLlm wrapper
                     with response_format={"type":"json_object"}.

These tests pin the routing contract for both modes plus the helpers
that classify and clone — no network, no real ADK runner.
"""

from __future__ import annotations

import importlib
import json

import pytest
from pydantic import BaseModel

PKG = "open-innovation-strategy"


def _providers():
    return importlib.import_module(f"{PKG}.providers")


# ---------------------------------------------------------------------------
# Tiny Pydantic schema used by the tests
# ---------------------------------------------------------------------------

class _TinySchema(BaseModel):
    """Stand-in for AgentAction / StrategicArtefact / etc. — keeps tests
    independent of the real role schemas, which carry heavy framework deps."""

    kind: str
    text: str | None = None


# ===========================================================================
# 1. classify_structured_output_mode
# ===========================================================================

class TestClassifyStructuredOutputMode:
    """Each provider must land in the right capability bucket. Native
    Gemini is always strict; LiteLLM-wrapped providers are classified
    by their model-ID prefix. The defaults bias toward "schema" so a
    new provider doesn't silently lose strict enforcement.
    """

    def test_native_gemini_pro_string_is_schema_mode(self):
        p = _providers()
        assert p.classify_structured_output_mode("gemini-2.5-pro") == "schema"

    def test_native_gemini_flash_string_is_schema_mode(self):
        p = _providers()
        assert p.classify_structured_output_mode("gemini-2.5-flash") == "schema"

    def test_claude_litellm_is_schema_mode(self, monkeypatch):
        p = _providers()
        spec = p.get_model("claude")
        assert p.classify_structured_output_mode(spec) == "schema"

    def test_openai_litellm_is_schema_mode(self, monkeypatch):
        p = _providers()
        spec = p.get_model("openai")
        assert p.classify_structured_output_mode(spec) == "schema"

    def test_groq_litellm_is_schema_mode(self, monkeypatch):
        p = _providers()
        spec = p.get_model("groq")
        assert p.classify_structured_output_mode(spec) == "schema"

    def test_deepseek_litellm_is_json_object_mode(self, monkeypatch):
        """The motivating case — DeepSeek rejects json_schema and only
        accepts the weaker json_object hint."""
        p = _providers()
        spec = p.get_model("deepseek")
        assert p.classify_structured_output_mode(spec) == "json_object"

    def test_ollama_litellm_is_json_object_mode(self, monkeypatch):
        """Ollama-served models vary in structured-output support;
        defaulting to json_object keeps the framework safe by default."""
        p = _providers()
        spec = p.get_model("ollama")
        assert p.classify_structured_output_mode(spec) == "json_object"

    def test_unknown_litellm_prefix_defaults_to_schema(self):
        """A novel LiteLLM prefix should be treated as strict-capable
        until we explicitly observe and add it to the json_object set —
        biases toward strict enforcement rather than silent weakening."""
        p = _providers()

        # Stub LiteLlm-like object with an unknown prefix.
        class _Spec:
            model = "novelvendor/some-future-model"
        assert p.classify_structured_output_mode(_Spec()) == "schema"

    def test_empty_or_missing_model_attribute_defaults_to_schema(self):
        p = _providers()

        class _Spec:
            model = ""
        assert p.classify_structured_output_mode(_Spec()) == "schema"


# ===========================================================================
# 2. build_structured_agent — schema mode
# ===========================================================================

class TestBuildStructuredAgentSchemaMode:
    """In schema mode the adapter must behave like a direct
    `LlmAgent(...)` construction: same instruction, same model,
    `output_schema` set on the agent so ADK enforces server-side.
    """

    def test_schema_mode_preserves_output_schema(self):
        p = _providers()
        agent = p.build_structured_agent(
            name="X",
            model="gemini-2.5-pro",
            instruction="do the thing",
            description="desc",
            output_schema=_TinySchema,
        )
        assert getattr(agent, "output_schema") is _TinySchema

    def test_schema_mode_does_not_modify_instruction(self):
        p = _providers()
        agent = p.build_structured_agent(
            name="X",
            model="gemini-2.5-pro",
            instruction="do the thing",
            description="desc",
            output_schema=_TinySchema,
        )
        assert getattr(agent, "instruction") == "do the thing"

    def test_schema_mode_passes_native_string_model_through(self):
        p = _providers()
        agent = p.build_structured_agent(
            name="X",
            model="gemini-2.5-pro",
            instruction="do the thing",
            description="desc",
            output_schema=_TinySchema,
        )
        assert getattr(agent, "model") == "gemini-2.5-pro"

    def test_schema_mode_preserves_litellm_model_unchanged(self, monkeypatch):
        """Claude/OpenAI/Groq → schema mode → adapter must NOT clone or
        rewrap the LiteLlm; the same instance flows through."""
        p = _providers()
        spec = p.get_model("claude")
        agent = p.build_structured_agent(
            name="X",
            model=spec,
            instruction="i",
            description="d",
            output_schema=_TinySchema,
        )
        assert getattr(agent, "model") is spec


# ===========================================================================
# 3. build_structured_agent — json_object mode
# ===========================================================================

class TestBuildStructuredAgentJsonObjectMode:
    """The DeepSeek/Ollama path: no `output_schema` on the agent, the
    instruction carries the schema as text, and the LiteLlm wrapper
    gets `response_format={"type":"json_object"}` so the provider
    still commits to returning a JSON object.
    """

    def test_json_object_mode_drops_output_schema(self, monkeypatch):
        """If `output_schema` reached the LlmAgent in json_object mode,
        ADK would inject the strict json_schema response_format and
        DeepSeek would 400 — the whole point of the adapter."""
        p = _providers()
        spec = p.get_model("deepseek")
        agent = p.build_structured_agent(
            name="X",
            model=spec,
            instruction="do the thing",
            description="desc",
            output_schema=_TinySchema,
        )
        assert getattr(agent, "output_schema", None) is None

    def test_json_object_mode_suffixes_instruction_with_schema(self, monkeypatch):
        p = _providers()
        spec = p.get_model("deepseek")
        agent = p.build_structured_agent(
            name="X",
            model=spec,
            instruction="do the thing",
            description="desc",
            output_schema=_TinySchema,
        )
        instruction = getattr(agent, "instruction", "")
        # The original instruction is preserved at the top.
        assert instruction.startswith("do the thing")
        # The schema-suffix block is appended.
        assert "OUTPUT FORMAT" in instruction
        assert "_TinySchema" in instruction
        # The actual JSON Schema is rendered verbatim.
        schema_dict = _TinySchema.model_json_schema()
        for key in schema_dict.keys():
            assert key in instruction

    def test_json_object_mode_sets_response_format_on_litellm(self, monkeypatch):
        """Cloned LiteLlm wrapper carries the kwarg so litellm.completion
        sends `response_format={"type":"json_object"}` to DeepSeek
        instead of the strict json_schema form."""
        p = _providers()
        spec = p.get_model("deepseek")
        agent = p.build_structured_agent(
            name="X",
            model=spec,
            instruction="i",
            description="d",
            output_schema=_TinySchema,
        )
        new_model = getattr(agent, "model")
        # New wrapper, not the original.
        assert new_model is not spec
        # Same model ID.
        assert getattr(new_model, "model") == getattr(spec, "model")
        # response_format is the weaker json_object form.
        assert p._litellm_setting(new_model, "response_format") == {"type": "json_object"}

    def test_json_object_mode_preserves_api_base_for_ollama(self, monkeypatch):
        """Ollama requires `api_base` on the LiteLlm wrapper — the
        clone must keep it or every request goes to the wrong endpoint."""
        p = _providers()
        spec = p.get_model("ollama")
        original_base = p._litellm_setting(spec, "api_base")
        assert original_base, "test precondition: Ollama spec must have api_base"
        agent = p.build_structured_agent(
            name="X",
            model=spec,
            instruction="i",
            description="d",
            output_schema=_TinySchema,
        )
        new_model = getattr(agent, "model")
        assert p._litellm_setting(new_model, "api_base") == original_base

    def test_json_object_mode_does_not_mutate_original_wrapper(self, monkeypatch):
        """Clone-not-mutate: other phases that share the same model
        spec must not see a stray response_format leak through."""
        p = _providers()
        spec = p.get_model("deepseek")
        had_response_format_before = hasattr(spec, "response_format")
        p.build_structured_agent(
            name="X",
            model=spec,
            instruction="i",
            description="d",
            output_schema=_TinySchema,
        )
        # The original wrapper must still NOT have response_format
        # (unless it already did — in which case it must be unchanged).
        assert hasattr(spec, "response_format") == had_response_format_before


# ===========================================================================
# 4. Integration with real role-agent factories
# ===========================================================================

class TestRoleFactoriesRouteThroughAdapter:
    """Sanity check that the five rewired call sites land in the right
    mode end-to-end. Uses the actual factory functions, not the
    adapter directly, so a regression where someone re-introduces a
    bare LlmAgent(output_schema=...) gets caught.
    """

    def test_concurrent_role_agent_deepseek_lands_in_json_object_mode(
        self, monkeypatch
    ):
        """The motivating bug: cell_5 (TMT_PROVIDER=deepseek) used to
        send strict json_schema to DeepSeek via output_schema=AgentAction.
        Confirm the wrapper now omits output_schema for that provider."""
        monkeypatch.setenv("TMT_PROVIDER", "deepseek")
        for role in ("CEO", "CTO", "COO", "CMO",
                     "Product_Strategist", "Product_Designer"):
            monkeypatch.delenv(f"TMT_PROVIDER_{role.upper()}", raising=False)
        cm = importlib.import_module(f"{PKG}.orchestrator.concurrent_mode")
        p = _providers()

        # Build a minimal base agent the wrapper can read .model + .instruction from.
        class _BaseAgent:
            instruction = "base instructions"
            model = p.get_role_model("CEO")

        wrapped = cm._build_concurrent_role_agent(_BaseAgent(), "CEO")
        assert getattr(wrapped, "output_schema", None) is None
        # Schema text appears in instruction (json_object-mode signature).
        assert "OUTPUT FORMAT" in getattr(wrapped, "instruction", "")

    def test_concurrent_role_agent_gemini_keeps_strict_schema(self, monkeypatch):
        """Schema-mode providers must keep output_schema=AgentAction so
        ADK enforces server-side as before. Adapter must not silently
        weaken any provider that doesn't need it."""
        monkeypatch.setenv("TMT_PROVIDER", "gemini_pro")
        for role in ("CEO", "CTO", "COO", "CMO",
                     "Product_Strategist", "Product_Designer"):
            monkeypatch.delenv(f"TMT_PROVIDER_{role.upper()}", raising=False)
        cm = importlib.import_module(f"{PKG}.orchestrator.concurrent_mode")
        p = _providers()

        class _BaseAgent:
            instruction = "base instructions"
            model = p.get_role_model("CEO")

        wrapped = cm._build_concurrent_role_agent(_BaseAgent(), "CEO")
        assert getattr(wrapped, "output_schema") is cm.AgentAction
