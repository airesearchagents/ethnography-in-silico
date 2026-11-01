"""Method A — anchored dictionary scoring of the openness rubric's
26 sub-dimensions across three channels (public / private /
researcher), with per-role attribution where available.

This is a lexicon, or dictionary, method: it scores a run's text by counting words
from fixed lists tied to each sub-dimension, a narrow item of the openness rubric
(the scoring guide). A channel is one kind of record in a run (one complete simulated
meeting and debrief), and a role is one of the six simulated executives.

Algorithm:

1. Extract text from each channel's sources, attributing to a role
   where possible (`_ALL` for non-role-attributable sources like the
   observation summary, the researcher agent's single account of the team's
   discussion, or the researcher's field notes, its running notes).

2. Tokenise (split) each source into sentences.

3. For every sentence, scan the pro-openness and anti-openness regex (regular
   expression: a written pattern for finding text) lists for each sub-dimension in
   `studies/openness_maneuvering/subdimension_lexicon.py`. Apply a
   ±3-token (here, three words either side) negation window so `"not proprietary"` flips polarity.

4. Per `(channel, role, sub_dimension)` slice, count hits and compute
   `score = (n_pro - n_anti) / n_sentences`. Length-weighted
   aggregation up to `(channel, _ALL, sub_dimension)` and onward to
   `(channel, _ALL, dimension)` via uniform OR
   measurability-weighted means (both written).

5. Write four CSVs (plain-text tables any spreadsheet can open) to `<run_folder>/06_subdimension_scores/`.

Pure-Python; no new dependencies (extra packages of ready-made code). The scorer
is the second
methodological artefact of the measurement layer (the first is the
lexicon itself).
"""

from __future__ import annotations

import csv
import json
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    # `analysis.text_measures.dictionary` is three levels deep; `...studies`
    # walks back to the package root to find `studies.openness_maneuvering`.
    from ...studies.openness_maneuvering.subdimension_lexicon import (
        OPENNESS_SUBDIMENSION_LEXICON,
        measurability_weight,
        subdimensions_for,
    )
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from studies.openness_maneuvering.subdimension_lexicon import (  # type: ignore[no-redef]
        OPENNESS_SUBDIMENSION_LEXICON,
        measurability_weight,
        subdimensions_for,
    )

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Snake-case channel keys used in the output CSVs.
CHANNEL_PUBLIC = "public"
CHANNEL_PRIVATE = "private"
CHANNEL_RESEARCHER = "researcher"

# The aggregate-across-roles key used in CSV `role` columns.
ROLE_ALL = "_ALL"

# Negation tokens checked within ±N words of a regex match. Lifted
# from the standard negation-windowing literature; keep small to avoid
# false flips on sentences like "we don't think this is bad — we
# definitely want to release weights".
NEGATION_TOKENS: frozenset[str] = frozenset({
    "not", "no", "never", "without",
    "don't", "doesnt", "doesn't",
    "isn't", "isnt",
    "aren't", "arent",
    "wasn't", "wasnt",
    "weren't", "werent",
    "cannot", "can't", "cant",
    "won't", "wont",
    "shouldn't", "shouldnt",
    "haven't", "havent",
    "hasn't", "hasnt",
    "neither", "nor",
})

NEGATION_WINDOW = 3  # tokens before AND after a hit.

# Minimum sentence length (in words) to be scored. Filters out
# isolated punctuation, headers, etc.
MIN_SENTENCE_WORDS = 3

# Top-K evidence sentences to record per (channel, role, sub_dim).
EVIDENCE_TOP_K = 3

# The seven rubric parent dimensions, in canonical order for CSV output.
# Bumped from five at rubric v0.2: `boundary_permeability` split into
# inbound/outbound (Dahlander & Gann 2010), and `temporal_openness_
# maneuvering` added to capture the timing/sequencing logic the RQ (research question) asks
# about (Henkel 2006 dynamic; Alexy/Henkel/Wallin 2013).
DIMENSIONS_ORDER: Tuple[str, ...] = (
    "component_disclosure",
    "process_openness",
    "boundary_permeability_inbound",
    "boundary_permeability_outbound",
    "ecosystem_orchestration",
    "value_capture_posture",
    "temporal_openness_maneuvering",
)

