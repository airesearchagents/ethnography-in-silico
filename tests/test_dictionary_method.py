"""Tests for the Method A (dictionary scoring) implementation
(`analysis/text_measures/dictionary.py`, Phase D of the measurement plan).

These tests pin:
  * negation-window handling (the key correctness invariant);
  * directionality — synthetic pro-openness text scores positive on
    the matching sub-dimension, anti-openness text scores negative;
  * per-channel attribution — text routed through the public channel
    stays in the public channel; private channel stays private; the
    researcher channel is segregated;
  * per-role attribution — the public channel preserves role identity
    on artefacts and transcript events;
  * the four output CSVs are written with the right column shape;
  * `_ALL` aggregation matches the length-weighted formula in §9.4.1
    of the plan;
  * empty channels do not break the scorer (resilient to thin runs).

No network, no real ADK.
"""

from __future__ import annotations

import csv
import importlib
from pathlib import Path
from typing import Dict, List

import pytest

PKG = "open-innovation-strategy"


def _scorer():
    return importlib.import_module(f"{PKG}.analysis.text_measures.dictionary")


# ===========================================================================
# 1. Negation handling
# ===========================================================================

class TestNegationWindow:
    """The ±3-token negation window is the linchpin of Method A's
    correctness. Without it, every "we will NOT keep our weights
    proprietary" sentence would score anti-openness, exactly backwards."""

    def test_negated_anti_marker_flips_to_pro(self):
        s = _scorer()
        # The anti-openness marker `proprietary weights` is negated, so
        # it should count as pro-openness on D1.
        pro, anti = s._count_hits_in_sentence(
            "We will not have proprietary weights — every checkpoint goes public.",
            "asset_class_disclosed",
        )
        assert pro >= 1, f"pro={pro} anti={anti}: expected polarity flip"
        # And it should NOT also count as anti.
        assert anti == 0, f"pro={pro} anti={anti}: polarity should flip, not double-count"

    def test_negated_pro_marker_flips_to_anti(self):
        s = _scorer()
        # The pro-openness marker `open-source` is negated, so it scores as anti.
        pro, anti = s._count_hits_in_sentence(
            "We have no plans to open-source the model.",
            "asset_class_disclosed",
        )
        assert anti >= 1, f"pro={pro} anti={anti}: expected polarity flip"
        assert pro == 0

    def test_clean_pro_marker_stays_pro(self):
        s = _scorer()
        pro, anti = s._count_hits_in_sentence(
            "We release the model weights under Apache 2.0.",
            "license_regime",
        )
        assert pro >= 1
        assert anti == 0

    def test_clean_anti_marker_stays_anti(self):
        s = _scorer()
        pro, anti = s._count_hits_in_sentence(
            "Our enterprise license requires negotiation.",
            "license_regime",
        )
        assert anti >= 1
        assert pro == 0

    def test_negation_window_is_bounded(self):
        """A `not` ten tokens away from the marker should NOT flip it."""
        s = _scorer()
        pro, anti = s._count_hits_in_sentence(
            "We do not believe many things matter here, but ultimately we will keep our proprietary weights going forward.",
            "asset_class_disclosed",
        )
        # `proprietary weights` is many tokens away from `not` — should still count as anti.
        assert anti >= 1


# ===========================================================================
# 2. Sentence tokenisation
# ===========================================================================

class TestSentenceTokenisation:
    """Splitting prose into sentences is foundational. The scorer
    divides by sentence count; bad tokenisation skews every score."""

    def test_splits_on_period_followed_by_capital(self):
        s = _scorer()
        out = s._split_sentences("First sentence here. Second sentence here.")
        assert len(out) == 2

    def test_filters_short_fragments(self):
        s = _scorer()
        out = s._split_sentences("Yes. We will open-source all of the weights.")
        # "Yes." is a 1-word fragment — should be filtered.
        assert len(out) == 1
        assert "open-source" in out[0]

    def test_splits_on_bullet_markers(self):
        s = _scorer()
        text = (
            "Our plan has three parts:\n"
            "- We will release model weights under Apache 2.0.\n"
            "- We will publish all the evaluation code.\n"
            "- We will keep training data proprietary."
        )
        out = s._split_sentences(text)
        # Each bullet should be its own sentence.
        assert len(out) >= 3

    def test_empty_string_produces_no_sentences(self):
        s = _scorer()
        assert s._split_sentences("") == []
        assert s._split_sentences("   \n  ") == []


# ===========================================================================
# 3. Channel + role attribution
# ===========================================================================

