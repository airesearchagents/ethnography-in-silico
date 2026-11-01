"""Post-hoc verification of evidence quotes against persisted markdown.

PR-D commit 5/6 (a PR, or pull request, is a proposed set of code changes; a commit
is one saved change). A judge is a language model that scores a finished run (one complete simulated meeting and debrief) against
a rubric, a scoring guide. The v0.4 judge prompt (the text sent to it) requires every
sub-dimension (one narrow rubric item)
score's `EvidenceQuote.quote` to come VERBATIM from one of the run's
persisted markdown (plain text with simple marks for headings) artefacts (deliberation log, role strategy
documents, observer summary, debriefing transcript). The judge is
told not to quote external knowledge — training-time priors (what a model absorbed
from text before we used it) about the firm, public news, prior literature.

This module (a Python file with one job) enforces that contract by
substring-checking (looking for the exact run of text) every quote
against the file named in its `source_file` field. Quotes that don't
match are flagged in a per-provider (provider: the company supplying a model) audit
file (`<provider>_quote_audit.md`) for the PI (principal investigator, the lead
researcher) to review during qualitative
analysis. The verification is post-hoc and non-blocking: failed
quotes are surfaced, never auto-discarded — a quote that fails the
substring check may still be useful evidence (the judge may have
lightly normalised whitespace or rendered an em-dash as a hyphen).

Matching policy
---------------
* Case sensitive (the judge is instructed to quote verbatim;
  case insensitivity would mask real fabrication).
* Whitespace-normalised (spaces, tabs and line breaks treated alike) on both
  sides: runs of any Unicode whitespace
  collapse to a single ASCII space, leading / trailing whitespace
  stripped. Catches the most common normalisation a judge applies
  to a multi-line quote without giving away genuine fabrication.
* Substring match: the normalised quote must appear as a contiguous
  substring in the normalised file content.

What's NOT a quote-verification failure
---------------------------------------
* A judge supplying zero quotes for a "near-absent" (score_pct ≤ 14)
  sub-dim — the prompt explicitly allows that path.
* A judge supplying one demonstrating-the-absence quote for a near-
  absent score — the prompt allows that path too.

(The ≥2-quote rule is enforced by the schema-validation (checking a reply against a
template of required fields) layer +
the judge prompt itself, not here.)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ===========================================================================
# Report schema
# ===========================================================================

class QuoteAuditEntry(BaseModel):
    """One quote's verification result."""

    sub_dimension_key: str = Field(..., description="The sub-dim this quote backs.")
    source_file: str = Field(..., description="Relative path inside run_dir.")
    source_role: Optional[str] = Field(None, description="Role attribution if present.")
    quote: str = Field(..., description="The quote as supplied by the judge.")
    passed: bool = Field(..., description="True iff the quote substring-matched.")
    failure_reason: Optional[str] = Field(
        None,
        description=(
            "Brief failure description when passed=False: "
            "'source_file missing', 'no substring match', etc."
        ),
    )


class QuoteAuditReport(BaseModel):
    """Per-judge quote-verification report."""

    judge_id: str = Field(..., description="Provider key of the judge.")
    n_total: int = Field(0, description="Total quotes checked.")
    n_passed: int = Field(0, description="Quotes that substring-matched.")
    n_failed: int = Field(0, description="Quotes that didn't match (surfaced; not auto-discarded).")
    fail_rate: float = Field(0.0, description="n_failed / n_total. 0.0 if n_total == 0.")
    entries: List[QuoteAuditEntry] = Field(default_factory=list)


# ===========================================================================
# Substring matching with whitespace normalisation
# ===========================================================================

_WHITESPACE_RE = re.compile(r"\s+")


def _normalise_whitespace(text: str) -> str:
    """Collapse runs of whitespace to a single ASCII space; strip ends.

    Mirrors the most common normalisation a judge applies when copying
    a multi-line passage into a single-line quote field. Without
    normalisation, every quote that spanned a hard newline in the
    source would fail.
    """
    return _WHITESPACE_RE.sub(" ", text).strip()


