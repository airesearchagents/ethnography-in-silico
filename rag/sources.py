"""Check local grounding documents against the source list.

Grounding documents are the real firm documents given to agents so their text
can be traced to sources. This command confirms that your local copies are the
same files the project used.

Usage
-----
    python -m rag.sources --root rag_corpora

    python -m rag.sources --root <pilot>/data --column pilot_path

`<pilot>` is your copy of the pilot study's repository (its project folder).

What it does
------------
Source documents may be under publisher copyright, so they stay out of git
(the tool that keeps the repository's shared history).
Instead, `rag_corpora/SOURCES.csv` lists every document with its path and
SHA-256 hash (a short fingerprint computed from a file's contents). This
command looks up each listed file under `--root`, using
the path in `--column` (default `path`, laid out as `<Firm>/<file>`), and
reports files that are missing or whose content differs from the list.

Exit code (the number a program reports when it ends) 0 means every listed
document is present and matches; 1 means at
least one problem was found.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path
from typing import Iterable, List, Optional

DEFAULT_SOURCES = Path(__file__).resolve().parent.parent / "rag_corpora" / "SOURCES.csv"


def sha256_file(path: Path) -> str:
    """SHA-256 of a file's bytes, read in chunks."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_sources(csv_path: Path) -> List[dict]:
    """Rows of the source list as dicts keyed by column name."""
    with csv_path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def check_sources(rows: Iterable[dict], root: Path, column: str = "path") -> List[str]:
    """Return one message per missing or mismatched document; empty means all match."""
    problems: List[str] = []
    for row in rows:
        rel = row.get(column, "")
        if not rel:
            problems.append(f"{row.get('doc_id', '?')}: no value in column '{column}'")
            continue
        path = root / rel
        if not path.is_file():
            problems.append(f"{row.get('doc_id', '?')}: missing {rel}")
        elif sha256_file(path) != row.get("sha256", ""):
            problems.append(f"{row.get('doc_id', '?')}: content differs from the list for {rel}")
    return problems


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", required=True, type=Path,
                        help="Folder the listed paths are relative to.")
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES,
                        help="Source list CSV (default: rag_corpora/SOURCES.csv).")
    parser.add_argument("--column", default="path",
                        help="Column holding each document's path (default: path).")
    args = parser.parse_args(argv)

    rows = load_sources(args.sources)
    problems = check_sources(rows, args.root, args.column)
    for p in problems:
        print(p)
    print(f"{len(rows) - len(problems)} of {len(rows)} documents present and matching.")
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