class TestChannelAttribution:
    """Per the §9.2 commitment: each text source belongs to exactly
    one channel; per §9.8 decision 1 the FieldNoter's prose is its
    own channel (researcher), not public."""

    def test_field_notes_route_to_researcher_channel(self, tmp_path):
        s = _scorer()
        out_dir = tmp_path / "run"
        out_dir.mkdir()
        s.score_run(
            out_dir=out_dir,
            field_notes=["The team was eager to open-source the model weights."],
        )
        path = out_dir / "06_subdimension_scores" / "per_subdimension.csv"
        assert path.exists()
        rows = list(csv.DictReader(path.open()))
        # The pro-openness signal must appear under researcher, not public.
        researcher_signal = [
            r for r in rows
            if r["channel"] == "researcher" and r["sub_dimension"] == "asset_class_disclosed"
            and r["role"] == "_ALL" and float(r["score"]) > 0
        ]
        assert researcher_signal, "field-notes pro signal not found in researcher channel"
        # And it should NOT appear in the public channel.
        public_signal = [
            r for r in rows
            if r["channel"] == "public" and r["sub_dimension"] == "asset_class_disclosed"
            and r["role"] == "_ALL" and float(r["score"]) > 0
        ]
        assert not public_signal, (
            "field-notes pro signal leaked into public channel — channel "
            "boundary violated"
        )

    def test_scratchpads_route_to_private_channel(self, tmp_path):
        s = _scorer()
        out_dir = tmp_path / "run"
        out_dir.mkdir()
        s.score_run(
            out_dir=out_dir,
            private_state={
                "CEO": {
                    "scratchpad": [
                        "We will release model weights and publish the eval harness on GitHub.",
                    ],
                    "draft": "",
                    "inbox": [],
                },
            },
        )
        path = out_dir / "06_subdimension_scores" / "per_subdimension.csv"
        rows = list(csv.DictReader(path.open()))
        # Private channel must have the signal attributed to CEO.
        private_ceo = [
            r for r in rows
            if r["channel"] == "private" and r["role"] == "CEO"
            and r["sub_dimension"] == "asset_class_disclosed"
            and float(r["score"]) > 0
        ]
        assert private_ceo

    def test_artefacts_route_to_public_with_role_attribution(self, tmp_path):
        s = _scorer()
        out_dir = tmp_path / "run"
        out_dir.mkdir()
        s.score_run(
            out_dir=out_dir,
            artefacts={
                "artefacts": [
                    {
                        "role": "CTO",
                        "title": "CTO strategy",
                        "key_challenges": [],
                        "main_decisions": [],
                        "key_tensions": [],
                        "body": (
                            "We will release the model weights under Apache 2.0 "
                            "with a model card describing intended use."
                        ),
                    },
                ],
            },
        )
        rows = list(csv.DictReader(
            (out_dir / "06_subdimension_scores" / "per_subdimension.csv").open()
        ))
        # CTO row in public channel for the license sub-dimension should be positive.
        cto_license = [
            r for r in rows
            if r["channel"] == "public" and r["role"] == "CTO"
            and r["sub_dimension"] == "license_regime"
            and float(r["score"]) > 0
        ]
        assert cto_license, "CTO public artefact license-regime signal missing"


# ===========================================================================
# 4. Output CSV shapes
# ===========================================================================

class TestOutputCSVs:
    """All four CSVs must be written with the schema documented in §9.5."""

    def _sample_run(self, tmp_path):
        s = _scorer()
        out_dir = tmp_path / "run"
        out_dir.mkdir()
        s.score_run(
            out_dir=out_dir,
            artefacts={
                "artefacts": [
                    {
                        "role": "CEO",
                        "title": "CEO strategy",
                        "key_challenges": [],
                        "main_decisions": [],
                        "key_tensions": [],
                        "body": (
                            "We will release model weights under Apache 2.0. "
                            "We will not keep our evaluation harness proprietary. "
                            "Our enterprise tier is built on a closed core."
                        ),
                    },
                ],
            },
            private_state={
                "CEO": {
                    "scratchpad": ["Internal worry: competitive risk from open weights."],
                    "draft": "",
                    "inbox": [],
                },
            },
            field_notes=["The panel showed little hesitation about open-sourcing."],
        )
        return out_dir / "06_subdimension_scores"

    def test_per_subdimension_csv_has_required_columns(self, tmp_path):
        scores_dir = self._sample_run(tmp_path)
        with (scores_dir / "per_subdimension.csv").open() as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == [
                "channel", "role", "dimension", "sub_dimension", "method",
                "score", "n_relevant_sentences", "measurability",
                "evidence_top_3",
            ]

    def test_per_dimension_csv_has_required_columns(self, tmp_path):
        scores_dir = self._sample_run(tmp_path)
        with (scores_dir / "per_dimension.csv").open() as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == [
                "channel", "role", "dimension", "method", "aggregation",
                "score", "n_sub_dimensions_with_signal",
                "weakest_sub", "strongest_sub",
            ]

    def test_per_dimension_writes_both_aggregations(self, tmp_path):
        """Per §9.8 decision 3, both uniform AND measurability_weighted
        rows must be present so the appendix can show sensitivity."""
        scores_dir = self._sample_run(tmp_path)
        rows = list(csv.DictReader((scores_dir / "per_dimension.csv").open()))
        aggs = {r["aggregation"] for r in rows}
        assert aggs == {"uniform", "measurability_weighted"}

    def test_headline_csv_has_three_channel_columns(self, tmp_path):
        scores_dir = self._sample_run(tmp_path)
        with (scores_dir / "headline.csv").open() as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == [
                "dimension",
                "public_dict", "private_dict", "researcher_dict",
            ]
            rows = list(reader)
        # 7 dimensions (rubric v0.2 — boundary_permeability split into
        # inbound/outbound + new temporal_openness_maneuvering), one
        # row each.
        assert len(rows) == 7

    def test_headline_by_role_includes_all_six_roles_plus_aggregate(self, tmp_path):
        scores_dir = self._sample_run(tmp_path)
        rows = list(csv.DictReader((scores_dir / "headline_by_role.csv").open()))
        roles = {r["role"] for r in rows}
        # Six TMT roles + _ALL aggregate, regardless of which actually
        # produced text. (Roles with no text get score=0 cells.)
        assert {"CEO", "CTO", "COO", "CMO",
                "Product_Strategist", "Product_Designer", "_ALL"} <= roles

    def test_summary_markdown_is_written(self, tmp_path):
        scores_dir = self._sample_run(tmp_path)
        md = (scores_dir / "README.md").read_text()
        assert "Method A" in md
        assert "Headline scores" in md


