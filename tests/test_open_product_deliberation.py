"""Tests for the open-product deliberation refactor.

Earlier behaviour pre-baked a concrete product into the deliberation
prompt — `product_description` defaulted to "Next-generation
multimodal AI model with advanced reasoning capabilities" and
`strategic_question` asked "how should THIS product be developed".
The TMT walked in with the WHAT already decided and only deliberated
the HOW; that's a release-strategy meeting, not a strategy session.

These tests verify the new behaviour:
  * `product_description` defaults to None — the team has to choose
    the product direction itself.
  * The default `strategic_question` is a what-AND-how question that
    asks the team to surface candidate directions, evaluate them,
    converge on one, and then deliberate on development/governance/
    release.
  * `product_type` (Novel / Incremental) still constrains the scope
    (novel direction vs. enhancement of existing pipeline) without
    naming the product.
  * The CEO prompt builder omits the PRODUCT block when
    `product_description` is None.
  * The CEO prompt names the firm as an "AI firm" so the team picks
    a product within the AI domain (matches the 5-firm × 2×2 study
    design).
"""

from __future__ import annotations

import importlib
import inspect

import pytest

PKG = "open-innovation-strategy"


def _rs():
    return importlib.import_module(f"{PKG}.run_research_session")


def _agent_module():
    return importlib.import_module(f"{PKG}.agent")


# ===========================================================================
# 1. Defaults at the run_research_session level
# ===========================================================================

class TestRunResearchSessionDefaults:
    """`product_description` and `strategic_question` defaults must
    leave the WHAT undecided."""

    def test_product_description_default_is_none(self):
        rs = _rs()
        sig = inspect.signature(rs.run_research_session)
        assert sig.parameters["product_description"].default is None, (
            "product_description must default to None so the team "
            "decides the product itself"
        )

    def test_strategic_question_default_is_none(self):
        """The default is built lazily inside the function (so we can
        condition on product_type). Default in the signature is None."""
        rs = _rs()
        sig = inspect.signature(rs.run_research_session)
        assert sig.parameters["strategic_question"].default is None


# ===========================================================================
# 2. CEO prompt builder respects None product_description
# ===========================================================================

class TestCeoPromptBuilder:
    def _system(self):
        return _agent_module().TMTSystemWithA2A(
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
        )

    def test_no_product_block_when_description_is_none(self):
        system = self._system()
        prompt = system._compose_ceo_prompt(
            product_description=None,
            strategic_question="What should we build next?",
            product_type="Novel",
            context_text="rapid change",
        )
        # The "PRODUCT" section header must not appear when the team
        # has no pre-baked product to deliberate over.
        assert "PRODUCT\n" not in prompt
        assert "PRODUCT (context" not in prompt

    def test_no_product_block_when_description_is_empty_string(self):
        """Empty string and None should behave the same (truthiness
        check) — neither should add a PRODUCT block."""
        system = self._system()
        prompt = system._compose_ceo_prompt(
            product_description="",
            strategic_question="What should we build next?",
            product_type="Novel",
            context_text="rapid change",
        )
        assert "PRODUCT\n" not in prompt
        assert "PRODUCT (context" not in prompt

    def test_product_block_appears_when_caller_provides_description(self):
        """A caller running a controlled experiment can still pin the
        product — the block reappears in that case."""
        system = self._system()
        prompt = system._compose_ceo_prompt(
            product_description="A specific multimodal AI model",
            strategic_question="How do we release it?",
            product_type="Novel",
            context_text="rapid change",
        )
        assert "PRODUCT" in prompt
        assert "A specific multimodal AI model" in prompt
        # The block makes clear the team may still question/change.
        assert "may still question" in prompt

    def test_ceo_prompt_uses_scenario_brief_when_provided(self):
        """The firm-domain hint comes from the study's `scenario_brief`
        — passed explicitly into the CEO prompt builder. Without a
        study, no domain hint appears (clean default)."""
        system = self._system()
        prompt = system._compose_ceo_prompt(
            product_description=None,
            strategic_question="What should we build next?",
            product_type="Novel",
            context_text="rapid change",
            scenario_brief="An AI firm operating in a competitive industry.",
        )
        # The scenario brief (sans trailing dot) appears in parens
        # next to the company name.
        assert "An AI firm operating in a competitive industry" in prompt

    def test_ceo_prompt_omits_domain_hint_when_no_scenario_brief(self):
        """Without a scenario_brief, the company line is bare —
        no '(an AI firm)' is hardcoded into the framework anymore."""
        system = self._system()
        prompt = system._compose_ceo_prompt(
            product_description=None,
            strategic_question="What should we build next?",
            product_type="Novel",
            context_text="rapid change",
        )
        # No '(an AI firm)' parenthetical when scenario_brief is None.
        assert "(an AI firm)" not in prompt

    def test_prompt_does_not_contain_hardcoded_multimodal_default(self):
        """Guards against re-introducing the old default product. If
        anyone re-adds a hard-coded 'multimodal AI model' default we
        want this test to scream."""
        system = self._system()
        prompt = system._compose_ceo_prompt(
            product_description=None,
            strategic_question="What should we build next?",
            product_type="Novel",
            context_text="rapid change",
        )
        assert "multimodal AI model" not in prompt
        assert "next-generation multimodal" not in prompt.lower()


