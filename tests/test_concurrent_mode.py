"""Stubbed tests for orchestrator.concurrent_mode.

Verifies the concurrent runner without spinning up real LLM calls.
The stub runner returns scripted AgentAction JSON based on (role,
action_count) so we can assert specific behaviours:

  - SharedState mutations are concurrent-safe.
  - SPEAK appends to the shared transcript.
  - ASK delivers a DirectedMessage to the addressee's inbox AND
    echoes publicly.
  - ANSWER routes the answer to the asker's inbox and (if public)
    echoes to the transcript.
  - SCRATCHPAD writes to the role's private notes only.
  - DRAFT updates the role's working draft only.
  - DONE marks the role complete; the loop exits cleanly.
  - Per-role action cap is enforced.
  - Wall-clock cap cancels still-running role tasks.
  - Stale questions get [NO ANSWER] markers injected so askers
    move on.
  - The DiscussionMode.CONCURRENT dispatcher path produces a
    DeliberationOutcome with the right shape and stashes the
    SharedState for the researcher.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from dataclasses import dataclass

import pytest

PKG = "open-innovation-strategy"


def _concurrent():
    return importlib.import_module(f"{PKG}.orchestrator.concurrent_mode")


def _deliberation():
    return importlib.import_module(f"{PKG}.orchestrator.deliberation")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ROLES = ("CEO", "CTO", "COO", "CMO", "Product_Strategist", "Product_Designer")


@dataclass
class _StubAgent:
    name: str
    instruction: str = ""
    model: str = "stub-model"


def _role_agents() -> dict:
    return {r: _StubAgent(name=r) for r in ROLES}


def _doc_framing() -> dict:
    return {r: f"Doc for {r}" for r in ROLES}


def _normalise_role_name(agent_name: str) -> str:
    """Strip the `_Concurrent` / `_Artefact` suffix added by wrapper
    factories so tests can match by base role name."""
    for suffix in ("_Concurrent", "_Artefact"):
        if agent_name.endswith(suffix):
            return agent_name[: -len(suffix)]
    return agent_name


def _scripted_runner(script: dict):
    """Build a runner that returns the next action for each role.

    `script` is a dict `{role: [action_json_or_dict, ...]}`. On each
    call we pop the next item for that role (matching by base role
    name — wrapper suffixes are stripped). If the script runs out
    we default to DONE so the loop terminates.
    """
    counters = {role: 0 for role in script}

    async def runner(*, agent, prompt):
        role = _normalise_role_name(agent.name)
        seq = script.get(role, [])
        idx = counters.get(role, 0)
        if idx >= len(seq):
            return json.dumps({"kind": "DONE", "text": "ok"})
        counters[role] = idx + 1
        item = seq[idx]
        if isinstance(item, dict):
            return json.dumps(item)
        return item

    return runner


# ---------------------------------------------------------------------------
# 1. SharedState mutations
# ---------------------------------------------------------------------------

class TestParserTolerance:
    """The action parser must handle two LLM output quirks observed live:
    markdown code fences and {"action": {...}} wrapper nesting.
    """

    def test_strip_markdown_fences_with_lang_tag(self):
        c = _concurrent()
        inner = c._strip_markdown_fences(
            '```json\n{"kind": "DONE"}\n```'
        )
        assert inner == '{"kind": "DONE"}'

    def test_strip_markdown_fences_without_lang_tag(self):
        c = _concurrent()
        inner = c._strip_markdown_fences('```\n{"kind": "DONE"}\n```')
        assert inner == '{"kind": "DONE"}'

    def test_strip_markdown_fences_passthrough(self):
        c = _concurrent()
        # No fence → unchanged.
        assert c._strip_markdown_fences('{"kind": "DONE"}') == '{"kind": "DONE"}'

    def test_coerce_unwraps_action_nesting(self):
        c = _concurrent()
        action = c._coerce_action({"action": {"kind": "DONE", "text": "ok"}})
        assert action is not None
        assert action.kind == c.ActionKind.DONE
        assert action.text == "ok"

    def test_coerce_accepts_fenced_json_string(self):
        c = _concurrent()
        raw = '```json\n{"kind": "SCRATCHPAD", "text": "note"}\n```'
        action = c._coerce_action(raw)
        assert action is not None
        assert action.kind == c.ActionKind.SCRATCHPAD
        assert action.text == "note"

    def test_coerce_accepts_fenced_action_nesting_combo(self):
        c = _concurrent()
        raw = '```json\n{"action": {"kind": "DONE", "text": "done"}}\n```'
        action = c._coerce_action(raw)
        assert action is not None
        assert action.kind == c.ActionKind.DONE


class TestSharedState:
    def test_append_transcript_and_snapshot(self):
        c = _concurrent()
        async def go():
            ss = c.SharedState(roles=list(ROLES))
            await ss.append_transcript(
                c.TranscriptEntry(index=0, role="CEO", kind="speak", text="hi")
            )
            snap = await ss.snapshot_transcript()
            assert len(snap) == 1
            assert snap[0].role == "CEO"
            # Index auto-assigned.
            assert snap[0].index == 0
        asyncio.run(go())

    def test_push_inbox_tracks_asker(self):
        c = _concurrent()
        async def go():
            ss = c.SharedState(roles=list(ROLES))
            msg = c.DirectedMessage(
                id="q1", sender="CEO", recipient="CTO", kind="ASK",
                text="What's the tech risk?",
            )
            await ss.push_inbox(msg)
            cto_state = await ss.snapshot_role("CTO")
            assert len(cto_state.inbox) == 1
            assert cto_state.inbox[0].kind == "ASK"
            # asker_by_qid mapping populated by push monkeypatch.
            assert ss._asker_by_qid["q1"] == "CEO"  # type: ignore[attr-defined]
        asyncio.run(go())

    def test_pop_inbox_question_removes_it(self):
        c = _concurrent()
        async def go():
            ss = c.SharedState(roles=list(ROLES))
            await ss.push_inbox(c.DirectedMessage(
                id="q9", sender="CEO", recipient="CTO", kind="ASK", text="?"
            ))
            popped = await ss.pop_inbox_question("CTO", "q9")
            assert popped is not None
            cto_state = await ss.snapshot_role("CTO")
            assert cto_state.inbox == []
        asyncio.run(go())

    def test_age_inboxes_and_stale_detection(self):
        c = _concurrent()
        async def go():
            ss = c.SharedState(roles=list(ROLES))
            await ss.push_inbox(c.DirectedMessage(
                id="qstale", sender="CEO", recipient="CTO", kind="ASK", text="?"
            ))
            # Age 3 times.
            for _ in range(3):
                await ss.age_inboxes("CTO")
            stale = await ss.stale_questions(threshold=3)
            assert len(stale) == 1
            asker, q = stale[0]
            assert asker == "CEO"
            assert q.id == "qstale"
        asyncio.run(go())


# ---------------------------------------------------------------------------
# 2. Single-role loop behaviour via _apply_action
# ---------------------------------------------------------------------------

class TestActionApplication:
    def test_speak_appends_transcript(self):
        c = _concurrent()
        async def go():
            ss = c.SharedState(roles=list(ROLES))
            action = c.AgentAction(kind=c.ActionKind.SPEAK, text="hello team")
            await c._apply_action(role="CEO", action=action, shared=ss)
            t = await ss.snapshot_transcript()
            assert t[0].text == "hello team"
            assert t[0].kind == "speak"
        asyncio.run(go())

    def test_ask_delivers_to_inbox_and_echoes_publicly(self):
        c = _concurrent()
        async def go():
            ss = c.SharedState(roles=list(ROLES))
            action = c.AgentAction(
                kind=c.ActionKind.ASK,
                ask_recipient="CTO",
                ask_question="What's the latency cost?",
            )
            await c._apply_action(role="CEO", action=action, shared=ss)
            cto_state = await ss.snapshot_role("CTO")
            assert len(cto_state.inbox) == 1
            assert cto_state.inbox[0].sender == "CEO"
            t = await ss.snapshot_transcript()
            assert len(t) == 1
            assert t[0].kind == "ask_public_echo"
            assert t[0].addressed_to == "CTO"
        asyncio.run(go())

    def test_answer_routes_to_asker_and_echoes_public_by_default(self):
        c = _concurrent()
        async def go():
            ss = c.SharedState(roles=list(ROLES))
            # CEO asks first.
            await c._apply_action(
                role="CEO",
                action=c.AgentAction(
                    kind=c.ActionKind.ASK,
                    ask_recipient="CTO",
                    ask_question="latency?",
                ),
                shared=ss,
            )
            cto_inbox = (await ss.snapshot_role("CTO")).inbox
            qid = cto_inbox[0].id
            # CTO answers.
            await c._apply_action(
                role="CTO",
                action=c.AgentAction(
                    kind=c.ActionKind.ANSWER,
                    answer_to_question_id=qid,
                    text="under 200ms p50",
                ),
                shared=ss,
            )
            # CEO inbox now contains the answer.
            ceo_inbox = (await ss.snapshot_role("CEO")).inbox
            assert len(ceo_inbox) == 1
            assert ceo_inbox[0].kind == "ANSWER"
            assert ceo_inbox[0].text == "under 200ms p50"
            # And public transcript has both ASK echo + ANSWER echo.
            t = await ss.snapshot_transcript()
            kinds = [e.kind for e in t]
            assert "ask_public_echo" in kinds
            assert "answer_public" in kinds
        asyncio.run(go())

    def test_answer_private_does_not_echo_publicly(self):
        c = _concurrent()
        async def go():
            ss = c.SharedState(roles=list(ROLES))
            await c._apply_action(
                role="CEO",
                action=c.AgentAction(
                    kind=c.ActionKind.ASK, ask_recipient="CTO", ask_question="?"
                ),
                shared=ss,
            )
            qid = (await ss.snapshot_role("CTO")).inbox[0].id
            await c._apply_action(
                role="CTO",
                action=c.AgentAction(
                    kind=c.ActionKind.ANSWER,
                    answer_to_question_id=qid,
                    text="confidential answer",
                    answer_visibility="private",
                ),
                shared=ss,
            )
            t = await ss.snapshot_transcript()
            # No answer_public entries — only the original ask echo.
            answer_kinds = [e for e in t if e.kind == "answer_public"]
            assert answer_kinds == []
            # But CEO has it privately.
            ceo_inbox = (await ss.snapshot_role("CEO")).inbox
            assert any(m.text == "confidential answer" for m in ceo_inbox)
        asyncio.run(go())

    def test_scratchpad_isolated_per_role(self):
        c = _concurrent()
        async def go():
            ss = c.SharedState(roles=list(ROLES))
            await c._apply_action(
                role="CEO",
                action=c.AgentAction(
                    kind=c.ActionKind.SCRATCHPAD, text="CTO seems cautious"
                ),
                shared=ss,
            )
            ceo_notes = (await ss.snapshot_role("CEO")).scratchpad
            cto_notes = (await ss.snapshot_role("CTO")).scratchpad
            assert ceo_notes == ["CTO seems cautious"]
            assert cto_notes == []

            # And nothing in the public transcript.
            t = await ss.snapshot_transcript()
            assert t == []
        asyncio.run(go())

    def test_draft_replaces_existing_draft(self):
        c = _concurrent()
        async def go():
            ss = c.SharedState(roles=list(ROLES))
            await c._apply_action(
                role="CEO",
                action=c.AgentAction(kind=c.ActionKind.DRAFT, text="v1"),
                shared=ss,
            )
            await c._apply_action(
                role="CEO",
                action=c.AgentAction(kind=c.ActionKind.DRAFT, text="v2 polished"),
                shared=ss,
            )
            ceo = await ss.snapshot_role("CEO")
            assert ceo.draft == "v2 polished"
        asyncio.run(go())

    def test_done_marks_role_complete(self):
        c = _concurrent()
        async def go():
            ss = c.SharedState(roles=list(ROLES))
            await c._apply_action(
                role="CEO",
                action=c.AgentAction(kind=c.ActionKind.DONE, text="closing thought"),
                shared=ss,
            )
            ceo = await ss.snapshot_role("CEO")
            assert ceo.done is True
            assert ceo.finished_reason == "agent_declared_done"
        asyncio.run(go())


# ---------------------------------------------------------------------------
# 3. End-to-end run_concurrent_mode
# ---------------------------------------------------------------------------

class TestRunConcurrent:
    def test_all_roles_done_terminates_cleanly(self):
        """Every role's first action is DONE → deliberation ends fast."""
        c = _concurrent()
        script = {role: [{"kind": "DONE", "text": "ok"}] for role in ROLES}

        async def go():
            shared, log_obj, ended = await c.run_concurrent_mode(
                role_agents=_role_agents(),
                company="OpenAI",
                industry_context="Dynamic",
                product_type="Novel",
                product_description="X",
                strategic_question="Y",
                role_doc_framing=_doc_framing(),
                config=c.ConcurrentConfig(
                    max_actions_per_role=5,
                    max_wall_clock_seconds=10,
                    poll_interval_seconds=0.05,
                ),
                run_agent=_scripted_runner(script),
            )
            return shared, log_obj, ended

        shared, log_obj, ended = asyncio.run(go())
        assert ended == "all_done"
        # Every role marked done.
        states = asyncio.run(shared.snapshot_all_role_states())
        for role in ROLES:
            assert states[role].done is True
        # Transcript has one closing-text entry per role (from DONE.text).
        # All 6 'ok' lines should appear.
        assert len(log_obj.events) == 6

    def test_per_role_action_cap_enforced(self):
        """A role that never says DONE hits the cap and stops."""
        c = _concurrent()
        # Every role: keeps emitting SCRATCHPAD notes; never DONE.
        script = {
            role: [{"kind": "SCRATCHPAD", "text": f"note-{i}"} for i in range(20)]
            for role in ROLES
        }

        async def go():
            return await c.run_concurrent_mode(
                role_agents=_role_agents(),
                company="OpenAI",
                industry_context="Dynamic",
                product_type="Novel",
                product_description="X",
                strategic_question="Y",
                role_doc_framing=_doc_framing(),
                config=c.ConcurrentConfig(
                    max_actions_per_role=3,
                    max_wall_clock_seconds=20,
                    poll_interval_seconds=0.05,
                ),
                run_agent=_scripted_runner(script),
            )

        shared, _, ended = asyncio.run(go())
        assert ended == "all_done"  # all roles hit cap → marked done
        states = asyncio.run(shared.snapshot_all_role_states())
        for role in ROLES:
            assert states[role].action_count == 3
            assert states[role].finished_reason == "action_cap_reached"
            # 3 scratchpad notes recorded for each role.
            assert len(states[role].scratchpad) == 3

    def test_ask_answer_roundtrip(self):
        """CEO asks CTO → CTO answers → CEO sees answer in inbox before DONE."""
        c = _concurrent()
        script = {
            "CEO": [
                {"kind": "ASK", "ask_recipient": "CTO",
                 "ask_question": "tech risk?"},
                {"kind": "SCRATCHPAD", "text": "waiting on CTO"},
                {"kind": "SCRATCHPAD", "text": "still waiting"},
                {"kind": "DONE", "text": "CEO done"},
            ],
            "CTO": [
                # CTO needs to find the question in inbox, but the test
                # stub doesn't have access to the question id — we
                # use a sentinel and have the test runner intercept.
                {"kind": "SCRATCHPAD", "text": "thinking about latency"},
                # Then answer.
                # The runner will need to look up the question id;
                # easiest: write a custom runner below.
                {"kind": "DONE", "text": "CTO done"},
            ],
        }
        # The other roles immediately DONE.
        for role in ROLES:
            if role not in script:
                script[role] = [{"kind": "DONE", "text": "ok"}]

        async def custom_runner_factory():
            counters = {r: 0 for r in script}
            recorded_qid = {"qid": None}

            async def runner(*, agent, prompt):
                role = _normalise_role_name(agent.name)
                # Special handling: CTO's second action looks up the
                # ASK in its inbox and answers it.
                if role == "CTO" and counters[role] == 1:
                    # Parse inbox from the prompt (lazy approach: the
                    # AgentAction needs a real question id).
                    import re
                    m = re.search(r"ASK id=([a-f0-9-]+)", prompt)
                    qid = m.group(1) if m else "missing"
                    recorded_qid["qid"] = qid
                    counters[role] += 1
                    return json.dumps({
                        "kind": "ANSWER",
                        "answer_to_question_id": qid,
                        "text": "low — under 200ms",
                    })
                seq = script[role]
                idx = counters[role]
                if idx >= len(seq):
                    return json.dumps({"kind": "DONE", "text": "ok"})
                counters[role] += 1
                return json.dumps(seq[idx])

            return runner

        async def go():
            runner = await custom_runner_factory()
            return await c.run_concurrent_mode(
                role_agents=_role_agents(),
                company="OpenAI",
                industry_context="Dynamic",
                product_type="Novel",
                product_description="X",
                strategic_question="Y",
                role_doc_framing=_doc_framing(),
                config=c.ConcurrentConfig(
                    max_actions_per_role=10,
                    max_wall_clock_seconds=15,
                    poll_interval_seconds=0.05,
                    stale_question_threshold=99,  # don't inject NO ANSWER
                ),
                run_agent=runner,
            )

        shared, log_obj, ended = asyncio.run(go())
        assert ended == "all_done"
        # CEO inbox should have received the answer.
        ceo = asyncio.run(shared.snapshot_role("CEO"))
        answers = [m for m in ceo.inbox if m.kind == "ANSWER"]
        assert len(answers) == 1
        assert answers[0].text == "low — under 200ms"
        assert answers[0].sender == "CTO"

    def test_stale_question_gets_no_answer_marker(self):
        """If CTO never answers, the [NO ANSWER] marker unblocks CEO.

        The monitor injects NO ANSWER markers in two cases:
          (a) age_actions ≥ threshold (addressee has acted enough
              times without answering), OR
          (b) the addressee has gone DONE with the ASK still in inbox.

        In this test CTO goes DONE immediately → case (b) fires. We use
        a fast poll_interval and slow CEO down with an artificial
        delay between actions so the monitor runs between CEO's
        actions in stub-time.
        """
        c = _concurrent()

        # CEO asks once, then keeps scratchpadding (slow-paced so the
        # monitor can interleave), then DONE.
        script = {
            "CEO": (
                [{"kind": "ASK", "ask_recipient": "CTO",
                  "ask_question": "tech risk?"}]
                + [{"kind": "SCRATCHPAD", "text": f"waiting-{i}"}
                   for i in range(6)]
                + [{"kind": "DONE", "text": "done"}]
            ),
        }
        for role in ROLES:
            if role not in script:
                script[role] = [{"kind": "DONE", "text": "ok"}]

        base_runner = _scripted_runner(script)

        async def slow_runner(*, agent, prompt):
            # 10ms latency per call simulates real LLM round-trip
            # so the monitor (poll interval 5ms) can fire between
            # CEO actions.
            await asyncio.sleep(0.01)
            return await base_runner(agent=agent, prompt=prompt)

        async def go():
            return await c.run_concurrent_mode(
                role_agents=_role_agents(),
                company="OpenAI",
                industry_context="Dynamic",
                product_type="Novel",
                product_description="X",
                strategic_question="Y",
                role_doc_framing=_doc_framing(),
                config=c.ConcurrentConfig(
                    max_actions_per_role=15,
                    max_wall_clock_seconds=15,
                    poll_interval_seconds=0.005,
                    stale_question_threshold=99,  # rely on case (b)
                ),
                run_agent=slow_runner,
            )

        shared, _, ended = asyncio.run(go())
        assert ended == "all_done"
        ceo = asyncio.run(shared.snapshot_role("CEO"))
        no_answer_markers = [
            m for m in ceo.inbox
            if m.kind == "ANSWER" and m.sender == "system"
            and "[NO ANSWER" in m.text
        ]
        assert len(no_answer_markers) == 1


