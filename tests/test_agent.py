import httpx
import pytest

from jev_ra import config
from jev_ra.agent import Agent
from jev_ra.browser.session import StalePage
from jev_ra.decide import DecisionClient, JevBadResponse, Reply
from jev_ra.errors import Escalated

FORM_ACTIONS = [
    {"id": "e1", "node": 1, "role": "textbox", "kind": "fill", "label": "City", "value": ""},
    {"id": "e1", "node": 1, "role": "textbox", "kind": "click", "label": "Open City", "value": ""},
    {"id": "e2", "node": 2, "role": "button", "kind": "click", "label": "Search flights"},
    {"id": "wait", "kind": "wait", "label": "Wait for the page to update"},
]

FORM_ELEMENTS = [
    {"ref": "e1", "node": 1, "role": "textbox", "label": "City", "value": "", "rect": {}},
    {"ref": "e2", "node": 2, "role": "button", "label": "Search flights", "rect": {}},
]


SCROLL_DOWN = {"id": "scroll_down", "kind": "scroll", "label": "Scroll down", "delta": 560}


def scrollable(count=60):
    """Pages that always have more below the fold, the way a long listing does."""
    pages = []
    for index in range(count):
        one = page(index)
        pages.append({**one, "actions": [*FORM_ACTIONS, SCROLL_DOWN]})
    return pages


def page(marker, url="http://127.0.0.1/form.html", title="Booking form", text="Booking form"):
    return {
        "url": url,
        "title": title,
        "text": text,
        "elements": FORM_ELEMENTS,
        "actions": FORM_ACTIONS,
        "marker": marker,
        "page_key": [0, url, 0, 0, 1280, 900, [[1, "", None, None, False, False]]],
        "guards": {},
        "omitted": 0,
    }


class FakeSession:
    """Replays a list of pages; every act() advances to the next one unless told to go stale."""

    def __init__(self, pages=None, stale=0, max_elements=250, profile=None):
        self.pages = list(pages or [page(n) for n in range(60)])
        self.index = 0
        self.stale = stale
        self.max_elements = max_elements
        self.profile = profile
        self.acted = []
        self.closed = False
        self.target_id = "fake-target"
        self.cdp_url = "http://127.0.0.1:9222"
        self.chrome_source = "BU_CDP_URL"

    def open(self, url):
        return self.observe()

    def observe(self, timer=None):
        return self.pages[min(self.index, len(self.pages) - 1)]

    def act(self, action, page, text=None, timer=None):
        if self.stale > 0:
            self.stale -= 1
            raise StalePage("Page changed since this decision. Observe again.")
        self.acted.append((action["id"], action["kind"], text))
        self.index = min(self.index + 1, len(self.pages) - 1)
        return {"executed": action["id"]}

    def close(self):
        self.closed = True


def answer(choice, probabilities=None, confidence=0.9):
    probabilities = probabilities or {choice: 1.0}
    return {"choice": choice, "confidence": confidence, "probabilities": probabilities}


def decider(script, latency_ms=300, cost=0.0002):
    """Yields one scripted answer set per request; the last one repeats."""
    steps = list(script)
    seen = []

    def decide(state, questions):
        answers = dict(steps[min(len(seen), len(steps) - 1)])
        seen.append((state, questions))
        for name in list(answers):
            if name not in questions:
                del answers[name]
        return Reply(answers=answers, latency_ms=latency_ms, usage={"cost": cost})

    decide.seen = seen
    return decide


def agent_with(decide, session=None, env=None):
    return Agent(session=session or FakeSession(), config=config.load(env or {}), decide=decide)


CLICK_SUBMIT = {"operation": answer("CLICK"), "click_target": answer("e2"), "goal_achieved": {"noul": 0.1}}
DONE = {"operation": answer("DONE"), "goal_achieved": {"noul": 0.9}}


def test_happy_path_acts_then_reports_done():
    agent = agent_with(decider([CLICK_SUBMIT, DONE]))
    result = agent.run("find flights")
    assert (result.status, result.reason) == ("done", "goal_achieved")
    assert agent.session.acted == [("e2", "click", None)]
    assert result.decisions == 2
    assert result.cost == pytest.approx(0.0004)
    assert result.elapsed_ms >= 0
    assert result.url == "http://127.0.0.1/form.html"
    assert result.title == "Booking form"
    assert result.final_page["elements"][0]["label"] == "City"
    assert result.text_calls == []


