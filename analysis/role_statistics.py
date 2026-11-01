"""Test how far panel roles differ, and whether teams converge, with simple statistics.

Panel roles are the six simulated executives, as questioned in the debrief.

Two checks, both using `text-embedding-005` embeddings (lists of numbers standing
for a text's meaning, from Google's embedding model) at a very small cost:

  repeat test    on a probe (a test asking each role the same questions twice; see
                 `analysis/panel_probe.py`): is a role's repeat answer closer to
                 its first than
                 to other roles' answers? Reports the mean gap, a sign-flip
                 permutation test (a significance test that flips the data's signs
                 many times rather than assuming a distribution) and an interval
                 from resampling questions and
                 roles.
  convergence    on saved runs (a run is one complete simulated meeting and debrief):
                 does similarity between roles rise from the first to the last
                 third of the deliberation (the team's discussion)? Compares with
                 shuffled message order, and counts agreement and dissent words.

These describe the answers tested. Answers within one run are not independent, so
a small p-value here does not generalize to other teams; that takes many separate
runs. The word lists are narrow, so read the transcripts as well.

Usage
-----
    python -m analysis.role_statistics --probe <probe.json> --runs <run> <run> --out <report.md>
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np

try:
    from .semantic_similarity import Embedder, vertex_embedder
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from analysis.semantic_similarity import Embedder, vertex_embedder  # type: ignore[no-redef]

SEED = 11
MIN_WORDS = 25
AGREEMENT = re.compile(
    r"\b(fully aligned|i agree|we agree|i concur|aligned|consensus|i support|i endorse|fully back|locked)\b",
    re.I,
)
DISSENT = re.compile(
    r"\b(disagree|i push back|pushing back|i object|i reject|concerned that|i oppose|cannot accept|non-starter|i challenge)\b",
    re.I,
)


def sign_flip_p(differences: np.ndarray, rng: np.random.Generator, draws: int = 20000) -> float:
    """Two-sided test that the mean difference is zero, flipping signs at random."""
    observed = abs(differences.mean())
    flips = rng.choice([-1, 1], size=(draws, differences.size))
    hits = int((np.abs((flips * differences).mean(axis=1)) >= observed).sum())
    return (hits + 1) / (draws + 1)


def cluster_interval(
    grid: np.ndarray, rng: np.random.Generator, draws: int = 5000,
) -> tuple[float, float]:
    """95% interval for the mean, resampling rows (questions) and columns (roles)."""
    rows, columns = grid.shape
    means = [
        grid[np.ix_(rng.integers(0, rows, rows), rng.integers(0, columns, columns))].mean()
        for _ in range(draws)
    ]
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def repeat_gaps(answers: List[dict], vectors: np.ndarray) -> np.ndarray:
    """Questions by roles: repeat similarity minus mean similarity to other roles."""
    index = {(a["question"], a["role"], a["repeat"]): i for i, a in enumerate(answers)}
    roles = sorted({a["role"] for a in answers})
    # A role can pass (reply that it has nothing to add) or lose an answer;
    # compare only questions all roles answered twice.
    questions = sorted(
        q for q in {a["question"] for a in answers}
        if all((q, r, k) in index for r in roles for k in (0, 1))
    )
    grid = np.zeros((len(questions), len(roles)))
    for row, question in enumerate(questions):
        for column, role in enumerate(roles):
            repeat = vectors[index[(question, role, 0)]] @ vectors[index[(question, role, 1)]]
            others = [
                vectors[index[(question, role, k)]] @ vectors[index[(question, other, k)]]
                for other in roles if other != role for k in (0, 1)
            ]
            grid[row, column] = repeat - float(np.mean(others))
    return grid


def repeat_test(probe: dict, embed: Embedder) -> Dict[str, dict]:
    rng = np.random.default_rng(SEED)
    report = {}
    for name, condition in probe["conditions"].items():
        answers = condition["answers"]
        grid = repeat_gaps(answers, embed([a["text"][:8000] for a in answers]))
        low, high = cluster_interval(grid, rng)
        report[name] = {
            "mean_gap": round(float(grid.mean()), 3),
            "pairs_above_zero": int((grid > 0).sum()),
            "pairs": int(grid.size),
            "p": round(sign_flip_p(grid.ravel(), rng), 5),
            "interval": [round(low, 3), round(high, 3)],
        }
    return report


def between_role_similarity(vectors: np.ndarray, roles: Sequence[str], order: Sequence[int]) -> tuple[float, float]:
    """Mean similarity between different roles in the first and last third."""
    third = len(order) // 3
    if third == 0:
        return float("nan"), float("nan")
    results = []
    for segment in (order[:third], order[-third:]):
        values = [
            float(vectors[i] @ vectors[j])
            for i, j in combinations(segment, 2) if roles[i] != roles[j]
        ]
        results.append(float(np.mean(values)) if values else float("nan"))
    return results[0], results[1]


def convergence(run_dir: Path, embed: Embedder, draws: int = 3000) -> dict:
    rng = np.random.default_rng(SEED)
    log = json.loads((Path(run_dir) / "01_deliberation" / "interaction_log.json").read_text())
    events = [e for e in log.get("events", []) if len((e.get("text") or "").split()) >= MIN_WORDS]
    if len(events) < 3:
        raise ValueError(f"{run_dir} has {len(events)} usable messages; this needs at least 3.")
    vectors = embed([e["text"][:8000] for e in events])
    roles = [e.get("role", "?") for e in events]
    order = list(range(len(events)))
    early, late = between_role_similarity(vectors, roles, order)
    shuffled = []
    for _ in range(draws):
        a, b = between_role_similarity(vectors, roles, list(rng.permutation(order)))
        shuffled.append(b - a)
    change = late - early
    return {
        "messages": len(events),
        "early": round(early, 3),
        "late": round(late, 3),
        "change": round(change, 3),
        "p": round(float((np.abs(shuffled) >= abs(change)).mean()), 3),
        "agreement_words": sum(len(AGREEMENT.findall(e["text"])) for e in events),
        "dissent_words": sum(len(DISSENT.findall(e["text"])) for e in events),
    }


def render(repeat: Dict[str, dict], runs: Dict[str, dict]) -> str:
    lines = [
        "# Role statistics", "",
        "_Answers within one run are not independent, so these describe the answers tested and do not generalize to other teams. The word lists are narrow._",
        "", "## Is a role's repeat answer closer to its first than to other roles' answers?", "",
        "| Condition | Mean gap | Pairs above zero | Permutation p | 95% interval |",
        "|---|---|---|---|---|",
    ]
    for name, r in repeat.items():
        lines.append(
            f"| {name} | {r['mean_gap']} | {r['pairs_above_zero']} of {r['pairs']} | {'<0.001' if r['p'] < 0.001 else r['p']} | {r['interval'][0]} to {r['interval'][1]} |"
        )
    lines += [
        "", "## Do roles converge during deliberation?", "",
        "| Run | Messages | Similarity, first third | Last third | Change | Shuffled-order p | Agreement words | Dissent words |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, r in runs.items():
        lines.append(
            f"| {name} | {r['messages']} | {r['early']} | {r['late']} | {r['change']} | {r['p']} | {r['agreement_words']} | {r['dissent_words']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--labels", nargs="*", default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--location", default="us-west1")
    args = parser.parse_args()
    try:
        embed = vertex_embedder(args.location)
        repeat = repeat_test(json.loads(args.probe.read_text()), embed)
        labels = args.labels or [path.name for path in args.runs]
        runs = {label: convergence(path, embed) for label, path in zip(labels, args.runs)}
    except (OSError, KeyError, ValueError, subprocess.CalledProcessError) as exc:
        sys.exit(f"Cannot compute these statistics: {exc}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(repeat, runs))
    print(render(repeat, runs))


if __name__ == "__main__":
    main()