# The six TMT (top management team) role keys, in canonical order.
ROLES_ORDER: Tuple[str, ...] = (
    "CEO", "CTO", "COO", "CMO",
    "Product_Strategist", "Product_Designer",
)


# ---------------------------------------------------------------------------
# Sentence tokenisation
# ---------------------------------------------------------------------------

# Standard regex-based sentence splitter. Good enough for prose; not a
# linguistic tokeniser. Avoids the nltk (a language-processing package) dependency.
_SENT_SPLIT = re.compile(r"(?<=[\.\!\?])\s+(?=[A-Z\(\[])|(?<=[\.\!\?])\n+|\n{2,}")

# Word tokenizer for negation windowing — words, contractions, simple
# tokens. Hyphenated tokens are kept intact.
_WORD_TOK = re.compile(r"[A-Za-z][A-Za-z'\-]*")


def _split_sentences(text: str) -> List[str]:
    """Split prose into sentences. Filters out short fragments
    (under MIN_SENTENCE_WORDS) to avoid noise from headers / bullets."""
    if not text:
        return []
    raw = [s.strip() for s in _SENT_SPLIT.split(text) if s and s.strip()]
    out: List[str] = []
    for s in raw:
        # Also split on bullet markers that didn't end in a period.
        for bit in re.split(r"(?:^|\n)\s*[-\*•]\s+", s):
            bit = bit.strip()
            if not bit:
                continue
            words = _WORD_TOK.findall(bit)
            if len(words) >= MIN_SENTENCE_WORDS:
                out.append(bit)
    return out


# ---------------------------------------------------------------------------
# Compiled regex cache
# ---------------------------------------------------------------------------

_COMPILED_LEXICON: Optional[Dict[str, Dict[str, List[re.Pattern]]]] = None


def _compiled_lexicon() -> Dict[str, Dict[str, List[re.Pattern]]]:
    """Return the lexicon with all regex patterns precompiled.

    Lazily built on first call. Memoised (kept after the first build) for the lifetime of the
    process — the lexicon is module-level immutable.
    """
    global _COMPILED_LEXICON
    if _COMPILED_LEXICON is None:
        compiled: Dict[str, Dict[str, List[re.Pattern]]] = {}
        for sub_key, entry in OPENNESS_SUBDIMENSION_LEXICON.items():
            compiled[sub_key] = {
                "pro": [
                    re.compile(p, re.IGNORECASE) for p in entry["pro_openness"]
                ],
                "anti": [
                    re.compile(p, re.IGNORECASE) for p in entry["anti_openness"]
                ],
            }
        _COMPILED_LEXICON = compiled
    return _COMPILED_LEXICON


# ---------------------------------------------------------------------------
# Negation-aware hit counter
# ---------------------------------------------------------------------------

def _is_negated(sentence: str, match_start: int, match_end: int) -> bool:
    """Return True iff a negation token sits within ±NEGATION_WINDOW
    words of the matched span.

    Uses word offsets rather than character offsets so a long match
    surrounded by short words still has a sensible window.
    """
    pre_text = sentence[:match_start]
    post_text = sentence[match_end:]
    pre_words = _WORD_TOK.findall(pre_text)[-NEGATION_WINDOW:]
    post_words = _WORD_TOK.findall(post_text)[:NEGATION_WINDOW]
    window = [w.lower() for w in (pre_words + post_words)]
    return any(w in NEGATION_TOKENS for w in window)


def _count_hits_in_sentence(
    sentence: str, sub_key: str,
) -> Tuple[int, int]:
    """Return (n_pro_hits, n_anti_hits) for one sub-dimension in one
    sentence, with negation flipping polarity."""
    patterns = _compiled_lexicon()[sub_key]
    pro = 0
    anti = 0
    for pat in patterns["pro"]:
        for m in pat.finditer(sentence):
            if _is_negated(sentence, m.start(), m.end()):
                anti += 1
            else:
                pro += 1
    for pat in patterns["anti"]:
        for m in pat.finditer(sentence):
            if _is_negated(sentence, m.start(), m.end()):
                pro += 1
            else:
                anti += 1
    return pro, anti