def _file_text_or_none(run_dir: Path, source_file: str) -> Optional[str]:
    """Return the file's text content if it exists under run_dir, else None.

    `source_file` is a relative path (e.g.
    `01_deliberation/interaction_log.md`); paths that resolve outside
    `run_dir` are rejected to prevent a malicious / buggy judge from
    causing an arbitrary file read.
    """
    candidate = (run_dir / source_file).resolve()
    try:
        # Refuse anything that escapes run_dir.
        candidate.relative_to(run_dir.resolve())
    except ValueError:
        return None
    if not candidate.exists() or not candidate.is_file():
        return None
    try:
        return candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _verify_one_quote(
    *,
    run_dir: Path,
    source_file: str,
    quote: str,
) -> tuple[bool, Optional[str]]:
    """Return (passed, failure_reason_or_None)."""
    file_text = _file_text_or_none(run_dir, source_file)
    if file_text is None:
        return False, f"source_file not readable inside run_dir: {source_file!r}"
    needle = _normalise_whitespace(quote)
    if not needle:
        return False, "quote is empty after whitespace normalisation"
    haystack = _normalise_whitespace(file_text)
    if needle in haystack:
        return True, None
    return False, "no substring match in source_file (after whitespace normalisation)"


# ===========================================================================
# Public API
# ===========================================================================

def verify_quotes_in_assessment(
    *,
    assessment: Any,
    run_dir: Path,
) -> QuoteAuditReport:
    """Verify every EvidenceQuote in a ConstructAssessment.

    Works on either a Pydantic (a Python tool that checks records against a
    template) ConstructAssessment instance or a dict (plain named fields)
    payload (the latter for the persistence-from-disk path).
    """
    judge_id = (
        assessment.judge_id
        if hasattr(assessment, "judge_id")
        else assessment.get("judge_id", "unknown")
    )

    # Tolerate either typed object or dict.
    if hasattr(assessment, "sub_dimension_assessments"):
        sub_dims = assessment.sub_dimension_assessments or []
    else:
        sub_dims = assessment.get("sub_dimension_assessments") or []

    entries: List[QuoteAuditEntry] = []
    for sd in sub_dims:
        sub_key = (
            sd.sub_dimension_key if hasattr(sd, "sub_dimension_key")
            else sd.get("sub_dimension_key", "")
        )
        quotes = (
            sd.evidence_quotes if hasattr(sd, "evidence_quotes")
            else sd.get("evidence_quotes") or []
        )
        for q in quotes:
            source_file = q.source_file if hasattr(q, "source_file") else q.get("source_file", "")
            source_role = q.source_role if hasattr(q, "source_role") else q.get("source_role")
            quote = q.quote if hasattr(q, "quote") else q.get("quote", "")
            passed, reason = _verify_one_quote(
                run_dir=run_dir, source_file=source_file, quote=quote,
            )
            entries.append(QuoteAuditEntry(
                sub_dimension_key=sub_key,
                source_file=source_file,
                source_role=source_role,
                quote=quote,
                passed=passed,
                failure_reason=reason,
            ))

    n_total = len(entries)
    n_passed = sum(1 for e in entries if e.passed)
    n_failed = n_total - n_passed
    fail_rate = (n_failed / n_total) if n_total else 0.0

    return QuoteAuditReport(
        judge_id=judge_id,
        n_total=n_total,
        n_passed=n_passed,
        n_failed=n_failed,
        fail_rate=fail_rate,
        entries=entries,
    )


def render_quote_audit_md(report: QuoteAuditReport) -> str:
    """Render a `QuoteAuditReport` as human-readable markdown for the
    PI's qualitative-analysis review."""
    lines = [
        f"# Quote audit — judge: {report.judge_id}",
        "",
        "Post-hoc substring verification of every EvidenceQuote against "
        "its `source_file`. Whitespace-normalised both sides. Quotes "
        "that did not match are SURFACED here for review — they are "
        "not auto-discarded (the judge may have lightly normalised "
        "punctuation or dropped a trailing word).",
        "",
        "## Summary",
        "",
        f"- Total quotes checked: **{report.n_total}**",
        f"- Passed substring check: **{report.n_passed}**",
        f"- Failed substring check: **{report.n_failed}**",
        f"- Failure rate: **{report.fail_rate * 100:.1f}%**",
        "",
    ]
    if report.n_failed == 0:
        lines.append("All quotes substring-matched their source files.")
        return "\n".join(lines)

    lines.append("## Failed quotes (surfaced for PI review)")
    lines.append("")
    failed = [e for e in report.entries if not e.passed]
    for i, e in enumerate(failed, 1):
        lines.append(f"### {i}. {e.sub_dimension_key}")
        lines.append(f"- **source_file**: `{e.source_file}`")
        if e.source_role:
            lines.append(f"- **source_role**: {e.source_role}")
        lines.append(f"- **failure_reason**: {e.failure_reason}")
        lines.append(f"- **quote**: > {e.quote}")
        lines.append("")
    return "\n".join(lines)
