"""The next decision is asked from the first reading that shows a step's effect, while the page proves it."""

import threading

import pytest

from jev_ra import agent as agent_module
from jev_ra import config
from jev_ra.agent import Agent
from jev_ra.decide import Reply

LISTING = "/sites/restless-listing.html"


def certain(choice, criteria):
    return {"choice": choice, "confidence": 0.95, "probabilities": {key: float(key == choice) for key in criteria}}


def reply(questions, operation, target=None):
    answers = {"operation": certain(operation, questions["operation"]["criteria"])}
    if target is not None:
        name = operation.lower() + "_target"
        answers[name] = certain(target, questions[name]["criteria"])
    answers["goal_achieved"] = {"noul": 0.95 if operation == "DONE" else 0.05}
    if "prev_ok" in questions:
        answers["prev_ok"] = {"noul": 0.9}
    return Reply(answers=answers, model="scripted", latency_ms=1, usage={"cost": 0.0001})


def by_the_page(label):
    """Answers from the request alone, so a request asked early gets the answer it would get late."""
    calls = []
    lock = threading.Lock()

    def decide(state, questions):
        with lock:
            calls.append({"state": state, "observing": decide.observing})
        if any(step["action"] == label for step in state["recent_actions"]):
            return reply(questions, "DONE")
        offered = questions.get("click_target", {}).get("criteria", {})
        target = next((key for key, text in offered.items() if text.endswith(label)), None)
        if target is not None:
            return reply(questions, "CLICK", target)
        return reply(questions, "SCROLL_DOWN")

    decide.calls = calls
    decide.observing = False
    return decide


def watched(session, decide):
    """Mark the calls made while the session is still observing, which is where a settle runs."""
    observe = session.observe

    def observing(timer=None):
        decide.observing = True
        try:
            return observe(timer)
        finally:
            decide.observing = False

    session.observe = observing


@pytest.mark.browser
def test_the_decision_after_a_scroll_is_asked_while_the_page_is_still_settling(session, fixture_server):
    decide = by_the_page("Newest first")
    watched(session, decide)
    agent = Agent(session=session, config=config.load({}), decide=decide)
    result = agent.run("Sort this listing by newest first.", url=fixture_server + LISTING)
    assert (result.status, result.reason) == ("done", "goal_achieved")
    assert [step["operation"] for step in result.steps] == ["SCROLL_DOWN", "CLICK"]
    assert result.steps[1]["prefetched"] is True
    assert result.prefetched >= 1
    after_scroll = next(call for call in decide.calls if call["state"]["recent_actions"])
    assert after_scroll["observing"] is True


@pytest.mark.browser
def test_a_decider_that_answers_by_position_is_never_asked_during_a_settle(session, fixture_server):
    decide = by_the_page("Newest first")
    agent = Agent(session=session, config=config.load({}), decide=decide, prefetch=False)
    result = agent.run("Sort this listing by newest first.", url=fixture_server + LISTING)
    assert (result.status, result.reason) == ("done", "goal_achieved")
    assert (result.speculations, result.prefetched) == (0, 0)
    assert len(decide.calls) == 3


ACTIONS = [
    {"id": "e1", "node": 1, "role": "link", "kind": "click", "label": "Newest first"},
    {"id": "scroll_down", "kind": "scroll", "label": "Scroll down", "delta": 560},
    {"id": "wait", "kind": "wait", "label": "Wait for the page to update"},
]


def reading(marker, labels=("Newest first",)):
    elements = [{"ref": f"e{n}", "node": n, "role": "link", "label": label} for n, label in enumerate(labels, 1)]
    actions = [dict(ACTIONS[0], id=f"e{n}", node=n, label=label) for n, label in enumerate(labels, 1)]
    return {
        "url": "http://127.0.0.1/listing.html",
        "title": "Listing",
        "text": f"reading {marker}",
        "elements": elements,
        "actions": [*actions, *ACTIONS[1:]],
        "marker": marker,
        "page_key": [0, "http://127.0.0.1/listing.html", 0, 0, 1280, 900, []],
        "guards": {},
        "omitted": 0,
    }


class PreviewingSession:
    """Hands each step's early readings to whoever is listening, then observes the settled one."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.index = 0
        self.max_elements = 250
        self.preview = None

    def open(self, _url):
        return self.observe()

    def observe(self, timer=None):
        early, settled = self.steps[min(self.index, len(self.steps) - 1)]
        for page in early:
            if self.preview is not None:
                self.preview(page)
        return settled

    def act(self, action, page, text=None, timer=None):
        self.index += 1
        return {"executed": action["id"]}

    def close(self):
        pass


def test_a_lookahead_the_settled_page_does_not_ask_for_is_thrown_away():
    decide = by_the_page("Newest first")
    early = reading("early", labels=("Most popular",))
    session = PreviewingSession([((), reading("start", labels=())), ((early,), reading("settled"))])
    agent = Agent(session=session, config=config.load({}), decide=decide)
    result = agent.run("Sort this listing by newest first.")
    assert [step["operation"] for step in result.steps[:2]] == ["SCROLL_DOWN", "CLICK"]
    assert result.steps[1]["prefetched"] is False
    assert result.speculations >= 1
    assert result.cost == pytest.approx(0.0001 * len(decide.calls))


def test_a_page_that_keeps_changing_asks_ahead_no_more_than_the_limit():
    decide = by_the_page("Newest first")
    early = tuple(reading(f"early {n}", labels=(f"Item {n}",)) for n in range(agent_module.LOOKAHEADS + 3))
    session = PreviewingSession([((), reading("start", labels=())), (early, reading("settled"))])
    agent = Agent(session=session, config=config.load({}), decide=decide)
    result = agent.run("Sort this listing by newest first.", max_steps=2)
    assert result.speculations == agent_module.LOOKAHEADS
    assert result.prefetched == 0


def test_the_reading_the_settle_ends_on_is_the_one_that_answers():
    decide = by_the_page("Newest first")
    settled = reading("settled")
    session = PreviewingSession([((), reading("start", labels=())), ((settled,), settled)])
    agent = Agent(session=session, config=config.load({}), decide=decide)
    result = agent.run("Sort this listing by newest first.", max_steps=2)
    assert result.steps[1]["prefetched"] is True
    assert result.prefetched == 1
    assert result.decisions == len(result.steps)
