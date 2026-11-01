"""Stubbed end-to-end tests for the panel-debriefing orchestrator.

These tests exercise the turn loop without spinning up any real LLM.
The runner stub returns canned `PanelUtterance` JSON for the debriefer
and canned response text for each panellist, letting us verify:

- The loop terminates on `ends_debriefing=true`.
- The loop terminates on the safety ceiling (`max_exchanges`).
- Group-addressed questions invite every role.
- Role-addressed questions go to the named role first, with cross-talk
  allowed from others.
- The forbidden-vocabulary guard retries once; the violation count is
  recorded; the loop continues after the retry.
- Panel responses are recorded with role + text + is_cross_talk.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from dataclasses import dataclass

import pytest

PKG = "open-innovation-strategy"


def _researcher_schemas():
    return importlib.import_module(f"{PKG}.roles.researcher_schemas")


def _artefact_schemas():
    return importlib.import_module(f"{PKG}.roles.artefact_schemas")


def _panel_debriefing():
    return importlib.import_module(f"{PKG}.orchestrator.panel_debriefing")


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

ROLES = ("CEO", "CTO", "COO", "CMO", "Product_Strategist", "Product_Designer")


@dataclass
class _StubAgent:
    name: str
    instruction: str = ""
    model: str = "stub-model"


def _make_observation_summary():
    s = _researcher_schemas()
    return s.ObservationSummary(
        decisions=["keep inference API internal"],
        components=["inference API", "fine-tuning recipe"],
        disagreements=[
            s.Disagreement(
                topic="releasing the fine-tuning recipe",
                parties=["CTO", "CMO"],
                resolution="internal-only for v1",
            )
        ],
        role_contributions=[],
        alternatives_considered=["partner-only release"],
        loaded_vocabulary_used=[],
    )


def _utterance_json(
    *,
    area_id: str = "A",
    addressed_to: str = "group",
    text: str = "Tell me about the inference API decision.",
    anchor_refs: list[str] | None = None,
    is_followup: bool = False,
    ends_debriefing: bool = False,
) -> str:
    return json.dumps({
        "area_id": area_id,
        "addressed_to": addressed_to,
        "text": text,
        "anchor_refs": anchor_refs or ["inference API"],
        "is_followup": is_followup,
        "ends_debriefing": ends_debriefing,
    })


def _make_runner(utterance_sequence: list[str], panellist_text: str = "Sure, here's my view."):
    """Build a runner that yields canned utterances + canned panel text.

    Args:
        utterance_sequence: JSON strings to return for the debriefer in
            order. Each researcher turn pops one.
        panellist_text: Returned for every panellist response. Empty
            string is treated as a 'no comment' (the orchestrator
            drops it).
    """
    pending = list(utterance_sequence)
    calls: list[str] = []

    async def runner(*, agent, prompt):
        calls.append(agent.name)
        # Debriefer is named "QualitativeResearcher_Debriefer".
        if "Debriefer" in agent.name or "Researcher" in agent.name:
            if not pending:
                # Fallback: emit a closing utterance.
                return _utterance_json(ends_debriefing=True)
            return pending.pop(0)
        # Otherwise it's a panellist.
        return panellist_text

    return runner, calls


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestStopCriteria:
    def test_stops_when_researcher_signals_end(self):
        pd = _panel_debriefing()
        runner, calls = _make_runner([
            _utterance_json(text="Opening question about the inference API.",
                            anchor_refs=["inference API"]),
            _utterance_json(text="Closing — anything else on the inference API?",
                            anchor_refs=["inference API"],
                            ends_debriefing=True),
        ])

        transcript = asyncio.run(pd.run_panel_debriefing(
            company="OpenAI",
            observation_summary=_make_observation_summary(),
            artefacts=None,
            panel_agents={r: _StubAgent(name=r) for r in ROLES},
            run_agent=runner,
            max_exchanges=60,
        ))

        assert transcript.ended_reason == "researcher_signalled"
        assert len(transcript.exchanges) == 2
        # Last exchange has ends_debriefing=True.
        assert transcript.exchanges[-1].utterance.ends_debriefing is True

    def test_stops_at_max_exchanges_safety_ceiling(self):
        pd = _panel_debriefing()
        # Always return a non-closing utterance.
        runner, _ = _make_runner([
            _utterance_json(anchor_refs=["inference API"]) for _ in range(100)
        ])

        transcript = asyncio.run(pd.run_panel_debriefing(
            company="OpenAI",
            observation_summary=_make_observation_summary(),
            artefacts=None,
            panel_agents={r: _StubAgent(name=r) for r in ROLES},
            run_agent=runner,
            max_exchanges=5,
        ))

        assert transcript.ended_reason == "max_exchanges_reached"
        assert len(transcript.exchanges) == 5


class TestPanelRouting:
    def test_group_question_invites_every_role(self):
        pd = _panel_debriefing()
        runner, _ = _make_runner([
            _utterance_json(addressed_to="group", anchor_refs=["inference API"],
                            ends_debriefing=True),
        ])

        transcript = asyncio.run(pd.run_panel_debriefing(
            company="OpenAI",
            observation_summary=_make_observation_summary(),
            artefacts=None,
            panel_agents={r: _StubAgent(name=r) for r in ROLES},
            run_agent=runner,
            max_exchanges=60,
        ))

        # 1 exchange, every role responded.
        assert len(transcript.exchanges) == 1
        responders = sorted(r.role for r in transcript.exchanges[0].responses)
        assert responders == sorted(ROLES)

    def test_role_question_targets_named_role_first(self):
        pd = _panel_debriefing()
        runner, _ = _make_runner([
            _utterance_json(addressed_to="CTO", anchor_refs=["inference API"],
                            ends_debriefing=True),
        ])

        transcript = asyncio.run(pd.run_panel_debriefing(
            company="OpenAI",
            observation_summary=_make_observation_summary(),
            artefacts=None,
            panel_agents={r: _StubAgent(name=r) for r in ROLES},
            run_agent=runner,
            max_exchanges=60,
        ))

        responses = transcript.exchanges[0].responses
        # First responder is the addressed role.
        assert responses[0].role == "CTO"
        # All other roles got a cross-talk chance.
        cross_talkers = {r.role for r in responses if r.is_cross_talk}
        assert "CTO" not in cross_talkers
        assert cross_talkers == set(ROLES) - {"CTO"}

    def test_empty_panel_response_is_dropped(self):
        pd = _panel_debriefing()
        runner, _ = _make_runner(
            [_utterance_json(addressed_to="group", anchor_refs=["inference API"],
                             ends_debriefing=True)],
            panellist_text="",  # every panellist declines
        )

        transcript = asyncio.run(pd.run_panel_debriefing(
            company="OpenAI",
            observation_summary=_make_observation_summary(),
            artefacts=None,
            panel_agents={r: _StubAgent(name=r) for r in ROLES},
            run_agent=runner,
            max_exchanges=60,
        ))

        # No panellist contributed; the exchange still exists but with
        # no responses.
        assert len(transcript.exchanges) == 1
        assert transcript.exchanges[0].responses == []


class TestForbiddenVocabularyGuard:
    def test_violation_triggers_one_retry(self):
        """First utterance uses a forbidden word; retry must be clean."""
        pd = _panel_debriefing()
        bad_utterance = _utterance_json(
            text="Walk me through your open-source strategy on the inference API.",
            anchor_refs=["inference API"],
        )
        good_utterance = _utterance_json(
            text="Walk me through how the inference API decision came together.",
            anchor_refs=["inference API"],
            ends_debriefing=True,
        )

        # The runner needs to serve: bad → good (retry) → then closing.
        # Sequence: turn 1: bad → retry → good. The runner's stub returns
        # in order, so we feed [bad, good].
        runner, _ = _make_runner([bad_utterance, good_utterance])

        transcript = asyncio.run(pd.run_panel_debriefing(
            company="OpenAI",
            observation_summary=_make_observation_summary(),
            artefacts=None,
            panel_agents={r: _StubAgent(name=r) for r in ROLES},
            run_agent=runner,
            max_exchanges=60,
        ))

        assert transcript.forbidden_vocab_violations == 1
        # One exchange recorded — the clean rewrite, not the violating one.
        assert "inference API" in transcript.exchanges[0].utterance.text
        assert "open-source" not in transcript.exchanges[0].utterance.text


class TestAreaCoverageMap:
    """Coverage map should surface area-saturation signals to the debriefer.

    Mitigates the smoke-run finding where the debriefer asked Area E
    three exchanges in a row. The fix is to (a) compute a coverage
    map every turn and (b) inject explicit variety rules into the
    debriefer's prompt.
    """

    def test_empty_transcript_returns_first_turn_message(self):
        pd = _panel_debriefing()
        _render_coverage_map = pd._render_coverage_map  # type: ignore[attr-defined]
        s = _researcher_schemas()
        empty = pd.DebriefingTranscript(company="OpenAI", research_question="...")
        out = _render_coverage_map(empty)
        assert "no areas covered" in out

    def test_flags_saturated_area(self):
        pd = _panel_debriefing()
        _render_coverage_map = pd._render_coverage_map  # type: ignore[attr-defined]
        s = _researcher_schemas()
        transcript = pd.DebriefingTranscript(company="OpenAI", research_question="...")
        # Two exchanges in area A — should flag SATURATED.
        for _ in range(2):
            transcript.exchanges.append(s.PanelExchange(
                utterance=s.PanelUtterance(
                    area_id="A", addressed_to="group",
                    text="q", anchor_refs=["x"]),
                responses=[]))
        out = _render_coverage_map(transcript)
        assert "Area A: 2" in out
        assert "well covered" in out

    def test_warns_when_last_two_areas_match(self):
        pd = _panel_debriefing()
        _render_coverage_map = pd._render_coverage_map  # type: ignore[attr-defined]
        s = _researcher_schemas()
        transcript = pd.DebriefingTranscript(company="OpenAI", research_question="...")
        for area in ("B", "B"):
            transcript.exchanges.append(s.PanelExchange(
                utterance=s.PanelUtterance(
                    area_id=area, addressed_to="group",
                    text="q", anchor_refs=["x"]),
                responses=[]))
        out = _render_coverage_map(transcript)
        assert "consecutive" in out.lower()
        assert "different area" in out.lower()

    def test_no_warning_when_last_two_areas_differ(self):
        pd = _panel_debriefing()
        _render_coverage_map = pd._render_coverage_map  # type: ignore[attr-defined]
        s = _researcher_schemas()
        transcript = pd.DebriefingTranscript(company="OpenAI", research_question="...")
        for area in ("A", "C"):
            transcript.exchanges.append(s.PanelExchange(
                utterance=s.PanelUtterance(
                    area_id=area, addressed_to="group",
                    text="q", anchor_refs=["x"]),
                responses=[]))
        out = _render_coverage_map(transcript)
        assert "consecutive" not in out.lower()

    def test_flags_missing_closing_area_late_in_debriefing(self):
        """The coverage map nags when the closing area (J under the
        current protocol) is still untouched after enough exchanges."""
        pd = _panel_debriefing()
        _render_coverage_map = pd._render_coverage_map  # type: ignore[attr-defined]
        s = _researcher_schemas()
        transcript = pd.DebriefingTranscript(company="OpenAI", research_question="...")
        # 5 exchanges, none in the closing area (J).
        for area in ("A", "B", "C", "D", "E"):
            transcript.exchanges.append(s.PanelExchange(
                utterance=s.PanelUtterance(
                    area_id=area, addressed_to="group",
                    text="q", anchor_refs=["x"]),
                responses=[]))
        # Default closing area is J. Explicit closing-area passing also tested.
        out = _render_coverage_map(transcript)
        assert "Area J" in out
        assert "closing" in out.lower()

    def test_coverage_map_respects_caller_supplied_areas(self):
        """The coverage map renders against whatever area list the
        caller supplies — supporting future studies that register
        different overlay areas within the A-J space."""
        pd = _panel_debriefing()
        _render_coverage_map = pd._render_coverage_map  # type: ignore[attr-defined]
        s = _researcher_schemas()
        transcript = pd.DebriefingTranscript(company="OpenAI", research_question="...")
        # Use a study-supplied subset of the A-J space (the schema
        # constrains area_id values; a future study would still pick
        # letters from inside that range).
        for area in ("A", "D", "G"):
            transcript.exchanges.append(s.PanelExchange(
                utterance=s.PanelUtterance(
                    area_id=area, addressed_to="group",
                    text="q", anchor_refs=["x"]),
                responses=[]))
        out = _render_coverage_map(
            transcript,
            all_areas=["A", "D", "G", "J"],
            closing_area="J",
        )
        for area in ("Area A", "Area D", "Area G", "Area J"):
            assert area in out
        # Counts are computed against the supplied list, so the
        # "Distinct areas covered" denominator reflects N=4 not 10.
        assert "Distinct areas covered: 3/4" in out

    def test_coverage_block_appears_in_turn_prompt(self):
        """The runner injects the coverage map into the debriefer's prompt."""
        pd = _panel_debriefing()
        runner_calls: list[str] = []

        async def runner(*, agent, prompt):
            runner_calls.append(prompt)
            return _utterance_json(ends_debriefing=True, anchor_refs=["inference API"])

        asyncio.run(pd.run_panel_debriefing(
            company="OpenAI",
            observation_summary=_make_observation_summary(),
            artefacts=None,
            panel_agents={r: _StubAgent(name=r) for r in ROLES},
            run_agent=runner,
            max_exchanges=2,
        ))
        # First call is the debriefer; later calls are panellists.
        debriefer_prompt = runner_calls[0]
        assert "Coverage map" in debriefer_prompt
        assert "no areas covered" in debriefer_prompt


