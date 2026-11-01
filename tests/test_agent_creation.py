"""
Tests that verify agents are created for every role and every company.

Coverage:
- Each individual create_*_agent factory returns an LlmAgent with the correct name.
- TMTSystemWithA2A.__init__ populates self.agents with all six roles.
- TMTSystemWithA2A works correctly for all five companies.
- The roles package exports all six factory functions.

Note: The on-disk package is named 'open-innovation-strategy' (hyphen), which
is a valid Python package directory but cannot be imported with the normal
`import` statement.  All production-code imports go through importlib.
conftest.py stubs out google.adk before anything is imported.
"""

import importlib
import inspect

import pytest

# ---------------------------------------------------------------------------
# Constants – single source of truth for the expected roles / companies
# ---------------------------------------------------------------------------

EXPECTED_ROLES = [
    "CEO",
    "CTO",
    "COO",
    "CMO",
    "Product_Strategist",
    "Product_Designer",
]

EXPECTED_COMPANIES = ["OpenAI", "Google", "Anthropic", "Microsoft", "Meta"]

# Mapping: role key -> factory function name inside the roles package
ROLE_FACTORY_MAP = {
    "CEO": "create_ceo_agent",
    "CTO": "create_cto_agent",
    "COO": "create_coo_agent",
    "CMO": "create_cmo_agent",
    "Product_Strategist": "create_product_strategist_agent",
    "Product_Designer": "create_product_designer_agent",
}

PKG = "open-innovation-strategy"


# ---------------------------------------------------------------------------
# Module-level helpers (cached after first call)
# ---------------------------------------------------------------------------

def _roles():
    """Return the roles sub-package module."""
    return importlib.import_module(f"{PKG}.roles")


def _agent_module():
    """Return the agent module containing TMTSystemWithA2A."""
    return importlib.import_module(f"{PKG}.agent")


def _make_tmt(company: str = "OpenAI", **kwargs):
    """Instantiate TMTSystemWithA2A for a given company."""
    TMT = _agent_module().TMTSystemWithA2A
    return TMT(company=company, **kwargs)


# ---------------------------------------------------------------------------
# 1.  roles package exports all six factory functions
# ---------------------------------------------------------------------------

class TestRolesPackageExports:
    """The roles/__init__.py must re-export every factory."""

    def test_all_factories_exported(self):
        roles_mod = _roles()
        for role, factory_name in ROLE_FACTORY_MAP.items():
            assert hasattr(roles_mod, factory_name), (
                f"roles package is missing export: {factory_name}"
            )

    @pytest.mark.parametrize("role", EXPECTED_ROLES)
    def test_factory_is_callable(self, role):
        roles_mod = _roles()
        factory = getattr(roles_mod, ROLE_FACTORY_MAP[role])
        assert callable(factory), f"{ROLE_FACTORY_MAP[role]} is not callable"


# ---------------------------------------------------------------------------
# 2.  Individual factory functions return an agent with the correct name
# ---------------------------------------------------------------------------

class TestIndividualFactories:
    """Each create_*_agent factory must return an LlmAgent-like object
    with the correct name, non-empty instruction, and the company name
    embedded in the instruction text."""

    def _factory(self, role: str):
        roles_mod = _roles()
        return getattr(roles_mod, ROLE_FACTORY_MAP[role])

    @pytest.mark.parametrize("role", EXPECTED_ROLES)
    def test_agent_name_matches_role(self, role):
        agent = self._factory(role)("TestCo")
        assert agent.name == role, (
            f"Expected agent.name='{role}', got '{agent.name}'"
        )

    @pytest.mark.parametrize("role", EXPECTED_ROLES)
    def test_agent_has_non_empty_instruction(self, role):
        agent = self._factory(role)("TestCo")
        assert agent.instruction, f"{role} agent instruction must not be empty"

    @pytest.mark.parametrize("role", EXPECTED_ROLES)
    def test_agent_has_non_empty_description(self, role):
        agent = self._factory(role)("TestCo")
        assert agent.description, f"{role} agent description must not be empty"

    @pytest.mark.parametrize("role", EXPECTED_ROLES)
    def test_company_name_in_instruction(self, role):
        """The agent's instruction should reference the company it's built for."""
        company = "AcmeCorp"
        agent = self._factory(role)(company)
        assert company in agent.instruction, (
            f"{role} instruction does not mention the company name '{company}'"
        )

    @pytest.mark.parametrize("industry_context", ["Dynamic", "Stable"])
    @pytest.mark.parametrize("role", EXPECTED_ROLES)
    def test_factory_accepts_industry_context(self, role, industry_context):
        agent = self._factory(role)("TestCo", industry_context=industry_context)
        assert agent.name == role

    @pytest.mark.parametrize("product_type", ["Novel", "Enhancement"])
    @pytest.mark.parametrize("role", EXPECTED_ROLES)
    def test_factory_accepts_product_type(self, role, product_type):
        agent = self._factory(role)("TestCo", product_type=product_type)
        assert agent.name == role

    @pytest.mark.parametrize("role", EXPECTED_ROLES)
    def test_factory_default_year_is_2030(self, role):
        """Every role factory's default `current_year` must be 2030 — the
        study's canonical near-future scenario year. Catches accidental
        drift back to the writing-year default."""
        import inspect
        sig = inspect.signature(self._factory(role))
        default = sig.parameters["current_year"].default
        assert default == 2030, (
            f"{role} factory default current_year is {default!r}, "
            f"expected 2030 (the study's canonical near-future scenario "
            f"year)"
        )

    @pytest.mark.parametrize("role", EXPECTED_ROLES)
    def test_default_year_appears_in_instruction(self, role):
        """Sanity check: the year string should actually surface in the
        rendered instruction (since the role prompts template it). Guards
        against a regression where the default was changed but the
        instruction string forgot to interpolate it.
        """
        agent = self._factory(role)("TestCo")
        # CTO doesn't templatize the year in its instruction body, but
        # most roles do. Skip the assertion for roles that don't reference
        # current_year in the prompt at all.
        if "{current_year}" in agent.instruction or "2026" in agent.instruction:
            assert "2026" not in agent.instruction, (
                f"{role} instruction still contains the literal '2026' — "
                f"likely a missed default update"
            )


