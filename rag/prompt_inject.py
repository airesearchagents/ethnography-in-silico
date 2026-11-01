"""Format retrieved RAG snippets as a prompt block + a populate-citations instruction.

Used by `orchestrator.concurrent_mode._compose_role_prompt`,
`orchestrator.artefact_collection._build_artefact_prompt`, and
`orchestrator.panel_debriefing._single_panellist_response` — each one
accepts a list of `RetrievedSnippet` and prepends the rendered block to
the LLM prompt for that turn.

Contract
--------
- `snippets=None` or `snippets=[]` → returns `""`. The caller can
  unconditionally concatenate the result into the prompt; no-RAG runs
  see no change.
- Otherwise → returns a multi-line block:
    * a short framing sentence (no mention of RQ / lens — keeps
      invariant I5 from `docs/10_rag_repo_plan.md` § 10.5),
    * the populate-citations instruction with a JSON skeleton,
    * the excerpts themselves with `doc_id` / `chunk_id` / `score`
      headers so the LLM can copy the IDs verbatim into citations,
    * a closing reminder not to fabricate.

The rendering is plain text. The block lands inside an existing
backtick-free prompt string (every role prompt is plain prose), so we
don't wrap in markdown fences — that would confuse the LLM into
echoing back markdown formatting.
"""

from __future__ import annotations

import os
from typing import List, Optional

try:
    from .schemas import RetrievedSnippet
except ImportError:  # pragma: no cover  (script-style execution)
    from rag.schemas import RetrievedSnippet  # type: ignore[no-redef]


def excerpt_char_limit() -> Optional[int]:
    """Characters of each passage a role is shown. None shows the whole passage.

    Runs A to D showed 1,200 of about 4,000 characters, so a passage could be
    retrieved for text the role never saw. Set `TMT_PASSAGE_CHARS` to test how
    much agents need to see.
    """
    raw = os.environ.get("TMT_PASSAGE_CHARS", "").strip()
    return int(raw) if raw else None


def format_retrieved_context(
    role: str,
    snippets: Optional[List[RetrievedSnippet]],
    *,
    max_excerpt_chars: Optional[int] = None,
    plain_reply: bool = False,
) -> str:
    """Render `snippets` as a REFERENCE MATERIAL prompt block.

    Returns the empty string when `snippets` is None or empty. Callers
    can therefore unconditionally do:

        prompt = (
            ...
            + format_retrieved_context(role=role, snippets=snippets)
            + ...
        )

    without an explicit None-check; the no-RAG path adds no characters.

    Parameters
    ----------
    role : str
        The role name (CEO, CTO, ...) for the framing line. Used only
        for natural-language fitting in the framing sentence; does NOT
        carry the study's RQ or lens (invariant I5).
    snippets : list[RetrievedSnippet] | None
        The chunks Vertex RAG returned for this role's query this turn.
    max_excerpt_chars : int | None
        Per-excerpt limit. Defaults to `excerpt_char_limit()`, which
        shows the whole passage unless a study test sets a limit.
        Truncated excerpts are marked with a trailing `[...]` so the LLM
        doesn't quote partial sentences as if complete.
    plain_reply : bool
        True for calls whose reply is prose with no `citations` field, such
        as debrief answers. They are told to add the citations after the
        prose, where `split_panel_reply` finds them.

    Returns
    -------
    str
        The rendered block, or `""` when there's nothing to render.
    """
    if not snippets:
        return ""

    limit = max_excerpt_chars if max_excerpt_chars is not None else excerpt_char_limit()
    if plain_reply:
        how_to_cite = (
            "If your answer draws on any excerpt below, you MUST cite it. Write your\n"
            "answer as plain prose, then on a new line add one JSON object,\n"
            '{"citations": [...]}, with one entry per excerpt you actually leaned on:'
        )
        if_none = "If you don't lean on any excerpt, add nothing after your answer."
    else:
        how_to_cite = (
            "If your output draws on any excerpt below, you MUST populate the\n"
            "`citations` field of your structured action — one entry per excerpt\n"
            "you actually leaned on:"
        )
        if_none = "If you don't lean on any excerpt this turn, leave `citations` as an\nempty list `[]`."
    excerpts_block = "\n\n".join(
        _render_excerpt(idx + 1, s, limit)
        for idx, s in enumerate(snippets)
    )

    return f"""REFERENCE MATERIAL — {len(snippets)} excerpts from public documents about this firm
-------------------------------------------------------------------------------
You have access to excerpts from public documents about this firm
(interview and public-talk transcripts, earnings calls and published
case studies). These may or may not be relevant to the
question on the table. Use them as you
would any reference material: read them, decide whether they inform
your thinking, draw on them where useful, and ignore them when they
don't help. The retrieval is private to you for this turn; your peers
are seeing different excerpts based on their own queries.

{how_to_cite}

  {{
    "doc_id":   "<exact doc_id from the excerpt header below>",
    "chunk_id": "<exact chunk_id from the excerpt header below>",
    "quote":    "<verbatim phrase or sentence copied from the excerpt's text>",
    "supports": "<one short tag for which claim of yours this backs>"
  }}

{if_none} Don't fabricate citations — every `quote` is later
verified to be a substring of the excerpt's text it cites. Citations
referencing material outside the excerpts below are flagged as
fabrication.

EXCERPTS
--------
{excerpts_block}
"""


def _render_excerpt(idx: int, s: RetrievedSnippet, max_chars: Optional[int]) -> str:
    """Render one excerpt with a clear ID header the LLM can copy verbatim."""
    text = s.text or ""
    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars].rstrip() + " [...]"
    # 2-space indent on the body so the block visually groups with its
    # header but stays readable for any LLM that's strict about
    # whitespace cues.
    body = "\n".join(f"  {line}" for line in text.splitlines() if line.strip()) or "  (empty)"
    return (
        f"[{idx}] doc_id={s.doc_id}  chunk_id={s.chunk_id}  score={s.score:.3f}\n"
        f"{body}"
    )
