"""Panel-debriefing orchestrator.

Drives the qualitative researcher's Phase-2 debriefing one turn at a
time, routing each utterance to the addressed role (or inviting the
whole panel for group questions) and collecting the responses.

Loop semantics
--------------
On each researcher turn:
  1. Run the debriefer agent. It returns a single `PanelUtterance`.
  2. Run the forbidden-vocabulary guard against the utterance text
     (allowing echoes of words the panel itself used). On violation,
     re-prompt the debriefer ONCE with the violations quoted. If the
     rewrite still violates, log it and continue with the rewrite
     anyway — we will not stall the session indefinitely.
  3. Route the utterance:
       - `addressed_to="group"`: invite each TMT role one chance to
         respond (in role-rotation order); a role may decline by
         returning an empty response. Cross-talk = multiple roles
         responding to the same researcher utterance.
       - `addressed_to=<role>`: just that role responds, then any
         other role may volunteer a follow-on (one additional pass)
         to support cross-talk per protocol §4.1.
  4. Append the exchange (utterance + responses) to the transcript.
  5. Stop iff `utterance.ends_debriefing` is True OR the safety cap
     (`max_exchanges`, default 60) is hit.

Stop criterion
--------------
Per user direction, the researcher's stop rule is **relevance-based**:
continue as long as material is relevant — or even adjacent — to the
research question. The default research question is the openness /
value-capture framing from the conversation; it is a parameter so the
PI can refine it later without code changes.

A hard safety ceiling (`max_exchanges`) prevents a runaway debriefing.
60 is the default; tune as needed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Awaitable, Callable, List, Optional

from google.adk.agents import LlmAgent
from pydantic import BaseModel, Field

try:
    from ..providers import get_model
    from ..roles.artefact_schemas import ArtefactBundle
    from ..roles.forbidden_vocab import check_utterance, format_violations
    from ..roles.qualitative_researcher_agent import (
        create_debriefer_agent,
        utterance_violates_protocol,
    )
    from ..roles.researcher_schemas import (
        ObservationSummary,
        PanelExchange,
        PanelResponse,
        split_panel_reply,
        valid_citations,
        PanelUtterance,
    )
    from ..rag.schemas import RetrievedSnippet
    from ..rag.prompt_inject import format_retrieved_context
    from ..rag.queries import build_panellist_query
    from ..rag.runtime import RagSession
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from providers import get_model  # type: ignore[no-redef]
    from roles.artefact_schemas import ArtefactBundle  # type: ignore[no-redef]
    from roles.forbidden_vocab import check_utterance, format_violations  # type: ignore[no-redef]
    from roles.qualitative_researcher_agent import (  # type: ignore[no-redef]
        create_debriefer_agent,
        utterance_violates_protocol,
    )
    from roles.researcher_schemas import (  # type: ignore[no-redef]
        ObservationSummary,
        PanelExchange,
        PanelResponse,
        split_panel_reply,
        valid_citations,
        PanelUtterance,
    )
    from rag.schemas import RetrievedSnippet  # type: ignore[no-redef]
    from rag.prompt_inject import format_retrieved_context  # type: ignore[no-redef]
    from rag.queries import build_panellist_query  # type: ignore[no-redef]
    from rag.runtime import RagSession  # type: ignore[no-redef]

# StudyConfig is only used in type hints; lazy-import the actual class
# inside the few functions that need it to avoid import cycles.
try:
    from ..studies import StudyConfig
except (ImportError, ValueError):  # pragma: no cover
    try:
        from studies import StudyConfig  # type: ignore[no-redef]
    except (ImportError, ValueError):  # pragma: no cover
        StudyConfig = object  # type: ignore[misc, assignment]

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default research question — can be overridden per session
# ---------------------------------------------------------------------------

# DEFAULT_RESEARCH_QUESTION lived here pre-multi-study-refactor. It's
# now a property of `studies/openness_maneuvering/__init__.py::STUDY.
# research_question`. Kept as a thin alias for back-compat with the
# few legacy callers that still import it; resolved lazily on first
# access via __getattr__ so this module can be imported without
# triggering `load_study()` (which would cause an import cycle if
# the study itself imports from `orchestrator/`).
def _default_research_question() -> str:
    """Lazily resolve the default research question from the default
    study config. Avoids an import cycle at module-load time."""
    try:
        from ..studies import load_study, DEFAULT_STUDY_SLUG
    except (ImportError, ValueError):  # pragma: no cover
        from studies import load_study, DEFAULT_STUDY_SLUG  # type: ignore[no-redef]
    return load_study(DEFAULT_STUDY_SLUG).research_question


def __getattr__(name: str) -> str:
    """Module-level `__getattr__` (PEP 562) — fires only when an
    attribute is missing from the module's namespace. We use it to
    resolve `DEFAULT_RESEARCH_QUESTION` lazily on first access,
    sidestepping the import cycle that hits when the study config
    itself imports from `orchestrator/`."""
    if name == "DEFAULT_RESEARCH_QUESTION":
        value = _default_research_question()
        # Cache so subsequent accesses don't re-call load_study.
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

class DebriefingTranscript(BaseModel):
    """Full record of the Phase-2 panel debriefing."""

    company: str
    research_question: str
    exchanges: list[PanelExchange] = Field(default_factory=list)
    ended_reason: str = Field(
        "",
        description=(
            "Why the debriefing ended: 'researcher_signalled', "
            "'max_exchanges_reached', or 'error'."
        ),
    )
    forbidden_vocab_violations: int = Field(
        0,
        description="Count of researcher utterances flagged by the runtime guard.",
    )


# Type alias for the per-agent runner — same shape as artefact_collection.
RunnerFn = Callable[..., Awaitable]


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def run_panel_debriefing(
    *,
    company: str,
    observation_summary: ObservationSummary,
    artefacts: Optional[ArtefactBundle],
    panel_agents: dict,
    industry_context: str = "Dynamic",
    product_type: str = "Novel",
    research_question: Optional[str] = None,
    debriefer_model: Optional[str] = None,
    max_exchanges: int = 60,
    run_agent: RunnerFn,
    concurrent_shared_state: Optional[object] = None,
    study: Optional["StudyConfig"] = None,
    rag_session: Optional["RagSession"] = None,
    role_memory: Optional[dict] = None,
    researcher_memory: str = "",
    on_exchange: Optional[Callable[[DebriefingTranscript], None]] = None,
) -> DebriefingTranscript:
    """Drive the researcher's panel debriefing to completion.

    Args:
        company: Firm under simulation.
        observation_summary: The Phase-1 field notes.
        artefacts: The per-role strategic documents (may be `None` if
            artefact collection was skipped).
        panel_agents: Map from role name to the TMT LlmAgent that will
            respond as that panellist.
        industry_context / product_type: Scenario context (carried
            into the debriefer's system prompt).
        research_question: Embedded in the debriefer's prompt as the
            stop criterion's anchor. Override to refine the focus.
        debriefer_model: Provider key for `providers.get_model`. None
            falls back to `TMT_PROVIDER`.
        max_exchanges: Safety ceiling (default 60).
        run_agent: Awaitable that runs an `LlmAgent` against a prompt
            and returns its structured output. Injected for testability.
        concurrent_shared_state: If the deliberation was CONCURRENT,
            the SharedState object from the orchestrator. Gives the
            debriefer privileged access to per-role private
            scratchpads and drafts for grounding research probes.
            Panellists themselves do NOT see each other's scratchpads.
        role_memory: What each role remembers, by role, from
            `orchestrator.role_memory`. Model calls share no session, so
            this is how a role knows what happened in the deliberation.
        researcher_memory: The same for the debriefer.
        on_exchange: Called with the transcript after each exchange, so a
            late crash keeps the exchanges already finished.

    Returns:
        A `DebriefingTranscript` with every exchange recorded.
    """
    # Effective research question: explicit override > study > legacy default.
    # `DEFAULT_RESEARCH_QUESTION` is module-lazy (PEP 562 `__getattr__`)
    # to dodge the load_study → orchestrator import cycle; bare-name
    # lookup inside this module doesn't fire `__getattr__`, so we call
    # the resolver directly.
    effective_rq = research_question
    if effective_rq is None and study is not None:
        effective_rq = study.research_question
    if effective_rq is None:
        effective_rq = _default_research_question()

    debriefer = _build_debriefer(
        company=company,
        observation_summary=observation_summary,
        artefacts=artefacts,
        industry_context=industry_context,
        product_type=product_type,
        model=debriefer_model,
        concurrent_shared_state=concurrent_shared_state,
        study=study,
    )

    # Resolve the active protocol's areas + closing-area id once, so
    # the coverage map renders against the same area set the
    # debriefer's prompt was built from.
    try:
        from ..roles.qualitative_researcher_agent import (
            _apply_study_overlay,
            _load_protocol,
            closing_area_id,
        )
    except (ImportError, ValueError):  # pragma: no cover
        from roles.qualitative_researcher_agent import (  # type: ignore[no-redef]
            _apply_study_overlay,
            _load_protocol,
            closing_area_id,
        )
    _protocol = _apply_study_overlay(_load_protocol(), study)
    _all_areas = [a["id"] for a in _protocol.get("thematic_areas", []) if a.get("id")]
    _closing = closing_area_id(_protocol)
    # New at v2.1: protocol-level area-traversal mode. The Debriefer
    # is given an explicit "use area X next" instruction via the
    # coverage-map block until every area has been visited at least
    # once. See `protocols/ethnographic_protocol.yaml::panel_format.
    # area_traversal_mode` for the modes and defaults.
    _traversal_mode = _protocol.get("panel_format", {}).get(
        "area_traversal_mode", "free"
    )

    transcript = DebriefingTranscript(
        company=company,
        research_question=effective_rq,
    )

    # Running list of all panelist utterances — needed by the
    # forbidden-vocab guard for echo permission.
    panelist_quotes_history: list[str] = []

    for turn in range(max_exchanges):
        history_block = _render_transcript_for_prompt(transcript)
        coverage_block = _render_coverage_map(
            transcript,
            all_areas=_all_areas or None,
            closing_area=_closing,
            traversal_mode=_traversal_mode,
            target_exchanges=_protocol.get("panel_format", {}).get("target_exchanges"),
        ) + _render_exchanges_left(len(transcript.exchanges), max_exchanges)
        utterance = await _next_researcher_utterance(
            debriefer=debriefer,
            history_block=history_block,
            coverage_block=coverage_block,
            run_agent=run_agent,
            panelist_quotes_history=panelist_quotes_history,
            transcript=transcript,
            study=study,
            researcher_memory=researcher_memory,
        )
        if utterance is None:
            transcript.ended_reason = "error"
            break

        # Collect panel responses.
        lost_roles: list[str] = []
        try:
            responses = await _collect_panel_responses(
                utterance=utterance,
                panel_agents=panel_agents,
                history_block=history_block,
                artefacts=artefacts,
                run_agent=run_agent,
                rag_session=rag_session,
                lost_roles=lost_roles,
                role_memory=role_memory,
                first_speaker=turn,
            )
        except Exception:  # noqa: BLE001
            # Keep the exchanges already finished rather than lose the debrief.
            log.exception("Panel responses failed at exchange %d", turn + 1)
            transcript.ended_reason = "error"
            break

        for r in responses:
            panelist_quotes_history.append(r.text)

        transcript.exchanges.append(
            PanelExchange(
                utterance=utterance, responses=responses, lost_roles=lost_roles,
            )
        )
        if on_exchange is not None:
            on_exchange(transcript)

        if utterance.ends_debriefing:
            transcript.ended_reason = "researcher_signalled"
            return transcript

    if not transcript.ended_reason:
        transcript.ended_reason = "max_exchanges_reached"
    return transcript


# ---------------------------------------------------------------------------
# Debriefer construction with research-question framing
# ---------------------------------------------------------------------------

def _build_debriefer(
    *,
    company: str,
    observation_summary: ObservationSummary,
    artefacts: Optional[ArtefactBundle],
    industry_context: str,
    product_type: str,
    model: Optional[str],
    concurrent_shared_state: Optional[object] = None,
    study: Optional["StudyConfig"] = None,
) -> LlmAgent:
    """Build the debriefer.

    The base instruction (constructed by `create_debriefer_agent`)
    already contains the study's RESEARCH CONTEXT block with the
    "may or may not be answered — do not steer" framing (see
    `qualitative_researcher_agent._render_research_context`). Here we
    append:
      * artefact summaries (titles + decisions + tensions per role)
      * private per-role scratchpads (privileged channel; panellists
        never see each other's notebooks)
      * the running-transcript / coverage-map rules
      * the thematic-area variety rules
      * the stop criterion

    All of the appended content is study-agnostic — it describes the
    debriefer's BEHAVIOUR, not what to look for. Study framing
    (research question, lens, construct-specific vocab) flows in
    through `create_debriefer_agent(..., study=study)` and the merged
    forbidden-vocab list.
    """
    base = create_debriefer_agent(
        company=company,
        observation_summary=observation_summary,
        industry_context=industry_context,
        product_type=product_type,
        model=model,
        study=study,
    )

    # Resolve the closing area (the one with `always_ask: true`) from
    # the active protocol — which may have been extended by a study
    # overlay. Falls back to the conventional "J" / "Reflection" if
    # nothing is flagged, so studies that drop the closing flag don't
    # silently lose the close-with-reflection invariant.
    try:
        from ..roles.qualitative_researcher_agent import (
            _apply_study_overlay,
            _load_protocol,
            closing_area_id,
        )
    except (ImportError, ValueError):  # pragma: no cover  (script-style)
        from roles.qualitative_researcher_agent import (  # type: ignore[no-redef]
            _apply_study_overlay,
            _load_protocol,
            closing_area_id,
        )
    _active_protocol = _apply_study_overlay(_load_protocol(), study)
    _closing_id = closing_area_id(_active_protocol) or "J"
    _closing_name = next(
        (
            a.get("name", "Reflection")
            for a in _active_protocol.get("thematic_areas", []) or []
            if a.get("id") == _closing_id
        ),
        "Reflection",
    )
    _all_area_ids = [
        a["id"] for a in _active_protocol.get("thematic_areas", []) or []
        if a.get("id")
    ]
    _area_range_label = (
        f"{_all_area_ids[0]}–{_all_area_ids[-1]}"
        if _all_area_ids else "A–J"
    )
    _max_probe_depth = (
        _active_protocol.get("panel_format", {}).get("max_probe_chain_depth", 5)
    )

    artefact_block = _render_artefacts_for_prompt(artefacts) if artefacts else ""

    # Render private scratchpads for the researcher (CONCURRENT mode).
    # Panellists never saw these; the researcher is privileged.
    scratchpad_block = _render_scratchpads_for_debriefer(concurrent_shared_state)

    extra = f"""

STRATEGIC ARTEFACTS PRODUCED BY THE PANEL
-----------------------------------------
{artefact_block if artefact_block else "(none — debriefing proceeds from the deliberation alone)"}

The artefacts above are additional anchor material. You may reference
their `title`s and `main_decisions` items in `anchor_refs` alongside
the observation-summary items.
{scratchpad_block}

DEBRIEFING HISTORY
------------------
Each turn you will be shown the running transcript of exchanges so
far PLUS a "Coverage map" summarising how many exchanges you have
already spent in each thematic area ({_area_range_label}). Use these to:
  - avoid repeating questions or asking essentially the same probe
    from a different angle,
  - decide whether material is still on-topic relative to what the
    panel actually deliberated,
  - choose follow-ups that probe what the panel JUST said (not
    what you already covered three exchanges ago),
  - vary the thematic area you are working in.

USING THE THEMATIC AREAS
------------------------
The areas are a guide to help you start, not a script to complete.
What you find in the field decides where you go.

1. Stay on a single anchor for up to {_max_probe_depth} consecutive
   exchanges when probing deeper produces fresh material. After that,
   move to a new anchor — saturation on one item means the data has
   thinned out. The semi-structured probing rule (in your stance
   section) tells you WHEN to probe deeper; this rule caps HOW LONG.
2. If your last 2 utterances were in the same area AND were not part
   of a productive probe chain, move to a different area unless you
   are opening something new.
3. Prefer to cover at least four distinct areas before closing.
   Area {_closing_id} ({_closing_name}) is always the closing area;
   do not exit without asking at least one Area {_closing_id} question.
4. Do not anchor consecutive utterances on the same observed item
   from the field notes unless you are explicitly probing deeper on
   it. Rotate through different decisions / components / disagreements.

STOP CRITERION
--------------
Set ends_debriefing=true when ALL of:
  - Area {_closing_id} has been asked and answered,
  - at least 4 distinct areas have been covered,
  - the last 2 exchanges produced nothing new, and you have no recorded
    question or earlier answer left to pursue.
Otherwise: follow up, or pick a different area or anchor, and continue.
"""

    # Append the behaviour-only extras to the base instruction. The
    # study-framing block (research question + lens + RULES) is
    # already inside `base.instruction` via `create_debriefer_agent`.
    base_instruction = getattr(base, "instruction", "") or ""
    base.instruction = base_instruction + extra  # type: ignore[attr-defined]
    return base


def _render_artefacts_for_prompt(bundle: ArtefactBundle) -> str:
    if not bundle.artefacts:
        return ""
    lines: list[str] = []
    for a in bundle.artefacts:
        lines.append(f"### {a.role} — {a.title}")
        if a.main_decisions:
            lines.append("Main decisions:")
            for d in a.main_decisions:
                lines.append(f"  - {d}")
        if a.key_tensions:
            lines.append("Key tensions:")
            for t in a.key_tensions:
                lines.append(f"  - {t}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _render_transcript_for_prompt(transcript: DebriefingTranscript) -> str:
    """Render exchanges so far for the next researcher turn."""
    if not transcript.exchanges:
        return "(this is your first turn — no exchanges yet)"
    lines: list[str] = []
    for i, ex in enumerate(transcript.exchanges):
        lines.append(f"--- Exchange {i + 1} (area {ex.utterance.area_id}) ---")
        addressee = ex.utterance.addressed_to
        lines.append(f"Researcher → {addressee}: {ex.utterance.text}")
        for r in ex.responses:
            tag = " (cross-talk)" if r.is_cross_talk else ""
            lines.append(f"  {r.role}{tag}: {r.text}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _render_latest_exchange_for_followup(
    transcript: DebriefingTranscript,
) -> str:
    """Render the most-recent exchange + explicit follow-up instructions.

    Item 9 fix: forces the debriefer to react to what was just said
    before moving on. If there was a substantive panel response, the
    next utterance should either:
      - be a FOLLOW-UP that digs into that specific response, OR
      - explicitly acknowledge the panel's last point AND only then
        switch topic.

    On the first turn (no prior exchange), returns guidance about
    opening the debriefing with an Area A anchored question.
    """
    if not transcript.exchanges:
        return (
            "FIRST TURN\n"
            "----------\n"
            "Open with an Area A (Decision Anchoring) question anchored "
            "on a specific decision from the field notes. Pick the most "
            "consequential decision the team made."
        )

    latest = transcript.exchanges[-1]
    utt = latest.utterance
    responses = latest.responses
    n_responses = len(responses)

    lines = [
        "MOST RECENT EXCHANGE (you MUST react to this before moving on)",
        "----------------------------------------------------------------",
        f"You just asked (area {utt.area_id}, addressed to {utt.addressed_to}):",
        f"  > {utt.text}",
        "",
    ]
    if n_responses == 0:
        lines.extend([
            "No panellist responded substantively (all PASSed).",
            "",
            "Consider: was the question too vague, too abstract, or too "
            "far from anything observed? Reframe with a tighter anchor "
            "OR switch area cleanly. Do NOT repeat the same question.",
        ])
    else:
        lines.append("Panel response(s):")
        for r in responses:
            tag = " (cross-talk)" if r.is_cross_talk else ""
            preview = r.text[:600] + ("…" if len(r.text) > 600 else "")
            lines.append(f"  - {r.role}{tag}: {preview}")
        lines.extend([
            "",
            "YOUR NEXT MOVE",
            "Look first for anything surprising, puzzling, or unexplained "
            "in these answers, and for anything you would not have "
            "expected. If several roles gave nearly the same answer, that "
            "agreement is itself worth asking about. Then choose ONE:",
            "  (a) FOLLOW-UP — probe deeper into something specific that "
            "was just said (set `is_followup=true`). Quote or reference "
            "the panellist's actual words. This is the right move whenever "
            "an answer gives you something worth pursuing, even if it "
            "leads away from the areas below.",
            "  (b) AREA SWITCH — move to a different thematic area "
            "because nothing here is worth pursuing further. Explicitly "
            "acknowledge what you just heard (in the prose of your "
            "utterance) BEFORE pivoting. Do NOT just fire the next "
            "scripted question.",
            "",
            "Do NOT ignore what was just said. Forward motion that "
            "doesn't acknowledge the panel turns the debriefing into an "
            "interview and loses the ethnographic depth.",
        ])
    return "\n".join(lines)


def _render_coverage_map(
    transcript: DebriefingTranscript,
    *,
    all_areas: Optional[list[str]] = None,
    closing_area: Optional[str] = None,
    traversal_mode: str = "free",
    target_exchanges: Optional[list[int]] = None,
) -> str:
    """Summarise how many exchanges have been spent in each thematic area.

    Surfaced to the debriefer on every turn so it has explicit awareness
    of where it is over-investing. Mitigates the smoke-run finding
    where one area got 3 consecutive exchanges.

    Args:
        all_areas: Ordered list of area IDs in the active protocol.
            Defaults to the framework + openness-overlay union
            (`["A", "B", "C", "I", "J", "D", "E", "F", "G", "H"]`
            sorted alphabetically). The map is rendered in this order.
        closing_area: The id of the area flagged `always_ask: true`
            (e.g. ``"J"`` under the current protocol). Defaults to
            ``"J"`` for back-compat; callers that have access to the
            active protocol should pass the resolved id explicitly.
        traversal_mode: One of `"free"`, `"structured"`, or
            `"structured_then_followup"`. Controls whether the
            rendered map includes an explicit "next area is X" hard
            instruction for the Debriefer. See
            `protocols/ethnographic_protocol.yaml::panel_format.
            area_traversal_mode` for definitions. Defaults to
            `"free"` for back-compat — the framework's older callers
            don't pass this; only the Phase 4 loop does. New at
            v2.1.
    """
    # Defaults preserve the openness study's expected layout while
    # letting any future study pass its own area list.
    if all_areas is None:
        all_areas = sorted(
            {"A", "B", "C", "D", "E", "F", "G", "H", "I", "J"}
        )
    if closing_area is None:
        closing_area = "J"

    if not transcript.exchanges:
        first = all_areas[0] if all_areas else "A"
        base = f"Coverage map: (no areas covered yet — start with Area {first})"
        # In structured traversal modes, the very first turn still
        # gets the binding "use area X next" directive — otherwise
        # the Debriefer might open with a different area than the
        # declared first-pass order.
        if traversal_mode in ("structured", "structured_then_followup"):
            return (
                base
                + "\n\nAREA TRAVERSAL — binding\n"
                + "------------------------\n"
                + f"Mode: {traversal_mode}. First turn: your next "
                + f"utterance MUST use `area_id='{first}'` (the first "
                + "area in declared order) and anchor a question on "
                + "that area."
            )
        return base

    from collections import Counter
    counts = Counter(ex.utterance.area_id for ex in transcript.exchanges)
    anchors_per_area: dict[str, list[str]] = {}
    for ex in transcript.exchanges:
        anchors_per_area.setdefault(ex.utterance.area_id, []).extend(ex.utterance.anchor_refs)

    last_two_areas = [ex.utterance.area_id for ex in transcript.exchanges[-2:]]

    lines = ["Coverage map (exchanges per thematic area so far):"]
    untouched_non_closing: list[str] = []
    for area in all_areas:
        n = counts.get(area, 0)
        flag = ""
        if n >= 2:
            flag = "  ← well covered: stay only if the panel gave you something new to pursue"
        if area == closing_area and n == 0 and sum(counts.values()) >= 5:
            flag = (
                f"  ← still need to ask Area {closing_area} "
                f"(always the closing area)"
            )
        if n == 0 and area != closing_area:
            untouched_non_closing.append(area)
        lines.append(f"  Area {area}: {n}{flag}")

    lines.append("")
    lines.append(f"Last two areas asked: {last_two_areas}")
    recent_followup = bool(transcript.exchanges[-1].utterance.is_followup)
    if (
        len(last_two_areas) == 2
        and last_two_areas[0] == last_two_areas[1]
        and not recent_followup
    ):
        lines.append(
            "  ⚠ You have asked TWO consecutive questions in the same area. "
            "Your next utterance MUST switch to a different area unless "
            "you can identify a genuinely new dimension (or you are "
            "explicitly probing deeper on the same anchor, within the "
            "probe-chain budget)."
        )

    distinct = len([a for a in counts if counts[a] > 0])
    lines.append(f"Distinct areas covered: {distinct}/{len(all_areas)}")
    if distinct < 4:
        lines.append(
            f"  → Aim for at least 4 distinct areas before closing "
            f"(currently {distinct})."
        )

    # Untouched-area nag. When non-closing areas are still at zero,
    # surface them explicitly. The debriefer can still deliberately
    # skip an area if the deliberation didn't make it salient — but
    # they must do so consciously, not silently.
    if untouched_non_closing:
        lines.append(
            f"  Untouched non-closing areas: "
            f"{', '.join(untouched_non_closing)} "
            f"— consider whether each is salient given what the team "
            f"deliberated. Skip only if the deliberation truly does "
            f"not support that area; do not skip silently."
        )

    # Structured-traversal directive.
    if traversal_mode in ("structured", "structured_then_followup"):
        # First-pass: pick the first area in declared order that still
        # has zero exchanges. If every area has ≥1, the first pass is
        # complete and we hand off to follow-up mode (or stop in
        # strict "structured" mode). Follow-ups come before the close,
        # so that mode holds the closing area back from the first pass.
        first_pass_areas = (
            [a for a in all_areas if a != closing_area]
            if traversal_mode == "structured_then_followup"
            else all_areas
        )
        first_pass_target = next(
            (a for a in first_pass_areas if counts.get(a, 0) == 0),
            None,
        )
        lines.append("")
        if traversal_mode == "structured_then_followup":
            lines.append("AREA GUIDE")
            lines.append("----------")
        else:
            lines.append("AREA TRAVERSAL — binding")
            lines.append("------------------------")
        if first_pass_target is not None and traversal_mode == "structured_then_followup":
            lines.append(
                "The areas are a guide, not a script. If the latest answer "
                "gave you something worth pursuing, probe it first with "
                "`is_followup=true`, staying in the current area. When "
                f"nothing is worth pursuing, move on to `area_id='{first_pass_target}'`, "
                "the next area not yet visited."
            )
        elif first_pass_target is not None:
            lines.append(
                f"Mode: {traversal_mode}. First-pass coverage is "
                f"INCOMPLETE: area '{first_pass_target}' has no "
                "exchanges yet. Your next utterance MUST use "
                f"`area_id='{first_pass_target}'` and anchor a question "
                f"on that area. Do not switch to another area until "
                f"area '{first_pass_target}' has at least one "
                "exchange; you can come back for follow-ups later."
            )
        elif traversal_mode == "structured":
            # All areas covered exactly once. In strict "structured"
            # mode the Debriefer can stop now — every area has at
            # least one exchange.
            lines.append(
                "Mode: structured. First-pass coverage is COMPLETE — "
                "every area has at least one exchange. Set "
                "`ends_debriefing=true` on your next utterance unless "
                "you have a specific follow-up that materially "
                "improves the data (this mode disallows follow-ups "
                "by default)."
            )
        else:
            # structured_then_followup, first pass done.
            lines.append(
                "Mode: structured_then_followup. First-pass coverage "
                "is COMPLETE — every area has at least one exchange. "
                "You are now in FOLLOW-UP mode: freely pick the area "
                "and anchor that would give the richest additional "
                "data, prioritising places where the panel's earlier "
                "answer opened up a new dimension."
            )
            if counts.get(closing_area, 0) == 0:
                lines.append(
                    f"Area {closing_area} closes the debriefing: ask it "
                    "last, once follow-ups have gone thin."
                )

    if target_exchanges:
        done = len(transcript.exchanges)
        lines.append("")
        lines.append(
            f"Exchanges so far: {done}. Target: {target_exchanges[0]}–"
            f"{target_exchanges[1]}."
        )
        if done < target_exchanges[0] and closing_area:
            lines.append(
                f"Do not ask Area {closing_area} or end yet unless the "
                "panel has truly nothing left to explore. Go back to an "
                "earlier answer or to a question you recorded."
            )

    recorded = [
        (i, ex.utterance.emerging_question)
        for i, ex in enumerate(transcript.exchanges, 1)
        if ex.utterance.emerging_question
    ]
    if recorded:
        lines.append("")
        lines.append(
            "Questions you have recorded (the panel has not seen these). "
            "Pursue them if the panel's material allows:"
        )
        for i, question in recorded:
            lines.append(f"  - Exchange {i}: {question}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Single-turn helpers
# ---------------------------------------------------------------------------

async def _next_researcher_utterance(
    *,
    debriefer: LlmAgent,
    history_block: str,
    coverage_block: str,
    run_agent: RunnerFn,
    panelist_quotes_history: list[str],
    transcript: DebriefingTranscript,
    study: Optional["StudyConfig"] = None,
    researcher_memory: str = "",
) -> Optional[PanelUtterance]:
    """Run one researcher turn with the forbidden-vocab retry loop.

    The prompt explicitly tells the debriefer to react to the
    MOST-RECENT panel response before moving on. If the previous
    exchange's responses were substantive (any panellist actually
    answered), the next utterance must be either:
      - a FOLLOW-UP that probes deeper into what was just said
        (`is_followup=true`), OR
      - a deliberate area-switch with a justification in the role's
        own reasoning.

    This prevents the "researcher fires next scripted question
    without acknowledging the panel's answer" failure mode.
    """
    latest_block = _render_latest_exchange_for_followup(transcript)

    prompt = (
        researcher_memory
        + "Your turn. Produce ONE PanelUtterance JSON object.\n\n"
        + latest_block
        + "\n\n"
        + f"{coverage_block}\n\n"
        + "DEBRIEFING HISTORY SO FAR:\n"
        + f"{history_block}\n\n"
        + "UTTERANCE LENGTH (binding)\n"
        + "--------------------------\n"
        + "The `text` field of your PanelUtterance should be **1-2 short "
        + "sentences, under 60 words**. Ask one focused question. NO "
        + "preamble (\"That's interesting — let me ask about…\"), NO "
        + "restating the panel's answer back at them, NO multi-clause "
        + "compound questions. The panel will give you a richer answer "
        + "when the question is tight than when it is long. If you find "
        + "yourself writing a third sentence in `text`, stop and cut.\n"
    )

    raw = await _safe_run(run_agent, debriefer, prompt)
    utt = _coerce_utterance(raw)
    if utt is None:
        return None

    # ---- Repeat-detection retry ----
    # If the new utterance is too similar to any of the last 3
    # utterances, re-prompt for a genuinely different question. The
    # check is cheap (token-set Jaccard) and triggered at most once.
    repeat_of_idx = _detect_recent_repeat(utt.text, transcript)
    if repeat_of_idx is not None:
        prior_text = transcript.exchanges[repeat_of_idx].utterance.text
        repeat_retry_prompt = (
            prompt
            + "\n\nYOUR PROPOSED UTTERANCE IS TOO CLOSE TO A RECENT ONE.\n"
            + f"Earlier you asked (exchange {repeat_of_idx + 1}):\n"
            + f"  > {prior_text}\n"
            + "Now you proposed:\n"
            + f"  > {utt.text}\n\n"
            + "Generate a DIFFERENT question — either a true follow-up "
              "on a specific phrase from the panellist's latest answer, "
              "or a switch to a different thematic area you have not "
              "yet covered. Do NOT rephrase the same question. Return "
              "one PanelUtterance JSON only."
        )
        repeat_raw = await _safe_run(run_agent, debriefer, repeat_retry_prompt)
        repeat_utt = _coerce_utterance(repeat_raw)
        if repeat_utt is not None:
            utt = repeat_utt

    # ---- Forbidden-vocab retry (existing) ----
    violations = utterance_violates_protocol(
        utt, panelist_quotes_history, study=study,
    )
    if not violations:
        return utt

    # One retry with the violations quoted.
    transcript.forbidden_vocab_violations += 1
    retry_prompt = (
        prompt
        + "\n\nYOUR PREVIOUS UTTERANCE FAILED PROTOCOL VALIDATION:\n"
        + "\n".join(f"  - {v}" for v in violations)
        + "\n\nRewrite it. Keep the same area_id and anchor_refs if you "
          "can. Use the panel's own phrasing. Return one PanelUtterance "
          "JSON only."
    )
    retry_raw = await _safe_run(run_agent, debriefer, retry_prompt)
    retry_utt = _coerce_utterance(retry_raw)
    if retry_utt is None:
        return utt  # Stick with the original rather than abort.
    if utterance_violates_protocol(retry_utt, panelist_quotes_history, study=study):
        # There is no second retry, so count it and let the run show it.
        transcript.forbidden_vocab_violations += 1
    return retry_utt


def _detect_recent_repeat(
    new_text: str,
    transcript: DebriefingTranscript,
    *,
    lookback: int = 3,
    threshold: float = 0.65,
) -> Optional[int]:
    """Return the index of the prior exchange this utterance duplicates,
    or `None` if not a repeat.

    Token-set Jaccard against the last `lookback` exchanges. If any
    prior utterance has Jaccard >= `threshold` with `new_text`, it's
    treated as a repeat and the index is returned (so the retry
    prompt can quote the prior question back).

    Token-set Jaccard is cheap, deterministic, and good enough to
    catch verbatim and near-verbatim repeats. It does NOT catch
    semantic-but-differently-worded repeats; that would require a
    semantic similarity model and is out of scope for this guard.
    """
    if not transcript.exchanges:
        return None
    new_tokens = _tokenset(new_text)
    if not new_tokens:
        return None
    recent = transcript.exchanges[-lookback:]
    base_idx = len(transcript.exchanges) - len(recent)
    for offset, ex in enumerate(recent):
        prior_tokens = _tokenset(ex.utterance.text)
        if not prior_tokens:
            continue
        intersection = new_tokens & prior_tokens
        union = new_tokens | prior_tokens
        jaccard = len(intersection) / len(union)
        if jaccard >= threshold:
            return base_idx + offset
    return None


def _tokenset(text: str) -> set[str]:
    """Lowercase alphanumeric token set. Used by repeat-detection."""
    import re
    return set(re.findall(r"[a-z0-9]+", text.lower()))


async def _collect_panel_responses(
    *,
    utterance: PanelUtterance,
    panel_agents: dict[str, LlmAgent],
    history_block: str,
    artefacts: Optional[ArtefactBundle],
    run_agent: RunnerFn,
    rag_session: Optional["RagSession"] = None,
    lost_roles: Optional[list[str]] = None,
    role_memory: Optional[dict] = None,
    first_speaker: int = 0,
) -> list:
    """Invite responses from panellists for one researcher utterance.

    Cross-talk routing:

    `addressed_to == "group"`
        Every role is invited to respond, each through the "PASS by
        default" prompt. Silence is the default; cross-talk is opt-in.

    `addressed_to == <role>`
        The addressed role responds first. THEN each OTHER role is
        invited separately with an explicit "do you have something
        specific to add to {addressee}'s answer? Otherwise PASS."
        prompt. The PASS-biased peer prompt prevents runaway cross-
        talk; peers only contribute when they have
        something genuinely additive.

    The single-panellist prompt is built differently for the
    addressed-first role vs. the opt-in cross-talkers — see
    `_single_panellist_response` for the conditional framing.

    Later speakers read the answers already given, so the order matters.
    `first_speaker` moves round the table each exchange, so that no role
    always frames the answer for the others.
    """
    responses: list[PanelResponse] = []
    memory = role_memory or {}
    seats = list(panel_agents.items())
    if seats:
        start = first_speaker % len(seats)
        seats = seats[start:] + seats[:start]

    if utterance.addressed_to != "group" and utterance.addressed_to not in panel_agents:
        # "CTO and COO" and the like name nobody on the panel, so nobody would
        # be asked directly. Put the question to everyone instead.
        log.warning("Researcher addressed %r; treating as group", utterance.addressed_to)
        utterance = utterance.model_copy(update={"addressed_to": "group"})

    if utterance.addressed_to == "group":
        for role, agent in seats:
            r = await _single_panellist_response(
                role=role,
                agent=agent,
                utterance=utterance,
                history_block=history_block,
                artefacts=artefacts,
                run_agent=run_agent,
                is_cross_talk=bool(responses),
                cross_talk_to=None,
                rag_session=rag_session,
                lost_roles=lost_roles,
                answers_so_far=list(responses),
                memory=memory.get(role, ""),
            )
            if r is not None:
                responses.append(r)
        return responses

    # Role-addressed path.
    addressed = utterance.addressed_to
    if addressed in panel_agents:
        r = await _single_panellist_response(
            role=addressed,
            agent=panel_agents[addressed],
            utterance=utterance,
            history_block=history_block,
            artefacts=artefacts,
            run_agent=run_agent,
            is_cross_talk=False,
            cross_talk_to=None,
            rag_session=rag_session,
            lost_roles=lost_roles,
            memory=memory.get(addressed, ""),
        )
        if r is not None:
            responses.append(r)
    # Other roles get a STRICT opt-in pass. The prompt heavily biases
    # toward PASS so default silence holds.
    for role, agent in seats:
        if role == addressed:
            continue
        r = await _single_panellist_response(
            role=role,
            agent=agent,
            utterance=utterance,
            history_block=history_block,
            artefacts=artefacts,
            run_agent=run_agent,
            is_cross_talk=True,
            cross_talk_to=addressed,
            rag_session=rag_session,
            lost_roles=lost_roles,
            answers_so_far=list(responses),
            memory=memory.get(role, ""),
        )
        if r is not None:
            responses.append(r)

    return responses


async def _single_panellist_response(
    *,
    role: str,
    agent: LlmAgent,
    utterance: PanelUtterance,
    history_block: str,
    artefacts: Optional[ArtefactBundle],
    run_agent: RunnerFn,
    is_cross_talk: bool,
    cross_talk_to: Optional[str] = None,
    retrieved_snippets: Optional[List[RetrievedSnippet]] = None,
    rag_session: Optional["RagSession"] = None,
    lost_roles: Optional[list[str]] = None,
    answers_so_far: Optional[list[PanelResponse]] = None,
    memory: str = "",
) -> Optional[PanelResponse]:
    """Run a single panellist for one researcher utterance.

    Three prompt framings, by role-of-this-call:

      1. The researcher addressed THIS role specifically (`is_cross_talk
         is False, cross_talk_to is None`) → "you were asked; answer fully".
      2. The researcher addressed the GROUP (`addressed_to == 'group'`)
         → "any role may respond; PASS if you don't have something
         genuinely additive".
      3. The researcher addressed a DIFFERENT role and this role is
         being offered a strict opt-in cross-talk turn
         (`is_cross_talk is True, cross_talk_to == <addressee>`) → the
         strongest PASS bias: "PASS unless you have something specific
         that genuinely BUILDS ON or CONTRADICTS {addressee}'s answer".

    The opt-in path is the fix for item 6 (everyone-cross-talks-runaway).

    `answers_so_far` holds this exchange's earlier answers. `history_block`
    stops at the previous exchange, so without them a role asked to build on
    a colleague's answer would be reacting to text it was never shown.

    `memory` is what the role remembers of the deliberation. It holds the
    role's whole document, so the short summary below is only for callers
    that pass no memory.
    """
    own_artefact = None
    if artefacts and not memory:
        own_artefact = artefacts.by_role(role)  # type: ignore[arg-type]
    own_artefact_block = ""
    if own_artefact is not None:
        own_artefact_block = (
            f"\nYOUR ROLE'S ARTEFACT FROM THE DELIBERATION\n"
            f"Title: {own_artefact.title}\n"
            f"Main decisions: {own_artefact.main_decisions}\n"
            f"Key tensions: {own_artefact.key_tensions}\n"
        )

    # Choose the addressing framing.
    if utterance.addressed_to == "group":
        addressing_note = (
            "The researcher addressed the WHOLE PANEL — you may respond if "
            "you have something specific your role would add, qualify, or "
            "push back on. Otherwise reply with the literal string [PASS]. "
            "Silence is data."
        )
        bias = "moderate"
    elif cross_talk_to is not None and is_cross_talk:
        addressing_note = (
            f"The researcher addressed {cross_talk_to} directly. "
            f"You are {role}; you have NOT been asked. You are only being "
            "invited to cross-talk if you have something specific that "
            f"BUILDS ON or CONTRADICTS what {cross_talk_to} just said.\n\n"
            "DEFAULT: PASS. Reply with the literal string [PASS] unless "
            "ALL of the following are true:\n"
            "  - You have something concrete that the researcher would "
            "find informative.\n"
            f"  - Your point reacts to {cross_talk_to}'s answer "
            "specifically (not a general comment).\n"
            "  - Your role's perspective is needed to make the point.\n"
            "Most of the time the correct response is [PASS]."
        )
        bias = "strong-pass"
    else:
        # Directly addressed by name (not group, not cross-talk).
        addressing_note = (
            f"The researcher addressed YOU ({role}) directly. Answer "
            "specifically and in your own voice. Reference particular "
            "decisions, components, or moments from the deliberation by "
            "name."
        )
        bias = "answer"

    # RAG: empty string when no snippets (no-RAG runs). When snippets
    # are provided directly OR when a rag_session is available and the
    # caller didn't pass snippets, retrieve now and insert a REFERENCE
    # MATERIAL block + populate-citations instruction here.
    if retrieved_snippets is None and rag_session is not None and rag_session.enabled:
        query = build_panellist_query(
            role=role,
            utterance_text=utterance.text,
            recent_history_block=history_block,
        )
        retrieved_snippets = await rag_session.retrieve_for_role(
            role=role, query=query, phase="phase_4_debriefing",
        )
    reference_block = format_retrieved_context(
        role=role, snippets=retrieved_snippets, plain_reply=True,
    )

    # What stays the same between calls goes first, so automatic caching can
    # discount it. The note on how this role was addressed comes after the
    # history for the same reason.
    prompt = f"""You are {role} on the panel. The qualitative researcher
is debriefing the TMT.

{memory}DEBRIEFING HISTORY SO FAR
-------------------------
{history_block}
{own_artefact_block}
{reference_block}
RESEARCHER'S CURRENT QUESTION (area {utterance.area_id}):
{utterance.text}

{addressing_note}
{_render_answers_so_far(answers_so_far, cross_talk_to)}
Respond in your own voice as {role}. Be specific about what you actually
thought / decided / pushed back on during the deliberation. Reference
specific components, decisions, or moments by name. If you have nothing
specific to add, reply with the literal string [PASS]. Silence is data.

RESPONSE LENGTH (binding)
-------------------------
Reply in **80-150 words, 1-2 short paragraphs**. The researcher needs
focused field-note-grade material across many turns, not a position
paper per question. Get to the substantive point in the first
sentence; do NOT restate the question; do NOT preamble. If you find
yourself writing a third paragraph, stop and cut. Multi-paragraph
essays are a sign you are answering more than was asked.
"""

    raw = await _safe_run(run_agent, agent, prompt)
    if raw is None:
        # `_safe_run` returns None when the call failed. That is a lost
        # answer, not a decision to stay silent.
        log.error("Panel answer lost for %s: model call failed", role)
        if lost_roles is not None:
            lost_roles.append(role)
        return None
    answer, citations = split_panel_reply(_coerce_response_text(raw))
    answer = (answer or "").strip()
    if not answer:
        # An empty reply is a blocked or failed completion. [PASS] is how a
        # role chooses silence, so this is a lost answer.
        log.error("Panel answer lost for %s: empty reply", role)
        if lost_roles is not None:
            lost_roles.append(role)
        return None
    if _is_pass_response(answer):
        return None
    usable = valid_citations(citations)
    if len(usable) < len(citations):
        log.warning(
            "Dropped %d malformed citations from %s", len(citations) - len(usable), role,
        )
    return PanelResponse(
        role=role, text=answer, is_cross_talk=is_cross_talk, citations=usable,
    )


def _render_answers_so_far(
    answers: Optional[list[PanelResponse]], cross_talk_to: Optional[str] = None,
) -> str:
    """This exchange's answers so far, for roles speaking after the first."""
    answers = answers or []
    lines = "\n\n".join(f"{a.role}: {a.text}" for a in answers)
    block = f"\nANSWERS ALREADY GIVEN TO THIS QUESTION\n{lines}\n" if answers else ""
    if cross_talk_to and all(a.role != cross_talk_to for a in answers):
        block += f"\n{cross_talk_to} gave no answer to this question.\n"
    return block


def _render_exchanges_left(used: int, cap: int) -> str:
    """Tell the debriefer its room, so it can close before the cap ends it."""
    left = cap - used
    last = " This is your last exchange: close the debrief now." if left <= 1 else ""
    return f"\n\nEXCHANGES LEFT: {left} of {cap}.{last}"


def _is_pass_response(text: str) -> bool:
    """Whether a panellist response should be treated as silence.

    Handles literal '[PASS]', plus common near-misses an LLM might
    emit when nudged to stay silent.
    """
    if not text:
        return True
    cleaned = text.strip().strip(".'\"*_` ").upper()
    return cleaned in {
        "", "[PASS]", "PASS", "(PASS)",
        "[NO COMMENT]", "NO COMMENT", "(NO COMMENT)",
    }


# ---------------------------------------------------------------------------
# Coercion + safety helpers
# ---------------------------------------------------------------------------

# Retry-with-backoff for transient provider errors (429 / 5xx / rate-
# limit / asyncio.TimeoutError) was originally implemented inline here
# behind the Phase-4 hardening landed against the Meta-2032 cell
# post-mortem. It now lives in `orchestrator/llm_retry.py` so Phase 2
# (`artefact_collection`) can use the same retry policy. The helpers
# below are re-exported under the old underscore-prefixed names so any
# external import path still resolves; new call sites should import
# from `llm_retry` directly.

try:
    from .llm_retry import (  # noqa: F401  (re-exported)
        MAX_RETRIES as _PHASE4_MAX_RETRIES,
        is_transient_error as _is_transient_error,
        parse_retry_delay as _parse_phase4_retry_delay_v2,
        safe_run as _safe_run,
    )
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from orchestrator.llm_retry import (  # type: ignore[no-redef]
        MAX_RETRIES as _PHASE4_MAX_RETRIES,
        is_transient_error as _is_transient_error,
        parse_retry_delay as _parse_phase4_retry_delay_v2,
        safe_run as _safe_run,
    )


def _parse_phase4_retry_delay(exc, attempt):  # back-compat wrapper
    """Adapter so existing tests calling the old (exc, attempt=) signature
    keep working. New code should call `llm_retry.parse_retry_delay`
    directly."""
    return _parse_phase4_retry_delay_v2(exc, attempt=attempt)


def _coerce_utterance(raw: object) -> Optional[PanelUtterance]:
    if raw is None:
        return None
    if isinstance(raw, PanelUtterance):
        return raw
    if isinstance(raw, dict):
        try:
            return PanelUtterance.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            log.error("PanelUtterance validation failed: %s", exc)
            return None
    if isinstance(raw, str):
        # Strip ```json … ``` fences and prose framing — the debriefer
        # can run on `json_object`-mode providers (DeepSeek, Ollama)
        # which aren't schema-enforced server-side.
        cleaned = _strip_json_envelope(raw)
        try:
            return PanelUtterance.model_validate_json(cleaned)
        except Exception as exc:  # noqa: BLE001
            log.error("PanelUtterance JSON parse/validate failed: %s", exc)
            return None
    log.error("Unexpected utterance return type: %s", type(raw))
    return None


def _strip_json_envelope(text: str) -> str:
    """Strip ```json … ``` fences and prose framing around a JSON object.

    Symmetric helper to `artefact_collection._strip_json_envelope` and
    `openness_judging._strip_json_envelope` — needed wherever an LLM in
    `json_object` mode can return either a fenced block or stray prose
    around the structured output.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if 0 <= first_brace < last_brace:
        return stripped[first_brace : last_brace + 1]
    return stripped


def _coerce_response_text(raw: object) -> str:
    """Pull a plain-text response out of whatever the runner returned."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        # Some runners return {"text": "..."} or {"content": "..."}
        for key in ("text", "content", "response"):
            v = raw.get(key)
            if isinstance(v, str):
                return v
        return json.dumps(raw)
    return str(raw)


def _render_scratchpads_for_debriefer(
    concurrent_shared_state: Optional[object],
) -> str:
    """Render per-role private notes for the debriefer (researcher only).

    Empty string if the deliberation was not CONCURRENT (i.e. no
    scratchpads exist). Otherwise produces a privileged-access block
    the debriefer can mine for anchor_refs — but the prompt also
    instructs the debriefer to phrase any reference in the panellist's
    own public vocabulary, never quoting the scratchpad verbatim to
    the panel.
    """
    if concurrent_shared_state is None:
        return ""
    role_states_attr = getattr(concurrent_shared_state, "role_states", None)
    if role_states_attr is None:
        return ""
    lines: list[str] = [
        "",
        "PRIVATE PER-ROLE SCRATCHPADS (debriefer-only access)",
        "-----------------------------------------------------",
        "Each role kept a private notebook during the deliberation that",
        "no other panellist saw. As the researcher, you have privileged",
        "access to these notes — they reveal what each role thought but",
        "did NOT say. You MAY craft probes that surface this tension",
        "(e.g. you noted privately that X but in the discussion you said Y;",
        "tell me about that). When you do, phrase the probe in the role's",
        "OWN public vocabulary — never quote the scratchpad verbatim back",
        "to the panel (they don't know you've seen it).",
        "",
    ]
    for role, rs in role_states_attr.items():
        scratchpad = getattr(rs, "scratchpad", []) or []
        draft = getattr(rs, "draft", "") or ""
        if not scratchpad and not draft:
            continue
        lines.append(f"### {role}")
        if scratchpad:
            lines.append("Private notes:")
            for n in scratchpad:
                lines.append(f"  - {n}")
        if draft:
            preview = draft[:300] + ("..." if len(draft) > 300 else "")
            lines.append(f"Working draft preview: {preview}")
        lines.append("")
    return "\n".join(lines)
