"""Runtime guard (a check made while a run is under way): enforce the
forbidden-vocabulary rule of the protocol (the debrief's rules and topics).

The Virtual Ethnography Field Protocol (§4.4) names a set of
theoretically loaded words the researcher agent (the language model that watches
and questions the team) must NOT introduce. The
exception is *echoing*: if a panelist (one of the six role agents, when questioned in the debrief) uses one of these words
spontaneously, the researcher may use the panelist's phrasing back.

This module supplies a regex-based (regex, or regular expression: a written
pattern for finding text) runtime checker that runs alongside the prompt-level
instruction (the wording sent to the model). The pattern for the orchestrator (the code
that runs each stage of a run), where the debriefer is the researcher agent in
Phase 4, is:

    utterance = run_debriefer(...)
    violations = check_utterance(utterance.text, panelist_quotes_so_far)
    if violations:
        utterance = run_debriefer_retry(..., violations=violations)

The list of forbidden words is read from
`protocols/ethnographic_protocol.yaml` (YAML is a plain-text format for settings
and lists) so that file remains the single
source of truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Violation:
    """One occurrence of a forbidden word in a researcher utterance."""

    word: str
    position: int  # Character offset in the utterance text.
    snippet: str   # ±20 chars of context for logging.


_PROTOCOL_PATH = Path(__file__).resolve().parent.parent / "protocols" / "ethnographic_protocol.yaml"


@lru_cache(maxsize=16)
def load_forbidden_vocabulary(
    protocol_path: str | None = None,
    study_extras: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Load the merged forbidden-vocabulary list.

    Combines:
      * the protocol YAML's `methodological_forbidden_vocabulary` (or
        the legacy `forbidden_vocabulary` key if the new one is
        missing) — universal across studies;
      * `study_extras` — the study's
        `construct_forbidden_vocabulary` passed in as a tuple of
        strings.

    Cached (kept in memory and reused) because the file is read frequently. The cache key
    includes `study_extras` so different studies (or test fixtures, the prepared inputs that tests run on)
    can coexist without contamination.

    Args:
        protocol_path: Override the YAML location (mainly tests).
        study_extras: Additional words from the study config.
    """
    path = Path(protocol_path) if protocol_path else _PROTOCOL_PATH
    with path.open("r", encoding="utf-8") as fh:
        protocol = yaml.safe_load(fh)
    methodological = (
        protocol.get("methodological_forbidden_vocabulary")
        or protocol.get("forbidden_vocabulary")  # legacy key
        or []
    )
    # Deduplicate while preserving order: methodological first, then
    # construct-specific (study_extras).
    seen: set[str] = set()
    merged: list[str] = []
    for w in list(methodological) + list(study_extras):
        if w not in seen:
            merged.append(w)
            seen.add(w)
    return tuple(merged)


def _compile_patterns(words: tuple[str, ...]) -> list[tuple[str, re.Pattern[str]]]:
    """Compile word-boundary patterns for each forbidden word.

    We use `(?<!\\w)` / `(?!\\w)` rather than `\\b` so multi-token
    forbidden entries like 'open-source' and 'value capture' are matched
    correctly. Hyphens and spaces are not word characters under `\\b`,
    which would cause false negatives on 'open-source'.
    """
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for word in words:
        pattern = re.compile(r"(?<!\w)" + re.escape(word.lower()) + r"(?!\w)")
        compiled.append((word, pattern))
    return compiled


def check_utterance(
    text: str,
    panelist_quotes: list[str] | None = None,
    forbidden: tuple[str, ...] | None = None,
    protocol_path: str | None = None,
) -> list[Violation]:
    """Return all forbidden-word violations in `text`.

    A forbidden word is *allowed* if the same word also appears in any
    of `panelist_quotes`: this models protocol §4.4 ("If a panelist uses
    one of these words, the researcher may echo it back using the
    panelist's phrasing."). The check is intentionally lenient — a
    panelist using the bare word 'open' once is enough to permit the
    researcher to use 'open' in any phrasing later. Tightening this
    requires verbatim-quote matching, which is a later refinement.

    Args:
        text: The researcher's utterance text.
        panelist_quotes: All prior panelist utterances in the same
            debriefing, used to permit echoes.
        forbidden: Override the protocol's word list (mainly for tests).
        protocol_path: Override the YAML location (mainly for tests).

    Returns:
        A list of `Violation` objects; empty if the utterance is clean.
    """
    panelist_quotes = panelist_quotes or []
    panelist_blob = " ".join(panelist_quotes).lower()
    word_tuple = forbidden if forbidden is not None else load_forbidden_vocabulary(protocol_path)

    text_lower = text.lower()
    violations: list[Violation] = []
    for word, pattern in _compile_patterns(word_tuple):
        if word.lower() in panelist_blob:
            # The panel used this word. Allow echoes anywhere in the utterance.
            continue
        for m in pattern.finditer(text_lower):
            start = max(0, m.start() - 20)
            end = min(len(text), m.end() + 20)
            violations.append(
                Violation(word=word, position=m.start(), snippet=text[start:end])
            )
    return violations


def format_violations(violations: list[Violation]) -> str:
    """Render a violations list as a single human-readable string.

    Used to build the retry prompt for the debriefer when its first
    attempt contains forbidden vocabulary.
    """
    if not violations:
        return ""
    lines = ["The previous utterance violated the forbidden-vocabulary rule:"]
    for v in violations:
        lines.append(f"  - '{v.word}' at position {v.position}: …{v.snippet}…")
    lines.append(
        "Rewrite the utterance without these words. You may keep the same "
        "anchor_refs and area_id. Use the panel's own phrasing instead."
    )
    return "\n".join(lines)
