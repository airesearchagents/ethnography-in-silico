"""Studies package — per-research-project configuration modules.

Each study is a sub-package (a folder of Python code) under
`studies/<slug>/` (slug: a short name with no spaces) exporting a
module-level `STUDY: StudyConfig`. See `studies/base.py` for the
schema (the template of fields a study fills in), and
`studies/openness_maneuvering/__init__.py` for the
default study (strategic maneuvering of openness in open innovation
ecosystems).

Public API (what other code is meant to use here):
    StudyConfig             — the per-study config schema
    load_study(slug: str)   — import `studies.<slug>` and return its STUDY
    DEFAULT_STUDY_SLUG      — slug used when --study is not specified
"""

from .base import StudyConfig, load_study, DEFAULT_PANEL_ROLES

# The default study used when the CLI's (command-line interface's) --study
# flag (an option added to a command) is omitted. Set
# here so the framework has a single source of truth. A new study needs only
# its sub-package; change this constant only to change the default.
DEFAULT_STUDY_SLUG: str = "openness_maneuvering"

__all__ = [
    "StudyConfig",
    "load_study",
    "DEFAULT_PANEL_ROLES",
    "DEFAULT_STUDY_SLUG",
]
