"""Enter goes to the field that was observed, or it does not go at all."""

import pytest

from jev_ra.errors import StalePage

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