# ---------------------------------------------------------------------------
# Channel × role text extraction
# ---------------------------------------------------------------------------

# A (channel, role, sentence) triple is the unit the scorer operates
# on. We accumulate these from every source, then score each triple
# once against every sub-dimension.

def _public_sentences(
    *,
    artefacts: Optional[dict],
    deliberation_log: Optional[dict],
    observation_summary: Optional[dict],
    debriefing_transcript: Optional[dict],
) -> Iterable[Tuple[str, str]]:
    """Yield (role, sentence) tuples from the public channel.

    Role is one of CEO/CTO/COO/CMO/Product_Strategist/Product_Designer
    where attributable, else `_ALL`.
    """
    # P1 — Strategic artefacts (per role).
    if artefacts is not None:
        for a in artefacts.get("artefacts", []) or []:
            role = a.get("role", ROLE_ALL)
            chunks = [a.get("body", "") or ""]
            for field in ("key_challenges", "main_decisions", "key_tensions"):
                items = a.get(field, []) or []
                chunks.extend(items)
            for chunk in chunks:
                for s in _split_sentences(chunk):
                    yield role, s

    # P2 — Public deliberation transcript (per role).
    if deliberation_log is not None:
        for ev in deliberation_log.get("events", []) or []:
            role = ev.get("role", ROLE_ALL)
            if role == "unknown":
                role = ROLE_ALL
            for s in _split_sentences(ev.get("text", "") or ""):
                yield role, s

    # P3 — Observation summary (researcher-attributed structurally;
    # we mark it ROLE_ALL because it's not a role's voice).
    if observation_summary is not None:
        text_chunks = _flatten_strings(observation_summary)
        for chunk in text_chunks:
            for s in _split_sentences(chunk):
                yield ROLE_ALL, s

    # P5 — Debriefing transcript (per role on responses).
    if debriefing_transcript is not None:
        for ex in debriefing_transcript.get("exchanges", []) or []:
            for r in ex.get("responses", []) or []:
                role = r.get("role", ROLE_ALL)
                for s in _split_sentences(r.get("text", "") or ""):
                    yield role, s


def _private_sentences(
    *, private_state: Optional[dict],
) -> Iterable[Tuple[str, str]]:
    """Yield (role, sentence) tuples from the private channel."""
    if not private_state:
        return
    for role, rs in private_state.items():
        # Q1 — Scratchpads (per role).
        for note in rs.get("scratchpad", []) or []:
            for s in _split_sentences(note):
                yield role, s

        # Q2 — Final working draft (per role).
        for s in _split_sentences(rs.get("draft", "") or ""):
            yield role, s

        # Q3/Q4 — Inbox messages. Each message is attributed to the
        # ROLE WHOSE INBOX it is — i.e. `role` here — because that
        # role saw the message during deliberation. Asker/recipient
        # info is preserved in the JSON dump for finer-grained
        # analysis later.
        for msg in rs.get("inbox", []) or []:
            for s in _split_sentences(msg.get("text", "") or ""):
                yield role, s


def _researcher_sentences(
    *, field_notes: Optional[list],
) -> Iterable[Tuple[str, str]]:
    """Yield (role, sentence) from the researcher channel.

    Field notes are produced by the FieldNoter agent (the researcher agent during
    Phases 1 and 2); no role
    attribution applies. All sentences are emitted with role=`_ALL`.
    """
    if not field_notes:
        return
    for note in field_notes:
        for s in _split_sentences(note if isinstance(note, str) else str(note)):
            yield ROLE_ALL, s


def _flatten_strings(obj: Any) -> List[str]:
    """Walk a JSON-ish (structured, with named fields) object and yield every string value.

    Used for the observation summary, where the structured fields
    (decisions / components / ambiguities / ...) all contain useful
    text but with no fixed schema (a template of required fields) we want to bind
    the scorer to.
    """
    out: List[str] = []

    def _walk(o: Any) -> None:
        if isinstance(o, str):
            out.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                _walk(v)
        elif isinstance(o, list):
            for item in o:
                _walk(item)

    _walk(obj)
    return out


