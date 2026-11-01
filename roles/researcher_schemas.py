"""Pydantic schemas for the qualitative researcher's two-phase artifacts.

A schema is a template saying which fields a reply or record must contain, and
Pydantic is a Python tool that checks them. These schemas fix the form of what the
researcher agent (the language model that watches and questions the team) writes.
The two phases below are its own numbering; in a full run they are Phases 3 and 4.

Phase 1 — Silent observation
    The observer agent reads the deliberation (the team's discussion of the decision
    task, Phase 1 of a full run) log and emits an
    `ObservationSummary` (this module's main schema). The summary is
    structured field notes that drive Phase 2.

Phase 2 — Panel debriefing (the researcher questions the six role agents, together
called the panel)
    The debriefer agent emits one `PanelUtterance` per turn. The
    orchestrator (the code that runs each stage of a run) records who responded, with what, and feeds that back
    in for the next turn.

Both schemas mirror the YAML (a plain-text format for settings and lists) at
`protocols/ethnographic_protocol.yaml`, the protocol (the debrief's rules and topics).
The YAML is authoritative for human readers; this module is
authoritative for the runtime, meaning the running program (it is what the ADK
(Agent Development Kit: Google's ready-made software for building agents) `output_schema`
enforces). Keep the two in sync when either changes.

Method references (in comments only — not sent to the model):
- Charmaz, K. (2014). Constructing grounded theory (2nd ed.). SAGE.
- Patton, M. Q. (2015). Qualitative research and evaluation methods (4th ed.). SAGE.
- Strauss, A., & Corbin, J. (1998). Basics of qualitative research (2nd ed.). SAGE.
- Hine, C. (2015). Ethnography for the internet: Embedded, embodied and
  everyday. Bloomsbury.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

try:
    from ..rag.schemas import Citation
except (ImportError, ValueError):  # pragma: no cover  (script-style execution)
    from rag.schemas import Citation  # type: ignore[no-redef]

# Thematic-area letters (a thematic area is one topic of the debrief protocol)
# span the framework's (the shared software's) generic areas plus room
# for per-study overlay areas (a study's own topics, merged on top of the shared ones). Framework YAML carries A, B, C, I, J;
# the openness study's overlay adds D-H. Extending past J requires
# bumping this Literal (a fixed list of allowed values) and the coverage-map defaults in
# `orchestrator/panel_debriefing.py`.
ThematicAreaId = Literal["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]

# The six TMT (top management team) roles plus the special "group" address used by the panel
# format. We use a free `str` (rather than a Literal) so addressing a
# role from a non-standard team (e.g. for ablation studies, which remove a role to see what changes) does not
# require a schema change.


# ---------------------------------------------------------------------------
# Phase 1 — Observation summary
# ---------------------------------------------------------------------------

class Disagreement(BaseModel):
    """A disagreement, hesitation, or position shift observed in the deliberation."""

    topic: str = Field(
        ...,
        description="What the disagreement was about, in the panel's own words.",
    )
    parties: list[str] = Field(
        ...,
        description="The roles that took different positions (e.g. ['CTO', 'CMO']).",
    )
    resolution: str = Field(
        ...,
        description=(
            "How (if at all) the disagreement was resolved. Use 'unresolved' "
            "if it was left open. Quote the panel's wording where possible."
        ),
    )


class RoleContribution(BaseModel):
    """What a single role pushed for, pushed back on, or was quiet on."""

    role: str = Field(..., description="The TMT role name, e.g. 'CEO', 'CTO'.")
    pushed_for: list[str] = Field(
        default_factory=list,
        description="Items / positions this role advocated for, in the panel's wording.",
    )
    pushed_back_on: list[str] = Field(
        default_factory=list,
        description="Items / positions this role pushed back against.",
    )
    quiet_on: list[str] = Field(
        default_factory=list,
        description=(
            "Topics where this role notably did not contribute. Only "
            "include if the silence was salient (e.g. CTO silent on a "
            "purely technical decision)."
        ),
    )


class FlaggedVocabularyUse(BaseModel):
    """Spontaneous use of a watch-listed word by a panelist.

    The watch-list (`StudyConfig.flagged_vocabulary`) is a capture
    mechanism, not a steering mechanism: if the panel surfaces one of
    these words on their own, log the use here so the debriefer can
    legitimately echo it back later (protocol §4.4 permits echoing
    panel-introduced terms). The Observer is told WHICH words to flag
    but not WHY they matter.
    """

    word: str = Field(..., description="The watch-listed word the panelist used.")
    role: str = Field(..., description="Which role said it.")
    context: str = Field(
        ...,
        description=(
            "The surrounding panel utterance, verbatim if possible, so a "
            "reviewer can verify that the use was spontaneous."
        ),
    )


# Back-compat (backward compatibility: older code and saved records keep working) alias — old callers / persisted artefacts referencing
# the original class name still resolve. New code should use
# `FlaggedVocabularyUse`.
LoadedVocabUse = FlaggedVocabularyUse


class ObservationSummary(BaseModel):
    """Researcher's pre-debriefing field notes. Drives every Phase-2 question.

    The observer agent produces exactly one instance of this per
    deliberation. The debriefer agent reads it once when its system
    prompt is composed and references items from `decisions`,
    `components`, and `disagreements` as `anchor_refs` on every
    `PanelUtterance` it emits.
    """

    # Allow population by either the new name (`flagged_vocabulary_used`)
    # or the legacy alias (`loaded_vocabulary_used`). Lets existing
    # persisted JSON dumps (records saved earlier as plain text with named fields) load
    # without migration.
    model_config = {"populate_by_name": True}

    decisions: list[str] = Field(
        ...,
        description="Major decisions the TMT made, in their own words.",
    )
    components: list[str] = Field(
        ...,
        description=(
            "Components, products, or assets discussed, with the specific "
            "terminology the panel used. Do not paraphrase into "
            "researcher-side categories."
        ),
    )
    disagreements: list[Disagreement] = Field(
        default_factory=list,
        description="Disagreements, hesitations, position shifts observed.",
    )
    role_contributions: list[RoleContribution] = Field(
        default_factory=list,
        description="What each role pushed for, pushed back on, was quiet on.",
    )
    alternatives_considered: list[str] = Field(
        default_factory=list,
        description="Alternatives the TMT considered but did not pursue.",
    )
    flagged_vocabulary_used: list[FlaggedVocabularyUse] = Field(
        default_factory=list,
        alias="loaded_vocabulary_used",  # back-compat with persisted JSON
        description=(
            "Spontaneous use by a panelist of any word on the study's "
            "`flagged_vocabulary` watch-list. A capture mechanism — "
            "logging it here permits the debriefer to echo the panel's "
            "own framing later. The Observer is told which words to "
            "flag but not why they matter."
        ),
    )


# ---------------------------------------------------------------------------
# Phase 2 — Panel debriefing
# ---------------------------------------------------------------------------

class PanelUtterance(BaseModel):
    """One researcher turn in the panel debriefing.

    The debriefer emits this once per orchestrator iteration. The
    orchestrator validates it against the forbidden-vocabulary rule and
    the "must have anchor_refs" rule before delivering it to the panel.
    """

    area_id: ThematicAreaId = Field(
        ...,
        description="Which thematic area this utterance belongs to.",
    )
    addressed_to: str = Field(
        "group",
        description=(
            "'group' to invite any panelist (the default); otherwise a "
            "specific role name (e.g. 'CTO') when that role's perspective "
            "is specifically needed."
        ),
    )
    text: str = Field(
        ...,
        description=(
            "The actual question / probe addressed to the panel. Must "
            "reference observed items from the field notes and must not "
            "contain forbidden vocabulary unless echoing a panelist."
        ),
    )
    anchor_refs: list[str] = Field(
        ...,
        description=(
            "Items from the ObservationSummary (decisions / components / "
            "disagreements topics) or from the panel's answers in this "
            "debriefing that this utterance references, verbatim. Empty "
            "list is invalid — "
            "every question must be anchored in observed behaviour."
        ),
    )
    is_followup: bool = Field(
        False,
        description=(
            "True if this is a follow-up probe to the immediately previous "
            "exchange. Helps the analysis trace probe chains."
        ),
    )
    research_question_link: str = Field(
        "",
        description=(
            "How this question could help explore the research question, or "
            "`adjacent` if it follows something else. For the research "
            "record only; never shown to the panel."
        ),
    )
    emerging_question: str = Field(
        "",
        description=(
            "A new question worth studying that this exchange raised and "
            "the research question does not cover. Empty if none. For the "
            "research record only; never shown to the panel."
        ),
    )
    ends_debriefing: bool = Field(
        False,
        description=(
            "Set to True ONLY on the closing utterance, after the closing "
            "area has been asked and answered, or when follow-ups are producing "
            "thin or repetitive material."
        ),
    )


# ---------------------------------------------------------------------------
# Panel exchange — bookkeeping schema for the orchestrator (not for LLM, or large language model, input and output)
# ---------------------------------------------------------------------------

class PanelResponse(BaseModel):
    """One role's response to a researcher utterance."""

    role: str = Field(..., description="Which TMT role responded.")
    text: str = Field(..., description="The role's response, verbatim.")
    is_cross_talk: bool = Field(
        False,
        description=(
            "True if this response is a reaction to another role's "
            "preceding response in the same exchange (adding, qualifying, "
            "or contradicting)."
        ),
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description=(
            "Optional. Populate ONLY if your response drew on excerpts "
            "from the REFERENCE MATERIAL block in your panellist "
            "prompt. One entry per excerpt you actually leaned on: "
            "doc_id + chunk_id copied verbatim from the excerpt "
            "header, quote copied verbatim from the excerpt text, "
            "supports = a short tag for which claim of yours this "
            "backs. If you answered from memory or from your own "
            "judgment without drawing on the firm's past statements, "
            "leave this empty."
        ),
    )


