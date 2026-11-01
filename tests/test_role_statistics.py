"""The statistics must detect a real gap, and report none where there is none."""

from __future__ import annotations

import importlib
import json

import numpy as np

PKG = "open-innovation-strategy"


def _module():
    return importlib.import_module(f"{PKG}.analysis.role_statistics")


def test_sign_flip_separates_a_gap_from_noise():
    module = _module()
    rng = np.random.default_rng(1)
    assert module.sign_flip_p(np.full(24, 0.05), rng) < 0.001
    balanced = np.array([0.05, -0.05] * 12)
    assert module.sign_flip_p(balanced, rng) == 1.0


def test_repeat_gaps_are_positive_when_a_role_matches_itself():
    module = _module()
    answers = [
        {"question": q, "role": role, "repeat": k, "text": "x"}
        for q in (1, 2) for role in ("A", "B") for k in (0, 1)
    ]
    vectors = np.array([[1.0, 0.0] if a["role"] == "A" else [0.0, 1.0] for a in answers])
    grid = module.repeat_gaps(answers, vectors)
    assert grid.shape == (2, 2)
    assert (grid == 1.0).all()
    low, high = module.cluster_interval(grid, np.random.default_rng(1), draws=50)
    assert low == high == 1.0


def test_convergence_detects_roles_moving_together(tmp_path):
    module = _module()
    log = tmp_path / "01_deliberation"
    log.mkdir()
    words = " ".join(["word"] * 30)
    events = []
    for i in range(12):
        phase = "early" if i < 6 else "late"
        events.append({"role": "A" if i % 2 else "B", "text": f"{phase} {i} {words} We are fully aligned."})
    (log / "interaction_log.json").write_text(json.dumps({"events": events}))

    def embed(texts):
        rows = []
        for n, text in enumerate(texts):
            if text.startswith("late"):
                rows.append([1.0, 0.0])
            else:
                rows.append([1.0, 0.0] if n % 2 else [0.0, 1.0])
        return np.array(rows)

    report = module.convergence(tmp_path, embed, draws=200)
    assert report["late"] > report["early"]
    assert report["change"] > 0
    assert report["agreement_words"] == 12
    assert report["dissent_words"] == 0


def test_repeat_gaps_skip_a_question_with_a_lost_answer():
    answers = [
        {"question": q, "role": r, "repeat": k}
        for q in ("q1", "q2") for r in ("CEO", "CTO") for k in (0, 1)
        if not (q == "q2" and r == "CTO" and k == 1)
    ]
    grid = _module().repeat_gaps(answers, np.eye(len(answers)))
    assert grid.shape == (1, 2)


def test_too_few_messages_give_no_result_rather_than_a_misleading_one():
    stats = importlib.import_module("open-innovation-strategy.analysis.role_statistics")
    early, late = stats.between_role_similarity(np.eye(2), ["CEO", "CTO"], [0, 1])
    assert np.isnan(early) and np.isnan(late)