def test_step_records_carry_the_documented_fields():
    result = agent_with(decider([CLICK_SUBMIT, DONE])).run("find flights")
    step = result.steps[0]
    assert step["n"] == 1
    assert step["operation"] == "CLICK"
    assert step["target"] == "e2"
    assert step["target_label"] == "Search flights"
    assert step["probability"] == 1.0
    assert step["confidence"] == 0.9
    assert step["latency_ms"] == 300
    assert step["page_changed"] is True
    assert step["url"].endswith("/form.html")
    assert step["verified"]["text"] is False


def test_done_without_goal_achieved_waits_once_then_escalates():
    weak_done = {"operation": answer("DONE"), "goal_achieved": {"noul": 0.2}}
    agent = agent_with(decider([weak_done]))
    result = agent.run("find flights")
    assert (result.status, result.reason) == ("escalate", "unverified_done")
    assert result.decisions == 2
    assert agent.session.acted == [("wait", "wait", None)]
    assert [step["operation"] for step in result.steps] == ["WAIT"]


def test_an_unconfident_done_reads_the_page_a_beat_later():
    weak_done = {"operation": answer("DONE"), "goal_achieved": {"noul": 0.2}}
    agent = agent_with(decider([weak_done, DONE]))
    result = agent.run("find flights")
    assert (result.status, result.reason) == ("done", "goal_achieved")
    assert agent.session.acted == [("wait", "wait", None)]
    assert [step["operation"] for step in result.steps] == ["WAIT"]


def weak(score):
    return {"operation": answer("DONE"), "goal_achieved": {"noul": score}}


def test_a_weak_done_scrolls_to_look_for_the_proof_before_giving_up():
    agent = agent_with(decider([weak(0.2)]), session=FakeSession(scrollable()))
    result = agent.run("find flights")
    assert (result.status, result.reason) == ("escalate", "unverified_done")
    assert [action for action, _kind, _text in agent.session.acted] == ["scroll_down"]
    assert [step["operation"] for step in result.steps] == ["SCROLL_DOWN"]


def test_looking_goes_on_while_it_keeps_finding_more_of_the_answer():
    rising = [weak(0.2), weak(0.35), weak(0.5), DONE]
    agent = agent_with(decider(rising), session=FakeSession(scrollable()))
    result = agent.run("find flights")
    assert result.status == "done"
    assert [action for action, _kind, _text in agent.session.acted] == ["scroll_down"] * 3


def test_looking_stops_as_soon_as_it_stops_helping():
    falling = [weak(0.55), weak(0.49), weak(0.27)]
    agent = agent_with(decider(falling), session=FakeSession(scrollable()))
    result = agent.run("find flights")
    assert (result.status, result.reason) == ("escalate", "unverified_done")
    assert [action for action, _kind, _text in agent.session.acted] == ["scroll_down"]


def test_looking_is_bounded_even_when_every_look_helps_a_little():
    from jev_ra.agent import MAX_LOOKS

    creeping = [weak(0.1 + 0.05 * n) for n in range(4)] + [weak(0.3)] * 8
    agent = agent_with(decider(creeping), session=FakeSession(scrollable()))
    result = agent.run("find flights")
    assert (result.status, result.reason) == ("escalate", "unverified_done")
    assert len(agent.session.acted) == MAX_LOOKS


def test_the_proof_found_by_looking_finishes_the_run():
    weak_done = {"operation": answer("DONE"), "goal_achieved": {"noul": 0.2}}
    agent = agent_with(decider([weak_done, DONE]), session=FakeSession(scrollable()))
    result = agent.run("find flights")
    assert (result.status, result.reason) == ("done", "goal_achieved")
    assert [action for action, _kind, _text in agent.session.acted] == ["scroll_down"]


def test_a_weak_done_followed_by_a_real_one_still_finishes():
    weak_done = {"operation": answer("DONE"), "goal_achieved": {"noul": 0.2}}
    result = agent_with(decider([weak_done, CLICK_SUBMIT, DONE]), session=FakeSession(scrollable())).run("find flights")
    assert result.status == "done"


PANEL_ACTIONS = [
    *FORM_ACTIONS,
    {"id": "e3", "node": 3, "role": "textbox", "kind": "fill", "label": "Adults", "value": ""},
    {"id": "e4", "node": 4, "role": "button", "kind": "click", "label": "Confirm passengers"},
]

