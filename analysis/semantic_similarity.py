"""Compare panel answers by meaning, not wording.

Panel answers are the debrief replies of the six simulated executives.

`analysis/panel_probe.py` compares shared words. Two answers can make the same
point in different words, so this embeds answers and sentences (turns each into an
embedding, a list of numbers standing for its meaning) and asks three
questions, always against a yardstick:

  answer similarity   how alike whole answers are in meaning
  idea coverage       how many of one answer's sentences have a close match in
                      another answer
  topic overlap       how alike two roles' spread across topics is, using topics
                      clustered from all sentences

On a probe (a test asking each role the same questions twice), the yardstick is a
role's repeat answer: if roles were only labels,
different roles would score the same as a role does with itself. On a full run
(one complete simulated meeting and debrief) there are no repeat answers, so the
yardstick is the same role on other questions.

Usage
-----
    python -m analysis.semantic_similarity --probe <probe.json> --out-dir <dir>
    python -m analysis.semantic_similarity --run-dir <run> --out-dir <dir>

Embeddings use `text-embedding-005` (Google's embedding model) on Vertex AI (Google's
paid cloud service), at a very small cost. Scores
describe meaning as an embedding model sees it. They do not show whether agents (language
models given a role and instructions) reason independently or agree on what to do.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple

import numpy as np
import requests

try:
    from ..roles.researcher_schemas import split_panel_reply
    from .provenance import sentences
except (ImportError, ValueError):  # pragma: no cover  (script-style)
    from roles.researcher_schemas import split_panel_reply  # type: ignore[no-redef]
    from analysis.provenance import sentences  # type: ignore[no-redef]

MODEL = "text-embedding-005"
BATCH = 100
MATCH_THRESHOLD = 0.8
TOPICS = 12
SEED = 7

Embedder = Callable[[Sequence[str]], np.ndarray]


def vertex_embedder(location: str = "us-west1") -> Embedder:
    """Embed texts with Vertex AI, using the caller's Google credentials."""
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    token = subprocess.check_output(
        ["gcloud", "auth", "application-default", "print-access-token"],
        stderr=subprocess.DEVNULL, text=True,
    ).strip()
    url = (
        f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}"
        f"/locations/{location}/publishers/google/models/{MODEL}:predict"
    )

    def embed(texts: Sequence[str]) -> np.ndarray:
        vectors: List[List[float]] = []
        for start in range(0, len(texts), BATCH):
            body = {"instances": [
                {"content": text, "task_type": "SEMANTIC_SIMILARITY"}
                for text in texts[start : start + BATCH]
            ]}
            response = requests.post(url, json=body, timeout=120, headers={
                "Authorization": f"Bearer {token}",
                "x-goog-user-project": project,
            })
            response.raise_for_status()
            vectors.extend(p["embeddings"]["values"] for p in response.json()["predictions"])
        return _normalise(np.array(vectors, dtype=float))

    return embed


def _normalise(vectors: np.ndarray) -> np.ndarray:
    if vectors.size == 0:
        return vectors
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


def _mean(values: Sequence[float]) -> float | None:
    return round(float(np.mean(values)), 3) if len(values) else None


def _kmeans(vectors: np.ndarray, k: int) -> np.ndarray:
    """Spherical k-means (a way of grouping similar texts), seeded (its
    element of chance fixed) so a report can be reproduced."""
    k = min(k, len(vectors))
    rng = random.Random(SEED)
    centres = vectors[rng.sample(range(len(vectors)), k)]
    labels = np.zeros(len(vectors), dtype=int)
    for _ in range(50):
        new_labels = (vectors @ centres.T).argmax(axis=1)
        if (new_labels == labels).all() and _ > 0:
            break
        labels = new_labels
        for cluster in range(k):
            members = vectors[labels == cluster]
            if len(members):
                centre = members.mean(axis=0)
                centres[cluster] = centre / (np.linalg.norm(centre) or 1.0)
    return labels


def _jensen_shannon_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """1 means the same spread across topics, 0 means no overlap."""
    a = a / (a.sum() or 1.0)
    b = b / (b.sum() or 1.0)
    m = (a + b) / 2

    def kl(p: np.ndarray, q: np.ndarray) -> float:
        mask = p > 0
        return float((p[mask] * np.log2(p[mask] / q[mask])).sum())

    return 1 - (kl(a, m) + kl(b, m)) / 2


def _coverage(a: np.ndarray, b: np.ndarray) -> float:
    """Share of a's sentences with a close match among b's."""
    if not len(a) or not len(b):
        return 0.0
    return float(((a @ b.T).max(axis=1) >= MATCH_THRESHOLD).mean())


