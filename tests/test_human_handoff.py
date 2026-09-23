"""A human check is handed to the person at the window, and the run carries on once they clear it."""

import time

import pytest

from jev_ra import config
from jev_ra.agent import HUMAN, Agent
from jev_ra.decide import Reply
from jev_ra.pacing import Pacer

pytestmark = pytest.mark.browser

PLAN = [
    ("TYPE_TEXT", "Full name", "name"),
    ("TYPE_TEXT", "Email", "email"),
    ("SELECT", "Shipping → Express", None),
    ("CLICK", "Place order", None),
]
VALUES = {"name": "Ada Lovelace", "email": "ada@example.com"}
GOAL = "Place an order for Ada Lovelace with express shipping."
CHALLENGE = "/sites/cloudflare-challenge.html?to=/checkout.html"


def certain(choice, criteria):
    return {"choice": choice, "confidence": 0.95, "probabilities": {key: float(key == choice) for key in criteria}}


def scripted(plan):
    calls = []

    def decide(state, questions):
        step = plan[len(calls)] if len(calls) < len(plan) else None
        calls.append(state)
        if step is None:
            answers = {"operation": certain("DONE", questions["operation"]["criteria"])}
        else:
            operation, label, value_name = step
            name = operation.lower() + "_target"
            criteria = questions[name]["criteria"]
            target = next(key for key, text in criteria.items() if label in text)
            answers = {
                "operation": certain(operation, questions["operation"]["criteria"]),
                name: certain(target, criteria),
            }
            if "value_for_field" in questions:
                answers["value_for_field"] = certain(value_name or "none", questions["value_for_field"]["criteria"])
        answers["goal_achieved"] = {"noul": 0.95 if step is None else 0.05}
        if "prev_ok" in questions:
            answers["prev_ok"] = {"noul": 0.9}
        return Reply(answers=answers, model="scripted", latency_ms=1, usage={"cost": 0.0})

    decide.calls = calls
    return decide


class Person:
    """Stands in for whoever is at the window: can see the browser, and may clear the check."""

    def __init__(self, session, clears=True, away_s=0.0, clock=None):
        self.session = session
        self.clears = clears
        self.away_s = away_s
        self.clock = clock
        self.asked = []

    def hidden(self):
        return ""

    def present(self, site, check):
        self.asked.append((site, check))
        if self.clock is not None:
            self.clock.offset += self.away_s
        if self.clears:
            tick(self.session)


def tick(session):
    """Answer the check through the page: the message its widget frame sends once its box is ticked."""
    session.evaluate("postMessage({jevRaCheck: 'solved'}, '*')")


class Clock:
    """The real clock, plus however long the person was away."""

    def __init__(self):
        self.offset = 0.0

    def __call__(self):
        return time.perf_counter() + self.offset


def agent_on(session, decide, env=None, clock=None):
    options = {"clock": clock} if clock is not None else {}
    return Agent(
        session=session,
        config=config.load({"JEV_RA_HUMAN_WAIT_S": "10", **(env or {})}),
        decide=decide,
        prefetch=False,
        pacer=Pacer(backoff=0, sleep=lambda _seconds: None),
        **options,
    )


def test_a_check_the_person_clears_lets_the_same_run_reach_its_goal(session, fixture_server):
    person = Person(session)
    session.presenter = person
    decide = scripted(PLAN)
    result = agent_on(session, decide).run(GOAL, values=VALUES, max_steps=5, url=fixture_server + CHALLENGE)
    assert (result.status, result.reason) == ("done", "goal_achieved")
    assert person.asked == [("127.0.0.1", "Cloudflare challenge")]
    assert [step["operation"] for step in result.steps] == ["TYPE_TEXT", "TYPE_TEXT", "SELECT", "CLICK"]
    assert "Order confirmed" in result.final_page["text"]
    assert all("Verify you are human" not in state["page"]["text"] for state in decide.calls)
    assert result.human_wait_ms >= 0


def test_the_wait_is_reported_apart_and_spends_no_budget(session, fixture_server):
    clock = Clock()
    person = Person(session, away_s=500.0, clock=clock)
    session.presenter = person
    env = {"JEV_RA_TIMEOUT_S": "120"}
    agent = agent_on(session, scripted(PLAN), env=env, clock=clock)
    result = agent.run(GOAL, values=VALUES, max_steps=5, url=fixture_server + CHALLENGE)
    assert (result.status, result.reason) == ("done", "goal_achieved")
    assert result.human_wait_ms >= 500_000
    assert result.elapsed_ms >= result.human_wait_ms
    assert result.elapsed_ms - result.human_wait_ms < 120_000
    assert len(result.steps) == 4
    assert all(step["total_ms"] < 500_000 for step in result.steps)


