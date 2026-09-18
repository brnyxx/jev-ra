"""Everything one step waits for shares one budget and one reading of the page."""

import time

import pytest

from jev_ra.browser import session as session_module

pytestmark = pytest.mark.browser

INERT = "/sites/inert-button.html"
PANEL = "/sites/late-panel.html"


def action_for(page, label, kind):
    return next(a for a in page["actions"] if a["label"] == label and a["kind"] == kind)


def counted(session):
    reads = []
    original = session.evaluate

    def evaluate(expression, await_promise=False):
        reads.append(expression)
        return original(expression, await_promise)

    session.evaluate = evaluate
    return reads


def test_the_worst_case_click_costs_one_budget_not_three(session, fixture_server):
    page = session.open(fixture_server + INERT)
    reads = counted(session)
    started = time.monotonic()
    session.act(action_for(page, "Apply", "click"), page)
    session.observe()
    elapsed = time.monotonic() - started
    assert elapsed < session_module.SETTLE_BUDGET_S + 0.6
    assert len(reads) <= 14


def test_a_panel_that_mounts_late_is_still_waited_for(session, fixture_server):
    page = session.open(fixture_server + PANEL)
    session.act(action_for(page, "Open search panel", "click"), page)
    after = session.observe()
    assert [e["label"] for e in after["elements"] if e["role"] == "textbox"] == ["Search help"]