# ---------------------------------------------------------------------------
# Scoring core
# ---------------------------------------------------------------------------

class _SubDimAccumulator:
    """Running totals for one (channel, role, sub_dimension) slice."""

    __slots__ = ("n_pro", "n_anti", "n_relevant", "evidence")

    def __init__(self) -> None:
        self.n_pro: int = 0
        self.n_anti: int = 0
        self.n_relevant: int = 0  # sentences with at least one hit
        # Top-K (abs(score) descending) sentences for the evidence column.
        # Each entry: (abs_total_hits, signed_score, sentence)
        self.evidence: List[Tuple[int, int, str]] = []

    def add(self, n_pro: int, n_anti: int, sentence: str) -> None:
        self.n_pro += n_pro
        self.n_anti += n_anti
        if n_pro + n_anti > 0:
            self.n_relevant += 1
            abs_hits = n_pro + n_anti
            signed = n_pro - n_anti
            self.evidence.append((abs_hits, signed, sentence))
            # Keep only the top EVIDENCE_TOP_K by abs hits.
            self.evidence.sort(key=lambda t: (-t[0], -abs(t[1]), t[2]))
            if len(self.evidence) > EVIDENCE_TOP_K:
                self.evidence = self.evidence[:EVIDENCE_TOP_K]


def _score_channel(
    channel: str,
    sentence_stream: Iterable[Tuple[str, str]],
) -> Tuple[Dict[Tuple[str, str], _SubDimAccumulator], Dict[str, int]]:
    """Score every sentence in a channel against every sub-dimension.

    Returns:
        (accs, n_sentences) where
        - accs maps (role, sub_dim_key) → _SubDimAccumulator
        - n_sentences maps role → total sentence count in this channel
          (incl. role=_ALL, which we maintain by summing)
    """
    accs: Dict[Tuple[str, str], _SubDimAccumulator] = defaultdict(_SubDimAccumulator)
    n_sentences: Dict[str, int] = defaultdict(int)

    for role, sentence in sentence_stream:
        n_sentences[role] += 1
        n_sentences[ROLE_ALL] += 1
        for sub_key in OPENNESS_SUBDIMENSION_LEXICON.keys():
            n_pro, n_anti = _count_hits_in_sentence(sentence, sub_key)
            if n_pro == 0 and n_anti == 0:
                continue
            accs[(role, sub_key)].add(n_pro, n_anti, sentence)
            accs[(ROLE_ALL, sub_key)].add(n_pro, n_anti, sentence)

    return accs, dict(n_sentences)


def _density(acc: _SubDimAccumulator, n_sentences_in_slice: int) -> float:
    """(n_pro - n_anti) / n_sentences. Returns 0.0 when n_sentences == 0."""
    if n_sentences_in_slice <= 0:
        return 0.0
    return (acc.n_pro - acc.n_anti) / n_sentences_in_slice


# ---------------------------------------------------------------------------
# CSV writers
# ---------------------------------------------------------------------------

def _evidence_top_3_str(acc: _SubDimAccumulator) -> str:
    """Format evidence sentences as a single semicolon-joined string."""
    parts: List[str] = []
    for _abs_hits, _signed, sentence in acc.evidence:
        cleaned = re.sub(r"\s+", " ", sentence.strip())
        if len(cleaned) > 200:
            cleaned = cleaned[:197] + "..."
        parts.append(cleaned)
    return "; ".join(parts)


