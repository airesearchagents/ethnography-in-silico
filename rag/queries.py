"""Build retrieval queries from role state + recent discussion.

Three helpers, one per phase:

- `build_role_turn_query(role, task, my_state, transcript)` — Phase 1.
- `build_artefact_query(role, company, deliberation_summary)` — Phase 2.
- `build_panellist_query(role, utterance, recent_history_block)` — Phase 4.

Each helper constructs a short text query the retriever uses to find
relevant chunks in the firm's corpus.

Invariant I5 (no RQ/lens leak)
------------------------------
None of these helpers receive the study's `research_question` or
`theoretical_lens`. Construction inputs are:
  - role name
  - task (RoleTaskSpec — carries `strategic_question`, NOT the study RQ)
  - transcript entries (panellist utterances only)
  - role state (scratchpad / draft)
  - researcher utterance text (in Phase 4)

`strategic_question` is the user-facing deliberation prompt (e.g. "What
should we build next?") supplied by `StudyConfig.strategic_question_
template`, not the study's analytical research question. The two are
deliberately distinct in the codebase; conflating them would be a
methodological error, not just a leak.

The `tests/test_rag_no_query_leak.py` test parametrises every public
study fixture and asserts the queries from these helpers contain no
prefix of `study.research_question` or `study.theoretical_lens`.
"""

from __future__ import annotations

from typing import Any, Iterable, List


# Maximum characters in a query. Vertex RAG embeds the query; longer
# queries don't reliably help retrieval relevance and they cost a tiny
# amount more per call. ~800 chars (~200 tokens) is enough room for the
# role + question + last ~5 transcript entries.
_DEFAULT_MAX_CHARS = 800


def _truncate(s: str, n: int) -> str:
    """Truncate `s` to `n` chars on a word boundary where possible."""
    s = (s or "").strip()
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0]
    return cut + "..."


def _tail(s: str, n: int) -> str:
    """The last `n` chars of `s`, from a word boundary where possible."""
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return "..." + s[-n:].split(" ", 1)[-1]


def build_role_turn_query(
    *,
    role: str,
    task: Any,
    my_state: Any,
    transcript: List[Any],
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> str:
    """Query for a Phase-1 role turn.

    The query reflects the role's CURRENT information need, derived
    from the strategic question, the role's latest private notes /
    draft, and the most recent few transcript entries. Does not
    reference the study's research question or theoretical lens.
    """
    parts: List[str] = [f"Role: {role}"]
    strategic_q = getattr(task, "strategic_question", "") or ""
    if strategic_q:
        parts.append(f"Deliberation question: {_truncate(strategic_q, 240)}")
    company = getattr(task, "company", "") or ""
    if company:
        parts.append(f"Firm: {company}")
    industry = getattr(task, "industry_context", "") or ""
    product_type = getattr(task, "product_type", "") or ""
    if industry or product_type:
        parts.append(f"Context: {industry} / {product_type}".strip(" /"))

    # Role's own latest scratchpad entry (a hint at what the role is
    # focused on right now). Earlier entries are stale.
    scratchpad: Iterable[str] = getattr(my_state, "scratchpad", []) or []
    scratchpad_list = list(scratchpad)
    if scratchpad_list:
        parts.append(f"My latest note: {_truncate(scratchpad_list[-1], 200)}")

    # Most recent 5 transcript entries, newest first when room runs out,
    # because the latest turns matter most and the query has a size limit.
    room = max_chars - len("\n".join(parts)) - len("\nRecent discussion:")
    lines: List[str] = []
    for e in reversed(list(transcript or [])[-5:]):
        speaker = getattr(e, "role", "") or ""
        text = getattr(e, "text", "") or ""
        if not text:
            continue
        line = f"  {speaker}: {_truncate(text, 160)}"
        if len(line) + 1 > room:
            break
        lines.insert(0, line)
        room -= len(line) + 1
    if lines:
        parts.append("Recent discussion:")
        parts.extend(lines)

    return _truncate("\n".join(parts), max_chars)


def build_artefact_query(
    *,
    role: str,
    company: str,
    deliberation_summary: str,
    industry_context: str = "",
    product_type: str = "",
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> str:
    """Query for a Phase-2 artefact-authoring turn.

    The role is about to author its strategic document. The query
    reflects what the role is about to write — derived from the
    deliberation summary and the role's identity. Does not reference
    the study's research question or theoretical lens.
    """
    parts: List[str] = [
        f"Role: {role}",
        f"Firm: {company}",
        "Authoring strategic document.",
    ]
    if industry_context or product_type:
        parts.append(f"Context: {industry_context} / {product_type}".strip(" /"))
    if deliberation_summary:
        parts.append("Deliberation summary:")
        parts.append(_tail(deliberation_summary, 500))
    return _truncate("\n".join(parts), max_chars)


def build_panellist_query(
    *,
    role: str,
    utterance_text: str,
    recent_history_block: str = "",
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> str:
    """Query for a Phase-4 panellist response turn.

    The query reflects the question the researcher just asked.
    Critically, the query is built from the RESEARCHER'S UTTERANCE
    TEXT only — never from the RESEARCH CONTEXT block (which would
    leak RQ / lens via the debriefer's prompt). The caller must pass
    `utterance.text`, not the full Debriefer prompt.
    """
    parts: List[str] = [
        f"Role: {role}",
        "Answering panel debriefing question.",
    ]
    if utterance_text:
        parts.append(f"Researcher asks: {_truncate(utterance_text, 400)}")
    if recent_history_block:
        # Just the last ~200 chars of the history, to anchor the
        # question in what was just said. Long histories add noise.
        parts.append(f"Recent context: {_tail(recent_history_block, 200)}")
    return _truncate("\n".join(parts), max_chars)
