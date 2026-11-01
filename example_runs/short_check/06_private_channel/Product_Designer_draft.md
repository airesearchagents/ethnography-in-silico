# Product_Designer — final working draft (private)

*This is the role's last DRAFT before Phase 2. It is the*
*private precursor to the public artefact in*
*`02_strategy_documents/`. Peers did not see this content*
*during the deliberation.*

---

# Product & UX Design Document: Autonomous Scientific Collaborator

## 1. Strategic Context & Vision
Our next major product bet moves beyond explicit, turn-based chat interfaces into the realm of fully autonomous, long-running agentic workflows. Aligning with the CTO's proposal for "PhD-level intelligence," we are optimizing for a product that accelerates complex, high-stakes domains—most notably, scientific R&D. The primary objective is to design a platform capable [source text removed]."

We are intentionally trading away the low-latency, generalized consumer chat experience to build a specialized, high-trust enterprise paradigm.

## 2. Core UX Paradigm: The "Senior Co-Worker"
In the consumer space, AI is often conceptualized as a seamless "extension of the user." For this novel product, we are adopting a strictly different design principle: the AI as a distinct, highly capable "senior employee." As noted in our strategic assumptions, "[source text removed]" for complex, long-duration tasks.

This means the user experience fundamentally shifts from *chatting* to *delegation and management*.

## 3. Key Interaction Patterns
**Asynchronous Execution & Pinging:** Users will scope a project, and they will "[source text removed]." The UI will require:

*   **The Mission Control Dashboard:** A visual interface showing active autonomous tasks, compute utilization, and estimated completion times.
*   **Interrupt & Clarify Workflows:** When the agent hits an ambiguity, it surfaces a precise, bounded question to the human operator rather than halting entirely.
*   **Audit Trails (The "Show Your Work" feature):** In scientific and medical domains, outputs are useless without verifiable methodology. The agent must visually log its reasoning steps, API calls to simulators, and literature reviews.

## 4. Open Questions & Discovery Plan
*   **Trust Calibration:** We don't yet know how users will tolerate an agent spending high compute resources over a week without constant human oversight. We plan to discover this by prototyping bounded "check-in" gates where the agent must present a milestone before proceeding.
*   **Modality Needs:** Will scientists need spatial/visual manipulation of the data the agent returns, or are traditional 2D GUIs sufficient? We need to test the post-generation workflow.