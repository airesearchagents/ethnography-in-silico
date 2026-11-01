"""Product Designer role agent — prompt template for the synthetic
design-engineering hybrid role.

A role agent is a language model given a name, a role and instructions, and a
prompt is the text sent to a model to get one reply. This file sets up the agent
that plays the Product Designer, one of the six simulated executives.

A heuristic functional portrait for simulation purposes. The role is
intentionally hands-on: this designer prototypes in working code as
well as in design tools, owns feasibility against the architecture, and
sits between product strategy, engineering, and the user. The prompt
describes that operating reality rather than academic language about
user-experience pragmatic/hedonic dimensions or architectural
innovation dynamics.

Background framing (UX, or user experience, literature, product development decisions)
lives in ``roles/__init__.py`` for reference; it is kept out of the
LLM (large language model, the program that writes the agent's text)
prompt by design.
"""

from google.adk.agents import LlmAgent

try:
    from ..providers import get_role_model
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from providers import get_role_model  # type: ignore[no-redef]

from .context_definitions import get_industry_context_guidance, get_product_type_guidance


def create_product_designer_agent(
    company: str,
    current_year: int = 2030,
    industry_context: str = "Dynamic",
    product_type: str = "Novel",
) -> LlmAgent:
    """Product Designer — hands-on design + feasibility owner."""

    context_design = get_industry_context_guidance(industry_context, "product_design")
    product_design = get_product_type_guidance(product_type, "product_design")

    return LlmAgent(
        name="Product_Designer",
        model=get_role_model("Product_Designer"),
        instruction=f"""You are the Senior Product Designer at {company}.

What you do:
- Own the user experience across the product surface — interaction
  patterns, the design system, and how the product feels to use.
- You are a hands-on builder: you prototype in working code as well as
  in design tools, and you ship feasibility studies, not just mockups.
- You sit between the Product Strategist (what we should build),
  Engineering (what we can build), and the user (what works in their
  hands).
- Set the design principles, run usability research, mentor the design
  team, and review every major surface before it ships.
- When system architecture and user experience pull in opposite
  directions, you raise the tension early and own the resolution.

The year is {current_year}.

{context_design}

{product_design}

When consulted, give your design judgement together with the technical
feasibility read — what would actually work in users' hands, what would
need to be built to get there, and what the trade-offs look like.""",
        description=f"Product Designer at {company} ({industry_context} industry, {product_type} product)",
    )
