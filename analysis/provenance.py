"""Trace where the words in a finished run came from. Makes no model calls.

A run is one complete simulated meeting and debrief. Language models complete what
they are given, so a passage can read like a finding when a prompt (the text sent to
a model), a question or another agent (a model given a role and instructions)
supplied it. This report
gives a coder the checks to make before treating a passage as data:

  * where each debrief (the researcher agent's interview of the team) answer's
    phrases first appeared;
  * named terms that first appear in the debrief;
  * claims about the past that earlier records do not support;
  * researcher questions that repeat a protocol (the debrief's rules and topics) stem;
  * phrases the team shares across roles, and how alike the roles are;
  * for grounded runs (where roles receive and cite a firm's documents), whether
    cited quotes match what was retrieved.

These are text matches, so they flag passages to read. They do not decide
what caused a passage.

Usage
-----
    python -m analysis.provenance --run-dir <path>

    --prompts-root <dir>   Checkout (copy of the code) whose prompts the run used.
                           Default: this one.
    --out-dir <dir>        Default: results/provenance/<run>/

The source run is never changed.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from ..roles.researcher_schemas import split_panel_reply
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from roles.researcher_schemas import split_panel_reply  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parent.parent

PROMPT_FILES = (
    "protocols/ethnographic_protocol.yaml",
    "orchestrator/artefact_collection.py",
    "orchestrator/concurrent_mode.py",
    "roles/context_definitions.py",
)
PROMPT_GLOBS = ("roles/*_agent.py", "studies/*/debriefing_overlay.yaml")

# How much of each passage (a piece cut from a document for searching) agents get
# is logged as `shown_chars`. Runs from before
# that was logged showed this much.
SHOWN_CHARS = 1200

# Earliest source first. A phrase is credited to the first place it appears.
ORIGINS = (
    "prompts",
    "retrieved passages",
    "deliberation",
    "private notes",
    "strategy documents",
    "researcher's questions",
    "another role's earlier answer",
    "own earlier answer",
    "new in this answer",
)

STOPWORDS = frozenset(
    """a about above after again all also am an and any are as at be because been
    before being between both but by can could did do does doing down during each
    few for from further had has have having he her here hers him his how i if in
    into is it its itself just me more most my no nor not now of off on once only
    or other our ours out over own same she should so some such than that the their
    them then there these they this those through to too under until up very was we
    were what when where which while who whom why will with would you your us yes
    """.split()
)

ROLE_WORDS = frozenset(
    """ceo cto coo cmo product strategist designer strategy design engineering
    operations marketing technical technology ops gtm""".split()
)

PAST_CLAIM = re.compile(
    r"\b(during (?:the|our) deliberations?|in (?:the|our) deliberations?|we agreed|"
    r"as we agreed|i (?:explicitly |initially |aggressively )?"
    r"(?:mandated|insisted|pushed|flagged|proposed|argued|warned|demanded))\b",
    re.I,
)
NAMED_TERM = re.compile(
    r"['\"‘“]([A-Z][\w-]*(?: [\w-]+){0,4})['\"’”]"
    r"|\b([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})\b"
)
HYPHENATED = re.compile(r"\b[a-z]+(?:-[a-z]+)+\b")


def words(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+(?:['’-][a-z0-9]+)*", (text or "").lower().replace("’", "'"))


def ngrams(tokens: Sequence[str], n: int) -> Iterable[Tuple[str, ...]]:
    return (tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1))


def phrases(text: str, n: int = 3) -> set:
    """Word n-grams (runs of n words) with at least two content words, so 'of the
    firm' does not count."""
    return {
        gram
        for gram in ngrams(words(text), n)
        if sum(word not in STOPWORDS for word in gram) >= 2
    }


def sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def normalise(text: str) -> str:
    text = (text or "").lower().replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class Records:
    run_id: str
    deliberation: Dict[str, List[str]] = field(default_factory=lambda: defaultdict(list))
    private: Dict[str, List[str]] = field(default_factory=lambda: defaultdict(list))
    documents: Dict[str, str] = field(default_factory=dict)
    observer: str = ""
    retrieved: List[dict] = field(default_factory=list)
    exchanges: List[dict] = field(default_factory=list)
    citations: List[Tuple[str, str, dict]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    grounded: bool = False


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text()) if path.exists() else None


