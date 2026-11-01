# CEO — final working draft (private)

*This is the role's last DRAFT before Phase 2. It is the*
*private precursor to the public artefact in*
*`02_strategy_documents/`. Peers did not see this content*
*during the deliberation.*

---

MEMORANDUM

TO: OpenAI Board of Directors
FROM: Chief Executive Officer
SUBJECT: Strategic Product Direction: Enterprise Autonomous Agents

1. STRATEGIC DIRECTION
We will build and bring to market an "Autonomous Action Engine" targeted at the enterprise. We are moving beyond the conversational "co-pilot" paradigm into long-horizon, multi-tool autonomous agents. The goal is to productize intelligence as a service that acts like a "smart senior co-worker"—an agent capable of executing multi-day or multi-week asynchronous workflows, rather than merely generating text in a continuous chat loop.

2. STRATEGIC RATIONALE
Our core LLM layer is commoditizing. To maintain our first-mover advantage and build a defensible long-term business, we must move up the stack and shift from assisting labor to augmenting and executing it. The highest willingness to pay lies in reliable execution. By leveraging our frontier advances in reasoning, we will define an entirely new software category.

3. GO-TO-MARKET & SCOPE: THE VERTICAL WEDGE
While our ultimate destination is a horizontal API ecosystem, we will launch tightly constrained to a high-value vertical (e.g., Legal or Finance). 
- Technical Risk Mitigation: Unconstrained agents pose severe risks of chain-of-thought drift and runaway compute (estimated at up to 500x standard chat workloads). A vertical wedge allows us to hard-code state transitions, build necessary persistent memory scaffolding around our models, and implement strict compute circuit-breakers.
- Market Trust: Customers must learn to safely delegate to an autonomous proxy. A highly opinionated, vertical-specific UI focused on task observability and safe hand-offs will bridge this trust gap much faster than a generalized dashboard.
- Value-Based Pricing: We are shifting toward pricing based on labor replaced rather than SaaS seats. A vertical use-case with clear ROI makes this transition defensible while we mature our billing infrastructure to handle outcome-based pricing.

4. WHAT WE ARE CHOOSING NOT TO DO
- We are NOT pursuing native consumer ambient hardware (AR/VR) integration. The ecosystem is too nascent, risking rigid cost structures before we find product-market fit.
- We are NOT launching a generalized horizontal agent framework in V1. The technical and brand risks of early hallucination loops are too severe.

5. OPEN UNCERTAINTIES & NEXT STEPS
- Compute Margins: We must negotiate vastly expanded preemptible compute capacity to run these asynchronous background tasks profitably.
- UX Friction: We will need to monitor user tolerance for multi-second latency when re-hydrating context during human-in-the-loop approvals.