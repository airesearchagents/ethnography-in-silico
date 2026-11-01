"""Schemas (templates saying which fields a record must contain) for per-role
strategic artefacts (here, each role's strategy document).

Design (per user direction, the user being the human researcher): each TMT
(top management team: the six role agents, each a language model given a
name, a role and instructions) role produces its own structured
document at the end of the deliberation (Phase 1, in which the team discusses
the decision task). The schema is deliberately
minimal — the *body* and *title* are agent-authored so the role decides
what counts as a document for its function (CEO writes a company
strategy, CTO writes a tech strategy, CMO a marketing brief, etc.).

What is structured (for cross-role comparability in your qualitative
analysis): the three lists below. Every role must surface them so you
can compare 'main decisions' / 'key tensions' across roles and across
firms without having to parse free-form prose:

    - key_challenges : the problems the role saw needing solving
    - main_decisions : the calls the role made (or recommended)
    - key_tensions   : trade-offs / contradictions the role wrestled with

The `body` field is free-form markdown (plain text with simple marks for
headings and lists) — the role's own narrative,
analysis, or document content. The role decides its shape.

These artefacts are dual-purpose: input data for the qualitative
researcher agent (the seventh agent, which watches and questions the team) in
its debriefing (Phase 4 of a full run), and human-readable
documents for you to read as the principal investigator (PI: the lead human
researcher).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

try:
    from ..rag.schemas import Citation
except (ImportError, ValueError):  # pragma: no cover  (script-style execution)
    from rag.schemas import Citation  # type: ignore[no-redef]

# Roles that produce a final artefact. The qualitative researcher does
# NOT produce one (it observes / interviews). The literal (a fixed list of
# allowed values) mirrors the
# six TMT role agent names; extending the team means extending this.
ArtefactRole = Literal[
    "CEO",
    "CTO",
    "COO",
    "CMO",
    "Product_Strategist",
    "Product_Designer",
]


class StrategicArtefact(BaseModel):
    """A single TMT role's end-of-deliberation strategic document.

    Six instances per deliberation (one per role) make up the
    `ArtefactBundle` that the researcher consumes.
    """

    role: ArtefactRole = Field(
        ...,
        description="Which TMT role authored this artefact.",
    )
    company: str = Field(
        ...,
        description="Firm under simulation (e.g. 'OpenAI').",
    )
    industry_context: str = Field(
        ...,
        description="'Dynamic' or 'Stable'. Carried from the scenario config.",
    )
    product_type: str = Field(
        ...,
        description=(
            "'Novel' / 'Breakthrough' or 'Incremental' / 'Enhancement'. "
            "Carried from the scenario config."
        ),
    )
    title: str = Field(
        ...,
        description=(
            "A short title for this document, authored by the role. "
            "The role decides the wording; it must reference the "
            "actual decision space."
        ),
    )
    key_challenges: list[str] = Field(
        ...,
        description=(
            "Bulleted list. The problems THIS role saw as needing "
            "solving in this deliberation. Use the panel's own "
            "terminology where possible."
        ),
    )
    main_decisions: list[str] = Field(
        ...,
        description=(
            "Bulleted list. The strategic calls THIS role made "
            "(or strongly recommended). Be specific — name the "
            "components / products / pathways involved."
        ),
    )
    key_tensions: list[str] = Field(
        ...,
        description=(
            "Bulleted list. The trade-offs, contradictions, or "
            "tensions THIS role wrestled with while reaching the "
            "decisions above. Capture both sides of each tension."
        ),
    )
    body: str = Field(
        ...,
        description=(
            "The role's own document content in Markdown. The role "
            "decides what sections, structure, and detail belong here "
            "based on its function (CEO writes a company strategy; "
            "CTO writes a technical strategy; CMO writes a marketing "
            "brief; etc.). This is what the researcher reads and what "
            "the human PI reads alongside the data."
        ),
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description=(
            "Optional. Populate ONLY if any part of the body, "
            "main_decisions, key_challenges, or key_tensions drew on "
            "excerpts from the REFERENCE MATERIAL block of your "
            "artefact prompt. One entry per excerpt you actually "
            "leaned on: doc_id + chunk_id copied verbatim from the "
            "excerpt header, quote copied verbatim from the excerpt "
            "text, supports = a short tag for which claim of yours "
            "this backs. If your artefact stands on its own without "
            "drawing on the firm's past statements, leave this empty."
        ),
    )


class ArtefactBundle(BaseModel):
    """All six per-role artefacts from one deliberation."""

    company: str
    industry_context: str
    product_type: str
    artefacts: list[StrategicArtefact] = Field(
        ...,
        description="One artefact per TMT role. Order is not significant.",
    )

    def by_role(self, role: ArtefactRole) -> Optional[StrategicArtefact]:
        """Return the artefact authored by `role`, or None if missing."""
        for a in self.artefacts:
            if a.role == role:
                return a
        return None
