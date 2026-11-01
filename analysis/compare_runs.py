"""Side-by-side comparison of two (or more) replication packages.

Compares the per-run folders (a run is one complete simulated meeting and debrief)
produced by `analysis.persist_artefacts` plus the `manifest.json` (a file listing
what produced the run) written by `analysis.replication_package`.
Designed for the multi-LLM (LLM: large language model) robustness story — once
you've run the same scenario (the run's setting) on Gemini + Claude + GPT (language
models from Google, Anthropic and OpenAI), this tool surfaces the
deltas (differences).

What it compares
----------------

  * Manifest fields (which models were used? same prompts, the text sent to them?
    same git SHA, the fingerprint that git (the tool keeping the code's history) gives
    an exact code version? same env config,
    the settings held outside the code?).
  * Strategy-document summaries (key challenges / decisions / tensions
    per role).
  * Debriefing (the researcher agent's interview of the team) transcript shape
    (number of exchanges, each one question and its replies; areas covered, the
    debrief's topics; forbidden-vocab violations, uses of words the researcher
    agent must avoid in its own writing).
  * Observation summary (the researcher agent's single account of the team's
    discussion) deltas (decisions, components, disagreements).

Output
------
A markdown (plain text with simple marks for headings) report on stdout (printed
to the screen; or to `--out report.md`). Designed to be
copy-pasted into a PR (pull request: a proposed set of code changes) description,
methods section, or kept alongside
the run folders.

Usage
-----
    python -m analysis.compare_runs results/runs/OpenAI_gemini results/runs/OpenAI_claude
    python -m analysis.compare_runs run_a run_b run_c   # three-way
    python -m analysis.compare_runs --out report.md a b
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _safe_load(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def load_run(run_dir: Path) -> Dict[str, Any]:
    """Load every JSON (plain-text structured data) file we know about from one per-run folder."""
    return {
        "run_dir": str(run_dir),
        "manifest": _safe_load(run_dir / "manifest.json"),
        "meta": _safe_load(run_dir / "00_meta.json"),
        "deliberation_log": _safe_load(
            run_dir / "01_deliberation" / "interaction_log.json"
        ),
        "artefacts": _load_artefacts(run_dir / "02_strategy_documents"),
        "observation_summary": _safe_load(
            run_dir / "03_researcher" / "observation_summary.json"
        ),
        "debriefing_transcript": _safe_load(
            run_dir / "04_interview" / "transcript.json"
        ),
    }


def _load_artefacts(docs_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Load each `<role>_strategy.json` keyed by role."""
    if not docs_dir.is_dir():
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for json_path in sorted(docs_dir.glob("*_strategy.json")):
        role = json_path.stem.replace("_strategy", "")
        doc = _safe_load(json_path)
        if doc is not None:
            out[role] = doc
    return out


# ---------------------------------------------------------------------------
# Comparators (each returns markdown)
# ---------------------------------------------------------------------------

def compare_manifests(runs: List[Dict[str, Any]]) -> str:
    headers = [Path(r["run_dir"]).name for r in runs]
    manifests = [r.get("manifest") or {} for r in runs]
    if not any(manifests):
        return "## Manifests\n\n_No `manifest.json` found in any run._\n"

    lines = ["## Manifests", ""]

    # Top-level scalar fields.
    scalar_fields = [
        "company", "industry_context", "product_type", "launch_year",
        "started_at", "finished_at",
    ]
    lines.append("| Field | " + " | ".join(headers) + " |")
    lines.append("|---|" + "---|" * len(headers))
    for f in scalar_fields:
        row = [f] + [str((m or {}).get(f, "—")) for m in manifests]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # Models per role.
    lines.append("### Models per role")
    all_roles = sorted({
        role
        for m in manifests
        for role in (m.get("models_used", {}) or {})
    })
    lines.append("| Role | " + " | ".join(headers) + " |")
    lines.append("|---|" + "---|" * len(headers))
    for role in all_roles:
        row = [role]
        for m in manifests:
            mid = (m.get("models_used") or {}).get(role, "—")
            prov = (m.get("providers_used") or {}).get(role, "")
            row.append(f"{mid}{' (' + prov + ')' if prov else ''}")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # Git provenance.
    lines.append("### Git provenance")
    lines.append("| Field | " + " | ".join(headers) + " |")
    lines.append("|---|" + "---|" * len(headers))
    for f in ("commit_sha", "branch", "dirty"):
        row = [f]
        for m in manifests:
            gp = m.get("git_provenance") or {}
            row.append(str(gp.get(f, "—")))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    return "\n".join(lines)


