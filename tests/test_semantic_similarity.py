"""The semantic comparison must score roles against their own repeat answers."""

from __future__ import annotations

import hashlib
import importlib

import numpy as np

PKG = "open-innovation-strategy"


def _module():
    return importlib.import_module(f"{PKG}.analysis.semantic_similarity")


def _fake_embed(text_topics):
    """Texts sharing a topic word get nearly the same vector."""
    def embed(texts):
        rows = []
        for text in texts:
            topic = next((t for t in text_topics if t in text), "other")
            seed = int(hashlib.sha256(topic.encode()).hexdigest()[:8], 16)
            rows.append(np.random.default_rng(seed).normal(size=32))
        return _module()._normalise(np.array(rows))
    return embed


def _answers():
    rows = []
    for repeat in (0, 1):
        rows.append({"question": 1, "repeat": repeat, "role": "CTO",
                     "text": "Compute budgets set our ceiling here. Compute budgets drive the whole plan."})
        rows.append({"question": 1, "repeat": repeat, "role": "CMO",
                     "text": "Brand narrative comes first for buyers. Brand narrative shapes the whole launch."})
    return rows


def test_a_role_scores_higher_with_itself_when_roles_differ():
    report = _module().compare(_answers(), _fake_embed(["Compute", "Brand"]))
    similarity = report["answer_similarity"]
    assert similarity["same_role_repeat"] > similarity["different_roles_same_question"]
    coverage = report["idea_coverage_at_0.8"]
    assert coverage["same_role_repeat"] == 1.0
    assert coverage["different_roles_same_question"] == 0.0


def test_identical_roles_score_alike():
    report = _module().compare(_answers(), _fake_embed(["whole"]))
    similarity = report["answer_similarity"]
    assert similarity["same_role_repeat"] == similarity["different_roles_same_question"]


def test_topic_overlap_is_a_share():
    module = _module()
    same = module._jensen_shannon_similarity(np.array([1.0, 1.0]), np.array([2.0, 2.0]))
    apart = module._jensen_shannon_similarity(np.array([1.0, 0.0]), np.array([0.0, 1.0]))
    assert abs(same - 1) < 1e-9
    assert abs(apart) < 1e-9


def test_empty_input_is_handled():
    import importlib

    import numpy as np

    semantic = importlib.import_module("open-innovation-strategy.analysis.semantic_similarity")
    assert semantic._normalise(np.array([])).size == 0