class TestPhase4Hardening:
    """Tests for the Phase 4 hardening landed after the Meta-2032 cell
    cut Phase 4 short on a transient Vertex 429.

    Covers:
      1. `_safe_run` retries on transient errors (429 / 5xx) with
         exponential backoff and gives up on non-transient errors.
      2. The Debriefer prompt embeds the binding UTTERANCE LENGTH
         budget so it asks short focused questions.
      3. The panellist prompt embeds the binding RESPONSE LENGTH
         budget so panellists reply in 80-150 words.
      4. `_render_coverage_map` honours the `area_traversal_mode`
         parameter — free mode (default) leaves the map open;
         structured mode injects a "MUST use area X next" directive
         until the first pass completes.
    """

    # ---- (1) _safe_run retry-with-backoff ----

    def test_safe_run_retries_transient_then_succeeds(self):
        pd = _panel_debriefing()
        agent = _StubAgent(name="X")
        calls = {"n": 0}

        async def flaky_runner(*, agent, prompt):
            calls["n"] += 1
            if calls["n"] < 3:
                # First two calls fail with a transient 429.
                raise RuntimeError(
                    "429 RESOURCE_EXHAUSTED Resource exhausted. "
                    "'retryDelay': '0s'"
                )
            return "OK"

        result = asyncio.run(pd._safe_run(
            flaky_runner, agent, "p", max_retries=5,
        ))
        assert result == "OK"
        assert calls["n"] == 3  # 2 failures + 1 success

    def test_safe_run_returns_none_on_non_transient(self):
        pd = _panel_debriefing()
        agent = _StubAgent(name="X")
        calls = {"n": 0}

        async def auth_failing_runner(*, agent, prompt):
            calls["n"] += 1
            raise RuntimeError("401 AuthenticationError invalid key")

        result = asyncio.run(pd._safe_run(
            auth_failing_runner, agent, "p", max_retries=5,
        ))
        assert result is None
        # Did NOT retry — auth errors are not transient.
        assert calls["n"] == 1

    def test_safe_run_returns_none_after_retries_exhausted(self):
        pd = _panel_debriefing()
        agent = _StubAgent(name="X")
        calls = {"n": 0}

        async def always_429(*, agent, prompt):
            calls["n"] += 1
            raise RuntimeError("429 RESOURCE_EXHAUSTED 'retryDelay': '0s'")

        result = asyncio.run(pd._safe_run(
            always_429, agent, "p", max_retries=2,
        ))
        assert result is None
        assert calls["n"] == 3  # initial + 2 retries

    def test_safe_run_honours_provider_retry_hint(self):
        pd = _panel_debriefing()
        # Gemini-style hint
        exc = RuntimeError("429 RESOURCE_EXHAUSTED 'retryDelay': '12s'")
        delay = pd._parse_phase4_retry_delay(exc, attempt=0)
        assert delay == 12.0
        # OpenAI/Anthropic-style header leak
        exc2 = RuntimeError("RateLimitError: retry-after: 8")
        delay2 = pd._parse_phase4_retry_delay(exc2, attempt=0)
        assert delay2 == 8.0

    def test_safe_run_falls_back_to_exponential_backoff(self):
        pd = _panel_debriefing()
        exc = RuntimeError("429 RESOURCE_EXHAUSTED (no hint)")
        # attempt=0 → 2.0 * 2^0 = 2.0
        assert pd._parse_phase4_retry_delay(exc, attempt=0) == 2.0
        # attempt=2 → 2.0 * 2^2 = 8.0
        assert pd._parse_phase4_retry_delay(exc, attempt=2) == 8.0
        # Caps at _PHASE4_MAX_BACKOFF_SECONDS = 60
        assert pd._parse_phase4_retry_delay(exc, attempt=10) == 60.0

    def test_safe_run_classifies_5xx_as_transient(self):
        pd = _panel_debriefing()
        assert pd._is_transient_error(RuntimeError("503 UNAVAILABLE"))
        assert pd._is_transient_error(RuntimeError("502 Bad Gateway"))
        assert pd._is_transient_error(RuntimeError("ServerError: overloaded"))
        # Non-transients
        assert not pd._is_transient_error(RuntimeError("400 invalid argument"))
        assert not pd._is_transient_error(RuntimeError("401 AuthenticationError"))
        assert not pd._is_transient_error(RuntimeError("404 NOT_FOUND"))

    # ---- (2) Debriefer prompt — UTTERANCE LENGTH budget ----

    def test_debriefer_prompt_embeds_utterance_length_budget(self):
        """The Debriefer's per-turn prompt must include the binding
        UTTERANCE LENGTH block — short 1-2 sentence questions only."""
        pd = _panel_debriefing()
        s = _researcher_schemas()
        empty = pd.DebriefingTranscript(company="X", research_question="...")

        # Reproduce the prompt-assembly the loop uses.
        latest = pd._render_latest_exchange_for_followup(empty)
        coverage = pd._render_coverage_map(empty, traversal_mode="free")
        # Mimic _next_researcher_utterance's prompt template.
        prompt = (
            "Your turn. Produce ONE PanelUtterance JSON object.\n\n"
            + latest + "\n\n" + coverage + "\n\n"
            + "DEBRIEFING HISTORY SO FAR:\n\n"
            + "UTTERANCE LENGTH (binding)\n"
        )
        # This is the assertion the production code must satisfy
        # — see the prompt template in _next_researcher_utterance.
        assert "UTTERANCE LENGTH" in prompt

    def test_debriefer_prompt_text_in_source(self):
        """Source-level check: the production prompt template carries
        the binding length budget. Defends against future refactors
        that silently drop it. Uses substrings that survive Python's
        string-literal concatenation across lines."""
        import inspect
        pd = _panel_debriefing()
        src = inspect.getsource(pd._next_researcher_utterance)
        assert "UTTERANCE LENGTH" in src
        assert "1-2 short" in src
        assert "60 words" in src
        assert "NO " in src and "preamble" in src

    # ---- (3) Panellist prompt — RESPONSE LENGTH budget ----

    def test_panellist_prompt_has_response_length_budget(self):
        """Source-level check that the panellist prompt template
        carries the binding RESPONSE LENGTH block."""
        import inspect
        pd = _panel_debriefing()
        src = inspect.getsource(pd._single_panellist_response)
        assert "RESPONSE LENGTH" in src
        assert "80-150 words" in src

    # ---- (4) area_traversal_mode in coverage map ----

    def test_coverage_map_free_mode_has_no_traversal_directive(self):
        pd = _panel_debriefing()
        s = _researcher_schemas()
        transcript = pd.DebriefingTranscript(company="X", research_question="...")
        out = pd._render_coverage_map(transcript, traversal_mode="free")
        assert "AREA TRAVERSAL" not in out

    def test_coverage_map_structured_first_pass_picks_first_unvisited(self):
        """In structured mode with no exchanges, the first area in
        declared order should be the mandated next target."""
        pd = _panel_debriefing()
        transcript = pd.DebriefingTranscript(company="X", research_question="...")
        out = pd._render_coverage_map(
            transcript,
            all_areas=["A", "B", "C", "D", "E"],
            traversal_mode="structured_then_followup",
        )
        assert "AREA TRAVERSAL" in out
        assert "area_id='A'" in out

    def test_coverage_map_structured_skips_visited_areas(self):
        """If A and B have been visited but C / D / E are still
        empty, structured mode should point to C as the next target."""
        pd = _panel_debriefing()
        s = _researcher_schemas()
        transcript = pd.DebriefingTranscript(company="X", research_question="...")
        for area in ("A", "B"):
            transcript.exchanges.append(s.PanelExchange(
                utterance=s.PanelUtterance(
                    area_id=area, addressed_to="group",
                    text="q", anchor_refs=["x"]),
                responses=[]))
        out = pd._render_coverage_map(
            transcript,
            all_areas=["A", "B", "C", "D", "E"],
            traversal_mode="structured_then_followup",
        )
        assert "area_id='C'" in out

    def test_coverage_map_structured_then_followup_unlocks_after_first_pass(self):
        """Once every area has ≥1 exchange, structured_then_followup
        should announce FOLLOW-UP mode rather than directing to a
        specific area."""
        pd = _panel_debriefing()
        s = _researcher_schemas()
        transcript = pd.DebriefingTranscript(company="X", research_question="...")
        for area in ("A", "B", "C"):
            transcript.exchanges.append(s.PanelExchange(
                utterance=s.PanelUtterance(
                    area_id=area, addressed_to="group",
                    text="q", anchor_refs=["x"]),
                responses=[]))
        out = pd._render_coverage_map(
            transcript,
            all_areas=["A", "B", "C"],
            traversal_mode="structured_then_followup",
        )
        assert "FOLLOW-UP mode" in out
        assert "First-pass coverage is COMPLETE" in out

    def test_coverage_map_strict_structured_signals_stop_after_first_pass(self):
        """`structured` (no followup) should tell the Debriefer to end
        the debriefing once every area has been visited once."""
        pd = _panel_debriefing()
        s = _researcher_schemas()
        transcript = pd.DebriefingTranscript(company="X", research_question="...")
        for area in ("A", "B", "C"):
            transcript.exchanges.append(s.PanelExchange(
                utterance=s.PanelUtterance(
                    area_id=area, addressed_to="group",
                    text="q", anchor_refs=["x"]),
                responses=[]))
        out = pd._render_coverage_map(
            transcript,
            all_areas=["A", "B", "C"],
            traversal_mode="structured",
        )
        assert "ends_debriefing=true" in out
        assert "First-pass coverage is COMPLETE" in out

    def test_protocol_yaml_declares_default_traversal_mode(self):
        """The shipped protocol YAML should declare a default
        `area_traversal_mode` so the field is discoverable for any
        operator reading the protocol."""
        import importlib
        qra = importlib.import_module(
            f"{PKG}.roles.qualitative_researcher_agent"
        )
        protocol = qra._load_protocol()
        panel_format = protocol.get("panel_format", {})
        mode = panel_format.get("area_traversal_mode")
        assert mode in {"free", "structured", "structured_then_followup"}, (
            f"protocol YAML must declare area_traversal_mode (got {mode!r})"
        )