def load_records(run_dir: Path) -> Records:
    run_dir = Path(run_dir)
    if not (run_dir / "00_meta.json").exists():
        raise FileNotFoundError(f"{run_dir} is not a run folder (no 00_meta.json)")
    meta = _read_json(run_dir / "00_meta.json") or {}
    records = Records(run_id=meta.get("run_id", run_dir.name), errors=meta.get("errors", []) or [])
    log = _read_json(run_dir / "01_deliberation" / "interaction_log.json") or {}
    for event in log.get("events", []) or []:
        role = event.get("role", "?")
        records.deliberation[role].append(event.get("text", "") or "")
        for citation in event.get("citations", []) or []:
            records.citations.append(("deliberation", role, citation))
    for role, state in (_read_json(run_dir / "06_private_channel" / "private_state.json") or {}).items():
        records.private[role].extend(state.get("scratchpad") or [])
        records.private[role].append(state.get("draft") or "")
    for path in sorted((run_dir / "02_strategy_documents").glob("*_strategy.json")):
        document = json.loads(path.read_text())
        role = document.get("role", path.stem.replace("_strategy", ""))
        records.documents[role] = " ".join(
            str(document.get(key, "") or "")
            for key in ("title", "key_challenges", "main_decisions", "key_tensions", "body")
        )
        for citation in document.get("citations", []) or []:
            records.citations.append(("strategy documents", role, citation))
    observer = run_dir / "03_researcher" / "observation_summary.md"
    records.observer = observer.read_text() if observer.exists() else ""
    transcript = _read_json(run_dir / "04_interview" / "transcript.json") or {}
    records.exchanges = transcript.get("exchanges", []) or []
    for exchange in records.exchanges:
        for response in exchange.get("responses", []) or []:
            # Runs saved before answers were parsed keep citations in the text.
            response["text"], embedded = split_panel_reply(response.get("text", ""))
            response["citations"] = (response.get("citations") or []) + embedded
            for citation in response.get("citations", []) or []:
                records.citations.append(("debrief", response.get("role", "?"), citation))
    retrieval = run_dir / "07_rag" / "retrieval_log.jsonl"
    if retrieval.exists():
        records.grounded = True
        records.retrieved = [
            json.loads(line) for line in retrieval.read_text().splitlines() if line.strip()
        ]
    return records


def prompt_text(root: Path) -> str:
    root = Path(root)
    # A saved copy (example_runs/prompts_as_run/) adds .txt to each file name.
    paths = []
    for name in PROMPT_FILES:
        paths.extend(p for p in (root / name, root / f"{name}.txt") if p.exists())
    for pattern in PROMPT_GLOBS:
        paths.extend(sorted(root.glob(pattern)) + sorted(root.glob(f"{pattern}.txt")))
    if not paths:
        raise FileNotFoundError(f"No prompt files found under {root}")
    return "\n".join(path.read_text(errors="ignore") for path in paths)


def _retrieved_text(records: Records) -> str:
    return "\n".join(
        passage.get("text", "")
        for record in records.retrieved
        for passage in record.get("retrieved", []) or []
    )


def trace_answers(records: Records, prompts: str) -> dict:
    """Credit each 3-word phrase in each debrief answer to its earliest source."""
    earlier = {
        "prompts": phrases(prompts),
        "retrieved passages": phrases(_retrieved_text(records)),
        "deliberation": phrases(" ".join(t for ts in records.deliberation.values() for t in ts)),
        "private notes": phrases(" ".join(t for ts in records.private.values() for t in ts)),
        "strategy documents": phrases(" ".join(records.documents.values())),
    }
    questions: set = set()
    answered: Dict[str, set] = defaultdict(set)
    totals: Counter = Counter()
    by_exchange: List[dict] = []
    for number, exchange in enumerate(records.exchanges, 1):
        questions |= phrases(exchange.get("utterance", {}).get("text", ""))
        counts: Counter = Counter()
        this_exchange: Dict[str, set] = {}
        for response in exchange.get("responses", []) or []:
            role = response.get("role", "?")
            mine = phrases(response.get("text", ""))
            this_exchange[role] = mine
            others = set().union(*[seen for other, seen in answered.items() if other != role] or [set()])
            for phrase in mine:
                for origin, source in earlier.items():
                    if phrase in source:
                        counts[origin] += 1
                        break
                else:
                    if phrase in questions:
                        counts["researcher's questions"] += 1
                    elif phrase in others:
                        counts["another role's earlier answer"] += 1
                    elif phrase in answered[role]:
                        counts["own earlier answer"] += 1
                    else:
                        counts["new in this answer"] += 1
        for role, mine in this_exchange.items():
            answered[role] |= mine
        totals.update(counts)
        by_exchange.append({"exchange": number, **counts})
    total = sum(totals.values()) or 1
    return {
        "phrases": sum(totals.values()),
        "share": {origin: round(totals[origin] / total, 3) for origin in ORIGINS},
        "by_exchange": by_exchange,
    }


