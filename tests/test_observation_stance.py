"""Whether the researcher knows the question while observing is the study's choice."""

from __future__ import annotations

import importlib

PKG = "open-innovation-strategy"


def _qual():
    return importlib.import_module(f"{PKG}.roles.qualitative_researcher_agent")


def _study(**update):
    studies = importlib.import_module(f"{PKG}.studies")
    return studies.load_study("openness_maneuvering").model_copy(update=update)


def test_blind_is_the_default():
    study = _study()
    assert study.embedded_observation is False
    for build in (_qual().create_observer_agent, _qual().create_field_noter_agent):
        assert study.research_question not in build(company="X", study=study).instruction


def test_embedded_observer_and_field_noter_know_the_question():
    study = _study(embedded_observation=True)
    for build in (_qual().create_observer_agent, _qual().create_field_noter_agent):
        text = build(company="X", study=study).instruction
        assert study.research_question in text
        assert "embedded observation" in text
        assert "never share" in text


def test_embedded_observer_still_does_not_get_the_theoretical_lens():
    study = _study(embedded_observation=True, theoretical_lens="A lens only analysts read.")
    for build in (_qual().create_observer_agent, _qual().create_field_noter_agent):
        assert "A lens only analysts read." not in build(company="X", study=study).instruction


def test_no_study_means_blind():
    assert _qual()._render_observation_stance(None) == ""
