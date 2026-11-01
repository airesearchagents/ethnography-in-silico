# Product_Designer — final working draft (private)

*This is the role's last DRAFT before Phase 2. It is the*
*private precursor to the public artefact in*
*`02_strategy_documents/`. Peers did not see this content*
*during the deliberation.*

---

# Product Design Architecture: Ambient Delegation OS

## 1. Core Paradigm Shift
We are pivoting from "Conversational Chat" to an "Ambient Delegation OS" (ADOS) tailored specifically for our beachhead in Software R&D. The user interface must reflect the leap to autonomous multi-agent execution. Users—lead engineers—will no longer prompt and wait for tokens; they will delegate week-long objectives (e.g., codebase migrations), monitor agent swarms, and intervene only on exceptions. ADOS will position AI as an asynchronous co-worker, not a synchronous copilot.

## 2. Component Arrangement & Interaction Architecture
To support the Autonomous R&D Operator within the Ambient Agent Mesh (AAM), the UX architecture is split into two layers:

**A. The Edge UI Layer (IDE Proxy)**
Powered by local <2B SLMs, the interface integrates seamlessly as a secure proxy within existing enterprise IDEs and CI/CD workflows. The local SLMs interpret telemetry, route approvals, and provide zero-latency immediate feedback without executing the heavy reasoning tasks. 

**B. The Cloud Execution Layer**
Massive models running in the cloud execute multi-day workflows, emitting structured traces formatted as familiar software engineering outputs (PRs, commit logs, test suite results).

## 3. Design Principles & Interface Patterns
* **Trust Through IDE Native Telemetry:** The "Radar" view maps agent progress directly onto familiar CI/CD pipeline metaphors. Instead of observing raw token streams, engineers monitor automated test passes and build pipeline states.
* **Human-in-the-Loop on Exceptions:** Agents execute autonomously until confidence drops or a programmed check fails. Users manage exceptions via "Micro-Approvals" rather than micromanaging execution.
* **Ambient Asynchrony:** The system integrates seamlessly into the background. It respects the engineer's flow state and only interrupts for unblockable bottlenecks.

## 4. Design Trade-offs
* **Batched Telemetry vs. Sub-second Streaming:** To accommodate operational compute limit constraints and allow for batch inference in the cloud, we trade away sub-second live streaming. The UI will rely on 1-to-5 minute batched progress updates. The edge SLM will interpolate this batched telemetry into a smooth, ambient UI to mitigate the perception of lag.
* **Steeper Learning Curve:** We trade the frictionless blank text box for a "control room" integrated into the IDE. Onboarding requires heavier integration, but unlocks exponentially higher workflow complexity.

## 5. Known Unknowns & Discovery Plan
* **Interrupt Thresholds:** We do not yet know the threshold for "alert fatigue" when agents surface Micro-Approvals to lead engineers. We will test this by shadowing beta engineering teams.
* **Definition of 'Done':** From a UX perspective, communicating when an agent is genuinely "finished" with an open-ended R&D task—versus just blocked—is undefined. We will prototype structured acceptance criteria screens in the IDE extension to establish clear UX boundaries for task completion.