def split_panel_reply(text: str) -> tuple[str, list[dict]]:
    """Separate an answer from any citations a panellist wrapped around it.

    Grounded panellists (those given a firm's real documents to cite) are told to populate `citations`, and without a
    structured schema on this call they can reply with a JSON object, often
    fenced (wrapped in code marks). Returns the answer text and the citations as dicts. Anything that
    is not such an object comes back unchanged, with no citations.
    """
    stripped = (text or "").strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    wrapped = stripped.startswith(("{", "```")) or '"citations"' in stripped
    if start < 0 or end <= start or not wrapped:
        return text, []
    try:
        reply = json.loads(stripped[start : end + 1])
    except ValueError:
        return text, []
    if not isinstance(reply, dict):
        return text, []
    listed = reply.get("citations")
    citations = [c for c in listed if isinstance(c, dict)] if isinstance(listed, list) else []
    body = next(
        (reply[key] for key in ("body", "text", "response", "answer")
         if isinstance(reply.get(key), str)),
        None,
    )
    if body is not None:
        return body, citations
    # Prose first, then a citations object: keep the prose.
    prose = stripped[:start].rstrip().removesuffix("```json").removesuffix("```").strip()
    return prose or text, citations


def valid_citations(entries: list[dict]) -> list[Citation]:
    """The citations that validate. One malformed entry must not lose an answer."""
    valid = []
    for entry in entries:
        try:
            valid.append(Citation.model_validate(entry))
        except ValueError:
            continue
    return valid


class PanelExchange(BaseModel):
    """One full exchange: a researcher utterance plus all role responses to it."""

    utterance: PanelUtterance
    responses: list[PanelResponse] = Field(default_factory=list)
    lost_roles: list[str] = Field(
        default_factory=list,
        description=(
            "Roles whose answer was lost to a failed model call. A [PASS] "
            "is data; a lost answer is not, so the two are kept apart."
        ),
    )