PANEL_ELEMENTS = [
    *FORM_ELEMENTS,
    {"ref": "e3", "node": 3, "role": "textbox", "label": "Adults", "value": "", "rect": {}},
    {"ref": "e4", "node": 4, "role": "button", "label": "Confirm passengers", "rect": {}},
]


def opening_pages():
    """A click on Search flights that opens a panel below it instead of navigating."""
    before = page(0)
    after = {**page(1), "elements": PANEL_ELEMENTS, "actions": PANEL_ACTIONS}
    return [before, after, after]


def test_the_panel_a_click_opened_leads_the_next_states_element_table():
    decide = decider([CLICK_SUBMIT, DONE])
    agent = agent_with(decide, session=FakeSession(opening_pages()))
    agent.run("add passengers")
    state = decide.seen[1][0]
    labels = [element["label"] for element in state["elements"]]
    assert labels[:2] == ["Adults", "Confirm passengers"]
    opener = next(element for element in state["elements"] if element["label"] == "Search flights")
    assert opener["expanded"] == "true"


def test_a_click_that_navigated_opened_no_panel():
    moved = {**page(1), "url": "http://127.0.0.1/results.html", "elements": PANEL_ELEMENTS, "actions": PANEL_ACTIONS}
    decide = decider([CLICK_SUBMIT, DONE])
    agent = agent_with(decide, session=FakeSession([page(0), moved, moved]))
    agent.run("add passengers")
    assert all("expanded" not in element for element in decide.seen[1][0]["elements"])


def test_a_click_that_added_nothing_opened_no_panel():
    decide = decider([CLICK_SUBMIT, DONE])
    agent = agent_with(decide, session=FakeSession([page(0), page(1), page(1)]))
    agent.run("add passengers")
    assert all("expanded" not in element for element in decide.seen[1][0]["elements"])


def test_a_scroll_never_claims_to_have_opened_anything():
    pages = scrollable()
    pages[1] = {**pages[1], "elements": PANEL_ELEMENTS, "actions": [*PANEL_ACTIONS, SCROLL_DOWN]}
    decide = decider([weak(0.2), DONE])
    agent = agent_with(decide, session=FakeSession(pages))
    agent.run("add passengers")
    assert all("expanded" not in element for element in decide.seen[1][0]["elements"])


def test_blocked_is_reported_as_blocked_with_candidates():
    blocked = {
        "operation": answer("BLOCKED", {"BLOCKED": 0.7, "CLICK": 0.2, "TYPE_TEXT": 0.05, "WAIT": 0.05}),
        "click_target": answer("e2", {"e1": 0.4, "e2": 0.6}),
        "goal_achieved": {"noul": 0.1},
    }
    result = agent_with(decider([blocked])).run("find flights")
    assert (result.status, result.reason) == ("blocked", "blocked")
    assert result.candidates[0]["operation"] == "BLOCKED"
    assert result.detail["page_text"] == "Booking form"


def test_three_actions_without_a_page_change_escalate_as_a_loop():
    still = FakeSession(pages=[page("same")] * 6)
    result = agent_with(decider([CLICK_SUBMIT]), session=still).run("find flights")
    assert (result.status, result.reason) == ("escalate", "stuck_loop")
    assert len(result.steps) == 3
    assert all(step["page_changed"] is False for step in result.steps)


def test_a_confident_prev_ok_keeps_an_unchanged_page_out_of_the_loop_count():
    confident = dict(CLICK_SUBMIT, prev_ok={"noul": 0.9})
    still = FakeSession(pages=[page("same")] * 6)
    result = agent_with(decider([CLICK_SUBMIT, confident]), session=still).run("find flights")
    assert result.reason == "stuck_loop"
    # The repeated-choice rule, not the no-change rule, is what stops it.
    assert result.steps[-1]["prev_ok"] == 0.9


def test_a_page_that_hides_controls_escalates_as_too_many_controls():
    crowded = page("same")
    crowded["omitted"] = 40
    still = FakeSession(pages=[crowded] * 6)
    result = agent_with(decider([CLICK_SUBMIT]), session=still).run("find flights")
    assert result.reason == "too_many_controls"


def test_the_same_choice_three_times_running_is_a_loop_even_when_the_page_moves():
    result = agent_with(decider([CLICK_SUBMIT])).run("find flights")
    assert (result.status, result.reason) == ("escalate", "stuck_loop")
    assert len(result.steps) == 3