def compare_artefacts(runs: List[Dict[str, Any]]) -> str:
    headers = [Path(r["run_dir"]).name for r in runs]
    lines = ["## Strategy documents (per role)", ""]
    all_roles = sorted({
        role
        for r in runs
        for role in (r.get("artefacts") or {})
    })
    if not all_roles:
        return "## Strategy documents\n\n_No artefacts found._\n"

    for role in all_roles:
        lines.append(f"### {role}")
        lines.append("")
        for r, h in zip(runs, headers):
            doc = (r.get("artefacts") or {}).get(role)
            if doc is None:
                lines.append(f"**{h}:** _(missing)_")
                lines.append("")
                continue
            lines.append(f"**{h}** — *{doc.get('title', '(no title)')}*")
            for field in ("main_decisions", "key_tensions"):
                items = doc.get(field, []) or []
                if items:
                    lines.append(f"- {field}:")
                    for it in items[:5]:
                        lines.append(f"  - {it}")
                    if len(items) > 5:
                        lines.append(f"  - … and {len(items) - 5} more")
            lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def compare_debriefings(runs: List[Dict[str, Any]]) -> str:
    headers = [Path(r["run_dir"]).name for r in runs]
    lines = ["## Debriefing shape", ""]
    lines.append("| Metric | " + " | ".join(headers) + " |")
    lines.append("|---|" + "---|" * len(headers))

    def _row(label: str, extract):
        row = [label]
        for r in runs:
            t = r.get("debriefing_transcript")
            row.append(str(extract(t)) if t else "—")
        lines.append("| " + " | ".join(row) + " |")

    _row("Exchanges", lambda t: len(t.get("exchanges", []) or []))
    _row("Ended reason", lambda t: t.get("ended_reason", "?"))
    _row("Forbidden-vocab violations", lambda t: t.get("forbidden_vocab_violations", 0))

    def _areas(t):
        return sorted({
            (ex.get("utterance") or {}).get("area_id")
            for ex in (t.get("exchanges") or [])
            if (ex.get("utterance") or {}).get("area_id")
        })

    row = ["Areas covered"]
    for r in runs:
        t = r.get("debriefing_transcript")
        row.append(", ".join(_areas(t)) if t else "—")
    lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return "\n".join(lines)


def compare_observation_summaries(runs: List[Dict[str, Any]]) -> str:
    headers = [Path(r["run_dir"]).name for r in runs]
    lines = ["## Observation summaries", ""]
    lines.append("| Field | " + " | ".join(headers) + " |")
    lines.append("|---|" + "---|" * len(headers))

    def _row(label: str, key: str):
        row = [label]
        for r in runs:
            obs = r.get("observation_summary")
            if not obs:
                row.append("—")
            else:
                row.append(str(len(obs.get(key, []) or [])))
        lines.append("| " + " | ".join(row) + " |")

    _row("# decisions", "decisions")
    _row("# components", "components")
    _row("# disagreements", "disagreements")
    _row("# alternatives_considered", "alternatives_considered")

    # Field rename: `loaded_vocabulary_used` → `flagged_vocabulary_used`.
    # (Flagged vocabulary: words the researcher agent logs when the team uses them
    # unprompted.)
    # Old per-run JSON dumps may carry the legacy name; pick whichever
    # is populated. (The ObservationSummary loader is alias-aware, but
    # the persisted JSON preserves whichever name was used at write
    # time, so we have to inspect both here.)
    def _flagged_row():
        row = ["# flagged_vocabulary uses"]
        for r in runs:
            obs = r.get("observation_summary") or {}
            v = obs.get("flagged_vocabulary_used")
            if v is None:
                v = obs.get("loaded_vocabulary_used")
            row.append(str(len(v or [])) if obs else "—")
        lines.append("| " + " | ".join(row) + " |")

    _flagged_row()
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------

def render_report(run_dirs: List[Path]) -> str:
    runs = [load_run(p) for p in run_dirs]
    sections = [
        f"# Run comparison ({len(runs)} runs)",
        "",
        "**Runs compared:**",
        "",
    ]
    for r in runs:
        sections.append(f"- `{r['run_dir']}`")
    sections.append("")
    sections.append(compare_manifests(runs))
    sections.append(compare_observation_summaries(runs))
    sections.append(compare_debriefings(runs))
    sections.append(compare_artefacts(runs))
    return "\n".join(sections)


def main() -> None:  # pragma: no cover  (CLI)
    parser = argparse.ArgumentParser(
        description="Compare two or more per-run folders side-by-side."
    )
    parser.add_argument(
        "run_dirs", type=Path, nargs="+",
        help="Two or more run folders produced by analysis.persist_artefacts.",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="Write markdown to this file instead of stdout.",
    )
    args = parser.parse_args()

    if len(args.run_dirs) < 2:
        parser.error("need at least 2 run folders to compare")

    report = render_report(args.run_dirs)
    if args.out:
        args.out.write_text(report)
        print(f"Wrote: {args.out}")
    else:
        print(report)


if __name__ == "__main__":
    main()