def _named_terms(text: str) -> Counter:
    found: Counter = Counter()
    for match in NAMED_TERM.finditer(text or ""):
        term = (match.group(1) or match.group(2) or "").strip()
        term = re.sub(r"^(?:the|our|a|an|this|that) ", "", term, flags=re.I)
        if term and not all(word.lower() in STOPWORDS for word in term.split()):
            found[term.lower()] += 1
    for term in HYPHENATED.findall(text or ""):
        found[term] += 1
    return found


def new_in_debrief(records: Records, *, minimum: int = 2) -> List[dict]:
    """Named terms the panel (the six simulated executives when questioned) uses
    repeatedly that no earlier record contains."""
    before = normalise(
        " ".join(t for ts in records.deliberation.values() for t in ts)
        + " " + " ".join(t for ts in records.private.values() for t in ts)
        + " " + " ".join(records.documents.values())
        + " " + records.observer
    )
    uses: Counter = Counter()
    speakers: Dict[str, set] = defaultdict(set)
    first: Dict[str, Tuple[int, str]] = {}
    for number, exchange in enumerate(records.exchanges, 1):
        for response in exchange.get("responses", []) or []:
            for term, count in _named_terms(response.get("text", "")).items():
                uses[term] += count
                speakers[term].add(response.get("role", "?"))
                first.setdefault(term, (number, response.get("role", "?")))
    found = [
        {
            "term": term,
            "uses": count,
            "roles": len(speakers[term]),
            "first_exchange": first[term][0],
            "first_role": first[term][1],
        }
        for term, count in uses.most_common()
        if count >= minimum and term not in before
    ]
    return found


def unsupported_past_claims(records: Records, *, limit: int = 12) -> List[dict]:
    """Sentences claiming a past act, ranked by how little earlier records back them."""
    before = phrases(
        " ".join(t for ts in records.deliberation.values() for t in ts)
        + " " + " ".join(t for ts in records.private.values() for t in ts)
        + " " + " ".join(records.documents.values()),
        n=2,
    )
    claims: List[dict] = []
    for number, exchange in enumerate(records.exchanges, 1):
        for response in exchange.get("responses", []) or []:
            for sentence in sentences(response.get("text", "")):
                if not PAST_CLAIM.search(sentence):
                    continue
                grams = phrases(sentence, n=2)
                if len(grams) < 3:
                    continue
                claims.append({
                    "exchange": number,
                    "role": response.get("role", "?"),
                    "sentence": sentence,
                    "backed_by_earlier_records": round(len(grams & before) / len(grams), 2),
                })
    claims.sort(key=lambda claim: claim["backed_by_earlier_records"])
    return claims[:limit]


def question_echoes(records: Records, prompts: str, *, minimum: int = 5) -> List[dict]:
    """Researcher questions sharing a run of words with a protocol stem or prompt line."""
    prompt_runs = set()
    for n in range(minimum, minimum + 4):
        prompt_runs |= {gram for line in prompts.splitlines() for gram in ngrams(words(line), n)}
    echoes = []
    for number, exchange in enumerate(records.exchanges, 1):
        text = exchange.get("utterance", {}).get("text", "")
        tokens = words(text)
        best: Tuple[str, ...] = ()
        for n in range(minimum + 3, minimum - 1, -1):
            match = next((gram for gram in ngrams(tokens, n) if gram in prompt_runs), None)
            if match:
                best = match
                break
        if best:
            echoes.append({"exchange": number, "question": text, "shared_words": " ".join(best)})
    return echoes


def shared_phrases(records: Records, *, minimum_roles: int = 4, limit: int = 15) -> List[dict]:
    """Content phrases several roles use in the debrief, with how often the deliberation
    (the team's discussion) did."""
    by_role: Dict[str, set] = defaultdict(set)
    uses: Counter = Counter()
    for exchange in records.exchanges:
        for response in exchange.get("responses", []) or []:
            tokens = words(response.get("text", ""))
            for n in (2, 3):
                for gram in ngrams(tokens, n):
                    if all(word not in STOPWORDS for word in gram):
                        phrase = " ".join(gram)
                        by_role[phrase].add(response.get("role", "?"))
                        uses[phrase] += 1
    deliberation = normalise(" ".join(t for ts in records.deliberation.values() for t in ts))
    question_text = normalise(
        " ".join(e.get("utterance", {}).get("text", "") for e in records.exchanges)
    )
    found = [
        {
            "phrase": phrase,
            "roles": len(by_role[phrase]),
            "uses": uses[phrase],
            "in_deliberation": deliberation.count(phrase),
            "in_questions": question_text.count(phrase),
        }
        for phrase in uses
        if len(by_role[phrase]) >= minimum_roles
    ]
    found.sort(key=lambda item: (-item["roles"], -item["uses"]))
    return found[:limit]


