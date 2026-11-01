"""Orchestration layer for the multi-agent research session (one complete simulated
meeting and debrief, also called a run).

This folder runs a simulated meeting from start to finish. It calls the agents
(language models given a name, a role and instructions) in the right order and
collects what they write.

Composes the agent factories (the functions that build each agent) in `roles/`
into the three sequential phases (numbered stages of a run) that produce the
qualitative dataset:

    1. TMT (top management team: the six agents playing executives) deliberation (their
       discussion of the decision task)  →  inter-agent message log
       (see `agent.py::TMTSystemWithA2A.run_strategic_discussion`; A2A, or
       agent-to-agent, a way for agents to call each other, was removed and
       survives only in this name)

    2. Per-role artefact (the strategy document each role writes) collection
       →  six strategic documents
       (see `orchestrator.artefact_collection`)

    3. Observer (the researcher agent summing up what it saw) + panel
       debriefing (its interview of the six role agents)  →  observation
       summary + transcript
       (see `orchestrator.panel_debriefing`)

A higher-level wrapper (`run_research_session`) ties all three phases
into a single call. The orchestrator is intentionally separate from
the agent factories so the factories stay pure (they build agents and run
nothing) and unit-testable (checkable by small automatic tests)
without spinning up the full multi-phase pipeline.
"""

from .artefact_collection import collect_role_artefacts
from .panel_debriefing import run_panel_debriefing, DebriefingTranscript

__all__ = [
    "collect_role_artefacts",
    "run_panel_debriefing",
    "DebriefingTranscript",
]