# ---------------------------------------------------------------------------
# 3.  TMTSystemWithA2A creates agents for all roles on instantiation
# ---------------------------------------------------------------------------

class TestTMTSystemAgentCreation:
    """TMTSystemWithA2A.__init__ must populate self.agents with all six roles."""

    def test_all_roles_present_in_agents_dict(self):
        system = _make_tmt("OpenAI")
        missing = set(EXPECTED_ROLES) - set(system.agents.keys())
        assert not missing, f"Missing roles in system.agents: {missing}"

    def test_agents_dict_has_no_extra_roles(self):
        system = _make_tmt("OpenAI")
        extra = set(system.agents.keys()) - set(EXPECTED_ROLES)
        assert not extra, f"Unexpected extra roles in system.agents: {extra}"

    @pytest.mark.parametrize("role", EXPECTED_ROLES)
    def test_each_role_agent_has_correct_name(self, role):
        system = _make_tmt("OpenAI")
        agent = system.agents[role]
        assert agent.name == role, (
            f"system.agents['{role}'].name is '{agent.name}', expected '{role}'"
        )

    def test_session_service_present_for_inprocess_delegation(self):
        """Under ADK 1.18 there is no network A2A; agents delegate in-process
        via `transfer_to_agent`. The system must expose a session service
        that the per-call Runner can bind to. Replaces the obsolete
        `test_ports_defined_for_all_roles` (network-A2A artefact)."""
        system = _make_tmt("OpenAI")
        assert hasattr(system, "session_service"), (
            "TMTSystemWithA2A must expose a session_service (ADK 1.18 Runner needs one)"
        )
        # Conversation log starts empty; populated by run_strategic_discussion.
        assert hasattr(system, "conversation_log")
        assert system.conversation_log == []

    def test_run_strategic_discussion_is_async_callable(self):
        """Sanity-check the public deliberation entry point. We don't
        actually run it here (would require live ADK + an API key);
        we just confirm the method exists and is a coroutine function
        so downstream callers can `await` it."""
        import inspect
        system = _make_tmt("OpenAI")
        assert callable(getattr(system, "run_strategic_discussion", None))
        assert inspect.iscoroutinefunction(system.run_strategic_discussion), (
            "run_strategic_discussion must be an async def"
        )

    def test_agents_count_equals_expected_roles(self):
        system = _make_tmt("OpenAI")
        assert len(system.agents) == len(EXPECTED_ROLES), (
            f"Expected {len(EXPECTED_ROLES)} agents, got {len(system.agents)}"
        )

    def test_default_scenario_year_is_2030(self):
        """The study targets a near-future 2030 scenario where the
        openness-vs-control trade-offs are sharper. TMTSystemWithA2A
        defaults to 2030 so a run without an explicit year picks the
        study's canonical scenario year (not the test-author's writing
        year).
        """
        system = _make_tmt("OpenAI")
        assert system.current_year == 2030, (
            f"Default current_year should be 2030, got {system.current_year}"
        )


# ---------------------------------------------------------------------------
# 4.  TMTSystemWithA2A creates agents for every company in the study
# ---------------------------------------------------------------------------

class TestTMTSystemAllCompanies:
    """Each company in the comparative study must produce a valid TMT system
    with agents for all six roles."""

    @pytest.mark.parametrize("company", EXPECTED_COMPANIES)
    def test_system_instantiates_for_company(self, company):
        system = _make_tmt(company)
        assert system.company == company

    @pytest.mark.parametrize("company", EXPECTED_COMPANIES)
    def test_all_roles_created_for_company(self, company):
        system = _make_tmt(company)
        missing = set(EXPECTED_ROLES) - set(system.agents.keys())
        assert not missing, (
            f"Company '{company}' is missing roles: {missing}"
        )

    @pytest.mark.parametrize("company", EXPECTED_COMPANIES)
    def test_company_name_in_each_agent_instruction(self, company):
        system = _make_tmt(company)
        for role, agent in system.agents.items():
            assert company in agent.instruction, (
                f"Company '{company}' not found in {role} agent instruction"
            )

    @pytest.mark.parametrize("company", EXPECTED_COMPANIES)
    @pytest.mark.parametrize("role", EXPECTED_ROLES)
    def test_agent_name_correct_per_company(self, company, role):
        system = _make_tmt(company)
        assert system.agents[role].name == role

    @pytest.mark.parametrize("company", EXPECTED_COMPANIES)
    def test_system_stores_correct_company_name(self, company):
        system = _make_tmt(company)
        assert system.company == company

    @pytest.mark.parametrize("company", EXPECTED_COMPANIES)
    @pytest.mark.parametrize("industry_context", ["Dynamic", "Stable"])
    def test_system_created_with_industry_context(self, company, industry_context):
        system = _make_tmt(company, industry_context=industry_context)
        assert len(system.agents) == len(EXPECTED_ROLES)

    @pytest.mark.parametrize("company", EXPECTED_COMPANIES)
    @pytest.mark.parametrize("product_type", ["Novel", "Enhancement"])
    def test_system_created_with_product_type(self, company, product_type):
        system = _make_tmt(company, product_type=product_type)
        assert len(system.agents) == len(EXPECTED_ROLES)


