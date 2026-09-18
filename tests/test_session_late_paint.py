"""A page that finishes loading before it paints anything is not an empty page."""

import time

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


def test_a_page_whose_controls_are_below_the_fold_is_not_waited_for(session, fixture_server):
    from jev_ra.browser.session import PAINT_BUDGET_S

    started = time.perf_counter()
    page = session.open(fixture_server + "/sites/below-the-fold.html")
    elapsed = time.perf_counter() - started
    assert page["elements"] == []
    assert elapsed < PAINT_BUDGET_S / 2, f"waited {elapsed:.2f}s for a page that was ready"
    assert any(action["id"] == "scroll_down" for action in page["actions"])
