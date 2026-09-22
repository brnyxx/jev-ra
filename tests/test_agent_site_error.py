"""A site's bad minute costs one reload, and a site that stays down is reported as the site."""

import pytest

from jev_ra import config
from jev_ra.agent import Agent
from jev_ra.decide import Reply

pytestmark = pytest.mark.browser

ERROR_TEXT_PAGE = (
    "<!doctype html><html><head><title>Application Error</title></head>"
    "<body><p>An error occurred in the application and your page could not be served.</p></body></html>"
)


def certain(choice, criteria):
    return {"choice": choice, "confidence": 0.95, "probabilities": {key: float(key == choice) for key in criteria}}


def done_decider():
    """A decider that finishes on the form and keeps the questions it was offered."""
    calls = []

    def decide(_state, questions):
        calls.append(questions)
        answers = {
            "operation": certain("DONE", questions["operation"]["criteria"]),
            "goal_achieved": {"noul": 0.95},
        }
        return Reply(answers=answers, model="scripted", latency_ms=1, usage={"cost": 0.0})

    decide.calls = calls
    return decide


def offered(calls):
    return [
        text
        for questions in calls
        for name, question in questions.items()
        if name.endswith("_target")
        for text in question["criteria"].values()
    ]


def run_on(session, url, decide):
    agent = Agent(session=session, config=config.load({}), decide=decide, prefetch=False)
    return agent.run("Order a large pizza for Ada Lovelace.", url=url)


def test_a_site_that_hiccups_once_still_reaches_the_form(session, flaky_server):
    decide = done_decider()
    result = run_on(session, flaky_server(status=502, failures=1), decide)
    assert (result.status, result.reason) == ("done", "goal_achieved")
    assert result.decisions == 1
    assert any("Customer name" in text for text in offered(decide.calls))


def test_a_site_that_stays_down_is_reported_as_the_site(session, flaky_server):
    decide = done_decider()
    result = run_on(session, flaky_server(status=502, failures=2), decide)
    assert (result.status, result.reason) == ("escalate", "blocked_by_site")
    assert result.detail["wall"] == "http 502"
    assert result.decisions == 0
    assert decide.calls == []


def test_a_short_error_page_is_reloaded_even_when_the_status_is_not_one(session, flaky_server):
    decide = done_decider()
    result = run_on(session, flaky_server(status=200, failures=1, body=ERROR_TEXT_PAGE), decide)
    assert (result.status, result.reason) == ("done", "goal_achieved")
    assert any("Customer name" in text for text in offered(decide.calls))


def test_a_site_that_only_says_it_failed_is_reported_as_the_site(session, flaky_server):
    decide = done_decider()
    result = run_on(session, flaky_server(status=200, failures=2, body=ERROR_TEXT_PAGE), decide)
    assert (result.status, result.reason) == ("escalate", "blocked_by_site")
    assert result.detail["wall"] == "the page answered 'application error'"
    assert decide.calls == []
