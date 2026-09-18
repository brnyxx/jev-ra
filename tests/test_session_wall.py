"""A wall in front of a shop offers exactly one way on, and it has to work."""

import pytest

pytestmark = pytest.mark.browser

FIXTURE = "/sites/interstitial-wall.html"


def labels(page):
    return [element["label"] for element in page["elements"]]


def action_for(page, label, kind):
    return next(a for a in page["actions"] if a["label"] == label and a["kind"] == kind)


def test_the_wall_is_all_there_is_to_see(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert "Continue shopping" in labels(page)
    assert "Search books" not in labels(page)


def test_passing_the_wall_reveals_the_shop(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    session.act(action_for(page, "Continue shopping", "click"), page)
    page = session.observe()
    assert "Search books" in labels(page)
    assert "Continue shopping" not in labels(page)
    session.act(action_for(page, "Search books", "fill"), page, text="Godel Escher Bach")
    assert session.evaluate("document.getElementById('q').value") == "Godel Escher Bach"
