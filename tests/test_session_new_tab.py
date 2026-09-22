"""A link that asks for a new tab is followed in the one tab this run drives."""

import pytest

pytestmark = pytest.mark.browser

FIXTURE = "/sites/new-tab-links.html"


def action_for(page, label):
    return next(action for action in page["actions"] if action["label"] == label and action["kind"] == "click")


def test_a_blank_target_link_navigates_the_tab_the_run_is_on(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    session.act(action_for(page, "Latest policy"), page)
    after = session.observe()
    assert after["url"].endswith("/hash-router.html#install")
    assert "Library docs" in after["text"]


def test_a_self_target_link_is_untouched(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    session.act(action_for(page, "Documentation"), page)
    assert session.observe()["url"].endswith("/reveal-panel.html")


def test_a_link_with_no_target_is_untouched(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    session.act(action_for(page, "Library"), page)
    assert session.observe()["url"].endswith("/select-options.html")


def test_the_page_a_run_is_on_actually_moves(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    session.act(action_for(page, "Latest policy"), page)
    assert session.observe()["marker"] != page["marker"]