# ---------------------------------------------------------------------------
# 4. Dispatcher path: DiscussionMode.CONCURRENT works through deliberation.run_deliberation
# ---------------------------------------------------------------------------

class TestDispatcher:
    def test_concurrent_mode_via_run_deliberation_returns_outcome_with_shared_state(self):
        c = _concurrent()
        d = _deliberation()

        async def go():
            return await d.run_deliberation(
                role_agents=_role_agents(),
                company="OpenAI",
                industry_context="Dynamic",
                product_type="Novel",
                product_description="X",
                strategic_question="Y",
                config=d.DeliberationConfig(
                    discussion_mode=d.DiscussionMode.CONCURRENT,
                    concurrent=c.ConcurrentConfig(
                        max_actions_per_role=2,
                        max_wall_clock_seconds=10,
                        poll_interval_seconds=0.05,
                    ),
                ),
                run_agent=_scripted_runner(
                    {role: [{"kind": "DRAFT", "text": f"{role} draft v1"},
                            {"kind": "DONE", "text": "done"}]
                     for role in ROLES}
                ),
            )

        outcome = asyncio.run(go())
        assert outcome.discussion_mode == d.DiscussionMode.CONCURRENT
        assert outcome.ended_reason in {"all_done", "wall_clock_cap"}
        # SharedState is stashed on the outcome.
        shared = outcome.__dict__.get("_concurrent_shared_state")
        assert shared is not None
        states = asyncio.run(shared.snapshot_all_role_states())
        # Each role produced a draft.
        for role in ROLES:
            assert "draft v1" in states[role].draft


def test_a_role_whose_calls_keep_failing_stops_and_is_recorded():
    """A missing key or retired model fails at once; it must not spin to the wall clock."""
    cm = _concurrent()
    shared = cm.SharedState(["CEO"])
    config = cm.ConcurrentConfig(max_consecutive_llm_failures=3, llm_failure_backoff_seconds=0)
    task = cm.RoleTaskSpec(
        role="CEO", company="X", industry_context="Dynamic", product_type="Novel",
        strategic_question="What next?", doc_framing="memo",
    )
    calls = []

    async def failing(*, agent, prompt):
        calls.append(prompt)
        raise RuntimeError("404 not found")

    asyncio.run(cm._role_loop(
        role="CEO", agent=object(), task=task, shared=shared, config=config, run_agent=failing,
    ))
    state = shared.role_states["CEO"]
    assert len(calls) == 3
    assert state.finished_reason == cm.LLM_FAILURES_REASON
    assert state.scratchpad == []
    assert shared.llm_failures == ["CEO: 404 not found"] * 3
