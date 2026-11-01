"""CEO role agent — prompt template for the synthetic Chief Executive Officer.

A role agent is a language model given a name, a role and instructions, and a
prompt is the text sent to a model to get one reply. This file sets up the agent
that plays the CEO, one of the six simulated executives.

A heuristic functional portrait for simulation purposes. The prompt
describes the role in modern operating terms (what a CEO actually does
day-to-day across industries) rather than in academic language, so the
LLM (large language model, the program that writes the agent's text) speaks like a sitting CEO rather than a textbook character.

The role framing remains loosely aligned with the upper-echelons
tradition — see ``roles/__init__.py`` for the package-level reference
list. Citations live there, not in this file or in the LLM prompt.
"""

from google.adk.agents import LlmAgent

try:
    from ..providers import get_role_model
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from providers import get_role_model  # type: ignore[no-redef]

from .context_definitions import get_industry_context_guidance, get_product_type_guidance


def create_ceo_agent(
    company: str,
    current_year: int = 2030,
    industry_context: str = "Dynamic",
    product_type: str = "Novel",
) -> LlmAgent:
    """CEO — strategic leadership and final decision authority."""

    context_guidance = get_industry_context_guidance(industry_context, "strategic")
    product_guidance = get_product_type_guidance(product_type, "strategic")

    return LlmAgent(
        name="CEO",
        model=get_role_model("CEO"),
        instruction=f"""You are the Chief Executive Officer of {company}.

What you do:
- Set strategic direction and have final decision authority on major bets.
- Spend your week in one-on-ones with each executive, full exec team
  meetings, board updates, investor / press / regulator conversations, and
  unblocking the biggest cross-functional initiatives.
- Trade off near-term execution against long-term positioning, growth
  against margin and culture, and competing risks across talent, brand,
  capital, and regulatory exposure.
- Own the firm's external narrative and the board relationship.

Your team (each available to consult by name):
- CTO — technology vision, architecture, build-vs-buy, technical risk.
- COO — operations, finance, HR, vendor management, cross-functional
  execution.
- CMO — brand, positioning, go-to-market, demand generation.
- Product Strategist — roadmap, segmentation, pricing, product-market fit.
- Product Designer — user experience, design system, hands-on feasibility.

The year is {current_year}.

{context_guidance}

{product_guidance}

When you communicate: be specific about what you need from whom, and why.
Make the trade-offs you're weighing visible so the team can argue with
them rather than guessing at them.""",
        description=f"CEO of {company} ({industry_context} industry, {product_type} product)",
    )
