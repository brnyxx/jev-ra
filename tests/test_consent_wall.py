"""A consent wall in front of the page: its way through is the only thing on offer."""

import pytest

from jev_ra import config
from jev_ra.agent import Agent
from jev_ra.browser import actions
from jev_ra.decide import Reply

pytestmark = pytest.mark.browser

DIALOG = "/sites/consent-dialog.html"
OVERLAY = "/sites/consent-overlay.html"
GOAL = "Enter London as the departure station and show its suggestions."


def scroller():
    """A run that reads a page it cannot get past by scrolling, which is what the model did."""
    steps = []

    def decide(state, questions):
        steps.append((state, questions))
        operations = questions["operation"]["criteria"]
        choice = "SCROLL_DOWN" if "SCROLL_DOWN" in operations else "DONE"
        answers = {
            "operation": {"choice": choice, "confidence": 0.9, "probabilities": {key: 0.0 for key in operations}},
            "goal_achieved": {"noul": 0.05},
        }
        answers["operation"]["probabilities"][choice] = 1.0
        if "prev_ok" in questions:
            answers["prev_ok"] = {"noul": 0.5}
        return Reply(answers=answers, model="scripted", latency_ms=1, usage={"cost": 0.0})

    decide.steps = steps
    return decide


def observed(session, fixture_server, fixture):
    page = session.open(fixture_server + fixture)
    return page, actions.build(page)


def test_a_corner_dialog_marks_its_own_controls_and_nothing_else(session, fixture_server):
    page, _space = observed(session, fixture_server, DIALOG)
    inside = {element["label"] for element in page["elements"] if element.get("overlay")}
    assert inside == {"Accept Cookies", "Choose Cookies"}
    assert "From" in {element["label"] for element in page["elements"]}


def test_only_the_way_through_the_dialog_is_offered(session, fixture_server):
    _page, space = observed(session, fixture_server, DIALOG)
    assert space.offered() == ["CLICK"]
    assert [action["label"] for action in space.targets["CLICK"].values()] == ["Accept Cookies"]


def test_a_full_screen_wall_offers_only_its_accept(session, fixture_server):
    _page, space = observed(session, fixture_server, OVERLAY)
    assert space.offered() == ["CLICK"]
    assert [action["label"] for action in space.targets["CLICK"].values()] == ["Accept all"]


def test_the_page_behind_the_wall_comes_back_once_it_is_taken(session, fixture_server):
    page, space = observed(session, fixture_server, DIALOG)
    session.act(next(iter(space.targets["CLICK"].values())), page)
    space = actions.build(session.observe())
    labels = [action["label"] for action in space.targets["CLICK"].values()]
    assert "Find cheap tickets" in labels
    assert "Accept Cookies" not in labels
    assert "TYPE_TEXT" in space.offered()


def test_a_run_that_would_scroll_past_the_wall_cannot(session, fixture_server):
    decide = scroller()
    agent = Agent(session=session, config=config.load({}), decide=decide)
    agent.run(GOAL, values={"origin": "London"}, max_steps=4, url=f"{fixture_server}{DIALOG}")
    assert "SCROLL_DOWN" not in decide.steps[0][1]["operation"]["criteria"]
    assert "WAIT" not in decide.steps[0][1]["operation"]["criteria"]


def test_a_page_with_no_wall_keeps_every_control_it_had(session, fixture_server):
    _page, space = observed(session, fixture_server, "/form.html")
    assert "SCROLL_DOWN" in space.offered() or "WAIT" in space.offered()
    assert "TYPE_TEXT" in space.offered()