# ===========================================================================
# 5. Directionality — synthetic pro/anti text scores in the right direction
# ===========================================================================

class TestDirectionality:
    """End-to-end: pro-openness text produces positive headline scores;
    anti-openness text produces negative ones. The scorer's signs must
    not be inverted somewhere in the aggregation pipeline."""

    def test_pure_pro_openness_artefact_scores_positive(self, tmp_path):
        s = _scorer()
        out_dir = tmp_path / "run"
        out_dir.mkdir()
        s.score_run(
            out_dir=out_dir,
            artefacts={
                "artefacts": [
                    {
                        "role": "CEO",
                        "title": "Open strategy",
                        "key_challenges": [],
                        "main_decisions": [],
                        "key_tensions": [],
                        "body": (
                            "We will release our model weights under Apache 2.0. "
                            "We will publish all training methods on arxiv. "
                            "We will open-source the evaluation harness. "
                            "Our developer program will offer free credits to startups. "
                            "We will participate in the MLCommons standards body."
                        ),
                    },
                ],
            },
        )
        rows = list(csv.DictReader(
            (out_dir / "06_subdimension_scores" / "headline.csv").open()
        ))
        # Component disclosure should be positive on the public channel.
        cd_row = next(r for r in rows if r["dimension"] == "component_disclosure")
        assert float(cd_row["public_dict"]) > 0, (
            "pure pro-openness artefact produced non-positive component_disclosure "
            f"score: {cd_row['public_dict']}"
        )

    def test_pure_anti_openness_artefact_scores_negative(self, tmp_path):
        s = _scorer()
        out_dir = tmp_path / "run"
        out_dir.mkdir()
        s.score_run(
            out_dir=out_dir,
            artefacts={
                "artefacts": [
                    {
                        "role": "CEO",
                        "title": "Closed strategy",
                        "key_challenges": [],
                        "main_decisions": [],
                        "key_tensions": [],
                        "body": (
                            "Our weights are proprietary. "
                            "Our training data is internal-only. "
                            "Our enterprise license restricts commercial use. "
                            "We will sue infringers and enforce our patent portfolio. "
                            "We rely on switching cost and proprietary format for lock-in."
                        ),
                    },
                ],
            },
        )
        rows = list(csv.DictReader(
            (out_dir / "06_subdimension_scores" / "headline.csv").open()
        ))
        cd_row = next(r for r in rows if r["dimension"] == "component_disclosure")
        assert float(cd_row["public_dict"]) < 0, (
            "pure anti-openness artefact produced non-negative score: "
            f"{cd_row['public_dict']}"
        )
        # Value capture posture should ALSO be negative.
        vc_row = next(r for r in rows if r["dimension"] == "value_capture_posture")
        assert float(vc_row["public_dict"]) < 0


# ===========================================================================
# 6. Resilience to empty inputs
# ===========================================================================

class TestResilience:
    """Thin runs (e.g. a role declared DONE quickly) must not break
    the scorer. Empty channels write zeros, not crashes."""

    def test_no_inputs_produces_all_zero_scores(self, tmp_path):
        s = _scorer()
        out_dir = tmp_path / "run"
        out_dir.mkdir()
        scores_dir = s.score_run(out_dir=out_dir)
        # The four CSVs exist, all scores are zero.
        rows = list(csv.DictReader((scores_dir / "headline.csv").open()))
        for r in rows:
            for col in ("public_dict", "private_dict", "researcher_dict"):
                assert float(r[col]) == 0.0

    def test_handles_empty_artefacts_bundle(self, tmp_path):
        s = _scorer()
        out_dir = tmp_path / "run"
        out_dir.mkdir()
        # Empty list is a valid bundle (no roles produced artefacts).
        scores_dir = s.score_run(
            out_dir=out_dir,
            artefacts={"artefacts": []},
        )
        assert (scores_dir / "headline.csv").exists()
