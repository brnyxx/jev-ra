"""A wait lasts until the page has something new to show, and not a moment longer."""

import time

import pytest

from jev_ra.browser import session as session_module

pytestmark = pytest.mark.browser


def control(page, name):
    return next(action for action in page["actions"] if action["id"] == name)


def labels(page):
    return [element["label"] for element in page["elements"]]


def loading(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/load-more.html")
    session.act(next(a for a in page["actions"] if a["label"] == "Show more results"), page)
    page = session.observe()
    assert "Loading…" in labels(page) or "Loading…" in page["text"]
    return page


def test_a_wait_lasts_until_the_next_batch_arrives(session, fixture_server):
    page = loading(session, fixture_server)
    session.act(control(page, "wait"), page)
    page = session.observe()
    assert any(label.startswith("Result 11:") for label in labels(page))


def test_a_page_that_already_changed_is_not_waited_on_again(session, fixture_server):
    page = loading(session, fixture_server)
    session.evaluate("document.body.appendChild(document.createElement('p')).textContent = 'arrived'")
    started = time.monotonic()
    session.act(control(page, "wait"), page)
    session.observe()
    assert time.monotonic() - started < session_module.SETTLE_BUDGET_S


def test_a_page_that_never_changes_costs_one_settle_budget(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/static.html")
    started = time.monotonic()
    session.act(control(page, "wait"), page)
    session.observe()
    assert time.monotonic() - started < session_module.SETTLE_BUDGET_S + 1.0