def test_scrolling_three_times_running_is_reading_not_a_loop():
    script = {"operation": answer("SCROLL_DOWN"), "goal_achieved": {"noul": 0.1}}
    result = agent_with(decider([script]), session=FakeSession(scrollable())).run("find flights", max_steps=4)
    assert result.status == "budget"
    assert [step["operation"] for step in result.steps] == ["SCROLL_DOWN"] * 4


def test_max_steps_ends_the_run_on_budget():
    varied = [
        dict(CLICK_SUBMIT, click_target=answer("e2")),
        {"operation": answer("CLICK"), "click_target": answer("e1"), "goal_achieved": {"noul": 0.1}},
    ]
    result = agent_with(decider(varied)).run("find flights", max_steps=2)
    assert result.status == "budget"
    assert "max_steps (2)" in result.reason
    assert len(result.steps) == 2


def test_open_and_observe_delegate_to_the_session():
    agent = agent_with(decider([DONE]))
    assert agent.open("http://127.0.0.1/form.html")["title"] == "Booking form"
    assert agent.observe()["url"] == "http://127.0.0.1/form.html"


def test_act_runs_one_decided_step():
    result = agent_with(decider([DONE])).act("confirm the page")
    assert (result.status, result.reason) == ("done", "goal_achieved")


def test_select_picks_the_option_by_its_label():
    option = {
        "id": "e3",
        "node": 3,
        "role": "combobox",
        "kind": "select",
        "label": "Shipping → Express",
        "value": "express",
    }
    session = FakeSession(pages=[{**page(0), "actions": [option]}])
    agent = agent_with(decider([DONE]), session=session)
    agent.select("e3", "Express")
    assert session.acted == [("e3", "select", None)]


class PressSession(FakeSession):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pressed = []

    def press(self, key):
        self.pressed.append(key)


PRESS_ENTER = {"id": "press_enter", "node": 1, "kind": "press", "key": "Enter", "label": "Press Enter to submit City"}


def test_a_direct_enter_goes_through_the_observed_action_a_decided_one_would_use():
    focused = page(0)
    session = PressSession(pages=[{**focused, "actions": [*FORM_ACTIONS, PRESS_ENTER]}])
    agent = agent_with(decider([DONE]), session=session)
    assert agent.press("Enter")["title"] == "Booking form"
    assert session.acted == [("press_enter", "press", None)]
    assert session.pressed == []


def test_a_direct_enter_with_nothing_focused_is_refused_rather_than_pressed():
    session = PressSession()
    agent = agent_with(decider([DONE]), session=session)
    with pytest.raises(Escalated) as caught:
        agent.press("Enter")
    assert "nothing is focused" in caught.value.render().lower()
    assert session.pressed == []
    assert session.acted == []


def test_escape_and_tab_have_no_field_to_check_and_still_go_out():
    session = PressSession()
    agent = agent_with(decider([DONE]), session=session)
    assert agent.press("Escape")["title"] == "Booking form"
    assert agent.press("Tab")["title"] == "Booking form"
    assert session.pressed == ["Escape", "Tab"]


def test_close_closes_the_decision_client_it_owns():
    closed = []

    class Client:
        def decide(self, _state, _questions):
            raise AssertionError("no decision expected")

        def close(self):
            closed.append(True)

    agent = Agent(session=FakeSession(), config=config.load({}), client=Client())
    agent.close()
    assert closed == [True]


def test_the_agent_is_a_context_manager_that_closes_its_session():
    session = FakeSession()
    with agent_with(decider([DONE]), session=session) as agent:
        assert agent.session is session
    assert session.closed is True


def test_the_time_budget_also_ends_the_run():
    seen = []

    def alternate(_state, _questions):
        target = "e1" if len(seen) % 2 == 0 else "e2"
        seen.append(target)
        return Reply(
            answers={"operation": answer("CLICK"), "click_target": answer(target), "goal_achieved": {"noul": 0.1}},
            latency_ms=1,
        )

    result = agent_with(alternate, env={"JEV_RA_TIMEOUT_S": "0.001"}).run("find flights")
    assert result.status == "budget"
    assert "timeout_s" in result.reason


def test_a_second_unofferable_choice_escalates():
    def always_bad(_state, _questions):
        return Reply(
            answers={
                "operation": answer("CLICK"),
                "click_target": {"choice": "e9", "confidence": 0.5, "probabilities": {"e9": 1.0}},
                "goal_achieved": {"noul": 0.1},
            },
            latency_ms=1,
        )

    result = agent_with(always_bad).run("find flights")
    assert (result.status, result.reason) == ("escalate", "invalid_decision")
    assert result.decisions == 2


