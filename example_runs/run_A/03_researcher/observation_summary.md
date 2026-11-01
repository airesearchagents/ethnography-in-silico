# Researcher observation summary

## Decisions
- Commit fully to developing the Autonomous Enterprise Agent Platform
- Select B2B Software Engineering & R&D as our initial beachhead market
- Explicitly decline to pursue Embodied AI
- Adopt an Agentic Capacity pricing model
- Mandated a client-hosted execution sandbox model
- Prioritized batched telemetry polling over live continuous streaming
- Adopted the Ambient Agent Mesh architecture
- establish the Agentic Risk Board

## Components / assets discussed
- Autonomous Enterprise Agent Platform
- Autonomous R&D Operator
- Ambient Agent Mesh
- Ambient Delegation OS
- Vision-Language-Action foundation model
- Model-to-Model communication protocol
- edge SLMs
- Agentic Capacity pricing model
- L3 Human-in-the-Loop triage org
- Agentic Risk Board
- Radar view
- client-hosted execution sandbox
- edge proxy
- Telemetry Interpolation
- Micro-Approval framework

## Disagreements
- **Embodied AI vs. Autonomous Enterprise Agents** between CEO, COO, CMO → _CEO tabled the Embodied AI proposal due to physical liability risks and agreed to formally commit to the Autonomous Enterprise Agent platform._
- **Sub-second state streaming vs. batched telemetry polling** between Product_Designer, COO, CTO → _Prioritized batched telemetry polling to preserve cloud unit economics, utilizing edge SLMs for UI interpolation._
- **Hosting the execution sandbox** between CTO, Product_Strategist → _Mandated that the enterprise client MUST provide the sandbox and CI/CD compute environment._

## Role contributions
### CEO
- Pushed for: Embodied AI, Vision-Language-Action foundation model, Autonomous Enterprise Agent Platform, outcome-based pricing
- Pushed back on: SaaS seat pricing

### CTO
- Pushed for: Ambient Agent Mesh, hybrid edge-cloud architecture, Model-to-Model communication protocol, edge SLMs, asynchronous batch processing
- Pushed back on: monolithic conversational interfaces

### COO
- Pushed for: batched telemetry polling, compute circuit breakers, L3 Human-in-the-Loop triage org, Agentic Risk Board
- Pushed back on: Embodied AI, sub-second state streaming, hosting proprietary enterprise code execution

### CMO
- Pushed for: autonomous, multi-agent systems for enterprise operations, Software Engineering and Financial Operations beachheads, Agentic Capacity pricing model, Elevating the Engineer brand narrative, IDE-Native GTM Motion
- Pushed back on: Embodied AI, standalone OpenAI Control Room application

### Product_Strategist
- Pushed for: Autonomous R&D Operator, B2B Enterprise initial wedge, deterministic, programmatic verification, client-hosted execution sandbox
- Pushed back on: human-in-the-loop copilots, subjective human acceptance criteria, hosting proprietary enterprise code on our infrastructure

### Product_Designer
- Pushed for: Ambient Delegation OS, Radar view, Telemetry Interpolation, Micro-Approval framework, IDE-native integration
- Pushed back on: conversational chat paradigm

## Alternatives considered (but not pursued)
- Embodied AI
- Vision-Language-Action foundation model for third-party robotic hardware
- Standalone proprietary OpenAI-branded Control Room application
- Sub-second, push-based state streaming from the cloud to the edge UI
- Pure outcome-based pricing
- SaaS seat pricing

## Spontaneous use of watch-listed vocabulary
- **CTO** said _'modular'_ in: The dynamic nature of our environment demands modularity. Monolithic scaling is hitting latency, privacy, and cost limits.
- **CTO** said _'open-source'_ in: This dictates whether I should open-source the edge integration layers to encourage developer adoption, or keep the entire client-side architecture strictly proprietary.
- **COO** said _'closed'_ in: I am assuming we can firewall our risk by licensing the VLA strictly as a 'guidance API' rather than a closed-loop controller, but I haven't verified if Tier-1 OEMs will accept those terms.
- **CTO** said _'boundary'_ in: I need to know this to properly architect our security boundaries and assess our cloud compute liabilities.
- **CEO** said _'value capture'_ in: Value Capture vs. Margin Destruction: Capturing the non-linear value of autonomous work via outcome-based pricing, while strictly bounding the definition of 'done' to prevent infinite revision loops from subjective human clients.
- **CMO** said _'value capture'_ in: Outcome-Based Value Capture vs. Procurement Predictability: We want to charge for the massive non-linear value of completed work, but enterprise buyers require predictable CAPEX/OPEX budgets.