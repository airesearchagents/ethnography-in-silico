# CTO — final working draft (private)

*This is the role's last DRAFT before Phase 2. It is the*
*private precursor to the public artefact in*
*`02_strategy_documents/`. Peers did not see this content*
*during the deliberation.*

---

# Technology Strategy: Ambient Agent Mesh for Autonomous R&D

## 1. Technical Position & Architecture
**Architecture**: Hybrid Edge-Cloud Decentralized Network.
Our chosen direction—the Autonomous R&D Operator for Software Engineering—requires a fundamental shift from synchronous conversational APIs to massive, asynchronous multi-agent execution. 

- **Edge Layer (Client-Side)**: Small Language Models (<2B parameters) deployed locally within enterprise IDEs and developer environments. This layer handles continuous sensing, sub-second telemetry for the Designer's 'Radar' UI, and real-time intent routing without pinging the cloud for every state change.
- **Cloud Layer (Server-Side)**: Frontier massive models executing long-horizon, multi-step reasoning. To protect the COO's infrastructure constraints, the cloud will utilize aggressive batch inference rather than live streaming.
- **Connectivity**: A proprietary Model-to-Model (M2M) protocol that syncs context and coordinates state between the edge proxy and the cloud inference engines.

*Reasoning*: Monolithic cloud architectures cannot scale for continuous ambient sensing or massive parallel agent execution without hitting a relentless compute capacity ceiling. Decoupling edge perception and UI telemetry from heavy cloud reasoning optimizes unit economics while preserving the sub-second responsiveness required for user trust.

## 2. Asset Strategy
- **Frontier Models (Cloud)**: Proprietary, internal build. This remains our core intellectual property and reasoning moat.
- **Small Language Models (Edge) & IDE Integrations**: Open-weights and open-source (shared). We will open the edge intelligence and UI integration layers to commoditize the client side, encouraging seamless developer adoption and embedding into existing CI/CD tools.
- **M2M Protocol**: Proprietary standard, built in-house. 

## 3. Engineering Bets & Unknowns
- **Bet 1 (Compute Economics)**: We are betting that we can optimize batch inference in the cloud deeply enough to sustain 100,000+ persistent agent loops without violating our cloud vendor compute caps.
- **Bet 2 (Edge Telemetry)**: We are betting the local SLMs can extrapolate intermediate agent states sufficiently to drive the 'Radar' UX in real-time, bridging the gap between batched cloud updates.
- **Unknown (Execution Sandbox)**: We don't yet know the exact boundary of programmatic verification execution. We plan to discover through early enterprise PoCs whether clients require us to securely host the code compilation/test loops in our cloud, or if the edge agents will trigger these directly in the client's own VPCs. This drastically impacts our security and cloud liabilities.

## 4. Commitments & Options
- **Commits the firm to**: A structural reliance on enterprise integration capabilities (IDE plugins, CI/CD hooks), massive refactoring of our inference engines for asynchronous batching, and stringent enterprise data sovereignty compliance.
- **Leaves open**: The physical form factor. While we are targeting digital software R&D today, the decentralized M2M architecture remains fundamentally device-agnostic, preserving our optionality for Embodied AI when hardware supply chains mature.