class MovesWhileLooking(FakeSession):
    """The scroll lands; every read after it goes stale."""

    def observe(self, timer=None):
        if self.acted:
            raise StalePage("Page did not settle while it was looked at")
        return super().observe(timer)


def test_a_page_that_never_settles_while_being_looked_at_escalates_stale():
    weak_done = {"operation": answer("DONE"), "goal_achieved": {"noul": 0.2}}
    session = MovesWhileLooking(scrollable())
    result = agent_with(decider([weak_done]), session=session).run("find flights")
    assert (result.status, result.reason) == ("escalate", "stale")
    assert "while it was looked at" in result.detail["error"]


class MovesAfterActing(FakeSession):
    """The action lands; the observation that would verify it never settles."""

    def observe(self, timer=None):
        if self.acted:
            raise StalePage("Page did not settle after that action")
        return super().observe(timer)


def test_a_page_that_never_settles_after_acting_escalates_stale():
    session = MovesAfterActing()
    result = agent_with(decider([CLICK_SUBMIT]), session=session).run("find flights")
    assert (result.status, result.reason) == ("escalate", "stale")
    assert "after that action" in result.detail["error"]


BLOCKED_OVER_AN_ABSENT_FIELD = {
    "operation": answer("BLOCKED", {"BLOCKED": 0.7, "TYPE_TEXT": 0.3}),
    "click_target": answer("e2", {"e2": 1.0}),
    "goal_achieved": {"noul": 0.0},
}


def test_blocked_stays_blocked_when_the_typing_runner_up_has_no_field():
    button_only = {**page(0), "actions": [FORM_ACTIONS[2]], "elements": [FORM_ELEMENTS[1]]}
    agent = agent_with(decider([BLOCKED_OVER_AN_ABSENT_FIELD]), session=FakeSession(pages=[button_only]))
    result = agent.run("sign in")
    assert (result.status, result.reason) == ("blocked", "blocked")


def test_the_decision_budget_also_ends_the_run():
    result = agent_with(decider([CLICK_SUBMIT]), env={"JEV_RA_MAX_DECISIONS": "2"}).run("g", max_steps=40)
    assert result.status == "budget"
    assert "max_decisions (2)" in result.reason


def test_stale_pages_are_retried_before_escalating():
    recovered = FakeSession(stale=2)
    script = [CLICK_SUBMIT, CLICK_SUBMIT, CLICK_SUBMIT, DONE]
    result = agent_with(decider(script), session=recovered).run("find flights")
    assert result.status == "done"
    assert recovered.acted == [("e2", "click", None)]
    assert result.decisions == 4


def test_a_permanently_stale_page_escalates_after_three_retries():
    always = FakeSession(stale=99)
    result = agent_with(decider([CLICK_SUBMIT]), session=always).run("find flights")
    assert (result.status, result.reason) == ("escalate", "stale")
    assert always.acted == []
    assert always.stale == 99 - 4


def test_type_text_uses_a_host_value_and_never_calls_a_text_model():
    script = [
        {
            "operation": answer("TYPE_TEXT"),
            "type_text_target": answer("e1"),
            "value_for_field": answer("city"),
            "goal_achieved": {"noul": 0.1},
        },
        DONE,
    ]
    agent = agent_with(decider(script))
    result = agent.run("search for a city", values={"city": "London"})
    assert result.status == "done"
    assert agent.session.acted == [("e1", "fill", "London")]
    assert result.text_calls == []
    assert result.steps[0]["text"] == "London"


def test_type_text_without_a_fitting_value_escalates_as_needs_value():
    script = [
        {
            "operation": answer("TYPE_TEXT"),
            "type_text_target": answer("e1"),
            "value_for_field": answer("none"),
            "goal_achieved": {"noul": 0.1},
        }
    ]
    agent = agent_with(decider(script))
    result = agent.run("search for a city", values={"city": "London"})
    assert (result.status, result.reason) == ("escalate", "needs_value")
    assert result.detail["field"]["label"] == "City"
    assert result.detail["goal"] == "search for a city"
    assert agent.session.acted == []


