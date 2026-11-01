"""CTO role agent — prompt template for the synthetic Chief Technology Officer.

A role agent is a language model given a name, a role and instructions, and a
prompt is the text sent to a model to get one reply. This file sets up the agent
that plays the CTO, one of the six simulated executives.

A heuristic functional portrait for simulation purposes. The prompt
describes the role in modern operating terms (technology vision,
architecture, build-vs-buy, technical risk) rather than in academic
language about component-vs-architectural innovation. The
LLM (large language model, the program that writes the agent's text) is asked
to act like a sitting CTO at a contemporary firm.

Background framing — synthetic technology executive informed by
technology-strategy and innovation-management literature — lives in
``roles/__init__.py`` and is intentionally not included in the prompt.
"""

from google.adk.agents import LlmAgent

try:
    from ..providers import get_role_model
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from providers import get_role_model  # type: ignore[no-redef]

from .context_definitions import get_industry_context_guidance, get_product_type_guidance


def create_cto_agent(
    company: str,
    current_year: int = 2030,
    industry_context: str = "Dynamic",
    product_type: str = "Novel",
) -> LlmAgent:
    """CTO — technology vision, architecture, and technical-risk owner."""

    context_tech = get_industry_context_guidance(industry_context, "technical")
    product_tech = get_product_type_guidance(product_type, "technical")

    return LlmAgent(
        name="CTO",
        model=get_role_model("CTO"),
        instruction=f"""You are the Chief Technology Officer of {company}.

What you do:
- Own technology vision and architecture for the firm.
- Decide the technology stack, what to build and what to buy, the
  infrastructure, and the security and compliance baseline.
- Hire, structure, and grow the engineering organisation.
- Partner with Product on what the roadmap costs and how long it takes;
  with COO on capacity and vendor concentration; with the CEO and board on
  translating engineering reality into business terms (cost, speed, risk,
  downtime).
- Sign off on technical risk before it ships.

The year is {current_year}.

{context_tech}

{product_tech}

When asked for input, give your honest technical assessment — including
the trade-offs, the unknowns, and the cost of finding out. If you need
more information to give a good answer, ask for it specifically.""",
        description=f"CTO of {company} ({industry_context} industry, {product_type} product)",
    )
