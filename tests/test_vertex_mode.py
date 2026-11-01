"""Tests for the Vertex AI mode helpers in `providers.py`.

The framework supports two Gemini routings:

  AI Studio (default)     uses GOOGLE_API_KEY directly.
  Vertex AI (--vertex)    uses Application Default Credentials with
                          GOOGLE_GENAI_USE_VERTEXAI=true plus
                          GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_LOCATION.

The Gemini SDK auto-detects which one to use from the env vars; the
framework's job is to (a) flip the flag cleanly via `enable_vertex`,
(b) validate that project + location are set before the LLM call goes
out, and (c) capture the active mode in the replication manifest.

These tests cover all three responsibilities. They monkeypatch
`os.environ` so each test is hermetic.
"""

from __future__ import annotations

import importlib

import pytest

PKG = "open-innovation-strategy"


def _providers():
    return importlib.import_module(f"{PKG}.providers")


# ===========================================================================
# 1. is_using_vertex — truthy-value parsing
# ===========================================================================

class TestIsUsingVertex:
    """Read-only check that respects the truthy-value list the SDK uses."""

    @pytest.mark.parametrize("val", ["1", "true", "True", "TRUE", "yes", "on"])
    def test_truthy_values_enable_vertex(self, monkeypatch, val):
        monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", val)
        p = _providers()
        assert p.is_using_vertex() is True

    @pytest.mark.parametrize("val", ["0", "false", "False", "no", "off", ""])
    def test_falsy_values_disable_vertex(self, monkeypatch, val):
        monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", val)
        p = _providers()
        assert p.is_using_vertex() is False

    def test_unset_is_falsy(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
        p = _providers()
        assert p.is_using_vertex() is False

    def test_whitespace_is_stripped(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "  true  ")
        p = _providers()
        assert p.is_using_vertex() is True


# ===========================================================================
# 2. get_vertex_project / get_vertex_location — env reads with None fallback
# ===========================================================================

class TestVertexConfigReaders:
    def test_project_returned_when_set(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-edu-project")
        p = _providers()
        assert p.get_vertex_project() == "my-edu-project"

    def test_project_is_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        p = _providers()
        assert p.get_vertex_project() is None

    def test_project_is_none_when_empty(self, monkeypatch):
        """Empty-string env var is treated the same as unset — the SDK
        won't accept it as a project ID and downstream code can rely on
        None as the single 'unset' sentinel."""
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "")
        p = _providers()
        assert p.get_vertex_project() is None

    def test_location_returned_when_set(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        p = _providers()
        assert p.get_vertex_location() == "us-central1"

    def test_location_is_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
        p = _providers()
        assert p.get_vertex_location() is None


# ===========================================================================
# 3. validate_vertex_config — fail-fast guard at startup
# ===========================================================================

class TestValidateVertexConfig:
    """Vertex mode without project or location is a misconfiguration
    that would otherwise blow up 30s into a Phase 1 LLM call. The
    validator catches it at startup with an actionable error."""

    def test_noop_when_vertex_disabled(self, monkeypatch):
        """Validation is irrelevant when the user is on AI Studio."""
        monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
        p = _providers()
        # No exception even with empty project/location.
        p.validate_vertex_config()

    def test_passes_when_all_three_vars_set(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-edu-project")
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        p = _providers()
        p.validate_vertex_config()  # must not raise

    def test_raises_when_vertex_on_but_project_missing(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        p = _providers()
        with pytest.raises(ValueError) as exc:
            p.validate_vertex_config()
        # The error must name the missing var so the user can fix it.
        assert "GOOGLE_CLOUD_PROJECT" in str(exc.value)

    def test_raises_when_vertex_on_but_location_missing(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-edu-project")
        monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
        p = _providers()
        with pytest.raises(ValueError) as exc:
            p.validate_vertex_config()
        assert "GOOGLE_CLOUD_LOCATION" in str(exc.value)

    def test_raises_when_both_missing_names_both(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
        p = _providers()
        with pytest.raises(ValueError) as exc:
            p.validate_vertex_config()
        msg = str(exc.value)
        assert "GOOGLE_CLOUD_PROJECT" in msg
        assert "GOOGLE_CLOUD_LOCATION" in msg

    def test_error_message_includes_remediation_hint(self, monkeypatch):
        """The user should not have to grep through docs to know what
        to do next — the error itself tells them."""
        monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
        p = _providers()
        with pytest.raises(ValueError) as exc:
            p.validate_vertex_config()
        msg = str(exc.value)
        # Names the gcloud command needed for auth.
        assert "application-default login" in msg


# ===========================================================================
# 4. enable_vertex — flip the flag + optionally set project/location
# ===========================================================================

class TestEnableVertex:
    """The convenience helper that sets all three env vars in one call."""

    def test_sets_flag_when_called(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        p = _providers()
        p.enable_vertex()
        assert p.is_using_vertex()

    def test_project_and_location_args_are_persisted(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
        p = _providers()
        p.enable_vertex(project="my-edu", location="europe-west4")
        assert p.get_vertex_project() == "my-edu"
        assert p.get_vertex_location() == "europe-west4"

    def test_args_omitted_uses_existing_env(self, monkeypatch):
        """Don't clobber an env var the user already set."""
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "existing-proj")
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "asia-northeast1")
        p = _providers()
        p.enable_vertex()  # no args
        assert p.get_vertex_project() == "existing-proj"
        assert p.get_vertex_location() == "asia-northeast1"

    def test_raises_when_no_project_anywhere(self, monkeypatch):
        """Calling enable_vertex without an arg AND without env vars is
        a misconfiguration — fail fast (via the validator at the end)."""
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
        p = _providers()
        with pytest.raises(ValueError):
            p.enable_vertex()

    def test_idempotent(self, monkeypatch):
        """Calling twice has no observable difference from calling once."""
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        p = _providers()
        p.enable_vertex()
        p.enable_vertex()  # must not raise
        assert p.is_using_vertex()


# ===========================================================================
# 5. snapshot_vertex_config — stable shape for the replication manifest
# ===========================================================================

class TestSnapshotVertexConfig:
    """The manifest writer reads this — its shape must be stable across
    modes so downstream code can assume the same keys are always there."""

    def test_shape_when_disabled(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
        p = _providers()
        snap = p.snapshot_vertex_config()
        assert snap == {
            "enabled": False,
            "project": None,
            "location": None,
        }

    def test_shape_when_enabled(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-edu-project")
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        p = _providers()
        snap = p.snapshot_vertex_config()
        assert snap == {
            "enabled": True,
            "project": "my-edu-project",
            "location": "us-central1",
        }

    def test_never_raises_even_in_misconfig(self, monkeypatch):
        """The manifest must be writable even when the run is mis-
        configured; the snapshot exists to document the misconfig, not
        to refuse to capture it."""
        monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
        p = _providers()
        snap = p.snapshot_vertex_config()
        # Reports the misconfig faithfully — vertex on, project/location None.
        assert snap == {
            "enabled": True,
            "project": None,
            "location": None,
        }


# ===========================================================================
# 6. Replication manifest captures vertex_config
# ===========================================================================

class TestReplicationManifestVertexConfig:
    """The manifest writer pulls Vertex config so a reviewer can see
    whether the run used AI Studio or Vertex AI."""

    def test_manifest_records_vertex_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
        r = importlib.import_module(f"{PKG}.analysis.replication_package")
        m = r.build_replication_manifest(
            run_id="t", company="OpenAI",
            industry_context="Dynamic", product_type="Novel",
            launch_year=2030, started_at="2030-01-01T00:00:00",
            include_git=False, include_env=False,
        )
        assert m.vertex_config == {
            "enabled": False, "project": None, "location": None,
        }

    def test_manifest_records_vertex_enabled(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-edu")
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        r = importlib.import_module(f"{PKG}.analysis.replication_package")
        m = r.build_replication_manifest(
            run_id="t", company="OpenAI",
            industry_context="Dynamic", product_type="Novel",
            launch_year=2030, started_at="2030-01-01T00:00:00",
            include_git=False, include_env=False,
        )
        assert m.vertex_config["enabled"] is True
        assert m.vertex_config["project"] == "my-edu"
        assert m.vertex_config["location"] == "us-central1"

    def test_caller_can_override_vertex_config(self, monkeypatch):
        """`vertex_config=...` kwarg wins over env autodetection."""
        monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
        r = importlib.import_module(f"{PKG}.analysis.replication_package")
        m = r.build_replication_manifest(
            run_id="t", company="OpenAI",
            industry_context="Dynamic", product_type="Novel",
            launch_year=2030, started_at="2030-01-01T00:00:00",
            vertex_config={"enabled": True, "project": "p", "location": "l"},
            include_git=False, include_env=False,
        )
        assert m.vertex_config == {"enabled": True, "project": "p", "location": "l"}


# ===========================================================================
# 7. snapshot_env preserves Vertex routing variables (unredacted)
# ===========================================================================

class TestVertexEnvCapturedInSnapshot:
    """`GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_PROJECT` and
    `GOOGLE_CLOUD_LOCATION` are NOT secrets — they describe routing,
    not credentials. The snapshot keeps them verbatim so a reviewer
    knows which mode produced the run."""

    def test_vertex_routing_vars_appear_unredacted(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-edu-project")
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        r = importlib.import_module(f"{PKG}.analysis.replication_package")
        snap = r.snapshot_env()
        assert snap.get("GOOGLE_GENAI_USE_VERTEXAI") == "true"
        assert snap.get("GOOGLE_CLOUD_PROJECT") == "my-edu-project"
        assert snap.get("GOOGLE_CLOUD_LOCATION") == "us-central1"

    def test_routing_vars_absent_when_unset(self, monkeypatch):
        for k in ("GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_CLOUD_PROJECT",
                  "GOOGLE_CLOUD_LOCATION"):
            monkeypatch.delenv(k, raising=False)
        r = importlib.import_module(f"{PKG}.analysis.replication_package")
        snap = r.snapshot_env()
        # Absence is preserved — we don't fabricate the keys.
        assert "GOOGLE_GENAI_USE_VERTEXAI" not in snap
        assert "GOOGLE_CLOUD_PROJECT" not in snap
        assert "GOOGLE_CLOUD_LOCATION" not in snap
