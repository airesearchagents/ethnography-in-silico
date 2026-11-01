"""DECISIONS.md is cited by number, so its structure has to stay intact."""

from __future__ import annotations

import re
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "DECISIONS.md"
ENTRY = re.compile(r"^#### (\d+)\. ")
SECTION = re.compile(r"^### ([A-Z]\d+)\. ")
ROW = re.compile(r"^\| (\d+) \| .+ \| \[([A-Z]\d+)\]\(#[^)]+\) \| .*\|$")


def _parse():
    """Return (entry number -> section it sits in, index number -> section)."""
    entries: dict[int, str] = {}
    index: dict[int, str] = {}
    numbers: list[int] = []
    section = None
    for line in LOG.read_text().splitlines():
        if match := SECTION.match(line):
            section = match.group(1)
        elif match := ENTRY.match(line):
            numbers.append(int(match.group(1)))
            entries[int(match.group(1))] = section
        elif match := ROW.match(line):
            index[int(match.group(1))] = match.group(2)
    assert len(numbers) == len(set(numbers)), "an entry number is used twice"
    return entries, index


def test_numbers_are_consecutive():
    entries, _ = _parse()
    assert sorted(entries) == list(range(1, len(entries) + 1))


def test_every_entry_sits_in_a_section():
    entries, _ = _parse()
    assert all(entries.values())


def test_index_matches_the_entries():
    entries, index = _parse()
    assert index == entries


def test_sections_have_valid_anchors():
    text = LOG.read_text()
    headings = {
        re.sub(r"[^a-z0-9 -]", "", line[4:].lower()).replace(" ", "-")
        for line in text.splitlines()
        if SECTION.match(line)
    }
    for anchor in re.findall(r"\]\(#([^)]+)\)", text):
        assert anchor in headings, anchor
