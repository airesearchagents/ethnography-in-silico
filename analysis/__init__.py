"""Analysis helpers: persistence, replication manifest, comparison,
plotting, inter-rater reliability.

These tools work on a run (one complete simulated meeting and debrief) after it
has finished, turning its saved records into folders people can read and compare.

`persist_artefacts.burst_run(...)` turns a run's JSON (plain-text structured data) dump into a
human-browseable folder of strategy documents, transcripts, and
researcher notes — one folder per run.

`replication_package.build_replication_manifest(...)` writes a
sibling `manifest.json` (a file listing what produced the run) capturing
models / prompts (the text sent to a language model) / git (the tool that keeps
the code's history) / env (settings held outside the code) so a reviewer can
reproduce the run.

`compare_runs.render_report(...)` produces a markdown diff (comparison) of two or
more per-run folders for the multi-LLM (LLM: large language model, a program
trained on text to write likely continuations) robustness story.
"""

from .compare_runs import load_run, render_report
from .persist_artefacts import (
    burst_concurrent_log,
    burst_run,
    burst_run_from_files,
)
from .replication_package import (
    ReplicationManifest,
    build_replication_manifest,
    capture_from_system,
    redact_env,
    snapshot_env,
    snapshot_git_provenance,
    snapshot_python_and_packages,
    write_manifest,
)

__all__ = [
    "ReplicationManifest",
    "build_replication_manifest",
    "burst_concurrent_log",
    "burst_run",
    "burst_run_from_files",
    "capture_from_system",
    "load_run",
    "redact_env",
    "render_report",
    "snapshot_env",
    "snapshot_git_provenance",
    "snapshot_python_and_packages",
    "write_manifest",
]