def _write_per_subdimension_csv(
    out_dir: Path,
    rows: List[dict],
) -> Path:
    path = out_dir / "per_subdimension.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "channel", "role", "dimension", "sub_dimension", "method",
                "score", "n_relevant_sentences", "measurability",
                "evidence_top_3",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _write_per_dimension_csv(
    out_dir: Path,
    rows: List[dict],
) -> Path:
    path = out_dir / "per_dimension.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "channel", "role", "dimension", "method", "aggregation",
                "score", "n_sub_dimensions_with_signal",
                "weakest_sub", "strongest_sub",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _write_headline_csv(
    out_dir: Path,
    channel_score_rows: Dict[str, Dict[str, float]],
) -> Path:
    """Channel × dimension headline pivot — `role=_ALL`, uniform agg.

    `channel_score_rows[channel][dimension] = score`. Output columns
    are `{channel}_dict`. If Method B were also computed, additional
    `{channel}_embed` columns would join here; currently only Method A
    is wired.
    """
    path = out_dir / "headline.csv"
    cols = [f"{c}_dict" for c in (CHANNEL_PUBLIC, CHANNEL_PRIVATE, CHANNEL_RESEARCHER)]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["dimension"] + cols)
        writer.writeheader()
        for dim in DIMENSIONS_ORDER:
            row = {"dimension": dim}
            for ch in (CHANNEL_PUBLIC, CHANNEL_PRIVATE, CHANNEL_RESEARCHER):
                row[f"{ch}_dict"] = f"{channel_score_rows.get(ch, {}).get(dim, 0.0):+.3f}"
            writer.writerow(row)
    return path


def _write_headline_by_role_csv(
    out_dir: Path,
    role_score_rows: Dict[str, Dict[Tuple[str, str], float]],
) -> Path:
    """Channel × role × dimension headline pivot — uniform aggregation,
    Method A only."""
    path = out_dir / "headline_by_role.csv"
    cols = [f"{c}_dict" for c in (CHANNEL_PUBLIC, CHANNEL_PRIVATE, CHANNEL_RESEARCHER)]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["role", "dimension"] + cols)
        writer.writeheader()
        # Roles in canonical order + _ALL.
        for role in (*ROLES_ORDER, ROLE_ALL):
            for dim in DIMENSIONS_ORDER:
                row = {"role": role, "dimension": dim}
                for ch in (CHANNEL_PUBLIC, CHANNEL_PRIVATE, CHANNEL_RESEARCHER):
                    score = role_score_rows.get(ch, {}).get((role, dim), 0.0)
                    row[f"{ch}_dict"] = f"{score:+.3f}"
                writer.writerow(row)
    return path


# ---------------------------------------------------------------------------
# Markdown summary
# ---------------------------------------------------------------------------

