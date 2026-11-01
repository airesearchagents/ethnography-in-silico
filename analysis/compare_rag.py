"""Compare paired runs (with-RAG vs without-RAG) and emit a report.

A run is one complete simulated meeting and debrief. RAG (retrieval-augmented
generation) means searching a document collection and adding the passages found
to a language model's prompt (the text sent to it) before it writes. This file
compares runs with and without that step. TMT (top management team) means the
six simulated executives, or role agents.

This is the methodological-evidence layer for the RAG experiment. The
question it answers, in the principal investigator's words:

    "establish the fact that RAG is indeed helping the TMT members to
     refer and act given the task under a context."

Two sub-questions:

  1. Did RAG meaningfully change what the TMT decided?
       (Substantive divergence — different decisions / tensions /
        products named.)

  2. Did the TMT actually use the retrieved documents?
       (Provenance (where text came from) — citation density (how many citations
        a run holds), source coverage, no fabrication.)

The harness (a small program that runs the comparison) reads the per-run folders
that `burst_run` already produces, pairs them by their `manifest.json` (a file
listing what produced the run) content (study + scenario, the run's setting,
+ provider, the company supplying the model; condition flips on
`rag_config.enabled`), and writes one
Markdown (plain text with simple marks for headings) report per pair plus a
cross-pair summary + a flat CSV (a plain-text table any spreadsheet can open).

What it does NOT do
-------------------
- Doesn't run simulations.
- Doesn't make any LLM calls (LLM: large language model; a call is one prompt
  sent and one reply back).
- Doesn't ship significance tests — 20 paired observations is mode-
  finding (seeing what kinds of change occur), not hypothesis testing (see `08_known_limitations.md` § L8).
- Doesn't render plots — emits CSV for the notebook (an interactive
  analysis document) to consume.
- Doesn't crash on orphan (partnerless) or mismatched runs — emits warnings and
  continues so partial sweeps (planned sets of runs) still produce useful output.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models (here, the data records used below, not language models)
# ---------------------------------------------------------------------------

class PairKey(BaseModel):
    """The 6-tuple (six values taken together) that uniquely identifies a (firm × cell
    × provider) combination, where a cell is one mix of firm, industry context and
    product type. Two runs pair iff (if and only if) they match on every field except
    `rag_enabled` — which is the experimental contrast."""

    study_slug: str
    study_version: str
    company: str
    industry_context: str
    product_type: str
    tmt_provider: str  # 'gemini_pro' / 'claude' / 'openai' / etc.

    def render(self) -> str:
        """Filesystem-safe label for the per-pair output file."""
        return (
            f"{self.company}_{self.industry_context}_{self.product_type}"
            f"_{self.tmt_provider}"
        )


class RunRef(BaseModel):
    """One run's identity + parsed manifest. Held by reference so we
    can re-read the per-run JSON (plain-text structured data) files lazily during metric
    computation (no big in-memory blobs)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    path: Path
    key: PairKey
    rag_enabled: bool
    started_at: str
    manifest: Dict[str, Any] = Field(default_factory=dict)
    meta: Dict[str, Any] = Field(default_factory=dict)


class GroundedClaim(BaseModel):
    """One cited statement extracted from the RAG run.

    Three sources contribute these:
      * Phase 1 (a phase is a numbered stage of a run; this is the team's
        discussion) deliberation events with citations (most specific —
        the citation attaches to a single SPEAK/ASK/ANSWER utterance, a role's
        move in the discussion).
      * Phase 2 StrategicArtefact.citations (artefact-level — the
        citation is per-document, not per-sentence; we surface it as
        "this role's strategy document drew on this source").
      * Phase 4 (the debrief, when the researcher agent questions the team)
        panellist (a role agent being questioned) response citations.
    """

    role: str
    phase: str  # 'phase_1_deliberation' / 'phase_2_artefact' / 'phase_4_debriefing'
    statement_text: str  # the role's actual claim text
    doc_id: str
    chunk_id: Optional[str] = None
    quote: str
    supports: str = ""


class DecisionDiff(BaseModel):
    """Per-role diff of structured StrategicArtefact fields."""

    role: str
    main_decisions_added: List[str] = Field(default_factory=list)
    main_decisions_dropped: List[str] = Field(default_factory=list)
    main_decisions_kept: List[str] = Field(default_factory=list)
    key_tensions_added: List[str] = Field(default_factory=list)
    key_tensions_dropped: List[str] = Field(default_factory=list)
    key_tensions_kept: List[str] = Field(default_factory=list)
    key_challenges_added: List[str] = Field(default_factory=list)
    key_challenges_dropped: List[str] = Field(default_factory=list)
    key_challenges_kept: List[str] = Field(default_factory=list)


class CitationDensity(BaseModel):
    """How much the RAG run actually leaned on retrieved material."""

    total_citations: int = 0
    distinct_docs_cited: int = 0
    by_role: Dict[str, int] = Field(default_factory=dict)
    by_phase: Dict[str, int] = Field(default_factory=dict)
    pct_artefacts_with_citation: float = 0.0  # 0.0–1.0


class CorpusCoverage(BaseModel):
    """Which corpus (document collection) docs the run reached + actually used."""

    docs_in_corpus: List[str] = Field(default_factory=list)
    docs_retrieved_at_least_once: List[str] = Field(default_factory=list)
    docs_cited_at_least_once: List[str] = Field(default_factory=list)
    docs_never_used: List[str] = Field(default_factory=list)

    @property
    def coverage_retrieved_pct(self) -> float:
        n = len(self.docs_in_corpus)
        return (len(self.docs_retrieved_at_least_once) / n) if n else 0.0

    @property
    def coverage_cited_pct(self) -> float:
        n = len(self.docs_in_corpus)
        return (len(self.docs_cited_at_least_once) / n) if n else 0.0


