"""Enter goes to the field that was observed, or it does not go at all."""

import pytest

from jev_ra import config
from jev_ra.agent import Agent
from jev_ra.errors import Escalated, StalePage

pytestmark = pytest.mark.browser

FIXTURE = "/sites/two-filled-fields.html"


def press_action(page):
    return next(a for a in page["actions"] if a["id"] == "press_enter")


def test_the_offered_press_names_the_field_it_would_submit(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    press = press_action(page)
    coupon = next(e for e in page["elements"] if e["label"] == "Coupon code")
    assert press["node"] == coupon["node"]


def test_enter_is_refused_when_focus_moved_to_another_field(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    press = press_action(page)
    session.evaluate("document.getElementById('q').focus()")
    with pytest.raises(StalePage):
        session.act(press, page)
    assert session.evaluate("document.getElementById('out').textContent") == "nothing submitted"


def test_enter_submits_the_field_that_was_observed(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    session.act(press_action(page), page)
    assert session.evaluate("document.getElementById('out').textContent") == "coupon SAVE10"


def refusing(_state, _questions):
    raise AssertionError("a direct press never asks the model")


def test_a_direct_press_submits_the_field_that_was_observed(session, fixture_server):
    session.open(fixture_server + FIXTURE)
    Agent(session=session, config=config.load({}), decide=refusing).press("Enter")
    assert session.evaluate("document.getElementById('out').textContent") == "coupon SAVE10"


def test_a_direct_press_with_nothing_focused_refuses_instead_of_pressing_into_the_void(session, fixture_server):
    session.open(fixture_server + FIXTURE)
    session.evaluate("document.getElementById('coupon').blur()")
    agent = Agent(session=session, config=config.load({}), decide=refusing)
    with pytest.raises(Escalated):
        agent.press("Enter")
    assert session.evaluate("document.getElementById('out').textContent") == "nothing submitted"
