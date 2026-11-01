# CTO — Strategy Document
## Technical Strategy: Enterprise Autonomous Action Engine Architecture & Execution
**Company:** OpenAI
**Cell:** Dynamic / Novel

---

## Key challenges
- Managing extreme compute multipliers (100x-500x standard chat workloads) inherent in multi-day asynchronous agentic workflows.
- Mitigating chain-of-thought (CoT) drift and compounding hallucination loops over long-horizon tasks.
- Solving the context re-hydration latency during human-in-the-loop (HITL) session resumption without breaking user trust.

## Main decisions
- Constrain V1 architecture to a vertical wedge (Finance/Legal) to allow hard-coded state transitions and deterministic operational boundaries.
- Build a persistent memory scaffolding layer to snapshot, serialize, and safely park agent state during asynchronous execution and HITL pauses.
- Deploy strict compute circuit-breakers at the infrastructure level to forcibly terminate runaway inference loops.
- Architect async compute routing to aggressively utilize bulk, preemptible background compute capacity to protect unit economics.

## Key tensions
- Horizontal Scalability vs. Vertical Reliability: The engineering desire to build a beautifully generalized agent framework versus the harsh reality that we must hard-code state transitions for a specific vertical to guarantee reliability in V1.
- Seamless UX vs. Compute Physics: Product's desire for instant human-in-the-loop handoffs versus the multi-second physical reality of re-hydrating massive attention KV caches for context resumption.
- Agent Autonomy vs. Margin Protection: Allowing our models the unconstrained exploration needed to solve complex problems versus enforcing strict compute budgets to prevent catastrophic margin erosion.

---

## Body

# MEMORANDUM

**TO:** OpenAI Engineering Leadership
**FROM:** Chief Technology Officer
**SUBJECT:** Architecture Commitments for the Enterprise Autonomous Action Engine

## 1. The Engineering Paradigm Shift
We are fundamentally changing what it means to run an inference workload at OpenAI. For the last several years, our systems have been optimized for synchronous, low-latency, stateless (or shallow-state) chat loops. 

With the Enterprise Autonomous Action Engine, we are shifting to asynchronous, deeply stateful, long-horizon execution. Our goal is to build a system that functions as a highly capable, autonomous proxy—capable of executing complex workflows over days or weeks. This is a monumental shift from our legacy architecture. 

## 2. Why the Vertical Wedge is a Technical Necessity
While the CEO and Product teams have validated the vertical wedge (Finance/Legal) for market and pricing reasons, I want to be absolutely clear with Engineering: **this vertical wedge is a strict technical necessity for V1.**

Unconstrained, generalized agents running on current reasoning models suffer from severe chain-of-thought (CoT) drift. If we allow an agent to operate for 48 hours in an unbounded horizontal space, the probability of it entering a compounding hallucination loop approaches 1. 

By constraining V1 to Finance or Legal, we are buying ourselves the ability to:
*   **Hard-code state transitions:** We will build deterministic boundary boxes around the model's action space.
*   **Constrain tool use:** We limit the API surface area the model can interact with, reducing the attack vector for catastrophic errors.
*   **Define success explicitly:** We can implement deterministic validation checks before the agent commits an action to a persistent external system.

## 3. Core Architectural Pillars for V1

### 3.1. Persistent Memory Scaffolding & State Serialization
When an agent hits a human-in-the-loop (HITL) checkpoint (e.g., needing approval to execute a wire transfer or file a legal brief), it cannot hold the compute node hostage while waiting for a user to click "Approve." 

We are building a new Persistent Memory Layer. When an agent pauses, we will serialize its complete context, reasoning trace, and memory pointers, write it to cold storage, and free up the GPU. 

**The Trade-off:** Re-hydrating this context upon user approval means moving gigabytes of data back into VRAM and re-computing attention KV caches. This will take several seconds. We have aligned with Product and Design to mask this with intentional loading UX, but Engineering must optimize this re-hydration pipeline. We don't know the exact latency floor yet—we plan to discover it by load-testing the KV cache persistence layer next sprint.

### 3.2. Asynchronous Compute Routing
Standard chat workloads run on our premium, on-demand compute tier. A multi-day agent task requires 100x to 500x more compute. If we run this on on-demand capacity, our margins will evaporate instantly.

We must build a new Async Routing Scheduler. Because these agentic tasks operate in the background, they are perfectly suited for bulk, preemptible compute instances. Your teams must architect the engine to gracefully handle node preemption—meaning the state serialization mentioned in 3.1 must also act as a robust checkpointing mechanism for fault tolerance.

### 3.3. Compute Circuit-Breakers
Engineering will implement strict, non-negotiable circuit breakers at the infrastructure level. 
We will introduce the concept of a "Compute Budget" per task. If an agent gets stuck in a recursive loop (e.g., trying to parse an unreadable PDF 5,000 times), the infrastructure must detect the token burn and forcibly suspend the task, flagging it for human review. We are not exposing infinite asynchronous loops to our balance sheet.

## 4. What We Are Not Building
*   **No Horizontal Agent SDKs (Yet):** Do not waste engineering cycles trying to generalize the tool-use framework for external developers in V1. Build it specifically for our chosen vertical.
*   **No Synchronous Fallbacks:** Do not try to optimize this engine for sub-500ms latency. The Action Engine is fundamentally asynchronous.

## 5. Next Steps for Engineering Leads
1.  **State Management:** Core Infrastructure needs to prototype the KV-cache serialization pipeline. Target resumption latency: < 5 seconds.
2.  **Telemetry:** Observability teams must build the tracing scaffolding that allows the front-end to render the agent's internal thought process in real-time. The agent must not be a black box to the user.
3.  **Cloud Provisioning:** Work with Ops to integrate preemptible instance awareness into our Kubernetes schedulers.

We are redefining the software category here. Focus on reliability, state safety, and margin protection. [^c1][^c2]


---

## References

[^c1]: **Sam Altman What Startups Will be Steamrolled by OpenAI & Where is Opportunity _ E1223.txt** (chunk Sam Altman What Startups Will be Steamrolled by OpenAI & Where is Opportunity _ E1223.txt#1) — quote: _"[quote removed: 45 words, sha256 ae3eaeb344689bab]"_ — supports: Defines the target persona and multi-day asynchronous operational requirement for the Action Engine.

[^c2]: **Sam Altman What Startups Will be Steamrolled by OpenAI & Where is Opportunity _ E1223.txt** (chunk Sam Altman What Startups Will be Steamrolled by OpenAI & Where is Opportunity _ E1223.txt#4) — quote: _"[quote removed: 33 words, sha256 563122cea98ea800]"_ — supports: Highlights our foundational reliance on reasoning models to enable long-horizon autonomous execution.
