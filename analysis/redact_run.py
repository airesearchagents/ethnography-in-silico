"""Copy a grounded run with copyrighted source text removed, so it can be published.

Source documents may be under copyright, so the records of a grounded run (a run is
one complete simulated meeting and debrief; a grounded one gives roles a firm's
documents to cite) cannot be released as they stand. This writes a copy in which:

  * each retrieved passage keeps its document, chunk (the piece cut from it for
    searching), score and word count, plus a SHA-256 hash (a short fingerprint
    computed from the contents), but not its text;
  * each citation's quote is replaced by a hash and word count;
  * any run of at least `MIN_WORDS` words anywhere in the records that matches a
    retrieved passage or a supplied source document is replaced by a marker.

Quotes shorter than `MIN_WORDS` inside an agent's (a language
model given a role and instructions) own sentences can remain. Optional
scoring output is left out, and the cloud project ID is removed. The source run is
never changed.

Usage
-----
    python -m analysis.redact_run --run-dir <run> --out-dir <dir> --documents <folder>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Set, Tuple

try:
    from ..roles.researcher_schemas import split_panel_reply
    from .persist_artefacts import (
        _render_artefact_md,
        _render_debriefing_md,
        _render_deliberation_md,
    )
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from roles.researcher_schemas import split_panel_reply  # type: ignore[no-redef]
    from analysis.persist_artefacts import (  # type: ignore[no-redef]
        _render_artefact_md,
        _render_debriefing_md,
        _render_deliberation_md,
    )

MIN_WORDS = 6
MARKER = "[source text removed]"
WORD = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*")
PROJECT = re.compile(r"projects/[^/\s`\"']+")


def _tokens(text: str) -> list:
    return list(WORD.finditer(text.lower().replace("’", "'")))


def source_grams(texts: Iterable[str], size: int = MIN_WORDS) -> Set[Tuple[str, ...]]:
    grams: Set[Tuple[str, ...]] = set()
    for text in texts:
        words = [m.group(0) for m in _tokens(text)]
        grams.update(tuple(words[i : i + size]) for i in range(len(words) - size + 1))
    return grams


def scrub(text: str, grams: Set[Tuple[str, ...]], size: int = MIN_WORDS) -> str:
    """Replace every run of words that matches a source with one marker."""
    tokens = _tokens(text)
    words = [m.group(0) for m in tokens]
    covered = [False] * len(words)
    for i in range(len(words) - size + 1):
        if tuple(words[i : i + size]) in grams:
            for j in range(i, i + size):
                covered[j] = True
    out, last, i = [], 0, 0
    while i < len(words):
        if covered[i]:
            j = i
            while j + 1 < len(words) and covered[j + 1]:
                j += 1
            out.append(text[last : tokens[i].start()])
            out.append(MARKER)
            last = tokens[j].end()
            i = j + 1
        else:
            i += 1
    out.append(text[last:])
    return PROJECT.sub("projects/<project>", "".join(out))


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def clean_value(value: Any, grams: Set[Tuple[str, ...]]) -> Any:
    """Scrub strings throughout a JSON (structured data) value, replacing quotes by their hash."""
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if key == "quote" and isinstance(item, str):
                cleaned[key] = f"[quote removed: {len(item.split())} words, sha256 {_hash(item)[:16]}]"
            elif key in ("doc_id", "chunk_id", "display_name"):
                # Identifiers, often a document's title, and needed to check citations.
                cleaned[key] = item
            else:
                cleaned[key] = clean_value(item, grams)
        return cleaned
    if isinstance(value, list):
        return [clean_value(item, grams) for item in value]
    if isinstance(value, str):
        return scrub(value, grams)
    return value


def clean_retrieval(record: dict, grams: Set[Tuple[str, ...]]) -> dict:
    passages = []
    for passage in record.get("retrieved", []) or []:
        text = passage.get("text", "") or ""
        passages.append({
            "doc_id": passage.get("doc_id", ""),
            "chunk_id": passage.get("chunk_id", ""),
            "score": passage.get("score"),
            "words": len(text.split()),
            "text_sha256": _hash(text),
        })
    rest = {k: v for k, v in record.items() if k != "retrieved"}
    return {**clean_value(rest, grams), "retrieved": passages}


def _unwrap_answers(transcript: dict) -> None:
    """Move citations wrapped around saved answers into the citation field."""
    for exchange in transcript.get("exchanges", []) or []:
        for response in exchange.get("responses", []) or []:
            text, citations = split_panel_reply(response.get("text", ""))
            response["text"] = text
            response["citations"] = (response.get("citations") or []) + citations


def _hide_project(text: str) -> str:
    """Cloud resource names carry the project's name, which identifies its owner."""
    return re.sub(r"projects/[^/\s\"]+/", "projects/<project>/", text)


def redact_run(
    run_dir: Path, out_dir: Path, documents: Optional[Path] = None,
    extra_sources: Iterable[str] = (),
) -> Set[Tuple[str, ...]]:
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    if out_dir.resolve().is_relative_to(run_dir.resolve()):
        raise ValueError("Output must not go inside the source run.")
    if out_dir.exists():
        raise ValueError(f"{out_dir} already exists. Choose a new folder; nothing was changed.")
    log_path = run_dir / "07_rag" / "retrieval_log.jsonl"
    records = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()] if log_path.exists() else []
    sources = [p.get("text", "") for r in records for p in r.get("retrieved", []) or []]
    sources.extend(extra_sources)
    if documents:
        sources.extend(
            path.read_text(errors="ignore") for path in sorted(Path(documents).glob("*.txt"))
        )
    grams = source_grams(sources)

    shutil.copytree(
        run_dir, out_dir,
        ignore=shutil.ignore_patterns("05_judging", ".DS_Store", "retrieval_log.jsonl"),
    )
    transcript_path = out_dir / "04_interview" / "transcript.json"
    if transcript_path.exists():
        transcript = json.loads(transcript_path.read_text())
        _unwrap_answers(transcript)
        transcript_path.write_text(json.dumps(transcript, indent=2))
    for path in sorted(out_dir.rglob("*.json")):
        path.write_text(_hide_project(
            json.dumps(clean_value(json.loads(path.read_text()), grams), indent=2)
        ))
    for path in sorted(out_dir.rglob("*.md")):
        path.write_text(_hide_project(scrub(path.read_text(), grams)))

    # Rendered files print citations, so rebuild them from the cleaned records.
    if transcript_path.exists():
        (out_dir / "04_interview" / "transcript.md").write_text(
            _render_debriefing_md(json.loads(transcript_path.read_text()))
        )
    log_json = out_dir / "01_deliberation" / "interaction_log.json"
    if log_json.exists():
        (out_dir / "01_deliberation" / "interaction_log.md").write_text(
            _render_deliberation_md(json.loads(log_json.read_text()))
        )
    for path in sorted((out_dir / "02_strategy_documents").glob("*_strategy.json")):
        path.with_suffix(".md").write_text(_render_artefact_md(json.loads(path.read_text())))
    if records:
        (out_dir / "07_rag" / "retrieval_log.jsonl").write_text(
            "".join(json.dumps(clean_retrieval(r, grams)) + "\n" for r in records)
        )
    return grams


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--documents", type=Path, default=None)
    args = parser.parse_args()
    redact_run(args.run_dir, args.out_dir, args.documents)
    print(f"Wrote {args.out_dir}")


if __name__ == "__main__":
    main()