def _vectors(texts: Sequence[str], *, mask: frozenset = frozenset()) -> List[Dict[str, float]]:
    bags = [
        Counter(w for w in words(text) if w not in STOPWORDS and w not in mask) for text in texts
    ]
    document_frequency: Counter = Counter()
    for bag in bags:
        document_frequency.update(bag.keys())
    count = len(bags) or 1
    vectors = []
    for bag in bags:
        vector = {w: n * math.log((1 + count) / (1 + document_frequency[w])) for w, n in bag.items()}
        norm = math.sqrt(sum(v * v for v in vector.values())) or 1.0
        vectors.append({w: v / norm for w, v in vector.items()})
    return vectors


def cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(value * b.get(word, 0.0) for word, value in a.items())


def _mean(values: Sequence[float]) -> Optional[float]:
    return round(sum(values) / len(values), 3) if values else None


def role_similarity(answers: Sequence[Tuple[int, str, str]]) -> dict:
    """How alike answers are, and whether a reader could tell the roles apart.

    `answers` holds (question number, role, text). Attribution (guessing which
    role wrote an answer) masks (hides) role
    words and picks the nearest other answers by role, leaving each out.
    """
    if not answers:
        return {}
    vectors = _vectors([text for _, _, text in answers], mask=ROLE_WORDS)
    same_question: List[float] = []
    same_role: List[float] = []
    for i, j in combinations(range(len(answers)), 2):
        question_i, role_i, _ = answers[i]
        question_j, role_j, _ = answers[j]
        if question_i == question_j and role_i != role_j:
            same_question.append(cosine(vectors[i], vectors[j]))
        elif role_i == role_j and question_i != question_j:
            same_role.append(cosine(vectors[i], vectors[j]))
    roles = sorted({role for _, role, _ in answers})
    correct = 0
    tested = 0
    for i, (_, role, _) in enumerate(answers):
        scores: Dict[str, List[float]] = defaultdict(list)
        for j, (_, other, _) in enumerate(answers):
            if i != j:
                scores[other].append(cosine(vectors[i], vectors[j]))
        if len(scores) < 2 or not scores.get(role):
            continue
        guess = max(scores, key=lambda name: sum(scores[name]) / len(scores[name]))
        correct += guess == role
        tested += 1
    return {
        "answers": len(answers),
        "roles": len(roles),
        "different_roles_same_question": _mean(same_question),
        "same_role_different_questions": _mean(same_role),
        "role_attribution_accuracy": round(correct / tested, 3) if tested else None,
        "chance": round(1 / len(roles), 3) if roles else None,
    }


def check_citations(records: Records) -> dict:
    """Do cited quotes appear in what the same role was shown from that document?"""
    if not records.grounded:
        return {"grounded": False}
    shown: Dict[Tuple[str, str], str] = defaultdict(str)
    shown_docs: Dict[str, set] = defaultdict(set)
    corpus_docs: set = set()
    for record in records.retrieved:
        role = record.get("role", "?")
        for passage in record.get("retrieved", []) or []:
            # Agents get only the start of each passage; older logs don't say how much.
            text = passage.get("text", "")[: passage.get("shown_chars", SHOWN_CHARS)]
            shown[(role, passage.get("doc_id", ""))] += " " + normalise(text)
            shown_docs[role].add(passage.get("doc_id", ""))
            corpus_docs.add(passage.get("doc_id", ""))
    per_phase: Dict[str, Counter] = defaultdict(Counter)
    problems: List[dict] = []
    cited_docs: Counter = Counter()
    for phase, role, citation in records.citations:
        quote = normalise(citation.get("quote", ""))
        doc_id = citation.get("doc_id", "")
        cited_docs[doc_id] += 1
        counts = per_phase[phase]
        counts["citations"] += 1
        verbatim = bool(quote) and quote in shown[(role, doc_id)]
        doc_shown = doc_id in shown_docs[role]
        counts["quote_verbatim"] += verbatim
        counts["document_was_shown"] += doc_shown
        if not (verbatim and doc_shown):
            problems.append({
                "phase": phase, "role": role, "doc_id": doc_id,
                "quote": citation.get("quote", "")[:160],
                "quote_verbatim": verbatim, "document_was_shown": doc_shown,
            })
    answers = [r for e in records.exchanges for r in e.get("responses", []) or []]
    errors = sum(1 for record in records.retrieved if record.get("error"))
    return {
        "grounded": True,
        "retrievals": len(records.retrieved),
        "retrieval_errors": errors,
        "documents_retrieved": len(corpus_docs),
        "per_phase": {phase: dict(counts) for phase, counts in per_phase.items()},
        "debrief_answers": len(answers),
        "debrief_answers_citing": sum(bool(r.get("citations")) for r in answers),
        "most_cited": cited_docs.most_common(5),
        "problems": problems[:15],
        "problem_count": len(problems),
    }


