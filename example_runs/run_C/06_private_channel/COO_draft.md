# COO — final working draft (private)

*This is the role's last DRAFT before Phase 2. It is the*
*private precursor to the public artefact in*
*`02_strategy_documents/`. Peers did not see this content*
*during the deliberation.*

---

OPERATIONS STRATEGY: NOVEL PRODUCT INCUBATION
*Working Assumption: Persistent, Autonomous Enterprise Agents (Enterprise Autonomous Orchestrator)*

1. OPERATIONAL REALITY & RESOURCES
Our current operating model, infrastructure, and vendor agreements are heavily optimized for synchronous, stateless API calls and one-shot conversational interfaces. Pivoting to persistent, autonomous agents fundamentally alters our resource utilization. 
- Compute: This requires stateful, continuous compute. I do not yet know the exact compute-to-revenue ratio for a persistent agent. We plan to discover this by carving out a strict, hard-capped compute sandbox from our existing R&D cluster to run a 6-week pilot capped at 3 partners. 
- Vendor Reality: We cannot commit to large-scale, multi-year CapEx for specialized infrastructure until we understand the dominant design of this new product.

2. GOVERNANCE
We will govern this initiative via Stage-Gate funding rather than an annual budget allocation. The cross-functional incubation team will operate entirely with internal transfers (a 'tiger team') until they can demonstrate a viable, scalable unit-economic model. Heavy infrastructure commits require CEO and COO sign-off at Gate 2.

3. SCALE-UP PLAN
- Phase 1 (Months 1-3): Sandboxed experimentation with 2-3 trusted enterprise design partners. Focus is strictly on uncovering technical bottlenecks and measuring baseline compute burn. Billing for these early pilots will use bespoke, flat-rate manual contracts to bypass our current rigid token/SaaS billing systems.
- Phase 2 (Months 4-6): Conditional scale-up. If unit economics are viable, we will activate pre-negotiated flex-capacity clauses with our secondary cloud vendors. This prevents vendor lock-in while the product is still in the fluid phase of innovation.

4. ORGANIZATIONAL IMPLICATIONS & TALENT
Our talent pool is currently skewed toward model researchers and API-focused engineers. To support autonomous systems, we will face an immediate gap in Site Reliability Engineering (SRE) for long-running processes, as well as safety engineers focused on agentic loops. We will need to redirect recruiting spend to pipeline systems orchestration engineers immediately.

5. OPERATIONAL RISKS
- Runaway Compute: A persistent agent caught in an execution loop could silently burn massive compute capacity. We need strict, automated circuit breakers at the infrastructure level.
- Vendor Concentration: Relying entirely on our primary cloud partner for experimental architecture limits our leverage. We must multi-home this early.
- Compliance & Liability: Autonomous actions in enterprise environments carry heightened operational and legal risks that our current trust & safety operations are not scaled to monitor.

6. DECISIONS FOR RE-EXAMINATION
As we transition out of Phase 1 manual billing, we must re-evaluate our pricing operations. Our current token-based billing systems simply cannot handle variable-compute consumption effectively. We will need to design an automated pivot to compute-time or value-based billing, pulling from telemetry gathered during the design partner phase.