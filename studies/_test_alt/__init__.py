"""Test-only study used by methodological-invariant tests (automatic checks of
rules that must always hold, such as keeping the research question from
steering agents).

This module (a Python file of code) exists ONLY to verify that the framework
(the shared software) is genuinely multi-study — swapping `--study _test_alt`
(a command-line option) should swap the RESEARCH CONTEXT block of the Debriefer
(the researcher agent when questioning the team) while leaving the prompts
(text sent to a model) of the Observer + FieldNoter (the same agent summarising
and taking notes) unchanged, apart from the per-study flagged-vocabulary list
(words logged when the simulated executives use them unprompted).

The vocabulary is deliberately different from the openness study so
parametric tests (the same test repeated on each study) can distinguish the
two prompts and detect leaks (study wording reaching an agent that must not
see it). Not for production use, meaning real studies.
"""

from __future__ import annotations

from ..base import StudyConfig


STUDY: StudyConfig = StudyConfig(
    name="Test study: absorptive capacity (synthetic, for tests only)",
    slug="_test_alt",
    version="0.0.1",

    research_question=(
        "How do firms develop and deploy absorptive capacity for "
        "knowledge inflows from inter-firm R&D collaborations."
    ),

    theoretical_lens=(
        "Absorptive capacity (Cohen & Levinthal 1990) — the firm's "
        "ability to recognise, assimilate, and apply external "
        "knowledge. Inter-firm collaboration governance "
        "(Williamson 1991). Knowledge-similarity boundary "
        "conditions (Lane & Lubatkin 1998)."
    ),

    debriefer_background_block=(
        "Anchor probes on collaboration episodes the panel itself "
        "named — specific partner relationships, knowledge inflows, "
        "or assimilation steps the team described."
    ),

    construct_forbidden_vocabulary=[
        "absorptive",
        "assimilation",
        "knowledge spillover",
        "complementarity",
        "appropriability",
    ],

    flagged_vocabulary=[
        "absorptive",
        "assimilation",
        "knowledge spillover",
        "complementarity",
        "appropriability",
    ],

    scenario_brief="A pharmaceutical firm engaged in inter-firm R&D alliances.",

    strategic_question_template=(
        "What partnership and absorption strategy should the firm "
        "pursue for {direction_hint} given the current alliance "
        "portfolio?"
    ),
)
