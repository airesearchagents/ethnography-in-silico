"""Tests for the provenance manifest, per-role LLM override,
compare-runs helper, and the redaction guard.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

PKG = "open-innovation-strategy"


def _providers():
    return importlib.import_module(f"{PKG}.providers")


def _replication():
    return importlib.import_module(f"{PKG}.analysis.replication_package")


def _compare():
    return importlib.import_module(f"{PKG}.analysis.compare_runs")


def _agent_module():
    return importlib.import_module(f"{PKG}.agent")


# ===========================================================================
# 1. Per-role provider resolution
# ===========================================================================

class TestPerRoleProviderResolution:
    """`TMT_PROVIDER_<ROLE>` overrides `TMT_PROVIDER` for that role.
    Default is uniform team; per-role flags enable heterogeneous teams
    for ablation studies.
    """

    def test_default_all_roles_use_team_wide_provider(self, monkeypatch):
        monkeypatch.delenv("TMT_PROVIDER", raising=False)
        for role in ("CEO", "CTO", "COO", "CMO", "Product_Strategist", "Product_Designer"):
            monkeypatch.delenv(f"TMT_PROVIDER_{role.upper()}", raising=False)
        p = _providers()
        snapshot = p.snapshot_role_providers()
        # All roles → same default (`gemini_pro`).
        assert len(set(snapshot.values())) == 1
        assert snapshot["CEO"] == "gemini_pro"

    def test_team_wide_provider_changes_all_roles(self, monkeypatch):
        monkeypatch.setenv("TMT_PROVIDER", "claude")
        for role in ("CEO", "CTO", "COO", "CMO", "Product_Strategist", "Product_Designer"):
            monkeypatch.delenv(f"TMT_PROVIDER_{role.upper()}", raising=False)
        p = _providers()
        snapshot = p.snapshot_role_providers()
        assert all(v == "claude" for v in snapshot.values()), snapshot

    def test_per_role_override_wins(self, monkeypatch):
        monkeypatch.setenv("TMT_PROVIDER", "gemini_pro")
        monkeypatch.setenv("TMT_PROVIDER_CTO", "claude")
        monkeypatch.setenv("TMT_PROVIDER_CMO", "openai")
        p = _providers()
        snapshot = p.snapshot_role_providers()
        assert snapshot["CTO"] == "claude"
        assert snapshot["CMO"] == "openai"
        # Others still use team-wide default.
        assert snapshot["CEO"] == "gemini_pro"

    def test_get_role_model_returns_string_for_gemini(self, monkeypatch):
        monkeypatch.setenv("TMT_PROVIDER", "gemini_flash")
        for role in ("CEO", "CTO", "COO", "CMO", "Product_Strategist", "Product_Designer"):
            monkeypatch.delenv(f"TMT_PROVIDER_{role.upper()}", raising=False)
        p = _providers()
        spec = p.get_role_model("CEO")
        assert isinstance(spec, str)
        # The default Gemini Flash ID.
        assert "flash" in spec.lower()

    def test_snapshot_role_model_ids_returns_strings(self, monkeypatch):
        monkeypatch.setenv("TMT_PROVIDER", "gemini_pro")
        for role in ("CEO", "CTO", "COO", "CMO", "Product_Strategist", "Product_Designer"):
            monkeypatch.delenv(f"TMT_PROVIDER_{role.upper()}", raising=False)
        p = _providers()
        ids = p.snapshot_role_model_ids()
        assert all(isinstance(v, str) for v in ids.values())
        # All Gemini Pro → all the same string.
        assert len(set(ids.values())) == 1


# ===========================================================================
# 1b. Low-cost provider support (DeepSeek, Groq)
# ===========================================================================

class TestLowCostProviders:
    """DeepSeek and Groq are routed through ADK's LiteLlm wrapper, the
    same machinery that already serves Claude and OpenAI. The tests
    below pin the contract: the provider keys resolve, the LiteLlm
    model ID matches the env var or default, and per-role overrides
    work the same way they do for premium providers.
    """

    def test_deepseek_provider_resolves_via_litellm(self, monkeypatch):
        monkeypatch.delenv("TMT_DEEPSEEK_MODEL", raising=False)
        p = _providers()
        spec = p.get_model("deepseek")
        # LiteLlm wrapper, not a bare string (unlike Gemini).
        assert not isinstance(spec, str)
        # The default model ID propagated to the wrapper. The default
        # tracks `providers._DEFAULTS`; this test sources truth there
        # so a model-ID bump doesn't require a test-string edit.
        assert getattr(spec, "model", "") == p._DEFAULTS["deepseek"]

    def test_groq_provider_resolves_via_litellm(self, monkeypatch):
        monkeypatch.delenv("TMT_GROQ_MODEL", raising=False)
        p = _providers()
        spec = p.get_model("groq")
        assert not isinstance(spec, str)
        assert getattr(spec, "model", "") == p._DEFAULTS["groq"]

    def test_deepseek_env_var_override(self, monkeypatch):
        monkeypatch.setenv("TMT_DEEPSEEK_MODEL", "deepseek/deepseek-reasoner")
        p = _providers()
        spec = p.get_model("deepseek")
        assert getattr(spec, "model", "") == "deepseek/deepseek-reasoner"

    def test_groq_env_var_override(self, monkeypatch):
        monkeypatch.setenv("TMT_GROQ_MODEL", "groq/mixtral-8x7b-32768")
        p = _providers()
        spec = p.get_model("groq")
        assert getattr(spec, "model", "") == "groq/mixtral-8x7b-32768"

    def test_team_wide_deepseek_reaches_all_roles(self, monkeypatch):
        monkeypatch.setenv("TMT_PROVIDER", "deepseek")
        for role in ("CEO", "CTO", "COO", "CMO",
                     "Product_Strategist", "Product_Designer"):
            monkeypatch.delenv(f"TMT_PROVIDER_{role.upper()}", raising=False)
        p = _providers()
        snapshot = p.snapshot_role_providers()
        assert all(v == "deepseek" for v in snapshot.values()), snapshot

    def test_per_role_groq_override(self, monkeypatch):
        monkeypatch.setenv("TMT_PROVIDER", "gemini_pro")
        monkeypatch.setenv("TMT_PROVIDER_CMO", "groq")
        p = _providers()
        snapshot = p.snapshot_role_providers()
        assert snapshot["CMO"] == "groq"
        assert snapshot["CEO"] == "gemini_pro"

    def test_unknown_provider_error_message_lists_new_providers(self):
        p = _providers()
        with pytest.raises(ValueError) as exc:
            p.get_model("not_a_real_provider")
        msg = str(exc.value)
        # The error advertises every supported provider so callers
        # discover the new options without reading the source.
        for key in ("gemini_pro", "claude", "openai",
                    "deepseek", "groq", "ollama"):
            assert key in msg


# ===========================================================================
# 1.5. Judge-model resolution honours JUDGE_MODEL_OVERRIDES + env var
# ===========================================================================

class TestGetJudgeModel:
    """`providers.get_judge_model(provider)` resolves the model for a
    construct-judge agent. May differ from the TMT-side `get_model`
    when `JUDGE_MODEL_OVERRIDES` or `TMT_JUDGE_<PROVIDER>_MODEL`
    asks for one.

    Methodological background: the construct-validity ensemble (the
    α statistic) is methodologically weight-bearing — worth running
    on the premium tier even when TMT-side prompts run on the
    cost-quality midpoint. The OpenAI judge in particular runs on
    GPT-5.5 while the OpenAI TMT-side uses GPT-5.4.
    """

    def test_falls_back_to_get_model_when_no_override(self, monkeypatch):
        """For providers with no JUDGE_MODEL_OVERRIDES entry, the judge
        model matches the team-wide `get_model(provider)`."""
        monkeypatch.delenv("TMT_JUDGE_CLAUDE_MODEL", raising=False)
        p = _providers()
        team_spec = p.get_model("claude")
        judge_spec = p.get_judge_model("claude")
        # Both are LiteLlm-wrapped; compare the inner model ID.
        assert getattr(judge_spec, "model", "") == getattr(team_spec, "model", "")

    def test_openai_default_override_lifts_to_gpt55_pro(self, monkeypatch):
        """The framework ships with an OpenAI judge override:
        Both judge and TMT side currently resolve to GPT-5.4 — the
        judge USED to run on GPT-5.5-pro (Responses API), but that
        hit a server-side 3-min cap on long prompts (DECISIONS §32),
        so the judge moved to gpt-5.4 (Chat Completions) too. The
        override mechanism still works — kept for the case where an
        operator wants to pin a specific judge model at run time."""
        monkeypatch.delenv("TMT_JUDGE_OPENAI_MODEL", raising=False)
        p = _providers()
        judge_spec = p.get_judge_model("openai")
        team_spec = p.get_model("openai")
        # Both resolve to GPT-5.4 (judge via the override dict, team
        # via the defaults). They happen to be the same model now,
        # but they go through different resolution paths.
        assert getattr(judge_spec, "model", "") == "openai/gpt-5.4"
        assert getattr(team_spec, "model", "") == "openai/gpt-5.4"

    def test_env_var_override_beats_judge_overrides_dict(self, monkeypatch):
        """`TMT_JUDGE_<PROVIDER>_MODEL` takes precedence over
        `JUDGE_MODEL_OVERRIDES`, letting an operator pin a specific
        run's judge to a non-default model (e.g. an experiment, a
        cost-controlled run, or a candidate model)."""
        monkeypatch.setenv("TMT_JUDGE_OPENAI_MODEL", "openai/gpt-5.4-pro")
        p = _providers()
        spec = p.get_judge_model("openai")
        assert getattr(spec, "model", "") == "openai/gpt-5.4-pro"

    def test_env_var_override_works_for_no_default_override_providers(
        self, monkeypatch,
    ):
        """Even providers with no JUDGE_MODEL_OVERRIDES entry honour
        the env-var override (e.g. for an ablation that swaps the
        Claude judge to a different Anthropic model)."""
        monkeypatch.setenv("TMT_JUDGE_CLAUDE_MODEL", "anthropic/claude-sonnet-4-6")
        p = _providers()
        spec = p.get_judge_model("claude")
        assert getattr(spec, "model", "") == "anthropic/claude-sonnet-4-6"

    def test_env_var_override_for_native_gemini_returns_string(self, monkeypatch):
        """Native-Gemini judges return a model-ID string (no LiteLlm
        wrapper), the same routing as the team-wide `get_model`."""
        monkeypatch.setenv("TMT_JUDGE_GEMINI_PRO_MODEL", "gemini-2.5-pro")
        p = _providers()
        spec = p.get_judge_model("gemini_pro")
        assert spec == "gemini-2.5-pro"

    def test_get_judge_models_returns_full_ensemble(self, monkeypatch):
        """The plural `get_judge_models()` returns one entry per
        provider in `JUDGE_PROVIDERS`, each resolved via
        `get_judge_model`."""
        monkeypatch.delenv("TMT_JUDGE_GEMINI_PRO_MODEL", raising=False)
        monkeypatch.delenv("TMT_JUDGE_CLAUDE_MODEL", raising=False)
        monkeypatch.delenv("TMT_JUDGE_OPENAI_MODEL", raising=False)
        p = _providers()
        ensemble = p.get_judge_models()
        assert set(ensemble.keys()) == set(p.JUDGE_PROVIDERS)
        # OpenAI judge is GPT-5.4 (Chat Completions) — see DECISIONS §32
        # for why the override exists despite matching `_DEFAULTS`.
        assert getattr(ensemble["openai"], "model", "") == "openai/gpt-5.4"


# ===========================================================================
# 2. Role factories now use providers.get_role_model
# ===========================================================================

class TestRoleFactoriesUseProvidersGetRoleModel:
    """Each role factory looks up its model via providers.get_role_model,
    not via a hardcoded model ID. This is what makes the team-wide
    `TMT_PROVIDER` env var and per-role overrides actually reach the
    constructed agents.
    """

    def test_changing_env_changes_constructed_agent_model(self, monkeypatch):
        monkeypatch.setenv("TMT_PROVIDER", "gemini_flash")
        for role in ("CEO", "CTO", "COO", "CMO", "Product_Strategist", "Product_Designer"):
            monkeypatch.delenv(f"TMT_PROVIDER_{role.upper()}", raising=False)
        # Re-import roles to pick up the env at agent construction time.
        roles = importlib.import_module(f"{PKG}.roles")
        ceo = roles.create_ceo_agent("OpenAI")
        # On the stub LlmAgent, .model is whatever providers returned.
        assert isinstance(ceo.model, str)
        assert "flash" in ceo.model.lower()
        # Old hardcoding is gone:
        assert ceo.model != "gemini-2.0-flash" or "flash" in ceo.model.lower()

    def test_per_role_override_reaches_role_factory(self, monkeypatch):
        monkeypatch.setenv("TMT_PROVIDER", "gemini_flash")
        # Override CTO only.
        monkeypatch.setenv("TMT_PROVIDER_CTO", "gemini_pro")
        for role in ("CEO", "COO", "CMO", "Product_Strategist", "Product_Designer"):
            monkeypatch.delenv(f"TMT_PROVIDER_{role.upper()}", raising=False)
        roles = importlib.import_module(f"{PKG}.roles")
        ceo = roles.create_ceo_agent("OpenAI")
        cto = roles.create_cto_agent("OpenAI")
        # CEO uses Flash, CTO uses Pro.
        assert "flash" in ceo.model.lower()
        assert "pro" in cto.model.lower()
        assert ceo.model != cto.model


# ===========================================================================
# 3. Redaction
# ===========================================================================

class TestRedactEnv:
    def test_redacts_anything_with_key_in_name(self):
        r = _replication()
        out = r.redact_env({
            "GOOGLE_API_KEY": "AIzaSy_real_key_abcdefg",
            "ANTHROPIC_API_KEY": "sk-ant-foo",
            "OPENAI_API_KEY": "sk-foo",
        })
        for v in out.values():
            assert v == "<redacted>"

    def test_redacts_token_secret_password_credential_auth(self):
        r = _replication()
        out = r.redact_env({
            "MY_TOKEN": "abc",
            "DB_PASSWORD": "abc",
            "AWS_SECRET_ACCESS_KEY": "abc",
            "OAUTH_CREDENTIAL": "abc",
            "AUTHORIZATION": "Bearer abc",
        })
        for v in out.values():
            assert v == "<redacted>"

    def test_preserves_non_sensitive_values(self):
        r = _replication()
        out = r.redact_env({
            "TMT_PROVIDER": "gemini_pro",
            "TMT_GEMINI_PRO_MODEL": "gemini-2.5-pro",
            "PYTHONPATH": "/some/path",
        })
        assert out["TMT_PROVIDER"] == "gemini_pro"
        assert out["TMT_GEMINI_PRO_MODEL"] == "gemini-2.5-pro"
        assert out["PYTHONPATH"] == "/some/path"

    def test_case_insensitive(self):
        r = _replication()
        out = r.redact_env({"google_api_key": "abc"})
        assert out["google_api_key"] == "<redacted>"


class TestSnapshotEnv:
    def test_snapshot_env_includes_api_keys_redacted(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "AIzaSyXXXXXX")
        monkeypatch.setenv("TMT_PROVIDER", "gemini_pro")
        r = _replication()
        snap = r.snapshot_env()
        # API key is captured but redacted.
        assert snap.get("GOOGLE_API_KEY") == "<redacted>"
        # TMT_PROVIDER is preserved verbatim.
        assert snap.get("TMT_PROVIDER") == "gemini_pro"

    def test_snapshot_env_ignores_unrelated_envvars(self, monkeypatch):
        monkeypatch.setenv("UNRELATED_FOO", "bar")
        monkeypatch.setenv("TMT_PROVIDER", "gemini_pro")
        r = _replication()
        snap = r.snapshot_env()
        assert "UNRELATED_FOO" not in snap
        assert "TMT_PROVIDER" in snap


# ===========================================================================
# 4. Build + capture manifest
# ===========================================================================

class TestBuildManifest:
    def test_minimal_build(self):
        r = _replication()
        m = r.build_replication_manifest(
            run_id="t",
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            launch_year=2030,
            started_at="2030-01-01T00:00:00",
            include_git=False,
            include_env=False,
        )
        assert m.run_id == "t"
        assert m.launch_year == 2030
        assert m.models_used == {}
        assert m.git_provenance == {}

    def test_default_models_snapshot_captured_at_build_time(self):
        """The manifest snapshots `providers._DEFAULTS` plus the
        judge-side overrides. Distinct from `models_used`: this dict
        records what the framework's defaults WERE at the run's
        commit_sha — useful for reading old manifests."""
        r = _replication()
        p = _providers()
        m = r.build_replication_manifest(
            run_id="t", company="OpenAI",
            industry_context="Dynamic", product_type="Novel",
            launch_year=2030, started_at="2030-01-01T00:00:00",
            include_git=False, include_env=False,
        )
        # Default-models snapshot has one entry per provider key.
        for prov in ("gemini_pro", "gemini_flash", "claude", "openai",
                     "deepseek", "groq", "ollama"):
            assert prov in m.default_models, (
                f"default_models missing provider {prov}"
            )
            assert m.default_models[prov] == p._DEFAULTS[prov]
        # Judge-side overrides surface under `judge_<provider>` keys.
        # OpenAI judge moved from gpt-5.5-pro to gpt-5.4 (DECISIONS §32).
        assert m.default_models["judge_openai"] == "openai/gpt-5.4"

    def test_default_models_can_be_passed_in(self):
        """Caller can pass an explicit `default_models` dict to override
        the auto-snapshot. Useful when rebuilding a manifest from a
        historical run whose snapshot needs preserving."""
        r = _replication()
        custom = {"gemini_pro": "gemini-2.0-pro", "claude": "anthropic/claude-3.5-sonnet"}
        m = r.build_replication_manifest(
            run_id="t", company="X",
            industry_context="Dynamic", product_type="Novel",
            launch_year=2030, started_at="2030-01-01T00:00:00",
            default_models=custom,
            include_git=False, include_env=False,
        )
        # The passed-in dict overrides the auto-snapshot.
        assert m.default_models == custom

    def test_default_models_json_round_trip(self):
        """The new field round-trips via Pydantic JSON serialisation."""
        r = _replication()
        m = r.build_replication_manifest(
            run_id="t", company="X",
            industry_context="Dynamic", product_type="Novel",
            launch_year=2030, started_at="2030-01-01T00:00:00",
            include_git=False, include_env=False,
        )
        json_blob = m.model_dump_json()
        m2 = r.ReplicationManifest.model_validate_json(json_blob)
        assert m2.default_models == m.default_models

    def test_capture_from_system_records_six_roles_models_and_prompts(
        self, monkeypatch,
    ):
        monkeypatch.setenv("TMT_PROVIDER", "gemini_flash")
        for role in ("CEO", "CTO", "COO", "CMO", "Product_Strategist", "Product_Designer"):
            monkeypatch.delenv(f"TMT_PROVIDER_{role.upper()}", raising=False)
        a = _agent_module()
        r = _replication()
        system = a.TMTSystemWithA2A("OpenAI")
        m = r.capture_from_system(
            system,
            run_id="test_capture",
            started_at="2030-01-01T00:00:00",
        )
        # Every role's model AND prompt are captured.
        for role in ("CEO", "CTO", "COO", "CMO",
                     "Product_Strategist", "Product_Designer"):
            assert role in m.models_used, f"missing model for {role}"
            assert m.models_used[role], f"empty model for {role}"
            assert role in m.providers_used
            assert role in m.prompts_used
            assert m.prompts_used[role], f"empty prompt for {role}"

    def test_capture_from_system_with_extra_agents(self, monkeypatch):
        monkeypatch.setenv("TMT_PROVIDER", "gemini_pro")
        a = _agent_module()
        r = _replication()
        system = a.TMTSystemWithA2A("OpenAI")

        # Build a fake "observer" agent (just uses the stub LlmAgent).
        from google.adk.agents import LlmAgent
        observer = LlmAgent(name="observer", model="gemini-2.5-pro",
                            instruction="observer prompt")

        m = r.capture_from_system(
            system,
            run_id="x",
            started_at="2030-01-01T00:00:00",
            extra_agents={"observer": observer},
        )
        assert "observer" in m.models_used
        assert m.models_used["observer"] == "gemini-2.5-pro"
        assert m.prompts_used["observer"] == "observer prompt"


# ===========================================================================
# 5. write_manifest produces a file
# ===========================================================================

class TestWriteManifest:
    def test_writes_manifest_json_to_dir(self, tmp_path: Path):
        r = _replication()
        m = r.build_replication_manifest(
            run_id="abc",
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            launch_year=2030,
            started_at="2030-01-01T00:00:00",
            include_git=False,
            include_env=False,
        )
        p = r.write_manifest(m, tmp_path / "out")
        assert p.is_file()
        loaded = json.loads(p.read_text())
        assert loaded["run_id"] == "abc"
        assert loaded["schema_version"] == "1"


# ===========================================================================
# 6. compare_runs: report renders without crashing
# ===========================================================================

class TestCompareRuns:
    def test_load_run_handles_missing_files(self, tmp_path: Path):
        c = _compare()
        empty_run = tmp_path / "empty_run"
        empty_run.mkdir()
        loaded = c.load_run(empty_run)
        assert loaded["manifest"] is None
        assert loaded["meta"] is None
        assert loaded["artefacts"] == {}

    def test_render_report_with_two_minimal_runs(self, tmp_path: Path):
        c = _compare()
        r = _replication()

        # Build two run folders, each with just a manifest.
        for slug, provider in (("run_a", "gemini_pro"), ("run_b", "claude")):
            run_dir = tmp_path / slug
            run_dir.mkdir()
            m = r.build_replication_manifest(
                run_id=slug,
                company="OpenAI",
                industry_context="Dynamic",
                product_type="Novel",
                launch_year=2030,
                started_at="2030-01-01T00:00:00",
                models_used={"CEO": f"{provider}-model"},
                providers_used={"CEO": provider},
                include_git=False, include_env=False,
            )
            r.write_manifest(m, run_dir)

        report = c.render_report([tmp_path / "run_a", tmp_path / "run_b"])
        # Headline: 2 runs compared.
        assert "Run comparison (2 runs)" in report
        # Models per role section present + both providers visible.
        assert "Models per role" in report
        assert "gemini_pro" in report
        assert "claude" in report

    def test_render_report_with_three_runs_three_columns(self, tmp_path: Path):
        c = _compare()
        r = _replication()
        for slug in ("run_a", "run_b", "run_c"):
            run_dir = tmp_path / slug
            run_dir.mkdir()
            m = r.build_replication_manifest(
                run_id=slug, company="OpenAI",
                industry_context="Dynamic", product_type="Novel",
                launch_year=2030, started_at="2030-01-01T00:00:00",
                include_git=False, include_env=False,
            )
            r.write_manifest(m, run_dir)
        report = c.render_report([
            tmp_path / "run_a", tmp_path / "run_b", tmp_path / "run_c",
        ])
        assert "Run comparison (3 runs)" in report