def build_report(run_dir: Path, *, prompts_root: Path = REPO_ROOT) -> dict:
    records = load_records(run_dir)
    prompts = prompt_text(prompts_root)
    answers = [
        (number, response.get("role", "?"), response.get("text", ""))
        for number, exchange in enumerate(records.exchanges, 1)
        for response in exchange.get("responses", []) or []
    ]
    return {
        "run_id": records.run_id,
        "exchanges": len(records.exchanges),
        "answers": len(answers),
        "lost_answers": sum(len(e.get("lost_roles", []) or []) for e in records.exchanges),
        "origins": trace_answers(records, prompts),
        "new_in_debrief": new_in_debrief(records),
        "unsupported_past_claims": unsupported_past_claims(records),
        "question_echoes": question_echoes(records, prompts),
        "shared_phrases": shared_phrases(records),
        "role_similarity": role_similarity(answers),
        "citations": check_citations(records),
    }


def render_report(report: dict) -> str:
    lines = [
        f"# Provenance report: {report['run_id']}",
        "",
        "_Text matches that flag passages to read. They do not establish what caused a passage._",
        "",
        f"{report['exchanges']} exchanges, {report['answers']} answers, "
        f"{report['lost_answers']} lost answers.",
        "",
        "## Where debrief phrases first appeared",
        "",
        "| Source | Share of 3-word phrases |",
        "|---|---|",
    ]
    for origin in ORIGINS:
        lines.append(f"| {origin} | {report['origins']['share'][origin]:.1%} |")
    lines += ["", "## Named terms that first appear in the debrief", ""]
    lines += [
        f"- **{t['term']}**: {t['uses']} uses by {t['roles']} roles, "
        f"first by {t['first_role']} at exchange {t['first_exchange']}"
        for t in report["new_in_debrief"][:25]
    ] or ["None."]
    lines += ["", "## Claims about the past, least supported first", ""]
    lines += [
        f"- {c['backed_by_earlier_records']:.0%} backed. {c['role']}, exchange {c['exchange']}: {c['sentence']}"
        for c in report["unsupported_past_claims"]
    ] or ["None."]
    lines += ["", "## Researcher questions sharing words with a prompt", ""]
    lines += [
        f"- Exchange {e['exchange']}: \"{e['shared_words']}\""
        for e in report["question_echoes"]
    ] or ["None."]
    lines += ["", "## Phrases shared across roles in the debrief", "",
              "| Phrase | Roles | Uses | In deliberation | In questions |", "|---|---|---|---|---|"]
    lines += [
        f"| {p['phrase']} | {p['roles']} | {p['uses']} | {p['in_deliberation']} | {p['in_questions']} |"
        for p in report["shared_phrases"]
    ]
    similarity = report["role_similarity"]
    lines += ["", "## How alike the roles are", ""]
    lines += [f"- {key.replace('_', ' ')}: {value}" for key, value in similarity.items()]
    citations = report["citations"]
    lines += ["", "## Citations", ""]
    if not citations.get("grounded"):
        lines.append("Ungrounded run.")
    else:
        lines += [
            f"- Retrievals: {citations['retrievals']} ({citations['retrieval_errors']} errors), "
            f"from {citations['documents_retrieved']} documents.",
            f"- Debrief answers citing a source: {citations['debrief_answers_citing']} "
            f"of {citations['debrief_answers']}.",
            f"- Citations with a problem: {citations['problem_count']}.",
        ]
        for phase, counts in citations["per_phase"].items():
            lines.append(
                f"- {phase}: {counts.get('citations', 0)} citations, "
                f"{counts.get('quote_verbatim', 0)} quotes verbatim, "
                f"{counts.get('document_was_shown', 0)} from a document that role was shown."
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--prompts-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()
    report = build_report(args.run_dir, prompts_root=args.prompts_root)
    out_dir = args.out_dir or REPO_ROOT / "results" / "provenance" / args.run_dir.name
    if out_dir.resolve().is_relative_to(args.run_dir.resolve()):
        raise SystemExit("Output must not go inside the source run.")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2))
    (out_dir / "report.md").write_text(render_report(report))
    print(f"Wrote {out_dir / 'report.md'}")


if __name__ == "__main__":
    main()