class QuoteVerification(BaseModel):
    """Quote-against-source verification."""

    total_citations: int = 0
    verified: int = 0  # quote IS a substring of some retrieved chunk for the doc
                     # (substring: an exact run of text; chunk: a piece cut from a document for searching)
    unverified: int = 0  # quote not found — could be a fabrication OR could be
                          # text from a chunk this role wasn't shown (unlikely
                          # but possible if quote is paraphrased)
    flagged: List[Dict[str, Any]] = Field(default_factory=list)
    # Each flagged entry: {role, phase, doc_id, quote, reason}


class JudgingDelta(BaseModel):
    """When both runs had --judge (optional scoring of a finished run by judge
    models against a rubric, a scoring guide), the composite (combined score) + α
    (Krippendorff's alpha: agreement among the judges) delta (change)."""

    per_dimension_composite_no_rag: Dict[str, float] = Field(default_factory=dict)
    per_dimension_composite_rag: Dict[str, float] = Field(default_factory=dict)
    per_dimension_delta: Dict[str, float] = Field(default_factory=dict)
    alpha_no_rag: Optional[float] = None
    alpha_rag: Optional[float] = None
    alpha_delta: Optional[float] = None


class PairMetrics(BaseModel):
    """Everything we computed for one (no-RAG, RAG) pair."""

    key: PairKey
    no_rag_run: RunRef
    rag_run: RunRef
    grounded_claims: List[GroundedClaim] = Field(default_factory=list)
    decision_diffs: List[DecisionDiff] = Field(default_factory=list)
    citation_density: CitationDensity = Field(default_factory=CitationDensity)
    corpus_coverage: CorpusCoverage = Field(default_factory=CorpusCoverage)
    quote_verification: QuoteVerification = Field(default_factory=QuoteVerification)
    judging_delta: Optional[JudgingDelta] = None


class CrossPairMetrics(BaseModel):
    """Roll-ups across every pair."""

    n_pairs: int = 0
    n_orphans: int = 0
    orphan_reasons: List[str] = Field(default_factory=list)

    # Citation density distribution.
    citations_per_pair: List[int] = Field(default_factory=list)
    citations_per_pair_by_role: Dict[str, List[int]] = Field(default_factory=dict)

    # Doc coverage.
    avg_coverage_retrieved_pct: float = 0.0
    avg_coverage_cited_pct: float = 0.0

    # Decision divergence.
    avg_decisions_diff_per_role: float = 0.0  # mean of (added + dropped) across pairs

    # Fabrication.
    total_unverified_quotes: int = 0

    # Construct judging.
    pairs_with_judging: int = 0
    avg_composite_delta: Optional[float] = None


# ---------------------------------------------------------------------------
# Discovery + pairing
# ---------------------------------------------------------------------------

