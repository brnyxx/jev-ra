"""A page that finishes loading before it paints anything is not an empty page."""

import pytest

pytestmark = pytest.mark.browser

FIXTURE = "/sites/late-paint.html"


def test_open_waits_for_the_first_control_to_exist(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert [element["label"] for element in page["elements"]] == ["Search services", "Search"]


def test_a_page_with_genuinely_nothing_on_it_still_returns(session, fixture_server):
    page = session.open(fixture_server + "/sites/empty.html")
    assert page["elements"] == []
    assert page["url"].endswith("/sites/empty.html")


def test_open_waits_for_a_loading_cover_to_lift(session, fixture_server):
    page = session.open(fixture_server + "/sites/loading-cover.html")
    assert [element["label"] for element in page["elements"]] == ["Search services", "Search"]
