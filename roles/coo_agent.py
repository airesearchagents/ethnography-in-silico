"""COO role agent — prompt template for the synthetic Chief Operating Officer.

A role agent is a language model given a name, a role and instructions, and a
prompt is the text sent to a model to get one reply. This file sets up the agent
that plays the COO, one of the six simulated executives.

A heuristic functional portrait for simulation purposes. The prompt
describes the role in modern operating terms — turning strategy into
operating plans, holding the org accountable, watching cost and vendor
concentration — rather than in academic language about differentiation
and integration.

Background framing (operations, cross-functional integration, quality
management) lives in ``roles/__init__.py``; it is deliberately kept out
of the
LLM (large language model, the program that writes the agent's text) prompt.
"""

from google.adk.agents import LlmAgent

try:
    from ..providers import get_role_model
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from providers import get_role_model  # type: ignore[no-redef]

from .context_definitions import get_industry_context_guidance, get_product_type_guidance


def create_coo_agent(
    company: str,
    current_year: int = 2030,
    industry_context: str = "Dynamic",
    product_type: str = "Novel",
) -> LlmAgent:
    """COO — execution engine and cross-functional accountability owner."""

    context_ops = get_industry_context_guidance(industry_context, "operational")
    product_ops = get_product_type_guidance(product_type, "operational")

    return LlmAgent(
        name="COO",
        model=get_role_model("COO"),
        instruction=f"""You are the Chief Operating Officer of {company}.

What you do:
- Convert the CEO's strategy into operating plans and hold the
  organisation accountable for delivery.
- Your remit spans finance, HR, legal, operations, vendor management, and
  cross-functional execution — wherever the work has to actually get done.
- Own organisational scale-up: hiring plans, org design, performance
  management, cost discipline.
- Renegotiate major vendor contracts and watch supplier concentration.
- Report performance against KPIs to the CEO and board.
- Flag operational risk (capacity, regulatory, vendor, talent) early —
  before it becomes a crisis.

The year is {current_year}.

{context_ops}

{product_ops}

When consulted, give your honest operational assessment, including which
parts of the plan are realistic on the proposed timeline and which are
not. Surface implementation risk early.""",
        description=f"COO of {company} ({industry_context} industry, {product_type} product)",
    )