def test_a_supplied_value_with_no_field_is_asked_again_on_a_fresh_reading():
    no_field = {
        "operation": answer("TYPE_TEXT"),
        "type_text_target": answer("e1"),
        "value_for_field": answer("none"),
        "goal_achieved": {"noul": 0.1},
    }
    agent = agent_with(decider([no_field, DONE]))
    result = agent.run("search for a city", values={"city": "London"})
    assert (result.status, result.reason) == ("done", "goal_achieved")
    assert result.decisions == 2
    assert agent.session.acted == []


def test_an_unofferable_target_triggers_one_corrective_re_ask():
    script = [
        {"operation": answer("CLICK"), "click_target": answer("e2"), "goal_achieved": {"noul": 0.1}},
        DONE,
    ]
    decide = decider(script)
    seen = []

    def wrapped(state, questions):
        seen.append(questions)
        if len(seen) == 1:
            return Reply(
                answers={
                    "operation": answer("CLICK"),
                    "click_target": {"choice": "e9", "confidence": 0.5, "probabilities": {"e9": 1.0}},
                    "goal_achieved": {"noul": 0.1},
                },
                latency_ms=1,
            )
        return decide(state, questions)

    result = agent_with(wrapped).run("find flights")
    assert result.status == "done"
    assert result.decisions == 3
    assert "e9" not in seen[1]["click_target"]["criteria"]


def test_a_second_invalid_answer_set_escalates():
    def always_broken(state, questions):
        raise JevBadResponse("operation: probabilities do not sum to 1")

    result = agent_with(always_broken).run("find flights")
    assert (result.status, result.reason) == ("escalate", "invalid_decision")
    assert result.decisions == 2


def test_a_decision_the_provider_rejects_escalates_instead_of_escaping():
    def handler(request):
        return httpx.Response(400, json={"error": {"message": "HTTP 400: max_tokens_exceeded", "code": 400}})

    settings = config.load({"OPENROUTER_API_KEY": "sk-or-v1-test"})
    client = DecisionClient(settings, transport=httpx.MockTransport(handler))
    session = FakeSession()
    result = Agent(session=session, config=settings, client=client).run("find flights")
    assert (result.status, result.reason) == ("escalate", "provider_error")
    assert "HTTP 400" in result.detail["error"]
    assert session.acted == []


def test_escalation_candidates_stop_at_eight():
    many = {
        "elements": [{"ref": f"e{n}", "node": n, "role": "link", "label": f"Result {n}"} for n in range(1, 21)],
        "actions": [
            {"id": f"e{n}", "node": n, "role": "link", "kind": "click", "label": f"Result {n}"} for n in range(1, 21)
        ],
        "url": "http://127.0.0.1/list.html",
        "title": "Results",
        "text": "Results",
        "marker": "same",
        "page_key": [],
        "guards": {},
        "omitted": 0,
    }
    spread = {f"e{n}": (0.81 if n == 1 else 0.01) for n in range(1, 21)}
    script = [
        {
            "operation": answer("CLICK", {"CLICK": 0.9, "DONE": 0.07, "BLOCKED": 0.03}),
            "click_target": answer("e1", spread),
            "goal_achieved": {"noul": 0.1},
        }
    ]
    result = agent_with(decider(script), session=FakeSession(pages=[many] * 6)).run("open a result")
    assert result.status == "escalate"
    assert len(result.candidates) == 8


def test_single_step_helpers_never_reach_the_decision_model():
    calls = []

    def decide(state, questions):
        calls.append(questions)
        raise AssertionError("no decision should be made")

    agent = agent_with(decide)
    agent.click("e2")
    agent.type("e1", "London")
    agent.wait()
    assert agent.session.acted == [("e2", "click", None), ("e1", "fill", "London"), ("wait", "wait", None)]
    assert calls == []


def test_a_direct_action_for_a_missing_ref_is_a_lookup_error():
    agent = agent_with(decider([DONE]))
    with pytest.raises(LookupError, match="No click action for e9"):
        agent.click("e9")
    with pytest.raises(LookupError, match="scroll_down is not offered"):
        agent.scroll("down")


BLOCKED_OVER_TYPING = {
    "operation": answer("BLOCKED", {"BLOCKED": 0.52, "TYPE_TEXT": 0.45, "CLICK": 0.03}),
    "type_text_target": answer("e1", {"e1": 1.0}),
    "click_target": answer("e2", {"e2": 1.0}),
    "goal_achieved": {"noul": 0.0},
}


