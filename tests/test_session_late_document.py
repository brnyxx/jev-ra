"""A link that opens a page which paints itself late is read once there is something on it."""

import time

import pytest

from jev_ra.browser.session import ARRIVAL_BUDGET_S, SETTLE_BUDGET_S

pytestmark = pytest.mark.browser

FIXTURE = "/sites/late-document.html"


def follow(session, url, label):
    page = session.open(url)
    action = next(a for a in page["actions"] if a["label"] == label and a["role"] == "link")
    started = time.monotonic()
    session.act(action, page)
    return session.observe(), time.monotonic() - started


def test_a_page_that_arrives_as_an_empty_shell_is_read_once_it_has_painted(session, fixture_server):
    page, _ = follow(session, fixture_server + FIXTURE, "Seller resources")
    assert "page=resources" in page["url"]
    assert [element["label"] for element in page["elements"]] == ["Learn grading", "Learn pricing"]
    assert "Guides for sellers." in page["text"]


def test_a_page_whose_words_are_still_transparent_is_read_once_they_show(session, fixture_server):
    page, _ = follow(session, fixture_server + FIXTURE, "Seller standings")
    assert "page=standings" in page["url"]
    assert "Top sellers this week." in page["text"]


def test_a_page_that_arrives_painted_is_not_waited_for(session, fixture_server):
    page, elapsed = follow(session, fixture_server + FIXTURE, "Seller news")
    assert [element["label"] for element in page["elements"]] == ["Latest updates"]
    assert elapsed < SETTLE_BUDGET_S, f"waited {elapsed:.2f}s for a page that was ready"


def test_a_page_with_words_and_nothing_to_press_is_not_waited_for(session, fixture_server):
    page, elapsed = follow(session, fixture_server + FIXTURE, "Seller receipt")
    assert '"status": "received"' in page["text"]
    assert page["elements"] == []
    assert elapsed < SETTLE_BUDGET_S, f"waited {elapsed:.2f}s for a page that was ready"


def test_a_page_that_never_paints_costs_one_arrival_budget_and_is_still_read(session, fixture_server):
    page, elapsed = follow(session, fixture_server + FIXTURE, "Seller archive")
    assert "page=blank" in page["url"]
    assert page["elements"] == []
    assert elapsed < SETTLE_BUDGET_S + ARRIVAL_BUDGET_S + 1.0, f"waited {elapsed:.2f}s"


def test_a_page_that_is_a_human_check_is_not_waited_for(session, fixture_server):
    page, elapsed = follow(session, fixture_server + FIXTURE, "Seller check")
    assert page["challenge"]
    assert elapsed < SETTLE_BUDGET_S, f"waited {elapsed:.2f}s on a check that shows all it will"
