"""Text-grounded sub-dimensional measurement layer.

This package (a folder of code with one job) implements text-based scoring
against the openness rubric's (scoring guide's) 26 sub-dimensions (narrow items)
across three channels, kinds of record in a run (public / private / researcher).

It runs only with `--subdimension-scores` and is not part of the method in the
proposal.

Public entry point (where other code starts): `score_run(...)` in `dictionary.py`.

Methods that may be added later:
  - Method B (embedding-anchored similarity, comparing texts through lists of numbers
    that stand for their meaning) — needs sentence-transformers (a package that makes
    such numbers) as a dependency (extra package); deferred.
  - Method C (topic modelling via BERTopic, a package for it) — deferred to a study-
    level (cross-run) script; not part of the per-run pipeline.
"""

from .dictionary import score_run  # noqa: F401

__all__ = ["score_run"]