# ===========================================================================
# 3. Default strategic_question wording (Novel vs Incremental)
# ===========================================================================

class TestDefaultStrategicQuestion:
    """The default strategic_question is built inside
    run_research_session() and depends on product_type. We can't
    invoke that function without a runner, but we can read its source
    to confirm both branches exist."""

    def test_default_question_for_novel_picks_novel_direction(self):
        rs = _rs()
        source = inspect.getsource(rs.run_research_session)
        # Both branches present.
        assert "novel AI product direction" in source
        assert "enhancement of the firm's existing AI offering" in source

    def test_default_question_asks_what_and_how(self):
        """The default question must ask the team to decide the
        PRODUCT (what) before how to take it forward (how).

        We check individual phrases rather than long substrings because
        the production f-string is wrapped across lines (and the source
        text inspect.getsource returns has literal quote characters
        between adjoining string fragments)."""
        rs = _rs()
        source = inspect.getsource(rs.run_research_session)
        # Phrases that each fit within one source-line fragment.
        for phrase in (
            "What should we",
            "develop and bring",
            "to market next?",
            "evaluate them",
            "converge",
            "take it forward",
        ):
            assert phrase in source, f"missing phrase {phrase!r} in default question"

    def test_default_question_does_not_presuppose_a_specific_product(self):
        """The old default said 'decide how this product should be
        developed' — presupposing a specific product. The new default
        must not."""
        rs = _rs()
        source = inspect.getsource(rs.run_research_session)
        assert "how this product should be developed" not in source
        assert "multimodal AI model" not in source.lower()


# ===========================================================================
# 4. RoleTaskSpec accepts empty product_description
# ===========================================================================

class TestRoleTaskSpecAcceptsEmptyProduct:
    """The concurrent-deliberation RoleTaskSpec was previously a
    required `product_description: str`. It now defaults to empty so
    the role prompt simply omits the PRODUCT line."""

    def test_role_task_spec_accepts_empty_product_description(self):
        conc = importlib.import_module(
            f"{PKG}.orchestrator.concurrent_mode"
        )
        spec = conc.RoleTaskSpec(
            role="CTO",
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            strategic_question="What should we build?",
            doc_framing="CTO deliverable",
        )
        assert spec.product_description == ""

    def test_role_task_spec_accepts_none_product_description(self):
        """Regression: `run_research_session` passes
        `product_description=None` (the new default) through to
        `RoleTaskSpec`. The Pydantic field must accept None, not just
        the empty string, otherwise live runs fail with a
        `string_type` validation error.
        """
        conc = importlib.import_module(
            f"{PKG}.orchestrator.concurrent_mode"
        )
        spec = conc.RoleTaskSpec(
            role="CTO",
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            strategic_question="What should we build?",
            product_description=None,
            doc_framing="CTO deliverable",
        )
        # Pydantic accepts None → stored as None on the model.
        assert spec.product_description is None

    def test_role_prompt_omits_product_block_when_none(self):
        """Same as empty-string behaviour: None should NOT render a
        PRODUCT block in the role prompt."""
        conc = importlib.import_module(
            f"{PKG}.orchestrator.concurrent_mode"
        )
        spec = conc.RoleTaskSpec(
            role="CTO",
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            strategic_question="What should we build?",
            product_description=None,
            doc_framing="CTO deliverable",
        )
        state = conc.RoleState(role="CTO", scratchpad=[], draft="", inbox=[])
        prompt = conc._compose_role_prompt(
            role="CTO", task=spec, my_state=state, transcript=[],
        )
        assert "PRODUCT (context, not a decision)" not in prompt

    def test_role_prompt_omits_product_block_when_empty(self):
        conc = importlib.import_module(
            f"{PKG}.orchestrator.concurrent_mode"
        )
        spec = conc.RoleTaskSpec(
            role="CTO",
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            strategic_question="What should we build?",
            doc_framing="CTO deliverable",
        )
        state = conc.RoleState(role="CTO", scratchpad=[], draft="", inbox=[])
        prompt = conc._compose_role_prompt(
            role="CTO", task=spec, my_state=state, transcript=[],
        )
        assert "PRODUCT (context, not a decision)" not in prompt

    def test_role_prompt_shows_product_block_when_provided(self):
        conc = importlib.import_module(
            f"{PKG}.orchestrator.concurrent_mode"
        )
        spec = conc.RoleTaskSpec(
            role="CTO",
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            strategic_question="How do we release it?",
            product_description="A specific multimodal AI model",
            doc_framing="CTO deliverable",
        )
        state = conc.RoleState(role="CTO", scratchpad=[], draft="", inbox=[])
        prompt = conc._compose_role_prompt(
            role="CTO", task=spec, my_state=state, transcript=[],
        )
        assert "PRODUCT (context, not a decision)" in prompt
        assert "A specific multimodal AI model" in prompt
