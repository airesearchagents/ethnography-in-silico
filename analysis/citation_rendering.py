"""Markdown footnote rendering for `Citation` lists on persisted records.

A citation is a role agent's (one simulated executive's) record of the document,
passage and words it drew on. This file turns those records into numbered footnotes
in a run's readable files (Markdown: plain text with simple marks for headings).

Two things this module (a Python file with one job) owns:

1. **Inline footnote markers + footnote-definition block** — given a
   list of citations attached to a statement, return:
     a) the inline marker text to append to the statement
        (e.g. `[^c1][^c2]`),
     b) one footnote-definition string per citation, in Markdown
        footnote syntax (`[^c1]: ...`).

2. **References-section rendering** — given a list of (statement_id,
   citation) pairs accumulated across a whole document, render a
   References section at the bottom of the document with deduplicated
   doc entries.

Footnote naming
---------------
Footnote IDs are per-document (`c1`, `c2`, ...) — Markdown footnote
namespaces (sets of names that must not clash) are scoped to the file, not the
project. The caller (the code using this module) passes
in a fresh `CitationCounter` per document so a fresh integer sequence
starts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, List, Tuple


def _citation_dict(c: Any) -> dict:
    """Accept a Citation Pydantic model (Pydantic: a Python tool that checks
    records against a template) OR a dict (plain named fields, from persisted JSON, a plain-text format)."""
    if isinstance(c, dict):
        return c
    if hasattr(c, "model_dump"):
        return c.model_dump()
    # Fallback: introspect attributes.
    return {
        "doc_id": getattr(c, "doc_id", "?"),
        "chunk_id": getattr(c, "chunk_id", None),
        "quote": getattr(c, "quote", ""),
        "supports": getattr(c, "supports", ""),
    }


@dataclass
class CitationCounter:
    """Per-document footnote counter + accumulator.

    Each call to `register(citation)` returns the inline marker for
    that citation (e.g. `[^c3]`) and appends a footnote-definition
    line to `self.footnote_lines`. When the caller is done rendering
    the document body, they emit `self.footnote_block()` at the
    bottom of the .md file.

    Calling `register` twice with the same citation (same doc_id +
    same quote) reuses the existing marker — Markdown allows multiple
    inline markers to share one footnote definition, which is
    cleaner than duplicating.
    """

    next_idx: int = 1
    footnote_lines: List[str] = field(default_factory=list)
    # Map from (doc_id, quote) -> footnote_id, so duplicate citations
    # within the same document collapse to one footnote.
    _seen: dict = field(default_factory=dict)

    def register(self, citation: Any) -> str:
        """Add the citation if not already present, return the inline marker.

        Returns a string of the form `[^c<N>]` ready to append to the
        statement text the citation backs.
        """
        c = _citation_dict(citation)
        key = (c.get("doc_id", ""), c.get("quote", ""))
        if key in self._seen:
            return f"[^{self._seen[key]}]"
        fid = f"c{self.next_idx}"
        self.next_idx += 1
        self._seen[key] = fid

        doc_id = c.get("doc_id", "?")
        chunk_id = c.get("chunk_id") or doc_id
        quote = (c.get("quote") or "").strip()
        supports = (c.get("supports") or "").strip()

        # Markdown footnote definition. Multi-line continuations need
        # 4-space indentation to belong to the same footnote.
        line = f"[^{fid}]: **{doc_id}** "
        if chunk_id and chunk_id != doc_id:
            line += f"(chunk {chunk_id}) "
        if quote:
            line += f"— quote: _\"{quote}\"_"
        if supports:
            line += f" — supports: {supports}"
        self.footnote_lines.append(line)
        return f"[^{fid}]"

    def register_all(self, citations: Iterable[Any]) -> str:
        """Convenience: register all and return concatenated markers.

        Returns e.g. `[^c1][^c2]` for a two-citation list, or "" for
        an empty list. Suitable to append directly to the statement.
        """
        out: List[str] = []
        for c in citations or []:
            out.append(self.register(c))
        return "".join(out)

    def footnote_block(self) -> str:
        """Return the footnote-definitions block to append to the doc.

        Empty string when no citations were registered. Otherwise
        prefixed with a blank line and a horizontal rule + a
        'References' heading, then the footnote-definition lines.
        """
        if not self.footnote_lines:
            return ""
        return "\n\n---\n\n## References\n\n" + "\n\n".join(self.footnote_lines) + "\n"


def render_citation_footnotes_inline(citations: Iterable[Any]) -> Tuple[str, str]:
    """One-shot helper for a single statement with citations.

    Returns `(inline_markers, footnote_block)`. The caller is
    responsible for appending `inline_markers` to the statement text
    and `footnote_block` to the bottom of the document.

    Two-call API (the agreed way for code to use this module) for callers that
    want full control. Most callers use
    `CitationCounter` directly for accumulation across many
    statements in one document.
    """
    counter = CitationCounter()
    markers = counter.register_all(citations or [])
    return markers, counter.footnote_block()
