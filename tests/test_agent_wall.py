"""A site that answers with a wall is reported as the site refusing, not as a task that failed."""

import pytest

from jev_ra import config
from jev_ra.agent import Agent
from jev_ra.decide import Reply

pytestmark = pytest.mark.browser


def certain(choice, criteria):
    return {"choice": choice, "confidence": 0.95, "probabilities": {key: float(key == choice) for key in criteria}}


def always_click(label):
    """Clicks the named link every time it is offered, so the run keeps opening pages."""
    calls = []

    def decide(state, questions):
        calls.append(state)
        criteria = questions.get("click_target", {}).get("criteria", {})
        target = next((key for key, text in criteria.items() if label in text), None)
        if target is None:
            answers = {"operation": certain("DONE", questions["operation"]["criteria"]), "goal_achieved": {"noul": 0.9}}
        else:
            answers = {
                "operation": certain("CLICK", questions["operation"]["criteria"]),
                "click_target": certain(target, criteria),
                "goal_achieved": {"noul": 0.05},
            }
        if "prev_ok" in questions:
            answers["prev_ok"] = {"noul": 0.5}
        return Reply(answers=answers, model="scripted", latency_ms=1, usage={"cost": 0.0})

    decide.calls = calls
    return decide


def run_on(session, url, decide):
    agent = Agent(session=session, config=config.load({}), decide=decide)
    return agent.run("Search the shop for a keyboard.", url=url)


def test_a_refusal_is_reported_before_a_decision_is_ever_asked_for(session, fixture_server):
    decide = always_click("Try again")
    result = run_on(session, f"{fixture_server}/sites/bot-wall.html", decide)
    assert (result.status, result.reason) == ("escalate", "blocked_by_site")
    assert result.decisions == 0
    assert "access denied" in result.detail["wall"]


def test_a_host_that_answers_every_open_with_nothing_is_refusing(session, fixture_server):
    decide = always_click("next")
    result = run_on(session, f"{fixture_server}/sites/thin-wall.html", decide)
    assert (result.status, result.reason) == ("escalate", "blocked_by_site")
    assert result.detail["wall"].startswith("127.0.0.1 answered 3 opens")
    assert len(result.steps) == 2


def test_an_ordinary_page_is_not_a_wall(session, fixture_server):
    decide = always_click("Documentation")
    result = run_on(session, f"{fixture_server}/sites/off-site-links.html", decide)
    assert result.reason != "blocked_by_site"


def test_a_page_about_walls_is_not_a_wall(session, fixture_server):
    decide = always_click("Read the deployment protection guide")
    result = run_on(session, f"{fixture_server}/sites/captcha-mention.html", decide)
    assert result.reason != "blocked_by_site"
