"""Unit tests for the qualitative researcher agent (Phase 1 + Phase 2).

Coverage:
- The protocol YAML loads cleanly and exposes the expected sections.
- Forbidden-vocabulary checker flags violations, handles word
  boundaries, and permits panelist echoes.
- ObservationSummary / PanelUtterance schemas round-trip via Pydantic.
- The observer factory returns an agent pinned to the observer model
  with `output_schema=ObservationSummary`.
- The debriefer factory embeds the observation summary into the
  instruction and uses `output_schema=PanelUtterance`.
- `utterance_violates_protocol` enforces (a) forbidden vocab and
  (b) non-empty anchor_refs.

Like `test_agent_creation.py`, this file imports production code via
`importlib.import_module(f"{PKG}.…")` because the on-disk package name
contains a hyphen.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

PKG = "open-innovation-strategy"


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _researcher_module():
    return importlib.import_module(f"{PKG}.roles.qualitative_researcher_agent")


def _schemas_module():
    return importlib.import_module(f"{PKG}.roles.researcher_schemas")


def _vocab_module():
    return importlib.import_module(f"{PKG}.roles.forbidden_vocab")


def _roles_package():
    return importlib.import_module(f"{PKG}.roles")


def _make_summary():
    """Construct a small but representative ObservationSummary."""
    s = _schemas_module()
    return s.ObservationSummary(
        decisions=["keep the inference API internal"],
        components=["inference API", "fine-tuning recipe"],
        disagreements=[
            s.Disagreement(
                topic="whether to release the fine-tuning recipe",
                parties=["CTO", "CMO"],
                resolution="settled on internal-only for v1",
            )
        ],
        role_contributions=[
            s.RoleContribution(role="CTO", pushed_for=["internal inference"]),
            s.RoleContribution(role="CMO", pushed_back_on=["internal inference"]),
        ],
        alternatives_considered=["partner-only release"],
        loaded_vocabulary_used=[
            s.LoadedVocabUse(
                word="strategic",
                role="CMO",
                context="said 'this is a strategic moment for us'",
            )
        ],
    )


# ---------------------------------------------------------------------------
# 1. Protocol YAML loads with the expected sections
# ---------------------------------------------------------------------------

class TestProtocolYaml:
    def test_yaml_file_exists(self):
        worktree = Path(__file__).resolve().parent.parent
        yaml_path = worktree / "protocols" / "ethnographic_protocol.yaml"
        assert yaml_path.is_file(), f"Missing protocol YAML at {yaml_path}"

    def test_yaml_has_required_sections(self):
        researcher = _researcher_module()
        protocol = researcher._load_protocol()
        for key in (
            "stance",
            "behavioural_rules",
            "thematic_areas",
            "panel_format",
        ):
            assert key in protocol, f"Protocol YAML missing key: {key}"
        # The forbidden-vocab list moved to `methodological_forbidden_
        # vocabulary` in the multi-study refactor (the construct-
        # specific subset lives in the study config).
        assert "methodological_forbidden_vocabulary" in protocol

    def test_framework_yaml_has_generic_areas(self):
        """The framework-level YAML carries the 5 generic areas
        (A, B, C, I, J). Study-specific construct areas (D-H for the
        openness study) live in the per-study debriefing_overlay.yaml
        and get merged in via `_apply_study_overlay` at run time."""
        researcher = _researcher_module()
        protocol = researcher._load_protocol()
        areas = protocol["thematic_areas"]
        ids = [a["id"] for a in areas]
        assert ids == ["A", "B", "C", "I", "J"], (
            f"Framework YAML should carry generic areas A/B/C/I/J; got {ids}. "
            f"Construct-specific D-H must live in a study's overlay."
        )
        for a in areas:
            assert a.get("stems"), f"Area {a['id']} has no stems"

    def test_closing_area_marked_always_ask(self):
        """The closing area (always_ask: true) is now Area J — moved
        from Area F when the area-letter remap made room for openness-
        specific D-H in the study overlay."""
        researcher = _researcher_module()
        protocol = researcher._load_protocol()
        closing = researcher.closing_area_id(protocol)
        assert closing == "J"
        area_j = next(a for a in protocol["thematic_areas"] if a["id"] == "J")
        assert area_j.get("always_ask") is True

    def test_openness_overlay_adds_construct_areas(self):
        """When the openness study's overlay is applied, the merged
        protocol carries Areas D-H in addition to the framework A/B/C/I/J."""
        researcher = _researcher_module()
        studies_mod = importlib.import_module(f"{PKG}.studies")
        study = studies_mod.load_study("openness_maneuvering")
        merged = researcher._apply_study_overlay(researcher._load_protocol(), study)
        ids = [a["id"] for a in merged["thematic_areas"]]
        # Framework areas first, overlay areas appended.
        assert "A" in ids and "B" in ids and "C" in ids
        assert "D" in ids and "E" in ids and "F" in ids and "G" in ids and "H" in ids
        assert "I" in ids and "J" in ids
        # Closing area is still J after merge.
        assert researcher.closing_area_id(merged) == "J"


# ---------------------------------------------------------------------------
# 2. Forbidden-vocabulary checker
# ---------------------------------------------------------------------------

class TestForbiddenVocab:
    def _openness_extras(self):
        """Construct-specific forbidden vocab from the openness study —
        used as `study_extras` to reconstitute the historical merged
        list for backward-compat assertions below."""
        studies = importlib.import_module(f"{PKG}.studies")
        return tuple(
            studies.load_study("openness_maneuvering").construct_forbidden_vocabulary
        )

    def test_protocol_word_list_loaded_methodological_only(self):
        """With no study_extras, only the methodological subset loads.
        Construct-specific words live in the study config."""
        vocab = _vocab_module()
        # Clear the LRU cache between tests so the call below isn't
        # affected by earlier (cached) calls with different extras.
        vocab.load_forbidden_vocabulary.cache_clear()
        words = vocab.load_forbidden_vocabulary()
        # Methodological words present.
        assert "strategy" in words
        assert "strategic" in words
        # Construct-specific words ABSENT — they're not loaded unless
        # the study config is passed.
        assert "value capture" not in words
        assert "open-source" not in words

    def test_protocol_word_list_merges_study_extras(self):
        """Passing the study's `construct_forbidden_vocabulary` as
        `study_extras` reconstitutes the historical merged list."""
        vocab = _vocab_module()
        vocab.load_forbidden_vocabulary.cache_clear()
        words = vocab.load_forbidden_vocabulary(
            study_extras=self._openness_extras(),
        )
        for word in ("open", "closed", "open-source", "strategy", "value capture"):
            assert word in words, f"Expected '{word}' in merged vocabulary"

    def test_flags_forbidden_word_when_panel_did_not_use_it(self):
        vocab = _vocab_module()
        vio = vocab.check_utterance(
            "What was your strategy for the inference API?",
            panelist_quotes=[],
        )
        assert any(v.word == "strategy" for v in vio)

    def test_allows_echo_from_panelist(self):
        vocab = _vocab_module()
        panel_said = ["CMO: 'this was a strategic moment for us'"]
        vio = vocab.check_utterance(
            "You said this was a strategic moment — unpack that for me.",
            panelist_quotes=panel_said,
        )
        # 'strategic' should be permitted because the panel used it.
        assert all(v.word != "strategic" for v in vio)

    def test_word_boundary_does_not_match_substring(self):
        vocab = _vocab_module()
        # 'opens' contains 'open' as a substring but is not the forbidden word.
        vio = vocab.check_utterance(
            "Walk me through how that opens up the roadmap.",
            panelist_quotes=[],
        )
        assert all(v.word != "open" for v in vio)

    def test_multi_token_forbidden_entry_matches(self):
        """`value capture` is a study-specific construct word so the
        check has to be invoked with that word in the merged list —
        which happens when the openness study config is loaded."""
        vocab = _vocab_module()
        studies = importlib.import_module(f"{PKG}.studies")
        study_extras = tuple(
            studies.load_study("openness_maneuvering").construct_forbidden_vocabulary
        )
        vocab.load_forbidden_vocabulary.cache_clear()
        forbidden = vocab.load_forbidden_vocabulary(study_extras=study_extras)
        vio = vocab.check_utterance(
            "How were you thinking about value capture here?",
            panelist_quotes=[],
            forbidden=forbidden,
        )
        assert any(v.word == "value capture" for v in vio)

    def test_format_violations_returns_actionable_string(self):
        vocab = _vocab_module()
        vio = vocab.check_utterance("Your strategy was?", panelist_quotes=[])
        msg = vocab.format_violations(vio)
        assert "strategy" in msg
        assert "Rewrite" in msg

    def test_format_violations_empty_for_clean_utterance(self):
        vocab = _vocab_module()
        assert vocab.format_violations([]) == ""


# ---------------------------------------------------------------------------
# 3. Schemas round-trip via Pydantic
# ---------------------------------------------------------------------------

class TestSchemas:
    def test_observation_summary_roundtrip(self):
        summary = _make_summary()
        blob = summary.model_dump_json()
        s = _schemas_module()
        again = s.ObservationSummary.model_validate_json(blob)
        assert again.decisions == summary.decisions
        assert again.disagreements[0].topic == summary.disagreements[0].topic

    def test_panel_utterance_minimum_valid(self):
        s = _schemas_module()
        u = s.PanelUtterance(
            area_id="A",
            addressed_to="group",
            text="Walk me through the decision around the inference API.",
            anchor_refs=["inference API"],
        )
        assert u.is_followup is False
        assert u.ends_debriefing is False

    def test_panel_utterance_rejects_invalid_area_id(self):
        s = _schemas_module()
        with pytest.raises(Exception):
            s.PanelUtterance(
                area_id="Z",  # invalid
                addressed_to="group",
                text="x",
                anchor_refs=["x"],
            )


# ---------------------------------------------------------------------------
# 4. Factory functions
# ---------------------------------------------------------------------------

class TestObserverFactory:
    def test_returns_agent_with_expected_name(self):
        researcher = _researcher_module()
        agent = researcher.create_observer_agent("OpenAI")
        assert agent.name == "QualitativeResearcher_Observer"

    def test_observer_has_observation_summary_output_schema(self):
        researcher = _researcher_module()
        schemas = _schemas_module()
        agent = researcher.create_observer_agent("OpenAI")
        assert agent.output_schema is schemas.ObservationSummary

    def test_observer_instruction_mentions_company_and_scenario(self):
        researcher = _researcher_module()
        studies = importlib.import_module(f"{PKG}.studies")
        # Pass the openness study so the construct-specific forbidden
        # words appear in the instruction's forbidden-vocab list.
        agent = researcher.create_observer_agent(
            "Anthropic",
            industry_context="Stable",
            product_type="Incremental",
            study=studies.load_study("openness_maneuvering"),
        )
        text = agent.instruction
        assert "Anthropic" in text
        assert "Stable" in text
        assert "Incremental" in text
        # Construct-specific forbidden words appear in the merged list.
        assert "'open'" in text or "'open-source'" in text

    def test_observer_uses_observer_model(self):
        """Per Study Plan §3.3, observer must be pinned (Gemini Pro)."""
        researcher = _researcher_module()
        providers = importlib.import_module(f"{PKG}.providers")
        agent = researcher.create_observer_agent("OpenAI")
        expected = providers.get_observer_model()
        assert agent.model == expected


class TestDebrieferFactory:
    def test_returns_agent_with_expected_name(self):
        researcher = _researcher_module()
        agent = researcher.create_debriefer_agent("OpenAI", _make_summary())
        assert agent.name == "QualitativeResearcher_Debriefer"

    def test_debriefer_has_panel_utterance_output_schema(self):
        researcher = _researcher_module()
        schemas = _schemas_module()
        agent = researcher.create_debriefer_agent("OpenAI", _make_summary())
        assert agent.output_schema is schemas.PanelUtterance

    def test_debriefer_instruction_embeds_observation_summary(self):
        researcher = _researcher_module()
        agent = researcher.create_debriefer_agent("OpenAI", _make_summary())
        text = agent.instruction
        # Field-note items appear verbatim so the model can anchor questions.
        assert "inference API" in text
        assert "fine-tuning recipe" in text
        assert "partner-only release" in text  # alternatives_considered

    def test_debriefer_instruction_lists_framework_areas(self):
        """Without a study attached, the debriefer's instruction
        carries only the 5 framework-level generic areas (A/B/C/I/J).
        Study-specific D-H come from the study overlay — tested
        separately in `test_debriefer_instruction_lists_overlay_areas`."""
        researcher = _researcher_module()
        agent = researcher.create_debriefer_agent("OpenAI", _make_summary())
        text = agent.instruction
        for header in (
            "Area A — Decision anchoring",
            "Area B — Counterfactuals",
            "Area C — Disagreement and resolution",
            "Area I — Context sensitivity",
            "Area J — Reflection and unresolved",
        ):
            assert header in text, f"Missing header: {header}"

    def test_debriefer_instruction_lists_overlay_areas_when_study_attached(self):
        """When the openness study is attached, the debriefer's prompt
        gains construct-specific Areas D-H from its protocol overlay,
        in addition to the framework's A/B/C/I/J."""
        researcher = _researcher_module()
        studies_mod = importlib.import_module(f"{PKG}.studies")
        study = studies_mod.load_study("openness_maneuvering")
        agent = researcher.create_debriefer_agent(
            "OpenAI", _make_summary(), study=study,
        )
        text = agent.instruction
        for header in (
            "Area D — Differences in handling",
            "Area E — Who does the work",
            "Area F — Changes over time",
            "Area G — What the firm gets and gives",
            "Area H — Position relative to others",
        ):
            assert header in text, f"Missing overlay area header: {header}"

    def test_debriefer_instruction_includes_forbidden_vocab_list(self):
        """With no study, only the methodological forbidden words
        appear; passing the openness study restores the construct-
        specific words (open, closed, etc.)."""
        researcher = _researcher_module()
        studies = importlib.import_module(f"{PKG}.studies")

        # No study → only methodological terms (strategy, strategic, …).
        agent_no_study = researcher.create_debriefer_agent(
            "OpenAI", _make_summary(),
        )
        text_no_study = agent_no_study.instruction
        assert "'strategy'" in text_no_study  # methodological — always present
        assert "'open'" not in text_no_study  # construct-specific — absent without study

        # With openness study → construct-specific words appear too.
        agent_with_study = researcher.create_debriefer_agent(
            "OpenAI", _make_summary(),
            study=studies.load_study("openness_maneuvering"),
        )
        text_with_study = agent_with_study.instruction
        assert "'open'" in text_with_study
        assert "'closed'" in text_with_study
        assert "'strategy'" in text_with_study

    def test_debriefer_instruction_states_anchor_refs_required(self):
        researcher = _researcher_module()
        agent = researcher.create_debriefer_agent("OpenAI", _make_summary())
        text = agent.instruction
        assert "anchor_refs" in text
        assert "non-empty" in text or "MUST be non-empty" in text


