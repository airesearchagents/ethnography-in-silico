"""Nothing the panel reads may steer it toward the construct under study.

The study asks whether and how openness comes up on its own, so the
words that frame it (and worked examples that hand the team a product
idea) must stay out of every prompt the team agents see. The Debriefer's
stems are held to the same rule because the panel hears them. The judges
are exempt: they score the run afterwards and the panel never sees them.
"""

from __future__ import annotations

import asyncio
import importlib
import re
from pathlib import Path

import pytest

PKG = "open-innovation-strategy"

ROLE_FACTORIES = (
    ("ceo_agent", "create_ceo_agent"),
    ("cto_agent", "create_cto_agent"),
    ("coo_agent", "create_coo_agent"),
    ("cmo_agent", "create_cmo_agent"),
    ("product_strategist_agent", "create_product_strategist_agent"),
    ("product_designer_agent", "create_product_designer_agent"),
)

STEERING = re.compile(
    r"proprietar|open[- ]source|open[- ]weight|openness|closed[- ]source"
    r"|\bvs\.? (open|closed)\b|internal vs|\bmaneuver|\becosystem|\bmoat"
    r"|asymmetr|treated which way|research question|selective reveal"
    r"|\brelease\b|\bdisclos|stay close|go out\b|tightest|outsider|ends up outside"
    r"|beyond the firm|holding onto|putting it out"
    r"|edge-cloud|\bSLM\b|\bM2M\b",
    re.IGNORECASE,
)


def _assert_clean(text: str, where: str) -> None:
    hit = STEERING.search(text)
    assert hit is None, f"{where}: steering wording {hit.group()!r} in ...{text[max(0, hit.start() - 60):hit.end() + 60]!r}"


def _study():
    return importlib.import_module(f"{PKG}.studies").load_study("openness_maneuvering")


@pytest.mark.parametrize("module,factory", ROLE_FACTORIES)
@pytest.mark.parametrize("industry", ("Dynamic", "Stable"))
@pytest.mark.parametrize("product", ("Novel", "Enhancement"))
def test_role_instructions(module, factory, industry, product):
    mod = importlib.import_module(f"{PKG}.roles.{module}")
    agent = getattr(mod, factory)("ACME", industry_context=industry, product_type=product)
    _assert_clean(agent.instruction, f"{factory} {industry}/{product}")


def test_document_prompts():
    ac = importlib.import_module(f"{PKG}.orchestrator.artefact_collection")
    for role, framing in ac._ROLE_DOC_FRAMING.items():
        _assert_clean(framing, f"{role} document framing")


def test_strategic_question():
    template = _study().strategic_question_template
    _assert_clean(template, "strategic_question_template")
    source = Path(importlib.import_module(f"{PKG}.run_research_session").__file__).read_text()
    assert "govern, and release" not in source


@pytest.mark.parametrize("role", ("CEO", "CTO"))
def test_concurrent_turn_prompt(role):
    conc = importlib.import_module(f"{PKG}.orchestrator.concurrent_mode")
    ac = importlib.import_module(f"{PKG}.orchestrator.artefact_collection")
    spec = conc.RoleTaskSpec(
        role=role, company="ACME", industry_context="Dynamic", product_type="Novel",
        strategic_question=_study().strategic_question_template,
        doc_framing=ac._ROLE_DOC_FRAMING[role],
    )
    prompt = conc._compose_role_prompt(
        role=role, task=spec, my_state=conc.RoleState(role=role), transcript=[],
    )
    _assert_clean(prompt, f"{role} concurrent prompt")


def test_structured_output_descriptions():
    schemas = (
        (f"{PKG}.roles.artefact_schemas", "StrategicArtefact"),
        (f"{PKG}.rag.schemas", "Citation"),
        (f"{PKG}.orchestrator.concurrent_mode", "AgentAction"),
    )
    for module, name in schemas:
        model = getattr(importlib.import_module(module), name)
        for field, info in model.model_fields.items():
            _assert_clean(info.description or "", f"{name}.{field}")


def test_panellist_prompt_does_not_carry_the_research_question():
    pd = importlib.import_module(f"{PKG}.orchestrator.panel_debriefing")
    rs = importlib.import_module(f"{PKG}.roles.researcher_schemas")
    seen: list[str] = []

    async def run_agent(*, agent, prompt, **_):
        seen.append(prompt)
        return "An answer."

    utterance = rs.PanelUtterance(
        area_id="A", addressed_to="CTO", anchor_refs=["pricing"],
        text="Walk me through the pricing decision.",
    )
    asyncio.run(pd._single_panellist_response(
        role="CTO", agent=object(), utterance=utterance, history_block="(none)",
        artefacts=None, run_agent=run_agent, is_cross_talk=False,
    ))
    assert seen, "panellist was never called"
    _assert_clean(seen[0], "panellist prompt")
    assert _study().research_question not in seen[0]


