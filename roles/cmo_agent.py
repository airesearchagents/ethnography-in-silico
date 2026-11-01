"""CMO role agent — prompt template for the synthetic Chief Marketing Officer.

A role agent is a language model given a name, a role and instructions, and a
prompt is the text sent to a model to get one reply. This file sets up the agent
that plays the CMO, one of the six simulated executives.

A heuristic functional portrait for simulation purposes. The prompt
describes the role in modern operating terms — brand, positioning,
go-to-market, demand generation, pricing partnership, crisis comms —
rather than in academic language about market orientation as a
construct.

Background framing (market orientation, market-driven capabilities)
lives in ``roles/__init__.py`` and is intentionally not part of the
LLM (large language model, the program that writes the agent's text)
prompt.
"""

from google.adk.agents import LlmAgent

try:
    from ..providers import get_role_model
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from providers import get_role_model  # type: ignore[no-redef]

from .context_definitions import get_industry_context_guidance, get_product_type_guidance


def create_cmo_agent(
    company: str,
    current_year: int = 2030,
    industry_context: str = "Dynamic",
    product_type: str = "Novel",
) -> LlmAgent:
    """CMO — brand, positioning, go-to-market, and demand-generation owner."""

    context_market = get_industry_context_guidance(industry_context, "market")
    product_market = get_product_type_guidance(product_type, "market")

    return LlmAgent(
        name="CMO",
        model=get_role_model("CMO"),
        instruction=f"""You are the Chief Marketing Officer of {company}.

What you do:
- Own brand, positioning, and go-to-market.
- Set the firm's narrative for the segments it serves — customers,
  partners, press, analysts.
- Build the demand-generation engine across paid acquisition, content,
  events, and partnerships.
- Set pricing and packaging together with the Product Strategist and
  Finance.
- Watch customer acquisition cost, retention, and brand sentiment.
- Partner with the CTO on the technology stack that supports marketing.
- Own crisis communications when the firm's reputation is at stake.

The year is {current_year}.

{context_market}

{product_market}

When asked for input, share what you actually see in the market — what
customers are saying, what competitors are doing, where the brand stands
— rather than what would be convenient to hear.""",
        description=f"CMO of {company} ({industry_context} industry, {product_type} product)",
    )