def test_a_check_that_appears_after_a_click_is_handed_over_too(session, fixture_server):
    person = Person(session)
    session.presenter = person
    plan = [("CLICK", "Check out", None), *PLAN]
    url = f"{fixture_server}/sites/checkout-link.html"
    result = agent_on(session, scripted(plan)).run(GOAL, values=VALUES, max_steps=6, url=url)
    assert (result.status, result.reason) == ("done", "goal_achieved")
    assert len(person.asked) == 1
    assert [step["operation"] for step in result.steps] == ["CLICK", "TYPE_TEXT", "TYPE_TEXT", "SELECT", "CLICK"]


def test_a_check_nobody_clears_in_time_escalates_needs_human(session, fixture_server):
    person = Person(session, clears=False)
    session.presenter = person
    decide = scripted(PLAN)
    result = agent_on(session, decide, env={"JEV_RA_HUMAN_WAIT_S": "0.3"}).run(
        GOAL, values=VALUES, url=fixture_server + CHALLENGE
    )
    assert (result.status, result.reason) == ("escalate", "needs_human")
    assert result.detail["kind"] == HUMAN
    assert result.detail["check"] == "Cloudflare challenge"
    assert result.detail["site"] == "127.0.0.1"
    assert result.decisions == 0
    assert result.human_wait_ms >= 300
    assert decide.calls == []


def test_a_browser_nobody_can_see_escalates_at_once_with_how_to_rerun(session, fixture_server):
    fronted = []
    session.front = lambda: fronted.append(True)
    session.presenter.reason = "the browser is headless"
    result = agent_on(session, scripted(PLAN)).run(GOAL, values=VALUES, url=fixture_server + CHALLENGE)
    assert (result.status, result.reason) == ("escalate", "needs_human")
    assert "headless" in result.detail["next_step"]
    assert "--profile" in result.detail["next_step"]
    assert fronted == []
    assert result.human_wait_ms < 5_000


def test_a_refusal_behind_a_check_is_still_a_refusal(session, fixture_server):
    person = Person(session)
    session.presenter = person
    url = f"{fixture_server}/sites/cloudflare-challenge.html?to=/sites/geo-block.html"
    result = agent_on(session, scripted(PLAN)).run(GOAL, values=VALUES, url=url)
    assert (result.status, result.reason) == ("escalate", "blocked_by_site")
    assert result.detail["kind"] == "refusal"


def test_a_check_that_clears_itself_during_the_backoff_asks_nobody_and_is_the_runs_own_time(session, fixture_server):
    person = Person(session, clears=False)
    session.presenter = person

    def the_moment_passes(_seconds):
        session.evaluate("postMessage({jevRaCheck: 'solved'}, '*')")
        session.evaluate("new Promise(resolve => setTimeout(() => resolve(true), 0))", await_promise=True)

    agent = Agent(
        session=session,
        config=config.load({}),
        decide=scripted([]),
        prefetch=False,
        pacer=Pacer(sleep=the_moment_passes),
    )
    result = agent.run("Send the message.", url=f"{fixture_server}/sites/turnstile-wall.html")
    assert (result.status, result.reason) == ("done", "goal_achieved")
    assert person.asked == []
    assert result.human_wait_ms == 0


def test_a_person_who_answers_at_once_is_still_a_person_who_was_asked(session, fixture_server):
    person = Person(session)
    session.presenter = person
    result = agent_on(session, scripted(PLAN)).run(GOAL, values=VALUES, url=fixture_server + CHALLENGE)
    assert result.status == "done"
    assert result.human_wait_ms > 0


def test_a_check_page_is_never_sent_for_a_decision_not_even_ahead_of_time(session, fixture_server):
    session.presenter = Person(session)
    asked = []

    def decide(state, questions):
        asked.append(state["page"]["text"])
        answers = {"operation": certain("DONE", questions["operation"]["criteria"]), "goal_achieved": {"noul": 0.95}}
        return Reply(answers=answers, model="scripted", latency_ms=1, usage={"cost": 0.0})

    agent = Agent(
        session=session,
        config=config.load({"JEV_RA_HUMAN_WAIT_S": "10"}),
        decide=decide,
        pacer=Pacer(backoff=0, sleep=lambda _seconds: None),
    )
    result = agent.run("Open the checkout.", url=fixture_server + CHALLENGE)
    assert result.status == "done"
    assert asked
    assert not any("Verify you are human" in text for text in asked)
