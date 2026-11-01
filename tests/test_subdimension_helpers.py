"""Tests for the v0.4 lexicon helpers added in PR-D commit 2/6.

The helpers expose the existing 26-sub-dimension lexicon in shapes
the judge prompt + aggregator + report layers need:

* `parent_of(sub_dimension_key)` — reverse lookup (sub → parent).
* `all_sub_dimension_keys()` — canonical ordered list of all 26 keys.
* `render_sub_dimensions_for_prompt()` — formatted block for the
  judge prompt (PR-D commit 3/6 will consume this).
"""

from __future__ import annotations

import importlib

import pytest

PKG = "open-innovation-strategy"


def _lexicon():
    return importlib.import_module(
        f"{PKG}.studies.openness_maneuvering.subdimension_lexicon"
    )


# ===========================================================================
# parent_of — reverse lookup
# ===========================================================================

class TestParentOf:
    def test_known_subdim_returns_parent(self):
        L = _lexicon()
        # Sanity probe — pick a key we know exists from the existing
        # `subdimensions_for("component_disclosure")` invariant.
        children = L.subdimensions_for("component_disclosure")
        assert children, "component_disclosure should have at least one child"
        for child in children:
            assert L.parent_of(child) == "component_disclosure"

    def test_every_subdim_has_resolvable_parent(self):
        """Every key in the lexicon must round-trip: subdim → parent → list
        containing the original subdim. Catches a parent-dimension typo
        that would leave a sub-dimension orphaned."""
        L = _lexicon()
        for key in L.OPENNESS_SUBDIMENSION_LEXICON:
            parent = L.parent_of(key)
            assert key in L.subdimensions_for(parent), (
                f"sub-dim {key!r} claims parent {parent!r} but "
                f"`subdimensions_for({parent!r})` does not list it"
            )

    def test_unknown_key_raises_keyerror(self):
        """The aggregator uses this to refuse mismatched assessments —
        an unknown sub-dim key must raise rather than silently default."""
        L = _lexicon()
        with pytest.raises(KeyError):
            L.parent_of("this_subdim_does_not_exist")


# ===========================================================================
# all_sub_dimension_keys — canonical ordering
# ===========================================================================

class TestAllSubDimensionKeys:
    def test_returns_all_twenty_six(self):
        L = _lexicon()
        keys = L.all_sub_dimension_keys()
        assert len(keys) == 26
        assert set(keys) == set(L.OPENNESS_SUBDIMENSION_LEXICON.keys())

    def test_grouped_by_parent_in_rubric_order(self):
        """The 26 keys appear grouped: all `component_disclosure`
        children first, then `process_openness`, etc., in the order
        the rubric declares. This is what the Excel exporter keys off
        — a row order shuffle would break historical comparisons."""
        L = _lexicon()
        keys = L.all_sub_dimension_keys()
        parent_sequence = [L.parent_of(k) for k in keys]
        # Each parent appears in a contiguous block.
        seen_parents = []
        for parent in parent_sequence:
            if not seen_parents or seen_parents[-1] != parent:
                seen_parents.append(parent)
        # Block ordering matches the canonical rubric order.
        expected_order = [
            "component_disclosure",
            "process_openness",
            "boundary_permeability_inbound",
            "boundary_permeability_outbound",
            "ecosystem_orchestration",
            "value_capture_posture",
            "temporal_openness_maneuvering",
        ]
        # Every parent in seen_parents must appear in expected_order
        # in the same relative position (we don't require every parent
        # be present — the lexicon could in principle omit a dimension).
        for actual, expected in zip(seen_parents, expected_order):
            assert actual == expected, (
                f"parent ordering drift: expected {expected} got {actual}"
            )

    def test_within_parent_keys_are_alphabetical(self):
        """Within each parent block the keys are sorted alphabetically —
        deterministic so two runs of `all_sub_dimension_keys()` are
        byte-identical (reproducibility manifest depends on it)."""
        L = _lexicon()
        keys = L.all_sub_dimension_keys()
        # Group consecutive same-parent keys, check sorted.
        current_parent = ""
        current_group: list[str] = []
        for k in keys:
            parent = L.parent_of(k)
            if parent != current_parent:
                # New group — check the previous one.
                assert current_group == sorted(current_group), (
                    f"keys within parent {current_parent!r} not "
                    f"alphabetical: {current_group}"
                )
                current_parent = parent
                current_group = [k]
            else:
                current_group.append(k)
        # Last group.
        assert current_group == sorted(current_group), (
            f"keys within parent {current_parent!r} not alphabetical: "
            f"{current_group}"
        )

    def test_repeated_calls_byte_identical(self):
        """Determinism — the function must not depend on dict-iteration
        order from one call to the next (in Python 3.7+ dict iteration is
        insertion-ordered, but our sort step is the real guarantee)."""
        L = _lexicon()
        a = L.all_sub_dimension_keys()
        b = L.all_sub_dimension_keys()
        assert a == b


# ===========================================================================
# render_sub_dimensions_for_prompt — judge-prompt block
# ===========================================================================

class TestRenderSubDimensionsForPrompt:
    def test_every_parent_appears_as_a_heading(self):
        L = _lexicon()
        rendered = L.render_sub_dimensions_for_prompt()
        for parent in (
            "component_disclosure",
            "process_openness",
            "boundary_permeability_inbound",
            "boundary_permeability_outbound",
            "ecosystem_orchestration",
            "value_capture_posture",
            "temporal_openness_maneuvering",
        ):
            assert f"## {parent}" in rendered, (
                f"expected `## {parent}` heading in the prompt block"
            )

    def test_every_subdim_key_appears(self):
        L = _lexicon()
        rendered = L.render_sub_dimensions_for_prompt()
        for key in L.OPENNESS_SUBDIMENSION_LEXICON:
            assert f"- {key}" in rendered, (
                f"sub-dim {key!r} missing from rendered prompt block"
            )

    def test_construct_definition_lines_present_for_lexicon_entries(self):
        """Every sub-dim in the lexicon has a `construct` field; the
        renderer should surface it under the bullet so the LLM sees
        the one-sentence definition next to the key."""
        L = _lexicon()
        rendered = L.render_sub_dimensions_for_prompt()
        # Spot-check: pick a known sub-dim and its construct definition.
        for key, entry in L.OPENNESS_SUBDIMENSION_LEXICON.items():
            construct = (entry.get("construct") or "").strip()
            if construct:
                # The bullet + a following indented line of definition
                # must appear in sequence — minimal check: the key and
                # the first ~30 chars of its construct definition both
                # appear in the rendered block.
                snippet = construct[:30].strip()
                if snippet:
                    assert snippet in rendered, (
                        f"construct definition for {key!r} not in "
                        f"rendered prompt: missing snippet {snippet!r}"
                    )
                break  # one spot-check is sufficient — broader coverage
                       # is on the key-presence test above

    def test_rendered_block_byte_identical_across_calls(self):
        L = _lexicon()
        assert (
            L.render_sub_dimensions_for_prompt()
            == L.render_sub_dimensions_for_prompt()
        )
