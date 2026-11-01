"""Product Strategist role agent — prompt template for the synthetic
head-of-product role.

A role agent is a language model given a name, a role and instructions, and a
prompt is the text sent to a model to get one reply. This file sets up the agent
that plays the Product Strategist, one of the six simulated executives.

A heuristic functional portrait for simulation purposes. The prompt
describes the role in modern operating terms — roadmap ownership,
segmentation, pricing, customer discovery, product KPIs — rather than
in academic language about exploratory vs exploitative innovation.

"Product Strategist" is not a canonical upper-echelons label; it stands
in for what a VP of Product / Head of Product does today. See
``roles/__init__.py`` for the package-level reference list (kept out of
the
LLM (large language model, the program that writes the agent's text) prompt by design).
"""

from google.adk.agents import LlmAgent

try:
    from ..providers import get_role_model
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from providers import get_role_model  # type: ignore[no-redef]

from .context_definitions import get_industry_context_guidance, get_product_type_guidance


def create_product_strategist_agent(
    company: str,
    current_year: int = 2030,
    industry_context: str = "Dynamic",
    product_type: str = "Novel",
) -> LlmAgent:
    """Product Strategist — roadmap, segmentation, and product-market fit owner."""

    context_strategy = get_industry_context_guidance(industry_context, "product_strategy")
    product_strategy = get_product_type_guidance(product_type, "product_strategy")

    return LlmAgent(
        name="Product_Strategist",
        model=get_role_model("Product_Strategist"),
        instruction=f"""You are the Senior Product Strategist at {company}.

What you do:
- Own product strategy and the roadmap.
- Decide which customer segments matter, what the firm ships in what
  order, and at what price.
- Translate customer discovery — research, sales calls, support tickets,
  product telemetry — into prioritised bets.
- Partner with the CTO on what's buildable and at what cost; with the
  CMO on positioning and pricing; with the Product Designer on the
  experience.
- Own the product KPIs — activation, retention, satisfaction, expansion.
- Represent the product externally to customers, analysts, and the press.

The year is {current_year}.

{context_strategy}

{product_strategy}

When consulted, give your product judgement — what's worth building,
what should wait, and what would only ship to win the deck rather than
to serve a real user need.""",
        description=f"Product Strategist at {company} ({industry_context} industry, {product_type} product)",
    )
