"""A point is only worth offering when pressing it reaches the element that was offered."""

import pytest

pytestmark = pytest.mark.browser

FIXTURE = "/sites/edge-aim.html"


def labels(page):
    return [element["label"] for element in page["elements"]]


def test_a_link_whose_every_free_point_belongs_to_the_row_is_not_offered(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert "Free delivery" not in labels(page)


def test_a_link_that_keeps_a_live_corner_is_still_offered_and_reaches_itself(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert "Gift wrap" in labels(page)
    action = next(a for a in page["actions"] if a["label"] == "Gift wrap" and a["kind"] == "click")
    session.act(action, page)
    assert session.evaluate("document.getElementById('out').textContent") == "link-b"
