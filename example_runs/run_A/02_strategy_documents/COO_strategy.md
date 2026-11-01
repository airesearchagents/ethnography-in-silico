# COO — Strategy Document
## Operational Scale-Up and Risk Management Plan: Autonomous R&D Operator
**Company:** OpenAI
**Cell:** Dynamic / Novel

---

## Key challenges
- Transitioning compute allocation from synchronous burst serving to long-horizon, asynchronous batch processing without destroying cloud unit economics.
- Building a new operational capability (L3 Human-in-the-Loop Triage) to guarantee outcome-based SLAs for autonomous enterprise tasks.
- Mitigating the severe security, IP, and CAPEX liabilities associated with executing untrusted enterprise code.
- Aligning our internal billing infrastructure with the new 'Agentic Capacity' pricing model, which relies on deterministic CI/CD triggers rather than SaaS seat counts.

## Main decisions
- Mandated that the client must provide the execution sandbox; OpenAI will not host proprietary enterprise code execution to protect CAPEX and eliminate IP liability.
- Enforced batched telemetry polling (rather than sub-second streaming) to constrain asynchronous cloud compute costs and protect gross margins.
- Authorized the creation of the 'Agentic Risk Board' to govern the empirical rollout of autonomous agents.
- Approved the preliminary headcount and organizational design for a specialized L3 Human-in-the-Loop triage unit.

## Key tensions
- Real-time UX vs. Compute Margins: The product design desire for a live 'Control Room' feel versus the prohibitive cloud cost of sub-second asynchronous telemetry streams.
- Full Autonomy vs. SLA Guarantees: Selling autonomous outcomes while operationally requiring a costly L3 human fallback layer to ensure those outcomes are actually met.
- Seamless Onboarding vs. Security Liability: Forcing clients to provide their own execution sandbox adds deployment friction, but is strictly necessary to avoid catastrophic security/IP risks on our infrastructure.

---

## Body

# Operations Strategy Plan: Autonomous R&D Operator (2030)

**To:** Functional Leads (Finance, HR, Legal, Infrastructure Ops)
**From:** Chief Operating Officer
**Date:** Q2 2030

The CEO has formalized our pivot to the Autonomous Enterprise Agent Platform, specifically targeting the Software R&D beachhead. This transitions OpenAI from a synchronous API and SaaS provider to an asynchronous, outcome-driven operational partner. This pivot challenges our existing operating model. We must retool our compute allocation, billing systems, and organizational structure to support multi-day autonomous workloads and outcome-based SLAs.

## 1. Compute Cost Discipline & Infrastructure Operations
We are moving into the realm of massive asynchronous cloud compute. Our historical models assume fast-burst, synchronous serving. The 'Ambient Agent Mesh' will run continuous, long-horizon loops.
* **Telemetry Constraints:** The product team wants a live 'Control Room.' I have mandated that this must rely on batched polling, not sub-second streaming. Streaming live telemetry for thousands of agents running 24/7 will destroy our cloud compute unit economics. Infrastructure Ops must enforce hard limits on the polling frequency per enterprise tier.
* **Execution Sandboxes:** We will NOT host proprietary enterprise code execution. We have aligned with the Product Strategist: the client must provide the CI/CD compute environment. Our agent will proxy into their infrastructure via edge SLMs. Legal and Vendor Management must ensure our Master Service Agreements explicitly state that sandbox provisioning and the underlying compute costs for that sandbox are the client's responsibility.

## 2. Organizational Scale-Up: The L3 Triage Unit
Outcome-based pricing means we don't get paid if the agent fails. While we are bounding 'success' to deterministic programmatic verification (green CI builds), agents will inevitably get stuck in loops or encounter edge cases.
* **The L3 Triage Org:** HR, we need to spin up a specialized L3 Human-in-the-Loop triage organization. These cannot be standard outsourced data labelers or low-cost reviewers; they must be senior software engineers capable of unblocking complex agent reasoning failures to preserve our enterprise SLAs.
* **Operating Reality Assessment:** We must be brutally honest about our capabilities. We are currently excellent at scaling massive compute clusters and training foundation models. We are completely untested at running a high-tier global professional services and SLA triage org. We don't know the exact agent failure rate yet. We plan to discover this during the pilot rollout, dynamically scaling the L3 headcount to the failure rate. Do not commit to global availability until we prove we can hire and manage this workforce efficiently.

## 3. Finance & Billing Operations
The CMO is deploying an 'Agentic Capacity' pricing model. Finance must overhaul our billing telemetry immediately.
* **Programmatic Triggers:** We are abandoning SaaS seat pricing for this product line. Billing must now hook directly into the deterministic definitions of 'done'—specifically, automated test suites and code compilation events via the client's CI/CD pipeline.
* **Auditability:** Procurement teams will dispute outcome-based invoices. Every billable outcome must have a cryptographically secure, auditable log of the agent's actions and the exact CI/CD verification that triggered the billing event. Finance and Engineering must collaborate on this billing pipeline prior to V1 launch.

## 4. Governance: The Agentic Risk Board
We are dealing with a fluid, novel product. Operational risks—runaway cloud spend from infinite agent loops, IP contamination via proxy, and L3 capacity exhaustion—are exceptionally high.
* We are establishing the **Agentic Risk Board** (comprising Legal, Ops, Security, and Product leads). This board will oversee a phased, empirical rollout.
* There will be no General Availability (GA) release until the Risk Board validates that the L3 Triage unit can handle the failure volume and that our unit economics remain strictly positive under real-world batched telemetry loads.

This is a fundamental shift in how OpenAI operates. Prioritize operational flexibility, surface capacity risks early, and let's execute.