# The framework's role names. Used to derive role from strategy filenames
# like `02_strategy_documents/CEO_strategy.json`.
_ROLE_NAMES = {"CEO", "CTO", "COO", "CMO", "Product_Strategist", "Product_Designer"}


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    """Return the parsed JSON at `path`, or None if missing / invalid."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("compare_rag: could not parse %s: %s", path, exc)
        return None


def _provider_from_manifest(manifest: Dict[str, Any]) -> str:
    """Extract the TMT-team's effective provider.

    Heuristic: take `providers_used["CEO"]` when present (the team-wide
    provider). Falls back to "unknown" so the pair key never crashes
    but the orphan-report can flag it.
    """
    providers_used = manifest.get("providers_used") or {}
    return providers_used.get("CEO") or "unknown"


def load_run(run_dir: Path) -> Optional[RunRef]:
    """Build a RunRef from one results/runs/<id>/ folder, or return None.

    Reads `manifest.json` (preferred — has every key the pairing needs)
    or falls back to `00_meta.json` (less complete but still usable for
    the common fields). Returns None when neither is parseable.
    """
    manifest = _safe_load_json(run_dir / "manifest.json")
    meta = _safe_load_json(run_dir / "00_meta.json")
    if manifest is None and meta is None:
        log.info("compare_rag: skipping %s — no manifest or 00_meta", run_dir)
        return None

    src = manifest or meta or {}

    # PairKey fields. Manifest is the authoritative source; meta carries
    # most of them too via `extra_meta` from the burst_run path.
    company = src.get("company") or (meta or {}).get("company")
    industry_context = src.get("industry_context") or (meta or {}).get("industry_context")
    product_type = src.get("product_type") or (meta or {}).get("product_type")
    study_slug = src.get("study_slug") or (meta or {}).get("study_slug") or ""
    study_version = src.get("study_version") or (meta or {}).get("study_version") or ""
    started_at = src.get("started_at") or (meta or {}).get("started_at") or (meta or {}).get("written_at") or ""

    if not (company and industry_context and product_type):
        log.info("compare_rag: skipping %s — missing scenario keys", run_dir)
        return None

    tmt_provider = _provider_from_manifest(manifest or {})
    if tmt_provider == "unknown":
        # Runs from the command line have no manifest yet; their meta names each role's model.
        tmt_provider = ((meta or {}).get("role_models") or {}).get("CEO") or "unknown"

    rag_enabled = bool(
        (manifest or {}).get("rag_config", {}).get("enabled")
        or (meta or {}).get("phases_captured", {}).get("rag")
    )

    return RunRef(
        path=run_dir,
        key=PairKey(
            study_slug=study_slug,
            study_version=study_version,
            company=company,
            industry_context=industry_context,
            product_type=product_type,
            tmt_provider=tmt_provider,
        ),
        rag_enabled=rag_enabled,
        started_at=started_at,
        manifest=manifest or {},
        meta=meta or {},
    )


def discover_runs(runs_root: Path) -> List[RunRef]:
    """Scan `runs_root` for per-run subdirectories. Sort by started_at."""
    if not runs_root.is_dir():
        return []
    runs: List[RunRef] = []
    for child in sorted(runs_root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith(".") or child.name.startswith("_"):
            continue
        ref = load_run(child)
        if ref is not None:
            runs.append(ref)
    runs.sort(key=lambda r: r.started_at)
    return runs


def auto_pair_runs(
    runs: List[RunRef],
) -> Tuple[List[Tuple[RunRef, RunRef]], List[str]]:
    """Group runs by PairKey + condition; pair most-recent of each.

    Returns:
        pairs: list of (no_rag_run, rag_run)
        orphan_reasons: human-readable lines for keys without both
            conditions (shown in the cross-pair report).
    """
    # Bucket: key_tuple -> {rag: RunRef, no_rag: RunRef}, keeping latest.
    buckets: Dict[Tuple[str, ...], Dict[str, RunRef]] = {}
    for r in runs:
        k = tuple(r.key.model_dump().values())
        bucket = buckets.setdefault(k, {})
        cond = "rag" if r.rag_enabled else "no_rag"
        existing = bucket.get(cond)
        if existing is None or r.started_at >= existing.started_at:
            bucket[cond] = r

    pairs: List[Tuple[RunRef, RunRef]] = []
    orphans: List[str] = []
    for k, bucket in sorted(buckets.items()):
        if "rag" in bucket and "no_rag" in bucket:
            pairs.append((bucket["no_rag"], bucket["rag"]))
        else:
            present = sorted(bucket.keys())
            sample = next(iter(bucket.values()))
            orphans.append(
                f"{sample.key.render()}: only {present} present "
                f"(folder: {sample.path.name})"
            )
    return pairs, orphans


# ---------------------------------------------------------------------------
# Per-pair: grounded claims (statements traced to a firm's documents; the headline section)
# ---------------------------------------------------------------------------

def _strategy_file_role(path: Path) -> Optional[str]:
    """Derive a role name from `<role>_strategy.json`. None if not matching."""
    m = re.match(r"(.+?)_strategy\.json$", path.name)
    if not m:
        return None
    role = m.group(1)
    if role in _ROLE_NAMES:
        return role
    return None


def extract_grounded_claims(rag_run: RunRef) -> List[GroundedClaim]:
    """Pull every cited statement from the RAG run's three persisted phases.

    Phase 1 (`01_deliberation/interaction_log.json`) — citations tie
    to individual SPEAK/ASK/ANSWER events.
    Phase 2 (`02_strategy_documents/<Role>_strategy.json`) — citations
    are at the artefact level (per-doc, not per-sentence). We surface
    each as a claim against the role's overall document.
    Phase 4 (`04_interview/transcript.json`) — citations tie to
    individual panellist responses inside exchanges.
    """
    claims: List[GroundedClaim] = []

    # Phase 1
    delib = _safe_load_json(rag_run.path / "01_deliberation" / "interaction_log.json")
    for event in (delib or {}).get("events", []) or []:
        for c in event.get("citations") or []:
            claims.append(GroundedClaim(
                role=event.get("role", "?"),
                phase="phase_1_deliberation",
                statement_text=(event.get("text") or "").strip(),
                doc_id=c.get("doc_id", "?"),
                chunk_id=c.get("chunk_id"),
                quote=c.get("quote", ""),
                supports=c.get("supports", ""),
            ))

    # Phase 2
    strat_dir = rag_run.path / "02_strategy_documents"
    if strat_dir.is_dir():
        for fp in sorted(strat_dir.iterdir()):
            role = _strategy_file_role(fp)
            if role is None:
                continue
            artefact = _safe_load_json(fp) or {}
            for c in artefact.get("citations") or []:
                claims.append(GroundedClaim(
                    role=role,
                    phase="phase_2_artefact",
                    statement_text=(artefact.get("title") or "(strategy document)").strip(),
                    doc_id=c.get("doc_id", "?"),
                    chunk_id=c.get("chunk_id"),
                    quote=c.get("quote", ""),
                    supports=c.get("supports", ""),
                ))

    # Phase 4
    debrief = _safe_load_json(rag_run.path / "04_interview" / "transcript.json")
    for exchange in (debrief or {}).get("exchanges", []) or []:
        for resp in exchange.get("responses") or []:
            for c in resp.get("citations") or []:
                claims.append(GroundedClaim(
                    role=resp.get("role", "?"),
                    phase="phase_4_debriefing",
                    statement_text=(resp.get("text") or "").strip(),
                    doc_id=c.get("doc_id", "?"),
                    chunk_id=c.get("chunk_id"),
                    quote=c.get("quote", ""),
                    supports=c.get("supports", ""),
                ))

    return claims


# ---------------------------------------------------------------------------
# Per-pair: decision diff (set difference per role per field)
# ---------------------------------------------------------------------------

def _load_role_strategy(run: RunRef, role: str) -> Optional[Dict[str, Any]]:
    return _safe_load_json(
        run.path / "02_strategy_documents" / f"{role}_strategy.json"
    )


def compute_decision_diffs(no_rag: RunRef, rag: RunRef) -> List[DecisionDiff]:
    """Per-role set-diff of `main_decisions`, `key_tensions`, `key_challenges`."""
    diffs: List[DecisionDiff] = []
    for role in sorted(_ROLE_NAMES):
        no_rag_a = _load_role_strategy(no_rag, role) or {}
        rag_a = _load_role_strategy(rag, role) or {}
        if not no_rag_a and not rag_a:
            continue  # role didn't author in either run
        d = DecisionDiff(role=role)
        for field_name, attr_added, attr_dropped, attr_kept in [
            ("main_decisions", "main_decisions_added", "main_decisions_dropped", "main_decisions_kept"),
            ("key_tensions", "key_tensions_added", "key_tensions_dropped", "key_tensions_kept"),
            ("key_challenges", "key_challenges_added", "key_challenges_dropped", "key_challenges_kept"),
        ]:
            no_rag_set = set(no_rag_a.get(field_name) or [])
            rag_set = set(rag_a.get(field_name) or [])
            setattr(d, attr_added, sorted(rag_set - no_rag_set))
            setattr(d, attr_dropped, sorted(no_rag_set - rag_set))
            setattr(d, attr_kept, sorted(rag_set & no_rag_set))
        diffs.append(d)
    return diffs


# ---------------------------------------------------------------------------
# Per-pair: citation density
# ---------------------------------------------------------------------------

def compute_citation_density(rag_run: RunRef) -> CitationDensity:
    """Sum citations across all three persisted phases of the RAG run."""
    cd = CitationDensity()
    distinct_docs: set = set()
    total_artefacts = 0
    artefacts_with_citation = 0

    # Phase 1
    delib = _safe_load_json(rag_run.path / "01_deliberation" / "interaction_log.json")
    for event in (delib or {}).get("events", []) or []:
        cites = event.get("citations") or []
        if not cites:
            continue
        cd.total_citations += len(cites)
        cd.by_role[event.get("role", "?")] = (
            cd.by_role.get(event.get("role", "?"), 0) + len(cites)
        )
        cd.by_phase["phase_1_deliberation"] = (
            cd.by_phase.get("phase_1_deliberation", 0) + len(cites)
        )
        for c in cites:
            distinct_docs.add(c.get("doc_id", "?"))

    # Phase 2
    strat_dir = rag_run.path / "02_strategy_documents"
    if strat_dir.is_dir():
        for fp in sorted(strat_dir.iterdir()):
            role = _strategy_file_role(fp)
            if role is None:
                continue
            artefact = _safe_load_json(fp) or {}
            total_artefacts += 1
            cites = artefact.get("citations") or []
            if cites:
                artefacts_with_citation += 1
            cd.total_citations += len(cites)
            if cites:
                cd.by_role[role] = cd.by_role.get(role, 0) + len(cites)
                cd.by_phase["phase_2_artefact"] = (
                    cd.by_phase.get("phase_2_artefact", 0) + len(cites)
                )
            for c in cites:
                distinct_docs.add(c.get("doc_id", "?"))

    # Phase 4
    debrief = _safe_load_json(rag_run.path / "04_interview" / "transcript.json")
    for exchange in (debrief or {}).get("exchanges", []) or []:
        for resp in exchange.get("responses") or []:
            cites = resp.get("citations") or []
            if not cites:
                continue
            cd.total_citations += len(cites)
            cd.by_role[resp.get("role", "?")] = (
                cd.by_role.get(resp.get("role", "?"), 0) + len(cites)
            )
            cd.by_phase["phase_4_debriefing"] = (
                cd.by_phase.get("phase_4_debriefing", 0) + len(cites)
            )
            for c in cites:
                distinct_docs.add(c.get("doc_id", "?"))

    cd.distinct_docs_cited = len(distinct_docs)
    cd.pct_artefacts_with_citation = (
        artefacts_with_citation / total_artefacts if total_artefacts else 0.0
    )
    return cd


# ---------------------------------------------------------------------------
# Per-pair: corpus coverage
# ---------------------------------------------------------------------------

def _all_cited_doc_ids(rag_run: RunRef) -> set:
    """Union of doc_ids across all citations in the run."""
    out: set = set()
    delib = _safe_load_json(rag_run.path / "01_deliberation" / "interaction_log.json")
    for ev in (delib or {}).get("events", []) or []:
        for c in ev.get("citations") or []:
            out.add(c.get("doc_id", "?"))
    strat_dir = rag_run.path / "02_strategy_documents"
    if strat_dir.is_dir():
        for fp in sorted(strat_dir.iterdir()):
            if _strategy_file_role(fp) is None:
                continue
            artefact = _safe_load_json(fp) or {}
            for c in artefact.get("citations") or []:
                out.add(c.get("doc_id", "?"))
    debrief = _safe_load_json(rag_run.path / "04_interview" / "transcript.json")
    for ex in (debrief or {}).get("exchanges", []) or []:
        for r in ex.get("responses") or []:
            for c in r.get("citations") or []:
                out.add(c.get("doc_id", "?"))
    return out


def _read_retrieval_log(rag_run: RunRef) -> List[Dict[str, Any]]:
    """Read 07_rag/retrieval_log.jsonl as a list of records."""
    fp = rag_run.path / "07_rag" / "retrieval_log.jsonl"
    if not fp.exists():
        return []
    records: List[Dict[str, Any]] = []
    for line in fp.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            log.warning("compare_rag: skipping malformed retrieval_log line in %s", fp)
    return records


def _all_retrieved_doc_ids(retrieval_log: List[Dict[str, Any]]) -> set:
    out: set = set()
    for rec in retrieval_log:
        for r in rec.get("retrieved") or []:
            out.add(r.get("doc_id", "?"))
    return out


def compute_corpus_coverage(rag_run: RunRef) -> CorpusCoverage:
    """Which corpus docs were retrieved and/or cited at least once."""
    corpus_manifest = _safe_load_json(
        rag_run.path / "07_rag" / "corpus_manifest.json"
    ) or {}
    docs_in_corpus = [
        d.get("display_name") or d.get("doc_id") or "?"
        for d in corpus_manifest.get("documents", []) or []
        if d.get("display_name") or d.get("doc_id")
    ]
    retrieval_log = _read_retrieval_log(rag_run)
    retrieved = _all_retrieved_doc_ids(retrieval_log)
    cited = _all_cited_doc_ids(rag_run)
    never_used = [d for d in docs_in_corpus if d not in retrieved and d not in cited]
    return CorpusCoverage(
        docs_in_corpus=sorted(docs_in_corpus),
        docs_retrieved_at_least_once=sorted(retrieved & set(docs_in_corpus))
            or sorted(retrieved),
        docs_cited_at_least_once=sorted(cited & set(docs_in_corpus))
            or sorted(cited),
        docs_never_used=sorted(never_used),
    )


# ---------------------------------------------------------------------------
# Per-pair: quote verification
# ---------------------------------------------------------------------------

def _index_chunks_by_doc(retrieval_log: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """{doc_id -> list of chunk text strings ever retrieved for that doc}."""
    out: Dict[str, List[str]] = {}
    for rec in retrieval_log:
        for r in rec.get("retrieved") or []:
            doc = r.get("doc_id", "?")
            text = r.get("text") or r.get("text_preview") or ""
            if not text:
                continue
            out.setdefault(doc, []).append(text)
    return out


def _quote_found_in_any_chunk(quote: str, chunks: List[str]) -> bool:
    """Substring check across all retrieved chunks for that doc.

    Compares whitespace-collapsed lowercased strings — robust to minor
    casing/whitespace differences a role might introduce when copying
    a quote from the retrieved text.
    """
    if not quote:
        return False
    q = re.sub(r"\s+", " ", quote.lower()).strip()
    if not q:
        return False
    for c in chunks:
        normalised = re.sub(r"\s+", " ", c.lower())
        if q in normalised:
            return True
    return False


def verify_quotes(rag_run: RunRef) -> QuoteVerification:
    """For every citation, check the quote appears in some retrieved chunk
    of the same doc."""
    retrieval_log = _read_retrieval_log(rag_run)
    chunks_by_doc = _index_chunks_by_doc(retrieval_log)
    qv = QuoteVerification()

    def _check_one(role: str, phase: str, c: Dict[str, Any]) -> None:
        doc_id = c.get("doc_id", "?")
        quote = c.get("quote", "")
        chunks = chunks_by_doc.get(doc_id, [])
        qv.total_citations += 1
        if _quote_found_in_any_chunk(quote, chunks):
            qv.verified += 1
        else:
            qv.unverified += 1
            qv.flagged.append({
                "role": role,
                "phase": phase,
                "doc_id": doc_id,
                "quote": quote[:200],
                "reason": (
                    "doc_not_in_retrieval_log" if not chunks
                    else "quote_not_found_in_retrieved_chunks"
                ),
            })

    # Phase 1
    delib = _safe_load_json(rag_run.path / "01_deliberation" / "interaction_log.json")
    for ev in (delib or {}).get("events", []) or []:
        for c in ev.get("citations") or []:
            _check_one(ev.get("role", "?"), "phase_1_deliberation", c)

    # Phase 2
    strat_dir = rag_run.path / "02_strategy_documents"
    if strat_dir.is_dir():
        for fp in sorted(strat_dir.iterdir()):
            role = _strategy_file_role(fp)
            if role is None:
                continue
            artefact = _safe_load_json(fp) or {}
            for c in artefact.get("citations") or []:
                _check_one(role, "phase_2_artefact", c)

    # Phase 4
    debrief = _safe_load_json(rag_run.path / "04_interview" / "transcript.json")
    for ex in (debrief or {}).get("exchanges", []) or []:
        for r in ex.get("responses") or []:
            for c in r.get("citations") or []:
                _check_one(r.get("role", "?"), "phase_4_debriefing", c)

    return qv


# ---------------------------------------------------------------------------
# Per-pair: construct-judging delta (optional)
# ---------------------------------------------------------------------------

def _load_judging_aggregate(run: RunRef) -> Optional[Dict[str, Any]]:
    return _safe_load_json(run.path / "05_judging" / "aggregate.json")


def compute_judging_delta(no_rag: RunRef, rag: RunRef) -> Optional[JudgingDelta]:
    """Compute per-dimension composite + α delta if both runs ran Phase 5
    (judge scoring)."""
    nra = _load_judging_aggregate(no_rag)
    ra = _load_judging_aggregate(rag)
    if not (nra and ra):
        return None
    out = JudgingDelta()

    # The aggregate schema (a template of required fields) has `dimension_composites: Dict[str, float]`
    # and `alpha: Optional[float]`. Be tolerant of legacy shapes.
    no_rag_comp = nra.get("dimension_composites") or nra.get("composites") or {}
    rag_comp = ra.get("dimension_composites") or ra.get("composites") or {}
    out.per_dimension_composite_no_rag = dict(no_rag_comp)
    out.per_dimension_composite_rag = dict(rag_comp)
    for dim in set(no_rag_comp.keys()) | set(rag_comp.keys()):
        n = no_rag_comp.get(dim)
        r = rag_comp.get(dim)
        if n is not None and r is not None:
            out.per_dimension_delta[dim] = float(r) - float(n)

    out.alpha_no_rag = nra.get("alpha")
    out.alpha_rag = ra.get("alpha")
    if out.alpha_no_rag is not None and out.alpha_rag is not None:
        out.alpha_delta = float(out.alpha_rag) - float(out.alpha_no_rag)

    return out


# ---------------------------------------------------------------------------
# Per-pair driver
# ---------------------------------------------------------------------------

def compute_pair_metrics(no_rag: RunRef, rag: RunRef) -> PairMetrics:
    """Run every per-pair metric. Single call; lightweight."""
    return PairMetrics(
        key=no_rag.key,
        no_rag_run=no_rag,
        rag_run=rag,
        grounded_claims=extract_grounded_claims(rag),
        decision_diffs=compute_decision_diffs(no_rag, rag),
        citation_density=compute_citation_density(rag),
        corpus_coverage=compute_corpus_coverage(rag),
        quote_verification=verify_quotes(rag),
        judging_delta=compute_judging_delta(no_rag, rag),
    )


# ---------------------------------------------------------------------------
# Cross-pair roll-ups
# ---------------------------------------------------------------------------

def compute_cross_pair_metrics(
    pairs: List[PairMetrics], orphan_reasons: Optional[List[str]] = None,
) -> CrossPairMetrics:
    cm = CrossPairMetrics()
    cm.n_pairs = len(pairs)
    cm.n_orphans = len(orphan_reasons or [])
    cm.orphan_reasons = list(orphan_reasons or [])

    # Citation density.
    cm.citations_per_pair = [p.citation_density.total_citations for p in pairs]
    for p in pairs:
        for role, n in p.citation_density.by_role.items():
            cm.citations_per_pair_by_role.setdefault(role, []).append(n)

    # Doc coverage averages.
    if pairs:
        cm.avg_coverage_retrieved_pct = sum(
            p.corpus_coverage.coverage_retrieved_pct for p in pairs
        ) / len(pairs)
        cm.avg_coverage_cited_pct = sum(
            p.corpus_coverage.coverage_cited_pct for p in pairs
        ) / len(pairs)

    # Decision divergence: mean of (added + dropped) across all roles in all pairs.
    diff_counts: List[int] = []
    for p in pairs:
        for d in p.decision_diffs:
            diff_counts.append(
                len(d.main_decisions_added) + len(d.main_decisions_dropped)
                + len(d.key_tensions_added) + len(d.key_tensions_dropped)
                + len(d.key_challenges_added) + len(d.key_challenges_dropped)
            )
    cm.avg_decisions_diff_per_role = (
        sum(diff_counts) / len(diff_counts) if diff_counts else 0.0
    )

    # Fabrications.
    cm.total_unverified_quotes = sum(
        p.quote_verification.unverified for p in pairs
    )

    # Judging.
    with_judging = [p for p in pairs if p.judging_delta is not None]
    cm.pairs_with_judging = len(with_judging)
    if with_judging:
        deltas: List[float] = []
        for p in with_judging:
            jd = p.judging_delta  # noqa: PLW2901
            for v in jd.per_dimension_delta.values():
                deltas.append(v)
        cm.avg_composite_delta = sum(deltas) / len(deltas) if deltas else None

    return cm


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def render_pair_report_md(p: PairMetrics) -> str:
    """One per-pair Markdown report. Grounded claims first."""
    out: List[str] = []
    out.append(f"# {p.key.render()}")
    out.append("")
    out.append(f"- **Study:** {p.key.study_slug} v{p.key.study_version}")
    out.append(f"- **Provider:** {p.key.tmt_provider}")
    out.append(f"- **No-RAG run:** `{p.no_rag_run.path.name}` (started {p.no_rag_run.started_at})")
    out.append(f"- **RAG run:**    `{p.rag_run.path.name}` (started {p.rag_run.started_at})")
    out.append("")

    # 1. Headline: grounded claims (lead with this, per the PI's (lead researcher's) direction).
    out.append("## Grounded claims — RAG-backed statements with verbatim source")
    out.append("")
    if not p.grounded_claims:
        out.append("_No citations recorded in the RAG run._")
        out.append("")
    else:
        # Group by role for readability.
        by_role: Dict[str, List[GroundedClaim]] = {}
        for c in p.grounded_claims:
            by_role.setdefault(c.role, []).append(c)
        for role in sorted(by_role.keys()):
            claims = by_role[role]
            out.append(f"### {role} — {len(claims)} grounded claim{'s' if len(claims) != 1 else ''}")
            out.append("")
            for i, c in enumerate(claims, 1):
                phase_label = c.phase.replace("phase_", "P").replace("_", " ")
                out.append(f"**{i}. [{phase_label}]** _{c.supports or '(no supports tag)'}_")
                out.append("")
                stmt = c.statement_text or "(no statement text)"
                # Truncate long statement text — full text is in the JSON.
                if len(stmt) > 400:
                    stmt = stmt[:400].rstrip() + " […]"
                out.append(f"> {stmt}")
                out.append("")
                out.append(f"> ↳ **`{c.doc_id}`** _(chunk `{c.chunk_id or '?'}`)_")
                out.append("> ")
                qt = c.quote or "(no quote)"
                if len(qt) > 400:
                    qt = qt[:400].rstrip() + " […]"
                out.append(f"> > \"{qt}\"")
                out.append("")
            out.append("")

    # 2. Decision diff.
    out.append("## Decision diff")
    out.append("")
    if not p.decision_diffs:
        out.append("_No role artefacts found in either run._")
    else:
        for d in p.decision_diffs:
            out.append(f"### {d.role}")
            out.append("")
            for label, added, dropped, kept in [
                ("Main decisions", d.main_decisions_added, d.main_decisions_dropped, d.main_decisions_kept),
                ("Key tensions",   d.key_tensions_added,   d.key_tensions_dropped,   d.key_tensions_kept),
                ("Key challenges", d.key_challenges_added, d.key_challenges_dropped, d.key_challenges_kept),
            ]:
                out.append(f"**{label}** — {len(added)} added / {len(dropped)} dropped / {len(kept)} kept")
                out.append("")
                if added:
                    out.append("_Added (RAG only):_")
                    for x in added:
                        out.append(f"- {x}")
                    out.append("")
                if dropped:
                    out.append("_Dropped (no-RAG only):_")
                    for x in dropped:
                        out.append(f"- {x}")
                    out.append("")
            out.append("")
    out.append("")

    # 3. Citation density.
    cd = p.citation_density
    out.append("## Citation density")
    out.append("")
    out.append(f"- **Total citations:** {cd.total_citations}")
    out.append(f"- **Distinct documents cited:** {cd.distinct_docs_cited}")
    out.append(f"- **Strategy documents with ≥ 1 citation:** {_fmt_pct(cd.pct_artefacts_with_citation)}")
    out.append("")
    if cd.by_role:
        out.append("| Role | Citations |")
        out.append("|---|---:|")
        for role in sorted(cd.by_role.keys()):
            out.append(f"| {role} | {cd.by_role[role]} |")
        out.append("")
    if cd.by_phase:
        out.append("| Phase | Citations |")
        out.append("|---|---:|")
        for phase in sorted(cd.by_phase.keys()):
            out.append(f"| {phase} | {cd.by_phase[phase]} |")
        out.append("")

    # 4. Corpus coverage.
    cc = p.corpus_coverage
    out.append("## Corpus coverage")
    out.append("")
    out.append(f"- **Documents in corpus:** {len(cc.docs_in_corpus)}")
    out.append(f"- **Retrieved at least once:** {len(cc.docs_retrieved_at_least_once)} ({_fmt_pct(cc.coverage_retrieved_pct)})")
    out.append(f"- **Cited at least once:** {len(cc.docs_cited_at_least_once)} ({_fmt_pct(cc.coverage_cited_pct)})")
    if cc.docs_never_used:
        out.append(f"- **Never retrieved or cited:** {len(cc.docs_never_used)}")
        for d in cc.docs_never_used:
            out.append(f"  - {d}")
    out.append("")

    # 5. Quote verification.
    qv = p.quote_verification
    out.append("## Quote verification")
    out.append("")
    if qv.total_citations == 0:
        out.append("_No citations to verify._")
    else:
        out.append(f"- **Citations checked:** {qv.total_citations}")
        out.append(f"- **Verified (quote ⊆ retrieved chunk):** {qv.verified}")
        out.append(f"- **Unverified:** {qv.unverified}")
        if qv.flagged:
            out.append("")
            out.append("_Flagged for review:_")
            out.append("")
            for f in qv.flagged:
                out.append(
                    f"- **{f['role']}** in `{f['phase']}` cited `{f['doc_id']}` "
                    f"— reason: `{f['reason']}` — quote: \"{f['quote']}\""
                )
    out.append("")

    # 6. Construct-judging delta (optional).
    if p.judging_delta is not None:
        jd = p.judging_delta
        out.append("## Construct-judging delta (Phase 5)")
        out.append("")
        if jd.per_dimension_delta:
            out.append("| Dimension | No-RAG | RAG | Δ |")
            out.append("|---|---:|---:|---:|")
            for dim in sorted(jd.per_dimension_delta.keys()):
                n = jd.per_dimension_composite_no_rag.get(dim, 0.0)
                r = jd.per_dimension_composite_rag.get(dim, 0.0)
                out.append(f"| {dim} | {n:.2f} | {r:.2f} | {jd.per_dimension_delta[dim]:+.2f} |")
            out.append("")
        if jd.alpha_no_rag is not None or jd.alpha_rag is not None:
            out.append(
                f"- **Krippendorff's α:** no-RAG = {jd.alpha_no_rag}, "
                f"RAG = {jd.alpha_rag}, Δ = {jd.alpha_delta}"
            )
        out.append("")

    return "\n".join(out)


def render_cross_pair_summary_md(
    cross: CrossPairMetrics,
    pairs: List[PairMetrics],
) -> str:
    out: List[str] = []
    out.append("# Cross-pair RAG comparison summary")
    out.append("")
    out.append(f"Generated: {datetime.now().isoformat()}")
    out.append("")
    out.append(f"- **Paired runs:** {cross.n_pairs}")
    out.append(f"- **Orphaned runs (only one condition):** {cross.n_orphans}")
    if cross.orphan_reasons:
        out.append("")
        out.append("_Orphans:_")
        for line in cross.orphan_reasons:
            out.append(f"  - {line}")
    out.append("")

    if pairs:
        out.append("## Index")
        out.append("")
        for p in pairs:
            out.append(f"- [{p.key.render()}](per_pair/{p.key.render()}.md)")
        out.append("")

    out.append("## Citation density across pairs")
    out.append("")
    if cross.citations_per_pair:
        sorted_n = sorted(cross.citations_per_pair)
        n = len(sorted_n)
        median = (sorted_n[n // 2] if n % 2 else (sorted_n[n // 2 - 1] + sorted_n[n // 2]) / 2)
        out.append(f"- **Pairs:** {n}")
        out.append(f"- **Citations per pair — min / median / max:** {sorted_n[0]} / {median} / {sorted_n[-1]}")
        out.append(f"- **Citations per pair — mean:** {sum(sorted_n) / n:.1f}")
        out.append("")

    if cross.citations_per_pair_by_role:
        out.append("### Citations per role across pairs")
        out.append("")
        out.append("| Role | Mean | Min | Max |")
        out.append("|---|---:|---:|---:|")
        for role in sorted(cross.citations_per_pair_by_role.keys()):
            counts = cross.citations_per_pair_by_role[role]
            mean = sum(counts) / len(counts) if counts else 0.0
            out.append(
                f"| {role} | {mean:.1f} | {min(counts)} | {max(counts)} |"
            )
        out.append("")

    out.append("## Corpus coverage across pairs")
    out.append("")
    out.append(f"- **Avg % of corpus retrieved at least once:** {_fmt_pct(cross.avg_coverage_retrieved_pct)}")
    out.append(f"- **Avg % of corpus cited at least once:** {_fmt_pct(cross.avg_coverage_cited_pct)}")
    out.append("")

    out.append("## Decision divergence")
    out.append("")
    out.append(f"- **Mean count of (added + dropped) per role per pair:** {cross.avg_decisions_diff_per_role:.1f}")
    out.append("")
    out.append(
        "Interpretation: high numbers = RAG meaningfully moved the deliberation; "
        "low numbers = RAG runs landed on similar conclusions to no-RAG runs."
    )
    out.append("")

    out.append("## Quote-verification health")
    out.append("")
    out.append(f"- **Total unverified quotes across all pairs:** {cross.total_unverified_quotes}")
    out.append(
        "  _(non-zero is a fabrication signal — review the per-pair report for the source.)_"
    )
    out.append("")

    if cross.pairs_with_judging > 0:
        out.append("## Construct-judging deltas (where Phase 5 ran)")
        out.append("")
        out.append(f"- **Pairs with judging in both conditions:** {cross.pairs_with_judging}")
        if cross.avg_composite_delta is not None:
            out.append(
                f"- **Average composite delta across dimensions:** "
                f"{cross.avg_composite_delta:+.2f}"
            )
        out.append("")

    return "\n".join(out)


def emit_summary_csv(pairs: List[PairMetrics], out_path: Path) -> None:
    """Flat CSV: one row per pair × per role."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "study_slug", "study_version", "company", "industry_context",
        "product_type", "tmt_provider", "role",
        "main_decisions_added", "main_decisions_dropped", "main_decisions_kept",
        "key_tensions_added", "key_tensions_dropped", "key_tensions_kept",
        "key_challenges_added", "key_challenges_dropped", "key_challenges_kept",
        "citations_for_role",
    ]
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in pairs:
            cites_by_role = p.citation_density.by_role
            for d in p.decision_diffs:
                writer.writerow({
                    "study_slug": p.key.study_slug,
                    "study_version": p.key.study_version,
                    "company": p.key.company,
                    "industry_context": p.key.industry_context,
                    "product_type": p.key.product_type,
                    "tmt_provider": p.key.tmt_provider,
                    "role": d.role,
                    "main_decisions_added": len(d.main_decisions_added),
                    "main_decisions_dropped": len(d.main_decisions_dropped),
                    "main_decisions_kept": len(d.main_decisions_kept),
                    "key_tensions_added": len(d.key_tensions_added),
                    "key_tensions_dropped": len(d.key_tensions_dropped),
                    "key_tensions_kept": len(d.key_tensions_kept),
                    "key_challenges_added": len(d.key_challenges_added),
                    "key_challenges_dropped": len(d.key_challenges_dropped),
                    "key_challenges_kept": len(d.key_challenges_kept),
                    "citations_for_role": cites_by_role.get(d.role, 0),
                })