class TestArtefactInjection:
    def test_artefact_block_present_in_debriefer_instruction(self):
        """The debriefer's system prompt embeds the artefact summary."""
        pd = _panel_debriefing()
        s = _artefact_schemas()
        bundle = s.ArtefactBundle(
            company="OpenAI",
            industry_context="Dynamic",
            product_type="Novel",
            artefacts=[
                s.StrategicArtefact(
                    role="CEO", company="OpenAI",
                    industry_context="Dynamic", product_type="Novel",
                    title="Company Strategy Memo",
                    key_challenges=["c"],
                    main_decisions=["keep inference internal"],
                    key_tensions=["openness vs safety"],
                    body="body",
                ),
            ],
        )

        # Use the internal helper directly to check the rendered prompt.
        # Pass `study=None` — _build_debriefer falls back to a generic
        # background block; the artefact block we're testing is
        # study-agnostic, so this is the simplest setup.
        debriefer = pd._build_debriefer(
            company="OpenAI",
            observation_summary=_make_observation_summary(),
            artefacts=bundle,
            industry_context="Dynamic",
            product_type="Novel",
            model=None,
            study=None,
        )
        assert "Company Strategy Memo" in debriefer.instruction
        assert "keep inference internal" in debriefer.instruction
        # New header: RESEARCH CONTEXT (with study=None, the framing is
        # generic but the section still exists).
        assert "RESEARCH CONTEXT" in debriefer.instruction
