"""What an agent remembers when it writes a document or answers the debrief.

Model calls do not share a session, because a session re-sends every earlier
prompt on every call. So each prompt carries what its agent needs, once. The
memory goes first in the prompt and does not change between calls, which is
what lets the provider's automatic caching discount it.

A role remembers the public discussion and its own private notes and draft. It
never sees another role's. The researcher remembers everything it observed.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

_RULE = "---------------------------------------"


def render_document(document: Any) -> str:
    """A strategy document in full, as a role or the researcher would read it."""
    parts = [f"Title: {document.title}"]
    for label, items in (
        ("Key challenges", document.key_challenges),
        ("Main decisions", document.main_decisions),
        ("Key tensions", document.key_tensions),
    ):
        if items:
            parts.append(f"{label}:\n" + "\n".join(f"  - {item}" for item in items))
    if document.body:
        parts.append(document.body)
    return "\n".join(parts)


def role_memory_block(
    role: str,
    discussion: str,
    role_state: Optional[dict] = None,
    document: Any = None,
) -> str:
    """The memory one role carries into a prompt."""
    state = role_state or {}
    notes = "\n".join(f"- {note}" for note in state.get("scratchpad") or [])
    block = (
        "WHAT YOU REMEMBER FROM THE DELIBERATION\n"
        f"{_RULE}\n"
        f"The team's discussion, which you took part in as {role}:\n\n"
        f"{discussion or '(no discussion was recorded)'}\n\n"
        f"Your private notes, which no one else saw:\n{notes or '(none)'}\n\n"
        f"Your working draft, which no one else saw:\n{state.get('draft') or '(none)'}\n"
    )
    if document is not None:
        block += f"\nThe strategy document you wrote afterwards:\n{render_document(document)}\n"
    return block + f"{_RULE}\n\n"


def build_role_memory(
    roles: Iterable[str],
    discussion: str,
    role_states: Optional[dict] = None,
    artefacts: Any = None,
) -> Dict[str, str]:
    """A memory for each role. Pass `artefacts` once the documents are written."""
    states = role_states or {}
    return {
        role: role_memory_block(
            role,
            discussion,
            states.get(role),
            artefacts.by_role(role) if artefacts is not None else None,
        )
        for role in roles
    }


def build_researcher_memory(
    discussion: str,
    field_notes: Optional[List[str]] = None,
    artefacts: Any = None,
) -> str:
    """What the debriefer observed. Private notes reach it through its instruction."""
    notes = "\n\n".join(field_notes or [])
    documents = "\n\n".join(
        f"### {document.role}\n{render_document(document)}"
        for document in (artefacts.artefacts if artefacts is not None else [])
    )
    return (
        "WHAT YOU OBSERVED\n"
        f"{_RULE}\n"
        f"The deliberation, every utterance in order:\n\n"
        f"{discussion or '(no discussion was recorded)'}\n\n"
        f"Your field notes:\n{notes or '(none saved)'}\n\n"
        f"The strategy documents in full:\n{documents or '(none)'}\n"
        f"{_RULE}\n\n"
    )