# ---------------------------------------------------------------------------
# CLI (command-line interface: using a program by typing commands)
# ---------------------------------------------------------------------------

def _default_out_dir() -> Path:
    return Path("results/comparisons") / datetime.now().strftime("%Y-%m-%d_%H%M%S")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="analysis.compare_rag",
        description=(
            "Pair every (firm × cell × provider) run under --runs-root by "
            "rag_config.enabled, compute the with-RAG vs without-RAG diff, "
            "and emit a per-pair Markdown report + a cross-pair summary + a "
            "flat CSV of per-pair × per-role metrics."
        ),
    )
    p.add_argument(
        "--runs-root",
        default="results/runs",
        help="Parent directory to scan for per-run subfolders. Default: %(default)s",
    )
    p.add_argument(
        "--out",
        default=None,
        help=(
            "Output directory. Defaults to "
            "results/comparisons/<YYYY-MM-DD_HHMMSS>/. Created if missing."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="List the pairings the harness would form; don't compute metrics or write reports.",
    )
    p.add_argument(
        "--log-level",
        default="WARNING",
        help="Logger level: DEBUG / INFO / WARNING / ERROR. Default WARNING.",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.WARNING))

    runs_root = Path(args.runs_root)
    if not runs_root.is_dir():
        print(f"ERROR: --runs-root does not exist or is not a directory: {runs_root}")
        return 1

    print(f"scanning runs under: {runs_root}")
    runs = discover_runs(runs_root)
    print(f"found {len(runs)} valid run(s)")
    if not runs:
        return 0

    pairs_raw, orphan_reasons = auto_pair_runs(runs)
    print(f"paired: {len(pairs_raw)}")
    print(f"orphans: {len(orphan_reasons)}")

    if args.dry_run:
        print()
        print("--- pairings ---")
        for no_rag, rag in pairs_raw:
            print(f"  {no_rag.key.render()}")
            print(f"    no-RAG: {no_rag.path.name}")
            print(f"       RAG: {rag.path.name}")
        if orphan_reasons:
            print()
            print("--- orphans ---")
            for line in orphan_reasons:
                print(f"  {line}")
        return 0

    if not pairs_raw:
        print("nothing to compare — no paired runs found")
        # Still emit a summary so the orphan list is preserved.
        out_dir = Path(args.out) if args.out else _default_out_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        cross = compute_cross_pair_metrics([], orphan_reasons)
        (out_dir / "README.md").write_text(
            render_cross_pair_summary_md(cross, [])
        )
        return 0

    out_dir = Path(args.out) if args.out else _default_out_dir()
    per_pair_dir = out_dir / "per_pair"
    per_pair_dir.mkdir(parents=True, exist_ok=True)

    print(f"writing to: {out_dir}")
    pair_metrics: List[PairMetrics] = []
    for no_rag, rag in pairs_raw:
        pm = compute_pair_metrics(no_rag, rag)
        pair_metrics.append(pm)
        per_pair_path = per_pair_dir / f"{pm.key.render()}.md"
        per_pair_path.write_text(render_pair_report_md(pm))
        print(f"  + {per_pair_path.relative_to(out_dir)}")

    cross = compute_cross_pair_metrics(pair_metrics, orphan_reasons)
    (out_dir / "README.md").write_text(
        render_cross_pair_summary_md(cross, pair_metrics)
    )
    emit_summary_csv(pair_metrics, out_dir / "summary.csv")
    print(f"  + README.md")
    print(f"  + summary.csv")
    print()
    print(f"done — {len(pair_metrics)} pair(s) compared")
    return 0


if __name__ == "__main__":  # pragma: no cover  (exercised via tests)
    sys.exit(main())
