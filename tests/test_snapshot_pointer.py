"""A control whose pointer events route to its own wrapper is still reachable."""

import pytest

pytestmark = pytest.mark.browser

FIXTURE = "/sites/pointer-routed.html"


def labels(page):
    return {element["label"] for element in page["elements"]}


def test_a_link_the_card_clicks_for_is_still_offered(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert "인감증명서" in labels(page)
    assert "소득금액 증명" in labels(page)


def test_and_clicking_it_reaches_the_handler(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    action = next(a for a in page["actions"] if a["label"] == "인감증명서" and a["kind"] == "click")
    session.act(action, page)
    assert "opened: 인감증명서" in session.observe()["text"]


def test_a_wall_over_the_cards_still_hides_them(session, fixture_server):
    page = session.open(fixture_server + "/sites/consent-overlay.html")
    assert "From" not in labels(page)