def test_debriefing_stems_and_area_names():
    qual = importlib.import_module(f"{PKG}.roles.qualitative_researcher_agent")
    study = _study()
    protocol = qual._apply_study_overlay(qual._load_protocol(None), study)
    for area in protocol["thematic_areas"]:
        _assert_clean(area["name"], f"area {area['id']} name")
        _assert_clean(area.get("purpose", ""), f"area {area['id']} purpose")
        for stem in area["stems"]:
            _assert_clean(stem, f"area {area['id']} stem")


def test_researcher_background_is_neutral():
    study = _study()
    _assert_clean(study.theoretical_lens, "theoretical_lens")
    _assert_clean(study.debriefer_background_block or "", "debriefer_background_block")


@pytest.mark.parametrize("word", ("openness", "proprietary", "open-weight", "disclosure", "outsider"))
def test_synonyms_are_forbidden_and_watched(word):
    study = _study()
    assert word in study.construct_forbidden_vocabulary
    assert word in study.flagged_vocabulary


def _debriefer_instruction():
    qual = importlib.import_module(f"{PKG}.roles.qualitative_researcher_agent")
    return qual._render_research_context(_study())


def test_debriefer_treats_question_as_guiding_post():
    text = _debriefer_instruction()
    assert _study().research_question in text
    assert "guiding post" in text
    assert "Never state, paraphrase, or hint at the research question to the panel" in text
    assert "even if it leads away from the research" in text
    assert "emerging_question" in text


def test_emerging_question_stays_out_of_panel_prompt_and_is_saved():
    pd = importlib.import_module(f"{PKG}.orchestrator.panel_debriefing")
    rs = importlib.import_module(f"{PKG}.roles.researcher_schemas")
    persist = importlib.import_module(f"{PKG}.analysis.persist_artefacts")
    note = "Why did the team stop asking about pricing?"
    utterance = rs.PanelUtterance(
        area_id="A", addressed_to="CTO", anchor_refs=["pricing"],
        text="Walk me through the pricing decision.", emerging_question=note,
    )
    transcript = pd.DebriefingTranscript(company="ACME", research_question="rq")
    transcript.exchanges.append(rs.PanelExchange(utterance=utterance, responses=[]))
    seen: list[str] = []

    async def run_agent(*, agent, prompt, **_):
        seen.append(prompt)
        return "An answer."

    asyncio.run(pd._single_panellist_response(
        role="CTO", agent=object(), utterance=utterance,
        history_block=pd._render_transcript_for_prompt(transcript),
        artefacts=None, run_agent=run_agent, is_cross_talk=False,
    ))
    assert note not in seen[0]
    md = persist._render_debriefing_md(transcript.model_dump(mode="json"))
    assert f"- Exchange 1: {note}" in md


def test_research_question_link_stays_out_of_panel_prompt_and_is_saved():
    pd = importlib.import_module(f"{PKG}.orchestrator.panel_debriefing")
    rs = importlib.import_module(f"{PKG}.roles.researcher_schemas")
    persist = importlib.import_module(f"{PKG}.analysis.persist_artefacts")
    link = "Shows what the team kept to itself."
    utterance = rs.PanelUtterance(
        area_id="A", addressed_to="CTO", anchor_refs=["pricing"],
        text="Walk me through the pricing decision.", research_question_link=link,
    )
    transcript = pd.DebriefingTranscript(company="ACME", research_question="rq")
    transcript.exchanges.append(rs.PanelExchange(utterance=utterance, responses=[]))
    seen: list[str] = []

    async def run_agent(*, agent, prompt, **_):
        seen.append(prompt)
        return "An answer."

    asyncio.run(pd._single_panellist_response(
        role="CTO", agent=object(), utterance=utterance,
        history_block=pd._render_transcript_for_prompt(transcript),
        artefacts=None, run_agent=run_agent, is_cross_talk=False,
    ))
    assert link not in seen[0]
    md = persist._render_debriefing_md(transcript.model_dump(mode="json"))
    assert link in md


def test_debriefer_is_told_its_questions_explore_the_research_question():
    text = _debriefer_instruction()
    assert "your questions are there to explore it" in text
    assert "research_question_link" in text



def _listed_word_hit(text: str):
    words = sorted(_study().construct_forbidden_vocabulary, key=len, reverse=True)
    return re.search(r"\\b(" + "|".join(re.escape(w) for w in words) + r")\\b", text, re.IGNORECASE)


@pytest.mark.parametrize("module,factory", ROLE_FACTORIES)
@pytest.mark.parametrize("industry", ("Dynamic", "Stable"))
@pytest.mark.parametrize("product", ("Novel", "Enhancement"))
def test_role_instructions_carry_no_listed_word(module, factory, industry, product):
    mod = importlib.import_module(f"{PKG}.roles.{module}")
    agent = getattr(mod, factory)("ACME", industry_context=industry, product_type=product)
    assert _listed_word_hit(agent.instruction) is None


def test_turn_prompt_carries_no_listed_word():
    import inspect

    concurrent = importlib.import_module(f"{PKG}.orchestrator.concurrent_mode")
    assert _listed_word_hit(inspect.getsource(concurrent._compose_role_prompt)) is None
