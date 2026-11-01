"""Build or update a per-firm Vertex AI RAG corpus from local source files.

Vertex AI is Google's paid cloud service. RAG (retrieval-augmented generation)
means searching a document collection, the corpus, and adding the passages
found to an agent's prompt (the text sent to it). This command loads one firm's
documents into Google's service, ready for `--rag` runs (runs that use
documents). It costs money while the corpus exists (see Cost below).

Usage
-----
    python -m rag.corpus_build --company OpenAI

    python -m rag.corpus_build --company OpenAI --docs-dir custom/path/

    python -m rag.corpus_build --all-firms                       # iterate rag_corpora/*/

    python -m rag.corpus_build --company OpenAI --dry-run        # show plan, don't upload

    python -m rag.corpus_build --company OpenAI --list           # list current corpus files

    python -m rag.corpus_build --company OpenAI --delete-corpus  # tear down (with --yes)

What it does
------------
For each source file under `rag_corpora/<Company>/` (or `--docs-dir`):

1. Computes the SHA256, a short fingerprint of the file's contents, locally
   (so the run manifest, the file listing what produced a run, can pin which
   content went in — Vertex doesn't return a content hash).
2. Calls `vertex_corpus.build_or_get_corpus(display_name='<study_slug>__<Company>')`
   to ensure the corpus exists (a slug is a short name with no spaces).
   Idempotent (safe to repeat): re-running with the same
   docs-dir doesn't recreate it.
3. Calls `vertex_corpus.upload_documents(corpus_name, paths)`. Idempotent
   by display-name match: a file already in the corpus (same filename)
   is skipped. To force a re-upload (e.g. content changed) the operator
   manually `rag.delete_file(...)`s it first via the Vertex console (Google's
   web page for the service) or a follow-up SDK (Google's software kit) call.
4. Prints a per-file report: what was uploaded, what was skipped, the
   SHA256 each got.

The script DOES NOT delete files from the corpus that aren't in the local
docs-dir — that would silently lose content if the operator runs the
script with a different folder. Use `--delete-corpus` for explicit
teardown.

Supported file types
--------------------
Vertex AI RAG Engine (the part of Vertex that stores and searches a corpus)
extracts text from `.md`, `.txt`, `.pdf`, `.docx`,
`.html`, and a few others at upload time. This CLI (command-line tool) walks
the docs-dir
and passes through any file with a supported extension; the SHA256 is
computed on the raw bytes regardless of type.

Auth
----
Auth means proving who you are to Google. It requires the standard Vertex env
vars, or environment variables, named settings held outside the code (same as
the `--vertex` Gemini routing in the framework, the shared software; Gemini is
Google's language model):

    export GOOGLE_GENAI_USE_VERTEXAI=true
    export GOOGLE_CLOUD_PROJECT=<your-project>
    export GOOGLE_CLOUD_LOCATION=global        # for Gemini 3.x model calls
    export RAG_LOCATION=us-west1               # a region whose RAG tier you checked
    gcloud auth application-default login

The wrapper's (`rag/vertex_corpus.py`) lazy import, which loads Google's software
only when needed, surfaces a friendly error if either is missing.

Cost
----
Embedding (turning text into numbers that stand for its meaning) and retrieval
(the searches) cost little. The bill to watch is the RAG Engine database, which
runs while any corpus exists in the region (the location of the rented
computers), whatever its size: about $3 a day on the Basic tier (price level)
and about $30 a day on Scaled, at list prices (published rates) for Spanner,
the Google database behind it. This CLI prints the tier and refuses Scaled
unless you
pass --allow-scaled. When you finish, delete the corpus and set the tier
to Unprovisioned; docs/REPRODUCE.md has the steps.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional, Sequence

try:
    from . import vertex_corpus
except ImportError:  # pragma: no cover  (script-style execution)
    import rag.vertex_corpus as vertex_corpus  # type: ignore[no-redef]


# Default study slug used to derive the corpus display name. The
# openness study is the framework's default; a different study would
# pass `--study <slug>` to override.
DEFAULT_STUDY_SLUG = "openness_maneuvering"

# Default parent directory for per-firm source-document folders.
# Relative to the repository root (i.e. the working copy the script runs from).
DEFAULT_CORPORA_ROOT = Path("rag_corpora")

# File extensions Vertex AI RAG Engine extracts text from natively at
# upload time. The CLI walks the docs-dir and passes through any file
# matching one of these — Vertex handles the parsing server-side.
SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf", ".docx", ".html", ".rtf"}


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_source_files(docs_dir: Path) -> List[Path]:
    """Return all source files under `docs_dir` with supported extensions.

    Recursive — subdirectories are walked so an operator can organise
    docs by source-type (e.g. `OpenAI/letters/`, `OpenAI/blogs/`,
    `OpenAI/transcripts/`) without flattening. Hidden files (those
    starting with `.`) are skipped to dodge editor swap files +
    `.DS_Store` noise on macOS.

    Returns the list sorted by path so reproductions of the build are
    deterministic (upload order matters when display-names collide
    — they shouldn't, but if a folder has `foo.md` in two
    subdirectories the order of which one wins is now predictable).
    """
    if not docs_dir.is_dir():
        return []
    out: List[Path] = []
    for p in sorted(docs_dir.rglob("*")):
        if p.is_dir():
            continue
        if p.name.startswith("."):
            continue
        if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        out.append(p)
    return out


def corpus_display_name(*, study_slug: str, company: str) -> str:
    """Convention: `<study_slug>__<company>`.

    Mirrors `studies/openness_maneuvering/rag_loader.CORPUS_DISPLAY_NAME_PATTERN`.
    Picking the same string here means a fresh build + a fresh
    `--rag` run resolve to the same corpus without manual wiring.
    """
    return f"{study_slug}__{company}"


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def run_build(
    *,
    company: str,
    study_slug: str,
    docs_dir: Path,
    dry_run: bool = False,
    allow_scaled: bool = False,
) -> int:
    """Build/refresh one firm's corpus from local files. Returns exit code."""
    display_name = corpus_display_name(study_slug=study_slug, company=company)
    paths = discover_source_files(docs_dir)

    print(f"company:       {company}")
    print(f"docs-dir:      {docs_dir}")
    print(f"display name:  {display_name}")
    print(f"files found:   {len(paths)}")
    for p in paths:
        print(f"  - {p.relative_to(docs_dir) if docs_dir in p.parents else p}")

    if not paths:
        print("\nno source files found — nothing to upload")
        if dry_run:
            return 0
        print("(create files under the docs-dir and re-run)")
        return 1

    if dry_run:
        print("\n[dry run] would build/get corpus then upload the files listed above")
        return 0

    try:
        tier = vertex_corpus.rag_engine_tier()
    except Exception as exc:  # noqa: BLE001
        tier = "unknown"
        print(f"\nWARNING: could not read the RAG Engine tier ({exc}). Check it before relying on this.")
    print(f"\nRAG tier:      {tier} (the database bills while a corpus exists)")
    if tier == "scaled" and not allow_scaled:
        print(
            "ERROR: this region is on the Scaled tier, about ten times the cost of Basic. "
            "Set RAG_LOCATION to a Basic region, or pass --allow-scaled."
        )
        return 2

    print(f"\nresolving corpus '{display_name}'...")
    try:
        corpus_name = vertex_corpus.build_or_get_corpus(display_name)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not build/get corpus: {exc}")
        return 2
    print(f"corpus resource: {corpus_name}")

    print("\nuploading...")
    try:
        records = vertex_corpus.upload_documents(corpus_name, paths)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: upload failed: {exc}")
        return 3

    uploaded = sum(1 for r in records if r["uploaded"])
    skipped = sum(1 for r in records if not r["uploaded"])

    print()
    print(f"summary: {uploaded} uploaded, {skipped} skipped (already in corpus)")
    print()
    for r in records:
        flag = "+" if r["uploaded"] else "·"
        # SHA prefix only — the full 64 chars is noise in CLI output.
        sha_short = (r.get("sha256") or "")[:12]
        print(f"  {flag} {r['display_name']:50s} sha256={sha_short}")
    print()
    print(f"corpus '{display_name}' is ready. Run --rag against company={company} to use it.")
    return 0