def test_a_login_wall_asks_for_the_value_instead_of_reporting_blocked():
    result = agent_with(decider([BLOCKED_OVER_TYPING])).run("sign in to the account")
    assert (result.status, result.reason) == ("escalate", "needs_value")
    assert result.detail["field"]["label"] == "City"
    assert result.detail["field"]["ref"] == "e1"
    assert result.detail["reason"] == "the page needs a value that was not supplied"
    assert result.detail["goal"] == "sign in to the account"


def test_blocked_stays_blocked_when_the_caller_did_supply_values():
    result = agent_with(decider([BLOCKED_OVER_TYPING])).run("sign in", values={"city": "London"})
    assert (result.status, result.reason) == ("blocked", "blocked")


def test_blocked_stays_blocked_when_nothing_could_be_typed_into():
    blocked = {
        "operation": answer("BLOCKED", {"BLOCKED": 0.8, "CLICK": 0.2}),
        "click_target": answer("e2", {"e2": 1.0}),
        "goal_achieved": {"noul": 0.0},
    }
    result = agent_with(decider([blocked])).run("draw a red square")
    assert (result.status, result.reason) == ("blocked", "blocked")


class FlakySession(FakeSession):
    """Raises StalePage from observe() the first `stale_reads` times it is called."""

    def __init__(self, stale_reads=0, **kwargs):
        super().__init__(**kwargs)
        self.stale_reads = stale_reads
        self.reads = 0

    def observe(self, timer=None):
        self.reads += 1
        if self.reads <= self.stale_reads:
            raise StalePage("Page did not settle")
        return super().observe(timer)

    def open(self, url):
        return self.observe()


def test_a_page_that_will_not_settle_at_first_is_read_again():
    session = FlakySession(stale_reads=2)
    result = agent_with(decider([CLICK_SUBMIT, DONE]), session=session).run("find flights", url="http://x/")
    assert result.status == "done"
    assert session.reads > 2


def test_a_page_that_never_settles_escalates_rather_than_raising():
    session = FlakySession(stale_reads=99)
    result = agent_with(decider([DONE]), session=session).run("find flights", url="http://x/")
    assert (result.status, result.reason) == ("escalate", "stale")
    assert result.detail["error"]
    assert result.steps == []


def test_looking_below_the_fold_survives_the_page_moving_under_it():
    weak_done = {"operation": answer("DONE"), "goal_achieved": {"noul": 0.2}}
    session = FakeSession(scrollable(), stale=1)
    result = agent_with(decider([weak_done, DONE]), session=session).run("find flights")
    assert result.status == "done"
    assert session.acted == []


def test_a_page_that_keeps_moving_while_being_looked_at_still_ends_cleanly():
    weak_done = {"operation": answer("DONE"), "goal_achieved": {"noul": 0.2}}
    session = FakeSession(scrollable(), stale=99)
    result = agent_with(decider([weak_done]), session=session).run("find flights")
    assert (result.status, result.reason) == ("escalate", "unverified_done")


def test_a_provider_error_carrying_the_key_is_redacted_before_the_caller_sees_it():
    from jev_ra.errors import JevUnavailable

    key = "sk-or-v1-not-to-be-shared"

    def decide(_state, _questions):
        raise JevUnavailable(f"Could not reach the provider using {key}")

    settings = config.load({"OPENROUTER_API_KEY": key})
    result = Agent(session=FakeSession(), config=settings, decide=decide).run("find flights")
    assert (result.status, result.reason) == ("escalate", "provider_error")
    assert key not in result.detail["error"]
    assert "[redacted]" in result.detail["error"]


def test_an_unusable_answer_set_is_redacted_the_same_way():
    key = "sk-or-v1-not-to-be-shared"
    asked = []

    def decide(_state, _questions):
        asked.append(1)
        raise JevBadResponse(f"operation: unusable answer from {key}")

    settings = config.load({"OPENROUTER_API_KEY": key})
    result = Agent(session=FakeSession(), config=settings, decide=decide).run("find flights")
    assert result.reason == "invalid_decision"
    assert key not in result.detail["error"]


def test_a_rejected_key_is_its_own_reason_and_never_carries_the_key():
    # A budget is something the run spent and the host can give more of. A provider that will not
    # answer is neither: narrowing the goal and calling again spends money on the same refusal.
    key = "sk-or-v1-not-to-be-shared"

    def handler(request):
        return httpx.Response(401, json={"error": {"message": f"No auth credentials found for {key}", "code": 401}})

    settings = config.load({"OPENROUTER_API_KEY": key})
    client = DecisionClient(settings, transport=httpx.MockTransport(handler))
    session = FakeSession()
    result = Agent(session=session, config=settings, client=client).run("find flights")
    assert (result.status, result.reason) == ("escalate", "provider_error")
    assert "OPENROUTER_API_KEY" in result.detail["error"]
    assert "HTTP 401" in result.detail["error"]
    assert key not in result.detail["error"]
    assert session.acted == []
    assert result.decisions == 1