def compare(answers: List[dict], embed: Embedder) -> dict:
    """`answers` holds dicts with question, repeat, role and text."""
    answers = [a for a in answers if a["text"].strip()]
    whole = embed([a["text"][:8000] for a in answers])
    pieces: List[Tuple[int, str]] = [
        (i, sentence)
        for i, answer in enumerate(answers)
        for sentence in sentences(answer["text"])
        if len(sentence.split()) >= 5
    ]
    sentence_vectors = embed([text for _, text in pieces])
    by_answer: Dict[int, np.ndarray] = defaultdict(lambda: np.zeros((0, sentence_vectors.shape[1])))
    owners = np.array([owner for owner, _ in pieces])
    for i in range(len(answers)):
        by_answer[i] = sentence_vectors[owners == i]

    pairs: Dict[str, List[float]] = defaultdict(list)
    coverage: Dict[str, List[float]] = defaultdict(list)
    for i, j in combinations(range(len(answers)), 2):
        a, b = answers[i], answers[j]
        same_q, same_role = a["question"] == b["question"], a["role"] == b["role"]
        if same_q and same_role:
            key = "same_role_repeat"
        elif same_q and a.get("repeat", 0) == b.get("repeat", 0):
            key = "different_roles_same_question"
        elif same_role and not same_q:
            key = "same_role_other_questions"
        elif not same_role and not same_q:
            key = "different_roles_other_questions"
        else:
            continue
        pairs[key].append(float(whole[i] @ whole[j]))
        if same_q:
            coverage[key].append(_coverage(by_answer[i], by_answer[j]))
            coverage[key].append(_coverage(by_answer[j], by_answer[i]))

    labels = _kmeans(sentence_vectors, TOPICS)
    topic_count = int(labels.max()) + 1
    spread: Dict[Tuple[str, int], np.ndarray] = defaultdict(lambda: np.zeros(topic_count))
    for (owner, _), label in zip(pieces, labels):
        spread[(answers[owner]["role"], answers[owner].get("repeat", 0))][label] += 1
    roles = sorted({a["role"] for a in answers})
    repeats = sorted({a.get("repeat", 0) for a in answers})
    across = [
        _jensen_shannon_similarity(spread[(x, r)], spread[(y, r)])
        for x, y in combinations(roles, 2) for r in repeats
    ]
    within = [
        _jensen_shannon_similarity(spread[(role, x)], spread[(role, y)])
        for role in roles for x, y in combinations(repeats, 2)
    ]
    role_counts = {
        role: sum(spread[(role, r)] for r in repeats) for role in roles
    }
    top_share = [
        float(np.sort(counts)[-3:].sum() / (counts.sum() or 1.0))
        for counts in role_counts.values()
    ]
    return {
        "answers": len(answers),
        "sentences": len(pieces),
        "answer_similarity": {key: _mean(values) for key, values in sorted(pairs.items())},
        "idea_coverage_at_0.8": {key: _mean(values) for key, values in sorted(coverage.items())},
        "topic_overlap": {
            "between_roles": _mean(across),
            "same_role_repeat": _mean(within),
            "topics_clustered": topic_count,
            "share_of_a_role_in_its_top_3_topics": _mean(top_share),
        },
    }


def answers_from_run(run_dir: Path) -> List[dict]:
    transcript = json.loads((Path(run_dir) / "04_interview" / "transcript.json").read_text())
    return [
        {
            "question": number, "repeat": 0, "role": response["role"],
            "text": split_panel_reply(response.get("text", ""))[0],
        }
        for number, exchange in enumerate(transcript.get("exchanges", []), 1)
        for response in exchange.get("responses", []) or []
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--probe", type=Path)
    source.add_argument("--run-dir", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--location", default="us-west1")
    args = parser.parse_args()
    try:
        embed = vertex_embedder(args.location)
        if args.probe:
            probe = json.loads(args.probe.read_text())
            report = {
                name: compare(condition["answers"], embed)
                for name, condition in probe["conditions"].items()
            }
        else:
            report = {"run": compare(answers_from_run(args.run_dir), embed)}
    except (OSError, KeyError, ValueError, subprocess.CalledProcessError) as exc:
        # Embeddings need the gcloud command (Google Cloud's command-line tool), signed
        # in for application-default use.
        sys.exit(f"Cannot compare these answers: {exc}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    name = "semantic.json" if args.probe else f"semantic_{args.run_dir.name}.json"
    (args.out_dir / name).write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