def run_list(*, company: str, study_slug: str) -> int:
    """List files currently in the firm's corpus."""
    display_name = corpus_display_name(study_slug=study_slug, company=company)
    try:
        corpus_name = vertex_corpus.find_corpus(display_name)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not look up corpus: {exc}")
        return 2
    if not corpus_name:
        print(f"no corpus found with display_name='{display_name}'")
        return 0
    print(f"corpus: {corpus_name}")
    try:
        records = vertex_corpus.list_files_in_corpus(corpus_name)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not list files: {exc}")
        return 3
    print(f"files: {len(records)}")
    for r in records:
        # Description carries `sha256=<hex>` for files uploaded via
        # this CLI; show that so the operator can spot drift (a changed file).
        desc = r.get("description", "")
        print(f"  - {r.get('display_name', '?'):50s} {desc}")
    return 0


def run_delete(
    *,
    company: str,
    study_slug: str,
    yes: bool,
) -> int:
    """Delete the firm's corpus. Requires --yes to confirm."""
    display_name = corpus_display_name(study_slug=study_slug, company=company)
    try:
        corpus_name = vertex_corpus.find_corpus(display_name)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not look up corpus: {exc}")
        return 2
    if not corpus_name:
        print(f"no corpus found with display_name='{display_name}' (nothing to delete)")
        return 0
    if not yes:
        print(f"would delete corpus: {corpus_name}")
        print("re-run with --yes to confirm")
        return 0
    try:
        vertex_corpus.delete_corpus(corpus_name)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: delete failed: {exc}")
        return 3
    print(f"deleted corpus: {corpus_name}")
    return 0