def _render_summary_md(
    *,
    channel_score_rows: Dict[str, Dict[str, float]],
    n_sentences_by_channel: Dict[str, int],
) -> str:
    lines = [
        "# Sub-Dimensional Openness Scores (Method A — dictionary)",
        "",
        "Each cell is the **density score** for a (channel, parent dimension) pair: ",
        "`(pro-openness hits − anti-openness hits) / total sentences`. Positive ⇒ ",
        "the channel's text leans pro-openness on that dimension; negative ⇒ leans ",
        "anti-openness.",
        "",
        "## Sentence counts per channel",
        "",
        "| Channel | Sentences scored |",
        "| --- | ---: |",
    ]
    for ch in (CHANNEL_PUBLIC, CHANNEL_PRIVATE, CHANNEL_RESEARCHER):
        lines.append(f"| {ch} | {n_sentences_by_channel.get(ch, 0)} |")
    lines.append("")
    lines.append("## Headline scores (uniform sub-dimension aggregation)")
    lines.append("")
    lines.append(
        "| Dimension | public_dict | private_dict | researcher_dict |"
    )
    lines.append("| --- | ---: | ---: | ---: |")
    for dim in DIMENSIONS_ORDER:
        row = [
            f"`{dim}`",
            f"{channel_score_rows.get(CHANNEL_PUBLIC, {}).get(dim, 0.0):+.3f}",
            f"{channel_score_rows.get(CHANNEL_PRIVATE, {}).get(dim, 0.0):+.3f}",
            f"{channel_score_rows.get(CHANNEL_RESEARCHER, {}).get(dim, 0.0):+.3f}",
        ]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("## Files in this folder")
    lines.append("")
    lines.append("- `per_subdimension.csv` — every (channel, role, sub-dimension, method) slice")
    lines.append("- `per_dimension.csv` — collapse sub-dimensions into parent dimensions (uniform AND measurability-weighted aggregations)")
    lines.append("- `headline.csv` — the table above as a machine-readable CSV")
    lines.append("- `headline_by_role.csv` — same shape, broken out per role (CEO / CTO / COO / CMO / Product_Strategist / Product_Designer / _ALL)")
    lines.append("")
    lines.append("Method A is dictionary-based and reproducible. See ")
    lines.append("`studies/openness_maneuvering/subdimension_lexicon.py` for the ")
    lines.append("citable lexicon; see docs/09 for the methodology design (kept ")
    lines.append("locally, not committed).")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def score_run(
    *,
    out_dir: Path,
    artefacts: Optional[dict] = None,
    deliberation_log: Optional[dict] = None,
    observation_summary: Optional[dict] = None,
    debriefing_transcript: Optional[dict] = None,
    field_notes: Optional[list] = None,
    private_state: Optional[dict] = None,
) -> Path:
    """Compute Method A sub-dimensional scores for one run.

    Writes four CSVs + a markdown summary to
    `<out_dir>/06_subdimension_scores/`. Returns the path to that
    directory.

    Args:
        out_dir: The run folder (e.g.
            `results/runs/Anthropic_Dynamic_Novel_20260523_161327/`).
        artefacts: Dict form of `ArtefactBundle.model_dump(mode='json')`.
            Goes into the public channel with per-role attribution.
        deliberation_log: Dict form of `DeliberationLog.model_dump(...)`.
            Public channel, per-role.
        observation_summary: Dict form of `ObservationSummary.model_dump(...)`.
            Public channel, role=`_ALL` (researcher-structured, not a role's voice).
        debriefing_transcript: Dict form of
            `DebriefingTranscript.model_dump(...)`. Public channel, per-role
            on response speakers.
        field_notes: List of strings — the FieldNoter's running prose.
            **Researcher** channel, role=`_ALL`.
        private_state: Dict shape `{role: {scratchpad, draft, inbox, ...}}`
            from `ResearchSessionOutputs.private_state`. Private channel,
            per-role.

    Returns:
        The `06_subdimension_scores/` path. Caller can append to the
        run folder's README.
    """
    scores_dir = out_dir / "06_subdimension_scores"
    scores_dir.mkdir(parents=True, exist_ok=True)

    # --- 1. Score each channel ---------------------------------------
    public_accs, public_n = _score_channel(
        CHANNEL_PUBLIC,
        _public_sentences(
            artefacts=artefacts,
            deliberation_log=deliberation_log,
            observation_summary=observation_summary,
            debriefing_transcript=debriefing_transcript,
        ),
    )
    private_accs, private_n = _score_channel(
        CHANNEL_PRIVATE,
        _private_sentences(private_state=private_state),
    )
    researcher_accs, researcher_n = _score_channel(
        CHANNEL_RESEARCHER,
        _researcher_sentences(field_notes=field_notes),
    )

    channel_accs = {
        CHANNEL_PUBLIC: public_accs,
        CHANNEL_PRIVATE: private_accs,
        CHANNEL_RESEARCHER: researcher_accs,
    }
    channel_n = {
        CHANNEL_PUBLIC: public_n,
        CHANNEL_PRIVATE: private_n,
        CHANNEL_RESEARCHER: researcher_n,
    }

    # --- 2. Build per_subdimension.csv rows --------------------------
    per_sub_rows: List[dict] = []
    per_subdim_score: Dict[Tuple[str, str, str], float] = {}
    # (channel, role, sub_key) -> score
    for channel, accs in channel_accs.items():
        n_sentences_by_role = channel_n[channel]
        # All roles that appeared in this channel + _ALL.
        roles_in_channel = sorted({role for (role, _sub) in accs.keys()})
        if ROLE_ALL not in roles_in_channel and n_sentences_by_role.get(ROLE_ALL, 0) > 0:
            roles_in_channel.append(ROLE_ALL)
        for role in roles_in_channel:
            slice_n = n_sentences_by_role.get(role, 0)
            for sub_key, entry in OPENNESS_SUBDIMENSION_LEXICON.items():
                acc = accs.get((role, sub_key), _SubDimAccumulator())
                score = _density(acc, slice_n)
                per_subdim_score[(channel, role, sub_key)] = score
                per_sub_rows.append({
                    "channel": channel,
                    "role": role,
                    "dimension": entry["parent_dimension"],
                    "sub_dimension": sub_key,
                    "method": "dict",
                    "score": f"{score:+.3f}",
                    "n_relevant_sentences": acc.n_relevant,
                    "measurability": entry["measurability"],
                    "evidence_top_3": _evidence_top_3_str(acc),
                })

    # --- 3. Build per_dimension.csv rows (uniform + weighted) ---------
    per_dim_rows: List[dict] = []
    # Build a quick lookup of (channel, role, dim) -> uniform_score and
    # weighted_score for the headlines.
    channel_dim_uniform: Dict[str, Dict[str, float]] = defaultdict(dict)
    role_dim_uniform: Dict[str, Dict[Tuple[str, str], float]] = defaultdict(dict)

    for channel, accs in channel_accs.items():
        roles_in_channel = sorted({role for (role, _sub) in accs.keys()})
        if ROLE_ALL not in roles_in_channel and channel_n[channel].get(ROLE_ALL, 0) > 0:
            roles_in_channel.append(ROLE_ALL)
        for role in roles_in_channel:
            for dim in DIMENSIONS_ORDER:
                sub_keys = subdimensions_for(dim)
                sub_scores = [
                    per_subdim_score.get((channel, role, sk), 0.0)
                    for sk in sub_keys
                ]
                n_with_signal = sum(
                    1 for sk in sub_keys
                    if channel_accs[channel].get((role, sk), _SubDimAccumulator()).n_relevant > 0
                )
                if not sub_scores:
                    continue
                # Uniform aggregation.
                uniform_score = sum(sub_scores) / len(sub_scores)
                # Measurability-weighted aggregation.
                weights = [
                    measurability_weight(OPENNESS_SUBDIMENSION_LEXICON[sk]["measurability"])
                    for sk in sub_keys
                ]
                w_sum = sum(weights)
                weighted_score = (
                    sum(w * s for w, s in zip(weights, sub_scores)) / w_sum
                    if w_sum > 0 else 0.0
                )
                # Weakest/strongest sub-dimension by score.
                paired = list(zip(sub_keys, sub_scores))
                paired_sorted = sorted(paired, key=lambda p: p[1])
                weakest_sub, _ = paired_sorted[0]
                strongest_sub, _ = paired_sorted[-1]

                for aggregation, score in (
                    ("uniform", uniform_score),
                    ("measurability_weighted", weighted_score),
                ):
                    per_dim_rows.append({
                        "channel": channel,
                        "role": role,
                        "dimension": dim,
                        "method": "dict",
                        "aggregation": aggregation,
                        "score": f"{score:+.3f}",
                        "n_sub_dimensions_with_signal": n_with_signal,
                        "weakest_sub": weakest_sub,
                        "strongest_sub": strongest_sub,
                    })

                # Lookup tables for the headline csvs.
                if role == ROLE_ALL:
                    channel_dim_uniform[channel][dim] = uniform_score
                role_dim_uniform[channel][(role, dim)] = uniform_score

    # --- 4. Write the four CSVs --------------------------------------
    _write_per_subdimension_csv(scores_dir, per_sub_rows)
    _write_per_dimension_csv(scores_dir, per_dim_rows)
    _write_headline_csv(scores_dir, channel_dim_uniform)
    _write_headline_by_role_csv(scores_dir, role_dim_uniform)

    # --- 5. Markdown summary -----------------------------------------
    n_sentences_by_channel = {
        ch: channel_n[ch].get(ROLE_ALL, 0)
        for ch in (CHANNEL_PUBLIC, CHANNEL_PRIVATE, CHANNEL_RESEARCHER)
    }
    (scores_dir / "README.md").write_text(
        _render_summary_md(
            channel_score_rows=channel_dim_uniform,
            n_sentences_by_channel=n_sentences_by_channel,
        )
    )

    log.info(
        "subdimension_scores written to %s (sentences: pub=%d priv=%d res=%d)",
        scores_dir,
        n_sentences_by_channel[CHANNEL_PUBLIC],
        n_sentences_by_channel[CHANNEL_PRIVATE],
        n_sentences_by_channel[CHANNEL_RESEARCHER],
    )
    return scores_dir