# ---------------------------------------------------------------------------
# 5. utterance_violates_protocol runtime guard
# ---------------------------------------------------------------------------

class TestUtteranceGuard:
    def test_clean_utterance_passes(self):
        researcher = _researcher_module()
        schemas = _schemas_module()
        u = schemas.PanelUtterance(
            area_id="A",
            addressed_to="group",
            text="I want to start with the decision around the inference API. Walk me through how that one came together.",
            anchor_refs=["inference API"],
        )
        assert researcher.utterance_violates_protocol(u, []) == []

    def test_empty_anchor_refs_is_flagged(self):
        # Build the dataclass directly without going through Pydantic
        # validation so we can probe what the runtime guard does when
        # `anchor_refs` is missing. Pydantic itself rejects empty lists
        # if min_length is set; today the schema permits empty lists
        # and the runtime guard catches them. This double-layer is
        # deliberate (schema is documentation, guard is enforcement).
        researcher = _researcher_module()
        schemas = _schemas_module()
        u = schemas.PanelUtterance(
            area_id="A",
            addressed_to="group",
            text="Walk me through your reasoning.",
            anchor_refs=[],
        )
        msgs = researcher.utterance_violates_protocol(u, [])
        assert any("anchor_refs is empty" in m for m in msgs)

    def test_forbidden_word_is_flagged(self):
        researcher = _researcher_module()
        schemas = _schemas_module()
        u = schemas.PanelUtterance(
            area_id="A",
            addressed_to="group",
            text="Walk me through your open-source strategy on the inference API.",
            anchor_refs=["inference API"],
        )
        msgs = researcher.utterance_violates_protocol(u, [])
        joined = " | ".join(msgs)
        # Either 'open-source' or 'strategy' should trip the guard.
        assert "open-source" in joined or "strategy" in joined

    def test_echo_from_panelist_is_permitted(self):
        researcher = _researcher_module()
        schemas = _schemas_module()
        panel_history = [
            "CMO: 'I think this is a strategic shift, not a tactical move.'"
        ]
        u = schemas.PanelUtterance(
            area_id="A",
            addressed_to="group",
            text="You said this was a strategic shift — unpack that for me.",
            anchor_refs=["inference API"],
        )
        msgs = researcher.utterance_violates_protocol(u, panel_history)
        # 'strategic' and 'shift' were used by the panel, so they're allowed.
        assert all("strategic" not in m and "shift" not in m for m in msgs)


# ---------------------------------------------------------------------------
# 6. Public exports from the roles package
# ---------------------------------------------------------------------------

class TestPublicExports:
    @pytest.mark.parametrize(
        "name",
        [
            "create_observer_agent",
            "create_debriefer_agent",
            "utterance_violates_protocol",
            "ObservationSummary",
            "PanelUtterance",
            "PanelExchange",
            "PanelResponse",
            "Disagreement",
            "RoleContribution",
            "LoadedVocabUse",
        ],
    )
    def test_symbol_is_exported_from_roles_package(self, name):
        roles = _roles_package()
        assert hasattr(roles, name), f"roles package missing export: {name}"
