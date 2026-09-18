import pytest

from jev_ra import config
from jev_ra.agent import Agent
from jev_ra.browser.session import StalePage
from jev_ra.decide import JevInvalidResponse, Reply

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

    def __init__(self, pages=None, stale=0, max_elements=250):
        self.pages = list(pages or [page(n) for n in range(60)])
        self.index = 0
        self.stale = stale
        self.max_elements = max_elements
        self.acted = []
        self.closed = False

    def open(self, url):
        return self.observe()

    def observe(self):
        return self.pages[min(self.index, len(self.pages) - 1)]

    def act(self, action, page, text=None):
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


def test_done_without_goal_achieved_takes_one_more_step_then_escalates():
    weak_done = {"operation": answer("DONE"), "goal_achieved": {"noul": 0.2}}
    agent = agent_with(decider([weak_done]))
    result = agent.run("find flights")
    assert (result.status, result.reason) == ("escalate", "unverified_done")
    assert result.decisions == 2
    assert agent.session.acted == []


def test_a_weak_done_followed_by_a_real_one_still_finishes():
    weak_done = {"operation": answer("DONE"), "goal_achieved": {"noul": 0.2}}
    result = agent_with(decider([weak_done, CLICK_SUBMIT, DONE])).run("find flights")
    assert result.status == "done"


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


def test_max_steps_ends_the_run_on_budget():
    varied = [
        dict(CLICK_SUBMIT, click_target=answer("e2")),
        {"operation": answer("CLICK"), "click_target": answer("e1"), "goal_achieved": {"noul": 0.1}},
    ]
    result = agent_with(decider(varied)).run("find flights", max_steps=2)
    assert result.status == "budget"
    assert "max_steps (2)" in result.reason
    assert len(result.steps) == 2


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
        raise JevInvalidResponse("operation: probabilities do not sum to 1")

    result = agent_with(always_broken).run("find flights")
    assert (result.status, result.reason) == ("escalate", "invalid_decision")
    assert result.decisions == 2


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