def test_a_scripted_run_carries_a_stable_run_id():
    result = agent_with(decider([CLICK_SUBMIT, DONE])).run("find flights")
    assert len(result.run_id) == 12
    assert all(character in "0123456789abcdef" for character in result.run_id)


def test_a_real_client_lends_its_decision_session_id_to_the_run():
    settings = config.load({"OPENROUTER_API_KEY": "sk-or-v1-test"})
    client = DecisionClient(
        settings,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"answers": {}})),
    )
    agent = Agent(session=FakeSession(), config=settings, client=client, decide=decider([DONE]))
    result = agent.run("confirm the page")
    assert result.run_id == client.session_id


def test_the_run_id_is_what_the_agent_logs(monkeypatch, capsys):
    import logging

    from jev_ra import logs

    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    root.handlers = []
    monkeypatch.setenv("JEV_RA_LOG_LEVEL", "DEBUG")
    try:
        logs.configure()
        weak_done = {"operation": answer("DONE"), "goal_achieved": {"noul": 0.2}}
        result = agent_with(decider([weak_done])).run("find flights")
    finally:
        root.handlers, root.level = saved_handlers, saved_level
    assert result.run_id in capsys.readouterr().err


def test_the_default_log_level_keeps_agent_info_lines_off_stderr(monkeypatch, capsys):
    import logging

    from jev_ra import logs

    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    root.handlers = []
    monkeypatch.delenv("JEV_RA_LOG_LEVEL", raising=False)
    try:
        logs.configure()
        weak_done = {"operation": answer("DONE"), "goal_achieved": {"noul": 0.2}}
        result = agent_with(decider([weak_done])).run("find flights")
    finally:
        root.handlers, root.level = saved_handlers, saved_level
    assert result.run_id not in capsys.readouterr().err


def test_an_unknown_log_level_falls_back_to_warning():
    from jev_ra import logs

    assert logs.level({}) == "WARNING"
    assert logs.level({"JEV_RA_LOG_LEVEL": "debug"}) == "DEBUG"
    assert logs.level({"JEV_RA_LOG_LEVEL": "loud"}) == "WARNING"


def test_a_click_quoted_with_a_stale_page_key_is_refused():
    session = FakeSession()
    agent = agent_with(decider([DONE]), session=session)
    stale = session.observe()["page_key"]
    session.pages = [{**page(1), "page_key": [9, "http://elsewhere"]}]
    with pytest.raises(StalePage, match="the page changed since that observation"):
        agent.click("e2", page_key=stale)
    assert session.acted == []


def test_without_a_page_key_the_click_is_matched_on_the_fresh_page():
    session = FakeSession()
    agent = agent_with(decider([DONE]), session=session)
    session.pages = [{**page(1), "page_key": [9, "http://elsewhere"]}]
    agent.click("e2")
    assert session.acted == [("e2", "click", None)]


def never(_state, _questions):
    """A decider the direct tools must never reach."""
    raise AssertionError("no decision expected")


@pytest.mark.browser
def test_a_ref_quoted_with_a_page_key_is_refused_after_a_lazy_panel_mounts(session, fixture_server):
    agent = Agent(session=session, config=config.load({}), decide=never)
    opened = agent.open(f"{fixture_server}/sites/late-panel.html")
    old_key = opened["page_key"]
    after_open = agent.click("e1")
    fresh_ref = next(element["ref"] for element in after_open["elements"] if element["role"] == "textbox")
    with pytest.raises(StalePage, match="the page changed since that observation"):
        agent.type(fresh_ref, "help", page_key=old_key)


@pytest.mark.browser
def test_without_a_page_key_the_ref_is_matched_on_a_fresh_observation(session, fixture_server):
    agent = Agent(session=session, config=config.load({}), decide=never)
    agent.open(f"{fixture_server}/sites/late-panel.html")
    after_open = agent.click("e1")
    fresh_ref = next(element["ref"] for element in after_open["elements"] if element["role"] == "textbox")
    agent.type(fresh_ref, "help")
    assert session.evaluate("document.getElementById('q').value") == "help"
