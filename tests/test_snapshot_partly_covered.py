"""Something half under a floating bar is still there to be clicked, where it is not covered."""

import pytest

pytestmark = pytest.mark.browser

FIXTURE = "/sites/partly-covered.html"


def labels(page):
    return [element["label"].strip() for element in page["elements"]]


def test_a_brand_row_under_a_floating_bar_is_still_offered(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert "닥터자르트" in labels(page)
    assert "라네즈" in labels(page)


def test_and_clicking_it_reaches_the_checkbox(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    action = next(a for a in page["actions"] if a["label"].strip() == "닥터자르트" and a["kind"] == "click")
    session.act(action, page)
    assert "filtered: dr-jart" in session.observe()["text"]


def test_something_covered_everywhere_is_still_not_offered(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert "완전히 가려진 버튼" not in labels(page)