def run_all_firms(
    *,
    study_slug: str,
    corpora_root: Path,
    dry_run: bool = False,
) -> int:
    """Iterate every subdirectory of `corpora_root` as a firm name."""
    if not corpora_root.is_dir():
        print(f"ERROR: corpora root does not exist: {corpora_root}")
        return 1
    firms = sorted(
        p.name for p in corpora_root.iterdir()
        if p.is_dir() and not p.name.startswith(".") and not p.name.startswith("_")
    )
    if not firms:
        print(f"no firm subdirectories found under {corpora_root}")
        return 1
    print(f"found {len(firms)} firm folder(s) under {corpora_root}: {firms}")
    print()
    overall = 0
    for firm in firms:
        rc = run_build(
            company=firm,
            study_slug=study_slug,
            docs_dir=corpora_root / firm,
            dry_run=dry_run,
        )
        if rc != 0:
            overall = rc
        print()  # blank line between firms
    return overall


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rag.corpus_build",
        description=(
            "Build or update a per-firm Vertex AI RAG corpus from local "
            "source files. Idempotent: re-running with the same docs-dir "
            "uploads only new files."
        ),
    )
    p.add_argument(
        "--company",
        help=(
            "Firm name. Becomes part of the corpus display name as "
            "`<study_slug>__<Company>`. Required unless --all-firms is set."
        ),
    )
    p.add_argument(
        "--all-firms",
        action="store_true",
        help=(
            "Iterate every subdirectory of --corpora-root as a firm "
            "name and build each. Useful for the 5-firm openness sweep."
        ),
    )
    p.add_argument(
        "--study",
        default=DEFAULT_STUDY_SLUG,
        help=(
            "Study slug. Becomes the first half of the corpus display "
            "name. Defaults to '%(default)s'."
        ),
    )
    p.add_argument(
        "--docs-dir",
        default=None,
        help=(
            "Override the docs-dir for --company mode. Defaults to "
            "`<corpora-root>/<company>/`."
        ),
    )
    p.add_argument(
        "--corpora-root",
        default=str(DEFAULT_CORPORA_ROOT),
        help=(
            "Parent directory for per-firm doc folders. Defaults to "
            "'%(default)s'."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be uploaded; don't actually call Vertex.",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List files currently in the firm's corpus (read-only).",
    )
    p.add_argument(
        "--delete-corpus",
        action="store_true",
        help="Delete the firm's corpus. Requires --yes to actually do it.",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Confirm a destructive operation (currently only --delete-corpus).",
    )
    p.add_argument(
        "--allow-scaled",
        action="store_true",
        help="Build even if the region's RAG Engine tier is Scaled (about ten times Basic).",
    )
    p.add_argument(
        "--log-level",
        default="WARNING",
        help="Logger level for the underlying Vertex wrapper (default WARNING).",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Returns the exit code instead of calling sys.exit
    so the same function is testable.
    """
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.WARNING))

    corpora_root = Path(args.corpora_root)

    if args.all_firms:
        if args.list or args.delete_corpus:
            print("ERROR: --all-firms is incompatible with --list / --delete-corpus")
            return 1
        return run_all_firms(
            study_slug=args.study,
            corpora_root=corpora_root,
            dry_run=args.dry_run,
        )

    if not args.company:
        print("ERROR: --company is required (or use --all-firms)")
        return 1

    if args.list:
        return run_list(company=args.company, study_slug=args.study)

    if args.delete_corpus:
        return run_delete(
            company=args.company, study_slug=args.study, yes=args.yes,
        )

    docs_dir = Path(args.docs_dir) if args.docs_dir else corpora_root / args.company
    return run_build(
        company=args.company,
        study_slug=args.study,
        docs_dir=docs_dir,
        dry_run=args.dry_run,
        allow_scaled=args.allow_scaled,
    )


if __name__ == "__main__":  # pragma: no cover  (exercised via tests calling main())
    sys.exit(main())
